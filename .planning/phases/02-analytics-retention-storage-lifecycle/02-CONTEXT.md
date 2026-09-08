# Phase 2: Analytics Retention & Storage Lifecycle - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning

<domain>
## Phase Boundary

`request_logs` stops growing unbounded: configurable TTL retention, automatic purge (startup + periodic), WAL-safe non-blocking operation, reclaimable disk space. Delivers ANLT-01, ANLT-02. No observability stack (Phase 4), no deployment (Phase 3).

</domain>

<decisions>
## Implementation Decisions

### Retention Policy
- Env knob `ANALYTICS_RETENTION_DAYS` (int, default 90; `0` = keep-forever opt-out), documented in `.env.example` + README env table
- Policy applies to existing databases with no manual SQL

### Purge Mechanism
- Purge runs once at startup (after DB init, before/alongside writer start) and then every 6 hours inside the existing AnalyticsWriter background loop — no new scheduler dependency
- `DELETE FROM request_logs WHERE created_at < cutoff`, batched (≈1000 rows per commit) to keep WAL checkpoints short; never blocks response streaming (fire-and-forget preserved); WAL concurrent reads keep working during purge

### Space Reclamation
- `PRAGMA auto_vacuum=INCREMENTAL` set at DB creation; `PRAGMA incremental_vacuum` after each purge pass
- Existing databases: documented one-time migration (plain `VACUUM` to rebuild with auto_vacuum) — a docs note, not code
- Docs: README env table + AGENTS.md analytics section updated

### Verification
- Tests: purge correctness incl. boundary rows (exactly-old-enough purged, newest retained), periodic scheduling (6h tick), endpoints (`/v1/analytics/{summary,models,requests,credits}`) serve retained data correctly post-purge, streaming not blocked during purge
- Deterministic: injected clock/short intervals, no sleeps on real 6h cadence

### Claude's Discretion
None — all areas resolved.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `analytics/writer.py` AnalyticsWriter (Phase 1): background task loop, graceful stop — periodic purge rides this loop
- `analytics/db.py` AnalyticsDB (aiosqlite, WAL; `created_at` ISO-UTC strings + idx_logs_created_at index from initial schema — purge predicate is sargable)
- `config.py` Settings + `.env.example` pattern (Phase 1 added ANALYTICS_QUEUE_SIZE the same way)

### Established Patterns
- Batched writes + task_done; `PRAGMA journal_mode=WAL` at initialize
- pytest-asyncio conventions; deterministic time control patterns from Phase 1 research

### Integration Points
- `AnalyticsDB.initialize()` (pragma + startup purge call site), `AnalyticsWriter._run_loop` (periodic purge), `config.py`/`.env.example`, README env table, AGENTS.md analytics section

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
