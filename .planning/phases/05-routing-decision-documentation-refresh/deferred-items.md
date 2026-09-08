# Deferred Items — Phase 5

Out-of-scope discoveries found during plan execution, logged per the executor's scope-boundary rule (not auto-fixed; pre-existing, unrelated to the current task's changes).

## 05-03 (docs/deployment-guide.md + docs/code-standards.md)

- **RESOLVED at v1.0 close (2026-09-08):** docs/deployment-guide.md:186 corrected to "`APP_API_KEY` has no default (empty) — the gateway aborts startup if unset; set it in `.env` before first run" (verified against config.py:21 and main.py:27).
