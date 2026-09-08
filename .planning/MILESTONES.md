# Milestones

## v1.0 Gateway Hardening & Production Readiness (Shipped: 2026-09-08)

**Phases completed:** 5 phases, 15 plans, 33 tasks

**Key accomplishments:**

- Bounded AnalyticsWriter (drop-newest queue → serial SQLite drain) + nested OpenAI-style SSE error frames, proven end-to-end by a mid-stream quota failure delivering token frames, the exact quota error object, [DONE], and exactly one request_logs row
- Fail-fast startup validation: RATE_LIMIT model_validator via slowapi's own parser, lifespan APP_API_KEY/ANALYTICS_DB_PATH aborts naming the variable, zai/manifest no-key warnings that never abort, and provably secret-free startup output
- Deterministic pytest-asyncio proof of the bounded analytics write path: 20-stream gather burst with a slowed writer proves full token delivery + exactly-once rows, plus queue-unit tests for drop-newest/gated-drain/bounded-stop and a GeneratorExit disconnect proof — RELI-02 closed.
- TTL retention knob (Settings → lifespan → writer-first-action startup purge) with batched rowid-subquery DELETE, guarded incremental_vacuum reclamation, and pragma-before-schema auto_vacuum — proven end-to-end through one real lifespan startup
- 6h deadline-scheduled purge tick riding the existing AnalyticsWriter consumer loop (wait_for wakeup + lossless get_nowait salvage, no drift), inter-batch queue drain keeping fire-and-forget lossless mid-purge, and both ANLT-02 integration contracts proven: four endpoints serve retained data post-purge, 20 concurrent streams complete unblocked with purges interleaving
- Retention knob documented at both operator entry points (.env.example + README row with first-startup legacy-purge warning, escape hatch, and one-time `sqlite3 data/analytics.db "VACUUM;"` migration) and AGENTS.md's four analytics spots brought level with the 02-01/02-02 shipped purge lifecycle
- Multi-stage non-root Docker image (python:3.12-slim, venv-copy, chown'd volume) plus single-service compose stack reaching a live healthy `/health` on Rancher Desktop, gated by a one-line `AsyncGenerator` import fix that unblocks Python 3.12 entirely — volume persistence, SIGTERM drain, and sub-second in-container readiness proven live and documented in the README.
- GitHub Actions CI (lint + matrix tests + docker-build) proven green end-to-end on origin main, with ruff pinned to 0.16.6 per the approved checkpoint decision and three previously-invisible CI-only failure modes fixed along the way.
- Hand-rolled `/metrics` Prometheus v0.0.4 exposition (request counter + latency histogram) and a `/health/live`+`/health/ready` split replacing the old single `/health` route, with a real double-cumulative histogram bug caught and fixed by the plan's own boundary test.
- `tenacity.AsyncRetrying` wraps only the pre-stream `create()` call in `OpenAICompatibleProvider.chat_stream()` (3 total attempts, exponential backoff+jitter, allow-list predicate), paired with `max_retries=0` on `AsyncOpenAI` construction that closes a pre-existing, previously undetected gap where the SDK's own default retry could silently retry a z.ai quota/auth failure before ZAI-3's never-retry rule ever saw it.
- Per-Bearer-token rate limiting stacked alongside the existing per-IP `RATE_LIMIT` on `POST /v1/chat/completions`, using slowapi's dynamic (callable) limit-value support instead of the literal static-string pattern in 04-PATTERNS.md/04-RESEARCH.md, since a static string would have made `RATE_LIMIT_PER_KEY` frozen at import time and untestable via monkeypatch.
- Adds an opt-in `prometheus` Compose service (pinned `v3.14.0`, gated behind `profiles: ["observability"]`) scraping the gateway's `/metrics`, and brings README.md fully in line with everything Wave 1/2 shipped — health split, metrics endpoint, per-key rate limit, and the `tenacity` dependency.
- Closed the `model="auto"` deprecation question with two named regression tests plus a locked, dated ROUT-01 decision block in PROJECT.md — no routing code changed.
- Corrected `docs/project-overview-pdr.md` and `docs/project-roadmap.md` from the stale native 8-provider architecture to the shipped Manifest + z.ai GLM Coding Plan two-provider reality, marking superseded FRs historical (not deleted) for REQUIREMENTS.md traceability.

---
