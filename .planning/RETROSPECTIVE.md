# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Gateway Hardening & Production Readiness

**Shipped:** 2026-09-08
**Phases:** 5 | **Plans:** 15 | **Tasks:** 33

### What Was Built
- Bounded AnalyticsWriter (drop-newest queue → serial SQLite drain) with OpenAI-style nested SSE error frames, proven under a 20-stream concurrent burst with a slowed writer: full token delivery, exactly-once `request_logs` rows (Phase 1)
- Fail-fast startup validation (APP_API_KEY/ANALYTICS_DB_PATH aborts naming the variable; z.ai no-key notice that never aborts) + TTL retention with startup + 6h periodic purge and incremental-vacuum reclamation (Phases 1-2)
- Multi-stage non-root Docker image, single-service Compose stack, GitHub Actions CI (ruff 0.16.6 + 3.12/3.14 test matrix + docker-build), all proven live (Phase 3)
- Hand-rolled Prometheus `/metrics` (zero new deps), `/health/live`+`/health/ready` split, per-key rate limiting stacked on per-IP, tenacity same-provider-only transient retry with a ZAI-3-safe allow-list predicate — closing a pre-existing gap where the OpenAI SDK's own default retry could silently retry quota/auth failures (Phase 4)
- `model="auto"` deprecation question closed (KEEP — verified against current Manifest docs, regression-tested) and all four stale docs corrected to the shipped two-provider reality (Phase 5)

### What Worked
- Autonomous discuss → plan → check → execute → review → fix → verify pipeline per phase: every phase passed verification on its own evidence (real container builds, real CI runs, real openai SDK exception types), 0 surviving criticals across 5 phases
- GSD plan checker caught a genuinely load-bearing blocker: a docs plan whose own hardcoded test-file list was already stale (would have shipped freshly-stale docs); fixed with live `ls tests/*.py` enumeration + a TESTLIST_MATCH count check — self-healing against recurrence
- Locked-decision guardrails (ZAI-1..4) held across all resilience work: retry never touches quota/auth/Manifest-reroute paths, byte-exact, verified by code review against the real SDK exception hierarchy

### What Was Inefficient
- 53 commits sat unpushed across Phases 4-5, so a pre-existing ruff SIM117 violation landed on main undetected until the first push at close time — CI only proves what it actually runs
- `test_playground.py` and two playground assets were documented as shipped in AGENTS.md but never committed; the Phase-5 doc refresh then codified a 15-file test list that was only true of the local working tree
- Two near-simultaneous Phase-5 fix commits (self-contradicting heading, malformed covered_digest) were caught by verifier + advisory rather than by the executing agents' own final read-through

### Patterns Established
- Docs that enumerate files must enumerate them LIVE at write time (`ls tests/*.py`), never from a hardcoded list; a count-matching check (TESTLIST_MATCH) makes drift fail loudly
- Fire-and-forget work = held task reference + `add_done_callback`, bounded drop-newest queue in front of SQLite
- Same-provider-only retry via tenacity allow-list predicate + `max_retries=0` on the SDK client — the SDK default-retry layer must be explicitly disabled when it can violate a locked no-retry rule

### Key Lessons
1. Push before claiming CI-validated: "green on origin/main" is only true at the SHA CI actually ran; local-only commits carry unverified claims
2. A verification fingerprint over covered files goes stale the moment any later phase touches those files — expected cross-phase evolution, but it means milestone close needs either re-verification or an explicit override decision, never a silent pass
3. Scope discipline (executor deferring an out-of-scope doc bug to deferred-items.md) only works if someone owns the deferred list at close — the item sat until the close audit surfaced it

### Cost Observations
- Model mix: GLM-5.3 (z.ai coding endpoint) for execution + planning subagents; single-session milestone run
- Sessions: 1 continuous autonomous session (2026-09-08) covering Phases 1-5 close-out
- Notable: plan-checker and verifier subagent passes (the ones with real evidence requirements) earned their cost — both caught defects the executors missed

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | 1 | 5 | Bootstrap-from-ingest (no greenfield questioning); autonomous full-pipeline run with user gates only on locked decisions |

### Cumulative Quality

| Milestone | Tests | Coverage | Zero-Dep Additions |
|-----------|-------|----------|-------------------|
| v1.0 | 142 | not measured | Prometheus text exposition hand-rolled (0 deps); tenacity added by explicit decision (1) |

### Top Lessons (Verified Across Milestones)

1. (single milestone so far — trends begin at v1.1) Push-before-claiming-CI-validated
2. (single milestone so far — trends begin at v1.1) Live enumeration over hardcoded lists in generated docs
