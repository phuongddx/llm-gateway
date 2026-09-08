---
phase: 05-routing-decision-documentation-refresh
plan: 01
subsystem: testing
tags: [routing, pytest, decision-record, planning-docs]

# Dependency graph
requires: []
provides:
  - "Two named regression tests proving resolve_provider(\"auto\") == (\"manifest\", \"auto\") under both z.ai key states"
  - "Locked, dated ROUT-01 decision record in PROJECT.md (KEEP model=\"auto\" unchanged)"
affects: [05-02, 05-03]

# Actuals (#2632)
actuals:
  tokens: 1125
  tasks: 2
  commits: 2

# Tech tracking
tech-stack:
  added: []
  patterns: []

key-files:
  created: []
  modified:
    - tests/test_routing.py
    - .planning/PROJECT.md

key-decisions:
  - "ROUT-01: KEEP model=\"auto\" in MODEL_ROUTING unchanged — Manifest's 2026-09-01 deprecation removed the prompt-complexity classifier, not the auto keyword; auto now rides the Manifest-dashboard Default tier with automatic fallback"

patterns-established: []

requirements-completed: [ROUT-01]

coverage:
  - id: D1
    description: "resolve_provider(\"auto\") proven unaffected by z.ai key state via two named regression tests"
    requirement: "ROUT-01"
    verification:
      - kind: unit
        ref: "tests/test_routing.py#test_resolve_auto_unaffected_by_zai_key_state"
        status: pass
      - kind: unit
        ref: "tests/test_routing.py#test_resolve_auto_stays_manifest_even_with_zai_key"
        status: pass
    human_judgment: false
  - id: D2
    description: "PROJECT.md records exactly one locked, dated ROUT-01 decision block plus a Key Decisions table row"
    requirement: "ROUT-01"
    verification:
      - kind: other
        ref: "grep -c 'id=\"ROUT-01\"' .planning/PROJECT.md == 1; grep -c 'ROUT-01' .planning/PROJECT.md == 4"
        status: pass
    human_judgment: false

# Metrics
duration: 1min
completed: 2026-09-08
status: complete
---

# Phase 5 Plan 1: ROUT-01 Routing Decision & Regression Tests Summary

**Closed the `model="auto"` deprecation question with two named regression tests plus a locked, dated ROUT-01 decision block in PROJECT.md — no routing code changed.**

## Performance

- **Duration:** 1 min
- **Started:** 2026-09-08T14:53:23Z
- **Completed:** 2026-09-08T14:54:40Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Replaced the single `test_resolve_auto` test with two named regression tests (`test_resolve_auto_unaffected_by_zai_key_state`, `test_resolve_auto_stays_manifest_even_with_zai_key`) that pin `resolve_provider("auto") == ("manifest", "auto")` under both z.ai key states
- Recorded the ROUT-01 decision (KEEP `model="auto"` unchanged) as a locked, dated `<decisions>` block in PROJECT.md matching the ZAI-1..4 shape, cross-referencing the two new tests
- Resolved the "future decision" forward-reference in the ZAI locked-decisions paragraph and added a Key Decisions table row

## Task Commits

Each task was committed atomically:

1. **Task 1: ROUT-01 regression tests — `auto` stays pinned to Manifest** - `0e4071e` (test)
2. **Task 2: Record the ROUT-01 decision in PROJECT.md** - `8862621` (docs)

_No TDD tasks in this plan; each task is a single commit._

## Files Created/Modified
- `tests/test_routing.py` - Replaced `test_resolve_auto` with two named ROUT-01 regression tests
- `.planning/PROJECT.md` - Added locked ROUT-01 decision block, resolved cross-reference clause, added Key Decisions table row

## Decisions Made
- ROUT-01: KEEP `model="auto"` in `MODEL_ROUTING` exactly as-is — no routing code change. Manifest's 2026-09-01 deprecation removed the prompt-complexity classifier specifically, not the `auto` keyword; `auto` now routes to the Manifest-dashboard-configured Default tier (one model + up to 5 fallbacks) with automatic fallback recovery, verified against current Manifest docs 2026-09-08.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- ROUT-01 fully closed (decision recorded + regression-tested); no blockers for 05-02/05-03 (independent doc-refresh plans, different files)
- Full test suite green: 142 passed (141 baseline + 1 net new test, since one test was replaced by two)

---
*Phase: 05-routing-decision-documentation-refresh*
*Completed: 2026-09-08*

## Self-Check: PASSED

All created/modified files exist (`tests/test_routing.py`, `.planning/PROJECT.md`, this SUMMARY.md) and both task commits (`0e4071e`, `8862621`) are present in git history.
