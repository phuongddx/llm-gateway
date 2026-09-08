---
phase: 02-analytics-retention-storage-lifecycle
verified: 2026-09-08T08:32:17Z
status: passed
score: 13/14 must-haves verified
covered_files:
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-01-PLAN.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-02-PLAN.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-03-PLAN.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-01-SUMMARY.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-02-SUMMARY.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-03-SUMMARY.md
  - .planning/phases/02-analytics-retention-storage-lifecycle/02-REVIEW.md
  - config.py
  - analytics/db.py
  - analytics/writer.py
  - main.py
  - tests/conftest.py
  - tests/test_analytics_retention.py
  - tests/test_startup_validation.py
  - tests/test_analytics_writer.py
  - .env.example
  - README.md
  - AGENTS.md
covered_digest: "v1:sha256:dd4d80fecd10ccb269dde0860b84b83da623b8577330618056b3ea7488adde69"
behavior_unverified: 0 # every behavior-dependent truth has a passing behavioral test
overrides_applied: 0
human_verification:
  - test: "Review the ANALYTICS_RETENTION_DAYS warning wording in README.md:197 (and .env.example:30) as an operator would read it"
    expected: "The first-startup consequence (pre-existing rows older than 90 days — including everything already in the database — are purged) and the escape hatch (raise the TTL or set 0 before upgrading) are clear and discoverable enough that an operator with a long-lived data/analytics.db would NOT be surprised by data loss"
    why_human: "Prohibition ANLT-01 (02-03 must_haves, verification: judgment — 'MUST NOT let the retention default silently destroy an operator's pre-existing analytics history without warning'). Presence of all four facts is machine-verified (see T2); adequacy/clarity of the wording for a human operator is a judgment call no automated doc test in this repo can make. Flagged per the judgment-tier prohibition contract: unverified-prohibition — human review recommended; NOT a code gap."
---

# Phase 2: Analytics Retention & Storage Lifecycle Verification Report

**Phase Goal:** `request_logs` stops growing unbounded — long-running deployments keep analytics accurate, fast, and disk-bounded
**Verified:** 2026-09-08T08:32:17Z
**Status:** human_needed
**Re-verification:** No — initial verification (no prior `*-VERIFICATION.md` existed)

## Goal Achievement

### Observable Truths

Must-haves merged from ROADMAP Success Criteria (the contract — non-negotiable) + PLAN frontmatter truths (deduplicated against SCs) + both prohibitions. Plan truths map onto the SCs below: 02-01 TR1→T1/T2, TR2→T4, TR3→T11, TR4/TR5→T5, TR6→T3/T9, TR7→T12; 02-02 TR1→T6, TR2/TR3→T8, TR4→T9, TR5→T7; 02-03 TR1/TR2→T2, TR3→T13 (doc-truth evidence rolled into T2/T5).

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SC1/T1 — Operator can bound retention from `.env` (TTL days) with a documented default; knob validated at import (default 90, env var mapped, `0` = keep-forever opt-out, negative rejected naming `ANALYTICS_RETENTION_DAYS`, non-integer rejected) | ✓ VERIFIED | `config.py:32` field + `_validate_analytics_retention_days` (mode="after", message names the env var, mirrors queue-size validator); probes run: default==90, `-1`→ValidationError naming env var, `0` constructs, `"ninety"` rejected, `ANALYTICS_RETENTION_DAYS=30` env maps to field; 4 validator tests (`tests/test_startup_validation.py -k retention`) pass in full suite |
| 2 | SC1/T2 — Knob documented at both operator entry points with all four facts | ✓ VERIFIED | `.env.example:29-30` (comment `0 = keep forever` + `ANALYTICS_RETENTION_DAYS=90`, counts==1); README.md:197 row between `ANALYTICS_DB_PATH`(196) and `CORS_ORIGINS`(198), carrying purge cadence ("at startup and every 6 hours"), `0` opt-out, first-startup consequence + escape hatch, exact `sqlite3 data/analytics.db "VACUUM;"` (gateway stopped) — ordering + facts probe-verified |
| 3 | SC1 — Policy applies to an existing database without manual SQL | ✓ VERIFIED | `test_lifespan_startup_purge_removes_expired_rows_end_to_end` seeds a pre-existing file DB via raw sqlite3, runs the REAL lifespan, asserts survivors == `{"purge-e2e-fresh"}` and `writer.last_purged == 1`; passed (solo run + full suite) |
| 4 | SC2/T4 — Purge deletes exactly rows strictly older than cutoff (at-cutoff retained, 1µs-older purged) | ✓ VERIFIED | `test_purge_expired_boundary_trio_exact_cutoff_retained` passes; source: `DELETE … WHERE created_at < ?` via rowid-subquery (strict `<`, locked SQL predicate) |
| 5 | SC2/T5 — Purge mechanics: batched rowid-subquery DELETE with per-batch commits, termination + idempotence, `batch < 1` fail-fast, space reclaim, legacy guard | ✓ VERIFIED | `test_purge_multi_batch_deletes_all_expired` (2500→3 batches, second pass 0), `test_purge_reclaims_space_incremental_vacuum` (fresh file: `auto_vacuum`==2, freelist→0, page_count drops — pragma-based, no file-size), `test_vacuum_loop_terminates_on_legacy_auto_vacuum_zero_db` (bounded `wait_for`), `test_purge_rejects_batch_below_one_instead_of_spinning` (WR-01 fix: `ValueError` before any deletion, rows survive, 2s-bounded); source gates: `rowid IN` count==1, no direct-predicate delete, `_PURGE_BATCH==1000`, keyword-only `now`/`between_batches` |
| 6 | SC2/T6 — Rows purged automatically at startup AND periodically (6h tick, no drift) | ✓ VERIFIED | `_run()` opens with `await self._purge()` (first action) then deadline loop (`_PURGE_INTERVAL_S = 6*3600.0`, `timeout = max(0.0, next_purge - loop.time())`, `next_purge` recomputed after each purge); `test_periodic_tick_purges_reseeded_expired_rows` (interval 0.05s): row seeded AFTER startup removed by a LATER pass, `purges_run >= 2` |
| 7 | SC2/T7 — All four analytics endpoints serve only retained data after purge | ✓ VERIFIED | `test_endpoints_serve_retained_data_after_purge`: summary/models/requests/credits each exclude the two purged rows, include both fresh rows; fresh zai credits aggregate inside the 5h window; passed |
| 8 | SC3/T8 — Purging never blocks/delays streaming; mid-purge records lossless | ✓ VERIFIED | `test_burst_streams_unblocked_during_purge`: 20 concurrent streams, full token sequences + `[DONE]`, exactly-once rows, `dropped == 0`, `purges_run >= 2` interleaved; `test_interleave_queue_drained_between_purge_batches`: 30 records enqueued synchronously mid-purge all persist (between-batches `get_nowait` drain); `test_purge_between_batches_hook_awaited_per_batch`: hook fires 3× for 2500 rows |
| 9 | SC3/T9 — Lifespan request-readiness never awaits a purge (NFR-04) | ✓ VERIFIED | `test_startup_purge_does_not_block_lifespan_readiness`: with `purge_expired` gated on a never-set Event, lifespan reaches yield (entered-Event within 2s) while purge started (>=1) and not returned — fire-and-forget proven |
| 10 | SC3 — WAL-mode reads keep working during purge; on-disk growth bounded and purged space reclaimable | ✓ VERIFIED | `PRAGMA journal_mode=WAL` at initialize + `wal_checkpoint(PASSIVE)` after each pass (source); throwaway verifier probe: 3 `get_recent` reads executed between DELETE batches returned correct monotonically-shrinking totals (1550→550→50), no errors; reclaim + legacy one-liner documented (T2) and `auto_vacuum=INCREMENTAL` before schema (probe: index ordering holds) |
| 11 | T11 — Cutoff and stored `created_at` share the single canonical format; exact lexicographic comparison, integer days only | ✓ VERIFIED | `purge_expired` cutoff uses `datetime.now(timezone.utc).isoformat()` — identical producer call to `log_request`'s injected `created_at` default (db.py:113); review confirmed the pre-phase format at diff base `225a301` was identical (no drift for legacy rows); boundary trio exercises the exact compare; non-integer TTL rejected by pydantic (T1) |
| 12 | T12 — Wiring + Phase-1 record-path preservation + suite green | ✓ VERIFIED | `main.py:58` `retention_days=settings.analytics_retention_days` (count==1); AST check: every `log_request` call in writer.py inside `try`/`except Exception`; tracked-file suite **114 passed** (`git ls-files` scope; working-tree 117 = 114 + 3 pre-existing untracked `tests/test_playground.py` tests, also passing — not phase scope: phase diff touches exactly the 11 declared files) |
| 13 | Prohibition P1 (ANLT-02, test-tier) — purge logging MUST NOT emit row contents (ids, models, per-request data) | ✓ VERIFIED | Test-tier prohibition WITH wired enforcement: `test_purge_log_reports_count_and_no_row_contents` passes (solo run) — asserts count present in the "Analytics retention purge" log line and distinctive ids + model probe string absent from `caplog.text`; source: count-only `%d`-format log |
| 14 | Prohibition P2 (ANLT-01, judgment-tier) — retention default MUST NOT silently destroy pre-existing history without warning | ⚠️ FLAGGED (unverified-prohibition — human review recommended) | Judgment-tier: no automated doc test exists. LLM-judge verdict (non-authoritative): warning IS present and prominently placed — README env-table row itself (where the operator reads the knob) carries the first-startup consequence with the raise-TTL-or-set-0 escape hatch, `.env.example` comment carries the opt-out; all four facts machine-verified (T2). Adequacy of wording for a human operator → Human Verification item 1 |

**Score:** 13/14 must-haves verified (0 present-but-behavior-unverified — every behavior-dependent truth has a passing behavioral test)

### Required Artifacts

All phase artifacts exist, are substantive (no stubs), and are wired; docs cross-checked against shipped code (default 90 = `config.py`, 6h = `_PURGE_INTERVAL_S = 6*3600.0`, VACUUM one-liner byte-identical in README + AGENTS.md).

| Artifact | Expected | Status | Details |
|----------|----------|--------|--------|
| `config.py` | `analytics_retention_days` field + validator | ✓ VERIFIED | Field line 32; validator after queue-size pair, message names env var; `extra="ignore"` keeps old `.env` valid |
| `analytics/db.py` | `_PURGE_BATCH`, pragma ordering, `purge_expired`, between_batches | ✓ VERIFIED | 347 lines; all source gates pass (see T5); `except Exception` count==1 (purge propagates; containment lives in writer) |
| `analytics/writer.py` | retention/purge_interval kwargs, observables, `_purge`, `_drain_queued`, deadline `_run` | ✓ VERIFIED | ctor `['self','db','queue_size','retention_days','purge_interval_s']`; `wait_for(get())` count==1; `get_nowait`>=2; startup purge first action |
| `main.py` | lifespan passes `retention_days=settings.analytics_retention_days` | ✓ VERIFIED | One-line change at line 58; shutdown order untouched |
| `tests/test_analytics_retention.py` | tracer + storage/scheduling/integration proofs | ✓ VERIFIED | 14 tests (13 planned + WR-01 regression), all pass; repeat run stable (0.92s) |
| `tests/test_startup_validation.py` | 4 retention validator tests | ✓ VERIFIED | `def test_analytics_retention` count==4; `match="ANALYTICS_RETENTION_DAYS"` present |
| `tests/conftest.py` | `analytics_retention_writer` fixture, default fixture untouched | ✓ VERIFIED | New fixture present; `AnalyticsWriter(analytics_db, queue_size=1000)` default shape count==1 |
| `.env.example` / `README.md` / `AGENTS.md` | operator docs (02-03) | ✓ VERIFIED | Counts, ordering, all facts, `APScheduler\|cron`==0 in AGENTS.md; doc commits confined (`c3131db`: 2+1 lines; `a560f3a`: AGENTS.md only) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `config.py` settings | writer ctor | `main.py` lifespan `retention_days=settings.analytics_retention_days` | ✓ WIRED | count==1; e2e tracer proves the flow reaches `purge_expired` |
| writer `_run()` | `AnalyticsDB.purge_expired` | `_purge()` first action + deadline tick + `between_batches=self._drain_queued` | ✓ WIRED | source + tick/interleave/hook tests |
| `initialize()` | schema creation | `PRAGMA auto_vacuum=INCREMENTAL` strictly before `executescript(_SCHEMA)` | ✓ WIRED | index-ordering probe; legacy informational notice; read-only containment (deviation 1, curated `write_probe` abort preserved) |
| purge errors | consumer survival | `except Exception` + `logger.exception` in `_purge()` (db method propagates) | ✓ WIRED | source; `except Exception` count==1 in db.py |
| retention knob ↔ validator | `_validate_analytics_retention_days` mirrors `_validate_analytics_queue_size` | ✓ WIRED | mode="after", env-var-named message, placed directly after |
| `.env.example`/README/AGENTS ↔ shipped code | mirror contract | default 90, 6h cadence, `0` opt-out, VACUUM one-liner | ✓ WIRED | cross-checked byte-for-byte against `config.py`/`analytics/writer.py` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `analytics/db.py` | `cutoff` | `datetime.now(timezone.utc)` (or injected `now`) → real DELETE against `request_logs` | Yes — rowcounts returned and asserted | ✓ FLOWING |
| `analytics/writer.py` | `last_purged`/`purges_run` | return of real `purge_expired` calls | Yes — asserted ==1/==2500/… in tests | ✓ FLOWING |
| analytics endpoints | summary/models/requests/credits rows | real SQL aggregates over `request_logs` post-purge | Yes — endpoints test asserts exact retained sets | ✓ FLOWING |

No static returns, hardcoded empty data, or mock-terminated chains found on the retention path.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full tracked suite | `.venv/bin/python -m pytest $(git ls-files 'tests/test_*.py') -q` | **114 passed** | ✓ PASS |
| Full working-tree suite | `.venv/bin/python -m pytest tests/ -q` | **117 passed** (+3 pre-existing untracked playground tests) | ✓ PASS |
| Retention module repeat (timing stability) | `.venv/bin/python -m pytest tests/test_analytics_retention.py -q` | **14 passed** (0.92s) | ✓ PASS |
| e2e lifespan tracer (named) | `pytest tests/test_analytics_retention.py::test_lifespan_startup_purge_removes_expired_rows_end_to_end` | passed | ✓ PASS |
| Log-privacy prohibition (named, test-tier) | `pytest …::test_purge_log_reports_count_and_no_row_contents` | passed | ✓ PASS |
| WR-01 regression (named) | `pytest …::test_purge_rejects_batch_below_one_instead_of_spinning` | passed | ✓ PASS |
| Knob + signature probes | `python -c` (default/env/0/negative/non-integer; method + ctor signatures; `_PURGE_INTERVAL_S==21600.0`) | all asserts pass | ✓ PASS |
| Reads during active purge (verifier throwaway) | `purge_expired(90, between_batches=read)` on seeded in-memory DB | 3 mid-purge reads: totals 1550→550→50, final 50, deleted 2500 | ✓ PASS |
| Source gates | pragma ordering, rowid-subquery-only, AST try/except, wiring counts, doc facts/ordering | all asserts pass | ✓ PASS |

### Probe Execution

No `scripts/*/tests/probe-*.sh` probes exist or are declared by this phase; research probes were inlined as `python -c`/pytest acceptance gates — all executed above. N/A for script probes.

### Requirements Coverage

Plan frontmatter union: 02-01 `[ANLT-01, ANLT-02]`, 02-02 `[ANLT-02]`, 02-03 `[ANLT-01, ANLT-02]` → exactly `{ANLT-01, ANLT-02}`. REQUIREMENTS.md maps only ANLT-01/ANLT-02 to Phase 2 (both marked Complete; Traceability table agrees). **No orphaned requirements, no unmapped IDs.**

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| ANLT-01 | 02-01, 02-03 | Bound `request_logs` growth via `.env` TTL with documented default, applied to existing DBs without manual SQL | ✓ SATISFIED | T1 (knob+validator+tests), T2 (docs), T3 (existing-file e2e); prohibition P2 wording → human item 1 |
| ANLT-02 | 02-01, 02-02, 02-03 | Automatic purge (startup + periodic); endpoints serve retained data; streaming never blocked; WAL intact; disk bounded + reclaimable | ✓ SATISFIED | T3–T10; prohibition P1 test-tier enforcement green |

### Test Quality Audit

| Test File | Linked Req | Active | Skipped | Circular | Assertion Level | Verdict |
|-----------|-----------|--------|---------|----------|-----------------|---------|
| tests/test_analytics_retention.py | ANLT-01/02 | 14 | 0 | 0 | Value/Behavioral (exact id sets, exact counts, pragma values, sorted multiset equality) | ✓ OK |
| tests/test_startup_validation.py | ANLT-01 | 4 retention (19 total) | 0 | 0 | Value (exact defaults, `pytest.raises(match=…)`) | ✓ OK |
| tests/test_analytics_writer.py | regression | all | 0 | 0 | Value/Behavioral | ✓ OK |

Disabled-test scan across `tests/`: no `skip`/`skipif`/`xfail` markers. No circular expected-value generation (assertions are literal ids/counts, not captured outputs). No sleep with numeric literal >= 1 in the retention module (determinism levers only: 0.03–0.05s).

### Anti-Patterns Found

None. Debt-marker scan (`TBD|FIXME|XXX|TODO|HACK|PLACEHOLDER|coming soon|not yet implemented`) over all 11 phase files: zero matches. Empty-return/hollow-prop/console-only scans: nothing on the retention path. All three review findings (WR-01 batch<1 spin, IN-01 fixed-sleep flake, IN-02 NameError masking) verified FIXED in commits `5529dd1`, `4eb471e`, `09ab14c` with the WR-01 regression test present and passing.

### Decision Coverage

`check.decision-coverage-verify`: skipped — "No trackable decisions in CONTEXT.md" (02-CONTEXT.md uses plain locked-decision prose, not a `<decisions>` block). All four locked decisions named there (Retention Policy, Purge Mechanism, Space Reclamation, Verification) are visibly honored in the shipped artifacts (knob semantics, 6h-in-consumer-loop, auto_vacuum + VACUUM doc, injected-clock/injected-interval testing).

### Human Verification Required

### 1. Operator-facing warning adequacy (Prohibition ANLT-01, judgment-tier)

**Test:** Read the `ANALYTICS_RETENTION_DAYS` row at README.md:197 and the `.env.example` comment as an operator with a long-lived `data/analytics.db` would, before upgrading.
**Expected:** The first-startup consequence (pre-existing rows older than 90 days — "including everything already in the database" — are purged on first startup) and the escape hatch (raise the TTL or set `0` first) are clear and discoverable enough to prevent surprise data loss.
**Why human:** Presence of all four facts is machine-verified (T2); adequacy/clarity of wording for a human reader is a judgment call — no automated doc tests exist in this repo. Flagged as `unverified-prohibition — human review recommended` per the judgment-tier contract; it is NOT a code gap and does not block the phase's technical completeness.

This is the only human item. It is a docs-clarity confirmation, not a functional gap.

### Gaps Summary

**No gaps.** All 12 consolidated truths verified with behavioral evidence; both roadmap-level and plan-level must-haves hold in the codebase through HEAD (`8b49cce`, including all three review fixes); the phase diff touches exactly the 11 declared files; ANLT-01/ANLT-02 are satisfied and correctly marked Complete in REQUIREMENTS.md. The single `human_needed` driver is the judgment-tier ANLT-01 prohibition (doc-warning adequacy) — machine-checkable facts verified, human confirmation of wording requested.

Notes (informational, not findings):
- Working tree contains pre-existing untracked local files (`tests/test_playground.py` +3 passing tests, `server.log`, `repomix-*`, `plans/*`, `.omx/` etc.) — outside the phase diff; tracked-suite count is 114.
- `off_peak_share` deliberately unasserted in the endpoints test (wall-clock peak-window dependency) — recorded in 02-02-SUMMARY; acceptable.

---

_Verified: 2026-09-08T08:32:17Z_
_Verifier: Claude (gsd-verifier, Verify-P2)_
