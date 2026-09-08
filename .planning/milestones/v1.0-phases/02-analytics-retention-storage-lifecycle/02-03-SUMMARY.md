---
phase: 02-analytics-retention-storage-lifecycle
plan: 3
subsystem: analytics
tags: [docs, retention, env-knob, readme-env-table, agents-md, vacuum-migration, sqlite, operator-surface, analytics-retention]

# Dependency graph
requires:
  - phase: 02-analytics-retention-storage-lifecycle
    provides: "02-01/02-02's shipped retention lifecycle — analytics_retention_days knob (config.py), purge_expired + auto_vacuum=INCREMENTAL (analytics/db.py), startup-first-action purge + _PURGE_INTERVAL_S=21600.0 6h tick + between-batch drain (analytics/writer.py) — the surfaces these documents describe"
provides:
  - Operator surface for the retention knob — .env.example row (ANALYTICS_RETENTION_DAYS=90, 0-keeps-forever comment) restoring the AGENTS.md mirror contract broken by 02-01
  - README Gateway Settings row carrying all four operator facts: startup + 6h purge cadence, 0 opt-out, first-startup legacy-purge consequence with raise-TTL-or-set-0 escape hatch, one-time sqlite3 data/analytics.db "VACUUM;" migration (gateway stopped)
  - AGENTS.md truthfully describing the shipped lifecycle at four spots — Key Directories row, Code Conventions Async bullet (purge rides the consumer task), analytics/db.py bullet (purge_expired + pragma posture), .env.example enumeration (knob + VACUUM note)
  - Phase 2 closes with every doc claim true of the running system (cross-checked: default 90, 6h cadence, 0 opt-out, locked one-liner byte-identical)
affects: [verify-work UAT Phase 2 (doc wording review), future agent sessions reading AGENTS.md, Phase 3 deployment docs]

# Actuals (#2632) — same estimateTokens scale (chars/4 over the realized diff), never a harness count.
actuals:
  tokens: 1333    # git diff 5333 chars / 4 (estimate was 10000 — plan over-estimated ~7.5x, same over-estimation bias as 02-01/02-02)
  tasks: 2
  commits: 2      # MEASURED: git rev-list --count 60519a0..HEAD (ledger gsd-plan-head-before-02-03)
plan_head_before: 60519a072bb69de9a6defc85fe6b88aa50f77fc5

# Tech tracking
tech-stack:
  added: []       # docs-only plan — zero new deps
  patterns:
    - "Destructive-default disclosure in the env-table row itself: cadence + opt-out + first-startup consequence with escape hatch + one-time migration command in one telegraphic cell (warning lives where the operator reads the knob, not in a footnote)"

key-files:
  created: []
  modified:
    - .env.example
    - README.md
    - AGENTS.md

key-decisions:
  - ".env.example knob appended exactly per the plan's measurable diff gate — comment + assignment pair directly after ANALYTICS_QUEUE_SIZE (2 added lines, no extra separator), keeping the acceptance criterion's literal git-diff shape (1 line README, 2 lines .env.example)"
  - "README row carries all four TR2 facts in one cell, including the 'including everything already in the database' first-startup consequence (the real data/analytics.db holds 23 rows, all >90d — first default purge empties it) and the raise-the-TTL-or-set-0 escape hatch"
  - "ANALYTICS_RETENTION_DAYS appears exactly twice in AGENTS.md (env enumeration + Async bullet's 'TTL from' clause), meeting the >=2 verify floor; the locked VACUUM one-liner is byte-identical in README and AGENTS.md"
  - "Async bullet names _PURGE_INTERVAL_S as the cadence source and describes the between-batch drain without introducing any second-task or scheduler claim (grep APScheduler|cron == 0)"
  - "requirements-completed carries [ANLT-01, ANLT-02] — the final mark-complete lands with this plan per the cross-plan decision recorded in 02-01/02-02"

patterns-established:
  - "Pattern: when a locked docs note spans surfaces (README env table + AGENTS.md enumeration), keep the command string byte-identical everywhere and assert it with a python -c presence check — no automated doc framework needed for presence-truth"

requirements-completed: [ANLT-01, ANLT-02]  # per cross-plan decision: code halves proven in 02-01/02-02, docs half here

# Coverage metadata (#1602)
coverage:
  - id: D1
    description: "Retention knob discoverable at both operator entry points: .env.example row (comment + ANALYTICS_RETENTION_DAYS=90) and README Gateway Settings row beside ANALYTICS_DB_PATH carrying cadence, 0 opt-out, first-startup consequence + escape hatch, and the one-time VACUUM migration (gateway stopped)"
    requirement: ANLT-01
    verification:
      - kind: other
        ref: "python -c assertions on .env.example + README.md (assignment/comment counts == 1, row ordering DB_PATH < RETENTION < CORS, all four facts present incl. exact command string)"
        status: pass
    human_judgment: true
    rationale: "Prohibition ANLT-01 resolution: the warning wording's clarity/discoverability is reviewed at verify-work — no automated doc tests exist in this repo beyond the presence assertions that ran"
  - id: D2
    description: "AGENTS.md truthfully describes the shipped retention lifecycle at the four named spots — Key Directories row (purge_expired + auto_vacuum=INCREMENTAL), Async bullet (purge rides the consumer task: startup first action, 6h tick, between-batch drain), analytics/db.py bullet (batched rowid-subquery DELETE, guarded incremental_vacuum, pre-schema pragma no-op on legacy DBs), .env.example enumeration (knob + VACUUM note)"
    requirement: ANLT-02
    verification:
      - kind: other
        ref: "python -c assertions on AGENTS.md (purge_expired x2, auto_vacuum=INCREMENTAL x2, ANALYTICS_RETENTION_DAYS x2 incl. canonical-list bullet, exact VACUUM cmd x1, 'every 6 hours' x2, APScheduler|cron grep == 0, diff confined to 4 hunks)"
        status: pass
      - kind: other
        ref: "cross-check vs shipped code: config.py analytics_retention_days=90, writer.py _PURGE_INTERVAL_S = 6 * 3600.0"
        status: pass
    human_judgment: false

# Metrics
duration: 5min
completed: 2026-09-08
status: complete
---

# Phase 02 Plan 3: Operator Docs — Retention Knob, First-Purge Warning, VACUUM Migration Summary

**Retention knob documented at both operator entry points (.env.example + README row with first-startup legacy-purge warning, escape hatch, and one-time `sqlite3 data/analytics.db "VACUUM;"` migration) and AGENTS.md's four analytics spots brought level with the 02-01/02-02 shipped purge lifecycle**

## Performance

- **Duration:** 5 min (08:00:57Z → 08:05:53Z)
- **Started:** 2026-09-08T08:00:57Z
- **Completed:** 2026-09-08T08:05:53Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- `.env.example` gains the knob row (`# Analytics log retention in days (0 = keep forever)` + `ANALYTICS_RETENTION_DAYS=90`) — the AGENTS.md mirror contract (env example mirrors Settings fields exactly) holds again after 02-01 introduced the field
- README Gateway Settings gains the `ANALYTICS_RETENTION_DAYS` row (No / `90`) directly beside `ANALYTICS_DB_PATH`, carrying all four operator facts: rows older than the TTL purged at startup and every 6 hours; `0` keeps logs forever; with the default, pre-existing rows older than 90 days — including everything already in the database — are purged on the first startup (raise the TTL or set `0` first to keep them); existing databases need the one-time `sqlite3 data/analytics.db "VACUUM;"` migration (gateway stopped) to make purged space reclaimable
- AGENTS.md's four spots now tell the truth about the shipped lifecycle: Key Directories `analytics/` row (TTL retention lifecycle — `purge_expired` + `auto_vacuum=INCREMENTAL`), Code Conventions Async bullet (same consumer task runs the purge — startup first action + 6h `_PURGE_INTERVAL_S` tick + between-batch queue drain, never a second task), `analytics/db.py` bullet (`purge_expired(retention_days)` batched rowid-subquery `DELETE`, guarded `incremental_vacuum` + passive checkpoint, pragma before schema, silent no-op on legacy DBs), and the `.env.example` enumeration (knob + VACUUM note)
- Every doc claim cross-checked against the running system: default 90 (config.py), 6-hour cadence (`_PURGE_INTERVAL_S = 6 * 3600.0`), 0 opt-out, locked one-liner byte-identical in both docs; full suite stays at 116 passed (docs-only, baseline preserved)
- Phase 2 closes: ANLT-01/ANLT-02 requirement completion lands with this plan per the cross-plan decision recorded in 02-01/02-02

## Task Commits

Each task was committed atomically:

1. **Task 1: .env.example knob row + README env-table row with VACUUM migration note and first-startup consequence** - `c3131db` (docs)
2. **Task 2: AGENTS.md analytics section — purge_expired, auto_vacuum, env enumeration, 6h tick** - `a560f3a` (docs)

## Files Created/Modified
- `.env.example` - knob row appended to the analytics tail block (comment + `ANALYTICS_RETENTION_DAYS=90`)
- `README.md` - one row inserted in the Gateway Settings table between `ANALYTICS_DB_PATH` and `CORS_ORIGINS`; no other section touched
- `AGENTS.md` - four spots updated (Key Directories row, Async bullet, `analytics/db.py` bullet, `.env.example` bullet); docs-drift warning block and all other sections untouched

## Decisions Made
- Honored the plan's measurable diff gate literally: the `.env.example` pair was appended without an extra separator line so the acceptance criterion's "exactly two added lines" holds (the action text names exactly two lines of new content and "nothing else in the file changes")
- README row phrasing merges the `<action>` telegraphic order with TR2's "including everything already in the database" clause so both the task gate and the must-have truth are satisfied by one cell
- The second `ANALYTICS_RETENTION_DAYS` mention in AGENTS.md (verify floor >= 2) was placed in the Async bullet's "TTL from" clause — the natural spot tying the knob to the purge behavior it drives
- Otherwise followed plan as written (all wording anchored to the landed `analytics/db.py` / `analytics/writer.py` surfaces, per the plan's "describe what is" instruction)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- None — the environment's `od` binary is shadowed by a broken node shim (unrelated pre-existing workstation issue, out of scope); trailing-byte check rerun via `.venv/bin/python` instead

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 2 (Analytics Retention & Storage Lifecycle) is complete: knob (02-01) → scheduling + integration proofs (02-02) → operator docs (02-03), 116 tests green throughout
- The one-time legacy migration is documented, not automated — an operator with a pre-02 `data/analytics.db` who wants purged space reclaimed runs `sqlite3 data/analytics.db "VACUUM;"` once with the gateway stopped (README + AGENTS.md both carry it)
- No stubs, no skipped tests, no unrun verifications

## Self-Check: PASSED

- All 3 modified files exist on disk (checked with `[ -f ]`)
- Both task commits found in history (c3131db, a560f3a); measured commit count from ledger base 60519a0 = 2 (no uncommitted code changes)
- Task 1 gates re-run: automated verify PASS; AC1 token count == 1; AC2 row ordering DB_PATH(195) < RETENTION(196) < CORS(197); AC3 four description facts present; AC4 diff exactly 2 added lines (.env.example) + 1 (README.md), zero deletions
- Task 2 gates re-run: automated verify PASS (purge_expired 2, auto_vacuum=INCREMENTAL 2, ANALYTICS_RETENTION_DAYS 2, VACUUM cmd 1, every-6-hours 2); canonical-list bullet carries the knob; APScheduler|cron grep == 0; diff confined to the four named hunks
- Plan-level verification: code cross-check PASS (default 90, 6*3600.0, opt-out 0, byte-identical one-liner); full suite 116 passed in 2.75s

---
*Phase: 02-analytics-retention-storage-lifecycle*
*Completed: 2026-09-08*
