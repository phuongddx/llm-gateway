# Roadmap: LLM Gateway

## Overview

The gateway is live and validated: an OpenAI-compatible FastAPI service routing across Manifest (default) and the z.ai GLM Coding Plan endpoint (quota-backed, no-fallback), with SSE streaming, SQLite analytics, credit-burn visibility, and a playground UI. This milestone hardens what exists rather than building new surface: first make the running gateway fail fast and stream reliably under a real coding day (Phase 1), bound its analytics storage (Phase 2), put it on the stated Docker/Compose target runtime with CI (Phase 3), make it observable and transient-error resilient (Phase 4), then close the last open routing decision and make every doc tell the truth about the shipped system (Phase 5). Phase 6 (optional, preconditions unmet) holds the stress-support chatbot future direction and is not part of milestone completion.

**Locked-decision guardrails (apply to every phase; see PROJECT.md `<decisions>`):** Max-tier Coding Plan; coding endpoint with ToS risk accepted; all GLM → coding endpoint with NO fallback on z.ai errors (retry work must be same-provider, transient-only — never quota 429/1113, never auth 401/403, never a Manifest reroute); credit estimation stays in local analytics. Baseline contracts (REQUIREMENTS.md "Baseline" section, 20 REQs) must not regress.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Gateway Runtime Hardening** - Fail fast on bad config; bounded analytics writes under concurrent streaming; OpenAI-format SSE error frames (completed 2026-09-08)
- [x] **Phase 2: Analytics Retention & Storage Lifecycle** - Stop unbounded `request_logs` growth with a configurable, automatically enforced retention policy (completed 2026-09-08)
- [x] **Phase 3: Containerized Deployment & CI** - Multi-stage non-root Docker image, single-container Compose deployment, GitHub Actions pipeline (completed 2026-09-08)
- [ ] **Phase 4: Observability & Resilience** - Prometheus metrics, per-key rate limiting, same-provider-only transient retry; liveness vs readiness
- [ ] **Phase 5: Routing Decision & Documentation Refresh** - Resolve the `model="auto"` deprecation decision; refresh the four stale docs to shipped reality
- [ ] **Phase 6: Stress-Support Chatbot MVP (Optional)** - Future direction on top of the gateway; DO NOT START until preconditions are met

## Phase Details

### Phase 1: Gateway Runtime Hardening

**Goal**: The live gateway fails fast on bad configuration and keeps every stream intact under concurrent load, with client-compatible error frames — the "no quota-exhaustion surprises across a full coding day" foundation
**Depends on**: Nothing (first phase)
**Requirements**: RELI-01, RELI-02, RELI-03
**Success Criteria** (what must be TRUE):

  1. Operator starting the gateway without `APP_API_KEY` sees an immediate, actionable startup abort naming the missing variable — never a request-time SDK stack trace; starting with no effective z.ai key logs an explicit notice (no abort) and GLM routes degrade to Manifest per the key-gate, preserving opt-in/rollback-by-unset semantics
  2. Under a concurrent multi-stream burst (simulated coding-day traffic), every client receives its full token stream and every completed request appears exactly once in `request_logs`; pending analytics writes stay bounded (capped queue with graceful lag handling) even when SQLite writes fall behind
  3. SSE error frames carry an OpenAI-style error object (message/type fields) while z.ai quota exhaustion and authentication failure remain distinctly identifiable messages; no internal exception text reaches clients
  4. A z.ai quota event (HTTP 429 or error code 1113) surfaces to the client within one round-trip as the dedicated quota message — no hang, no retry loop, no Manifest reroute (locked ZAI-3)

**Plans**: 3/3 plans executed
Plans:

- [x] 01-01-PLAN.md
- [x] 01-02-PLAN.md
- [x] 01-03-PLAN.md
- [ ] 01-PLAN-01-tracer-bounded-writer-error-frames.md — tracer: bounded AnalyticsWriter write path + OpenAI-style SSE error frames + playground renderer (RELI-02, RELI-03)
- [ ] 01-PLAN-02-startup-validation.md — RATE_LIMIT model_validator + lifespan aborts and no-key notices (RELI-01)
- [ ] 01-PLAN-03-concurrency-proof.md — 20-stream burst + queue unit tests proving exactly-once bounded analytics writes (RELI-02)

### Phase 2: Analytics Retention & Storage Lifecycle

**Goal**: `request_logs` stops growing unbounded — long-running deployments keep analytics accurate, fast, and disk-bounded
**Depends on**: Phase 1 (write-path stabilization precedes lifecycle changes on the same analytics path)
**Requirements**: ANLT-01, ANLT-02
**Success Criteria** (what must be TRUE):

  1. Operator can bound retention from `.env` (TTL in days, e.g. `ANALYTICS_RETENTION_DAYS`) with a documented default; the policy applies to an existing database without manual SQL
  2. Rows older than the TTL are purged automatically (at startup and periodically); `/v1/analytics/{summary,models,requests,credits}` serve the retained data correctly afterwards
  3. Purging never blocks or delays response streaming (fire-and-forget preserved) and WAL-mode concurrent reads keep working during purge; on-disk growth is bounded and space from purged rows is reclaimable (auto-vacuum on, or a documented one-liner)

**Plans**: 3/3 plans executed
Plans:
**Wave 1**

- [x] 02-01-PLAN.md — tracer: `ANALYTICS_RETENTION_DAYS` knob → lifespan → writer startup purge → batched `purge_expired` + auto_vacuum reclamation, proven end-to-end in one real lifespan (ANLT-01, ANLT-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 02-02-PLAN.md — 6h deadline tick inside the writer loop + inter-batch drain; endpoints-post-purge and 20-stream burst-during-purge proofs (ANLT-02)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 02-03-PLAN.md — operator docs: `.env.example` knob, README env row + one-time VACUUM migration note, AGENTS.md analytics section (ANLT-01, ANLT-02)

### Phase 3: Containerized Deployment & CI

**Goal**: The gateway runs on the stated target runtime — a single Docker/Compose container — with CI gating every change
**Depends on**: Phase 1 (fail-fast startup defines the container's failure behavior; the hardened runtime is what gets packaged)
**Requirements**: DEPL-01, DEPL-02, DEPL-03
**Success Criteria** (what must be TRUE):

  1. `docker compose up` on a fresh clone with a `.env` brings the gateway to a green healthcheck (`GET /health`); the container process reaches request-readiness in <3s (NFR-04 holds in-container)
  2. The image is multi-stage and runs as non-root; no secrets are baked in — all configuration arrives via the single-`.env` passthrough (NFR-03 preserved)
  3. The analytics SQLite database lives on a persistent volume and survives container recreation with all historical request logs intact
  4. GitHub Actions runs lint + tests (and builds the image) on push/PR; a red pipeline identifies a broken change before it reaches the deployed container

**Plans**: 2/2 plans executed
Plans:
**Wave 1**

- [x] 03-01-PLAN.md — tracer: AsyncGenerator 3.12 fix → multi-stage non-root image → single-service compose → green /health + volume persistence + measured <3s readiness on the operator-started Rancher Desktop daemon; README deployment quickstart (DEPL-01, DEPL-02)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-02-PLAN.md — CI: lint-green code fixes + blocking ruff SUS-legitimacy checkpoint + three-job GitHub Actions pipeline (lint / matrix 3.12+3.14 / docker-build) green on push to main (DEPL-03)

### Phase 4: Observability & Resilience

**Goal**: The deployed gateway exposes operational metrics and absorbs transient provider failures — strictly within the locked no-fallback constraints
**Depends on**: Phase 3 (metrics/health integrate with the Compose target; CI gates the additions)
**Requirements**: OBSV-01, OBSV-02, OBSV-03
**Success Criteria** (what must be TRUE):

  1. A Prometheus-scrape endpoint exposes request count, latency histogram, and error rate; a Compose profile can run Prometheus alongside the gateway collecting them (prefer hand-rolled text exposition — zero new deps per NFR-02; any new dependency needs an explicit decision)
  2. A client exceeding its configured per-key rate limit receives HTTP 429 from the gateway without provider traffic being sent; the limit is configurable via `.env`
  3. Transient provider errors (network timeouts, 5xx) are retried with backoff against the same provider only; z.ai quota (429/1113) and auth (401/403) failures are never retried and never rerouted to Manifest (locked ZAI-3); after exhausted retries the client sees the provider-distinct error
  4. Health endpoints distinguish liveness from readiness — readiness reports the analytics DB as initialized before the container reports ready (feeds the Phase 3 healthcheck)

**Plans**: TBD

### Phase 5: Routing Decision & Documentation Refresh

**Goal**: The last open routing decision is closed and every doc tells the truth about the shipped system
**Depends on**: Phase 3, Phase 4 (docs must describe the containerized, observable deployment as shipped)
**Requirements**: ROUT-01, DOCS-01, DOCS-02
**Success Criteria** (what must be TRUE):

  1. The `model="auto"` fate — keep, pin to an explicit model, or remove (it rides Manifest's 2026-09-01-deprecated prompt-complexity router) — is decided with the user, recorded in PROJECT.md Key Decisions, and implemented with routing behavior + tests matching the recorded decision
  2. `docs/project-overview-pdr.md` and `docs/project-roadmap.md` describe the current two-provider (Manifest + zai-coding) architecture; superseded provider/pricing requirements are explicitly marked historical
  3. `docs/deployment-guide.md` documents the Docker/Compose deployment and the current env surface (`MANIFEST_API_KEY`, `ZAI_CODING_API_KEY`, credit quotas, `LLM_API_KEY` fallback) — no stale per-provider key/base-URL tables
  4. `docs/code-standards.md` file tree and the "Adding a New Provider" recipe match the shipped providers (base, openai_compatible_base, manifest, zai_coding — no pricing-table step)

**Plans**: TBD

### Phase 6: Stress-Support Chatbot MVP (Optional)

**Goal**: Groundwork for the planned product on top of the gateway — a placeholder phase that MUST NOT start until its preconditions are answered
**Depends on**: Phase 5; external preconditions (currently UNMET): target language, hosting target, crisis jurisdiction, source document formats
**Requirements**: SCB-01 (v2 — deferred; not counted in v1 coverage)
**Success Criteria** (what must be TRUE):

  1. All four preconditions are answered with the user and recorded in PROJECT.md before any implementation plan is written
  2. MVP delivers a product-specific `/v1/stress/chat` route — self-hosted Gemma 4 E4B instruct via vLLM, local document retrieval (RAG), rule-first crisis gating — while the generic `/v1/chat/completions` surface remains unchanged; MVP stays stateless and text-only

**Plans**: TBD (do not plan until preconditions resolved)

## Progress

| 3. Containerized Deployment & CI | 0/2 | Not started | - |
**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 (optional)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Gateway Runtime Hardening | 3/3 | Complete    | 2026-09-08 |
| 2. Analytics Retention & Storage Lifecycle | 3/3 | Complete    | 2026-09-08 |
| 3. Containerized Deployment & CI | 2/2 | Complete    | 2026-09-08 |
| 4. Observability & Resilience | 0/? | Not started | - |
| 5. Routing Decision & Documentation Refresh | 0/? | Not started | - |
| 6. Stress-Support Chatbot MVP (Optional) | 0/? | Deferred (preconditions unmet) | - |
