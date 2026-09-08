# Ingest Synthesis Summary (2026-09-08)

Entry point for `gsd-roadmapper`. MODE=new (bootstrap; no prior `.planning/`
context). PRECEDENCE: ADR > SPEC > PRD > DOC.

## Doc counts by type

- Total: 26
- ADR: 0
- SPEC: 2 — `docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md` (Approved, 2026-09-07, current-state authority), `docs/system-architecture.md` (current)
- PRD: 1 — `docs/project-overview-pdr.md` (partially superseded; see below)
- DOC: 23 — 13 phase fragments + 3 plan masters (0416 gateway-features, 0417 playground-web-ui, 0419 manifest-cutover — all executed/complete), 1 zai-coding implementation plan, 4 docs/ references (codebase-summary current; code-standards / deployment-guide / project-roadmap stale), 2 work journals
- UNKNOWN / low confidence: 0

## Decisions locked

0 (no ADR-classified docs; no source carries `locked: true`).
Decision-grade content preserved elsewhere: 4 user-locked z.ai Coding Plan
design decisions (Max tier · ToS risk accepted · all GLM → coding endpoint, no
fallback · credit estimation in analytics) are recorded as protocol
constraints in `constraints.md` (source: zai-coding design spec); historical
"Key Decisions" from the three completed plan sets are in `context.md`.

## Requirements extracted

28 (all from the single PRD): REQ-FR-01..REQ-FR-22, REQ-NFR-01..REQ-NFR-06.
- 8 SUPERSEDED: FR-7..FR-13 (native providers), FR-19 (pricing-table cost) —
  historical traceability only; do not route as current scope.
- 1 AMENDED: FR-2 (routing table semantics → passthrough for unknown models).
- Current, still-valid core: OpenAI-compatible chat API, SSE streaming, Bearer
  auth, `/v1/models`, analytics logging + summary/models/requests endpoints,
  usage extraction, SSE error payloads, per-provider key with LLM_API_KEY
  fallback, 6 NFRs (<50ms overhead, minimal deps, single .env, <3s startup,
  fire-and-forget logging, WAL).

## Constraints

21 entries — protocol 11, schema 5, api-contract 4, nfr 1. Sources: the two
SPECs (current-state contracts: provider abstraction, routing/canonicalization,
effective-key gate, credits formula + migration + analytics API, auth, config
layer, lifespan/write path, playground, zai-coding no-fallback error handling)
plus repo engineering conventions from the current zai-coding implementation
plan (Python 3.12+ floor, no new deps, mock/test conventions, no error-text
leakage, single settings singleton).

## Context topics

12 — project identity; architecture evolution timeline (Gemini-only →
7-provider router → playground → Manifest cutover → zai-coding); current
architecture pointer; superseded 8-provider reference (base URLs, env keys,
MODEL_PRICING); playground decisions/non-goals; z.ai Coding Plan economics &
risks; Manifest "auto" deprecation flag; stress-chatbot future direction;
production-readiness backlog; 0416 retrospective lessons; open engineering
items; documentation staleness map.

## Conflicts

0 blockers, 0 competing variants, 9 auto-resolved/informational — detail in
`../INGEST-CONFLICTS.md`. All contradictions are precedence-resolved
(SPEC > PRD/DOC) or temporal supersession within DOC; the superseded
8-native-provider architecture in the PRD/deployment/code-standards/roadmap
docs is preserved as historical context per ingest directive.

## Open items surfaced for the roadmapper

1. Manifest `"auto"` entry rides Manifest's deprecated (2026-09-01)
   prompt-complexity router — future decision flagged by the zai-coding spec.
2. Analytics retention: SQLite `request_logs` grows unbounded (no TTL/purge).
3. Load-test fire-and-forget `asyncio.create_task` logging under concurrent
   streaming; bounded queue if writes lag.
4. Startup API-key validation (fail fast instead of cryptic request-time SDK
   errors).
5. SSE error-frame schema alignment with the OpenAI error format.
6. Doc-refresh backlog: project-overview-pdr.md, deployment-guide.md,
   code-standards.md, project-roadmap.md still describe the superseded
   architecture.
7. Production-readiness backlog (roadmap Phase 3, not started): Docker +
   Compose, CI/CD, Prometheus metrics, liveness/readiness, per-key rate
   limiting, transient-error retry, secrets management, horizontal scaling,
   API versioning.
8. Stress-support chatbot MVP (future direction, separate plan folder not in
   this ingest): preconditions = target language, hosting target, crisis
   jurisdiction, source document formats.

## Files

- `decisions.md` — 0 ADR entries (header explains where decision-grade content lives)
- `requirements.md` — 28 REQ entries
- `constraints.md` — 21 entries
- `context.md` — 12 topics
- `../INGEST-CONFLICTS.md` — 0 BLOCKERS / 0 WARNINGS / 9 INFO
