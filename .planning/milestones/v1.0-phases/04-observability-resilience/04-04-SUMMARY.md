---
phase: 04-observability-resilience
plan: 04
subsystem: deployment
tags: [prometheus, docker-compose, documentation, observability]

# Dependency graph
requires:
  - phase: 04-observability-resilience
    plan: "01"
    provides: GET /metrics (Prometheus v0.0.4 text exposition) and GET /health/live + GET /health/ready
  - phase: 04-observability-resilience
    plan: "02"
    provides: tenacity same-provider transient retry, max_retries=0 on AsyncOpenAI construction
  - phase: 04-observability-resilience
    plan: "03"
    provides: RATE_LIMIT_PER_KEY env var + per-key rate limiting
provides:
  - Optional prom/prometheus Compose sidecar (profiles["observability"]) scraping the gateway's /metrics
  - prometheus/prometheus.yml scrape config (job llm-gateway, target gateway:8000, metrics_path /metrics, 15s interval)
  - README.md fully aligned with Phase 4's shipped surface (health split, /metrics, RATE_LIMIT_PER_KEY, tenacity) — no stale single-/health references
affects: [operator onboarding docs, any future Phase-5 DOCS-01/02 refresh (README is now current, no longer part of that backlog)]

# Actuals (#2632)
actuals:
  tokens: 1124
  tasks: 2
  commits: 2
  plan_head_before: 796a4f8

# Tech tracking
tech-stack:
  added: []
  patterns: ["Compose profiles: [\"observability\"] gate for an opt-in sidecar service — never starts on a bare `docker compose up`, validated via `docker compose --profile observability config -q`"]

key-files:
  created: [prometheus/prometheus.yml]
  modified: [docker-compose.yml, README.md]

key-decisions:
  - "Pinned prom/prometheus:v3.14.0 (verified as the highest stable non-rc semver tag on Docker Hub this session, not assumed) rather than `latest`, per the repo's reproducibility preference and the plan's explicit prohibition on pinning latest."
  - "README's tenacity note was placed in the Install section (nearest existing prose naming what `make install`/requirements.txt provisions) since the repo has no dedicated 'runtime dependencies' section — matches the task's fallback instruction ('or the nearest prose naming requirements.txt's contents')."
  - "GET /metrics section documents error rate as PromQL-derived (not a fourth metric), matching 04-01's actual metrics.py implementation exactly rather than inventing an error_rate gauge."

patterns-established: []

requirements-completed: [OBSV-01]

coverage:
  - id: D1
    description: "docker compose --profile observability config -q validates a prometheus service gated behind profiles:[\"observability\"], pinned to a non-latest image tag, mounting prometheus/prometheus.yml read-only, exposing port 9090"
    requirement: "OBSV-01"
    verification:
      - kind: other
        ref: "docker compose --profile observability config -q — exit 0"
        status: pass
      - kind: other
        ref: "docker compose config -q (no profile) — exit 0, services list unchanged ([gateway])"
        status: pass
    human_judgment: false
  - id: D2
    description: "prometheus/prometheus.yml scrapes gateway:8000/metrics"
    requirement: "OBSV-01"
    verification:
      - kind: other
        ref: "prometheus/prometheus.yml — job_name llm-gateway, static_configs target gateway:8000, metrics_path /metrics"
        status: pass
    human_judgment: false
  - id: D3
    description: "README.md documents GET /health/live, GET /health/ready, GET /metrics, RATE_LIMIT_PER_KEY, and tenacity with zero stale single-/health references"
    requirement: "OBSV-01"
    verification:
      - kind: other
        ref: "grep -c '/health/live' README.md == 3; grep -c '/health/ready' README.md == 3; grep -c '/metrics' README.md == 2; grep -c 'RATE_LIMIT_PER_KEY' README.md == 1; grep -c 'tenacity' README.md == 1"
        status: pass
    human_judgment: false

duration: ~15min
completed: 2026-09-08
status: complete
---

# Phase 4 Plan 4: Optional Prometheus Compose Profile + README Refresh Summary

**Adds an opt-in `prometheus` Compose service (pinned `v3.14.0`, gated behind `profiles: ["observability"]`) scraping the gateway's `/metrics`, and brings README.md fully in line with everything Wave 1/2 shipped — health split, metrics endpoint, per-key rate limit, and the `tenacity` dependency.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-09-08
- **Completed:** 2026-09-08
- **Tasks:** 2/2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `prometheus/prometheus.yml` (new): minimal scrape config — `job_name: llm-gateway`, `metrics_path: /metrics`, target `gateway:8000`, 15s scrape interval
- `docker-compose.yml`: new `prometheus` service using `prom/prometheus:v3.14.0` (verified highest stable non-rc tag on Docker Hub this session), gated behind `profiles: ["observability"]`, mounting the new scrape config read-only, exposing port 9090; existing `gateway` service definition untouched
- `README.md`: `### GET /health` split into `### GET /health/live` + `### GET /health/ready` (with an explicit no-back-compat-alias note); new `### GET /metrics` section documenting the counter/histogram and the optional Compose profile; `RATE_LIMIT_PER_KEY` row added to the env var table; tenacity dependency noted in the Install section

## Task Commits

1. **Optional Prometheus Compose profile scraping /metrics** - `41565dc` (feat)
2. **README — health split, /metrics, RATE_LIMIT_PER_KEY, tenacity** - `0f31e6e` (docs)

**Plan metadata:** commit pending (this SUMMARY + STATE/ROADMAP update)

## Files Created/Modified
- `prometheus/prometheus.yml` (new) - Prometheus scrape config for the optional Compose profile
- `docker-compose.yml` - `prometheus` service, `profiles: ["observability"]`-gated, pinned image, read-only config mount, port 9090
- `README.md` - health split, `/metrics`, `RATE_LIMIT_PER_KEY`, tenacity documentation; zero remaining stale single-`/health` references

## Decisions Made
- Verified the current highest stable non-rc `prom/prometheus` Docker Hub tag directly via the Docker Hub API this session (`v3.14.0`, ahead of the more-recently-published-but-lower-numbered `v3.13.3` patch backport) rather than guessing a version from training data — matches the plan's explicit "verify the current stable release tag at implementation time" instruction.
- Kept `docker-compose.yml`'s existing `gateway` service completely untouched — the new service is purely additive, confirmed via `git diff` showing only insertions.
- README's `/metrics` section documents error rate as PromQL-derived over `gateway_requests_total`'s `status` label, matching 04-01's actual `metrics.py` implementation exactly (no separate error-rate metric invented).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None for the code/config changes. An operator who wants live Prometheus scraping can run `docker compose --profile observability up` and reach Prometheus at `http://localhost:9090`; this was not run as a live smoke test in this plan (`docker compose --profile observability config -q` — the plan's own `<verify>` — was run and passed) since pulling the `prom/prometheus:v3.14.0` image is a live external dependency beyond the plan's specified verification.

## Next Phase Readiness
- OBSV-01 fully satisfied end-to-end: metrics endpoint (04-01), optional Compose scrape profile (this plan), and README documentation (this plan) all land together.
- README.md is now current on Phase 4's entire shipped surface — no longer part of the Phase-5 DOCS-01/02 stale-docs backlog for the health/metrics/rate-limit/tenacity surface specifically (the broader 8-provider-architecture drift noted in `AGENTS.md` remains out of this plan's scope and Phase 5's to address).
- Phase 4 (Observability & Resilience) is complete: OBSV-01/02/03 all requirements-complete per `REQUIREMENTS.md`.

---
*Phase: 04-observability-resilience*
*Completed: 2026-09-08*

## Self-Check: PASSED
- FOUND: prometheus/prometheus.yml
- FOUND: .planning/phases/04-observability-resilience/04-04-SUMMARY.md
- FOUND commit: 41565dc
- FOUND commit: 0f31e6e
