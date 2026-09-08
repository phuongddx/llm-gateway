---
phase: 05-routing-decision-documentation-refresh
reviewed: 2026-09-08T00:00:00Z
depth: deep
files_reviewed: 6
files_reviewed_list:
  - tests/test_routing.py
  - .planning/PROJECT.md
  - docs/project-overview-pdr.md
  - docs/project-roadmap.md
  - docs/deployment-guide.md
  - docs/code-standards.md
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 05: Code Review Report

**Reviewed:** 2026-09-08
**Depth:** deep (per-file read + cross-referenced every factual doc claim against the live source: `config.py`, `analytics/routing.py`, `providers/__init__.py`, `main.py`, `tests/conftest.py`, `Dockerfile`, `docker-compose.yml`, `Makefile`, `.planning/ROADMAP.md`, `.planning/REQUIREMENTS.md`)
**Files Reviewed:** 6 (commits 0e4071e, 8862621, ac42d69, 377ebcc, 22f1738, 092cb72, ce7d7ba, 7415920, de9adee)
**Status:** issues_found (2 warnings, 1 info — no blockers)

## Summary

This is a docs-only + one regression-test-file phase; there is no application/runtime code to review for classic bugs. Adversarial focus was therefore: (1) does the new `tests/test_routing.py` content actually prove what its docstrings and the ROUT-01 decision claim, verified by reading `analytics/routing.py`'s live `resolve_provider()`/`MODEL_ROUTING`; and (2) does every rewritten factual claim in the four doc files (env var defaults/table shape, Docker/Compose/Makefile targets, health endpoints, provider file layout, test file inventory, error-handling shape, factory dispatch style) match the current codebase exactly, given the phase's explicit goal is "every doc tells the truth about the shipped system."

**Test file (`tests/test_routing.py`):** Both new tests are correct and non-tautological. `resolve_provider()`'s key-gate branch (`if provider_name != "zai-coding" or _zai_key_present(): return entry`) only diverts `zai-coding`-provider entries; `"auto"`'s table entry is `("manifest", "auto")`, so the gate is structurally unreachable for it exactly as the docstrings assert — confirmed by reading the live implementation, not just trusting the comment. No bug found here.

**Deferred item confirmed as correct scope discipline:** the `deployment-guide.md:186` "Default `APP_API_KEY` is `changeme`" claim is stale (`config.py`'s real default is `""`; `changeme` is only a test-fixture convenience value in `tests/conftest.py`), and it correctly falls outside plan 05-03's six required corrections (env-var reference table, Docker section, provider-key troubleshooting names). Logging it to `deferred-items.md` instead of drive-by-fixing it was the right call — not a missed fix.

**The doc rewrites are, on the whole, unusually accurate** — every checked claim in `deployment-guide.md` (the 12-field `config.py` `Settings` table incl. defaults, `/health/live` + `/health/ready` replacing bare `/health`, Makefile `docker-build`/`docker-up`/`docker-down` targets, `docker-compose.yml`'s `gateway-data` volume/`env_file: .env`/`restart: unless-stopped`/healthcheck cadence, the Prometheus `observability` Compose profile pinned to `prom/prometheus:v3.14.0` on port 9090) and `code-standards.md` (4-file provider layout, 15-file test inventory enumerated exactly, `if`/`else` factory dispatch that never raises, nested `{message, type[, code]}` SSE error shape, `ASGITransport`-based `auth_headers()` fixture) matches the live code verbatim. Two accuracy defects were found in `project-overview-pdr.md`, plus one stale example left uncorrected in `code-standards.md`.

## Warnings

### WR-01: FR-11 table row contradicts its own status column

**File:** `docs/project-overview-pdr.md:44` (Requirements table)
**Issue:** The row reads: `| FR-11 | Route `glm-*` models to the z.ai GLM Coding Plan endpoint (superseded 2026-04-19 as a native provider, re-routed 2026-09-07 to the coding endpoint — current Baseline contract, not historical) | Must | Superseded (2026-04-19) |`. The parenthetical explicitly asserts the *current* form is "Baseline, not historical" (repeated again in the footnote immediately below the table: "FR-11's *current* form ... is Baseline, not historical"), yet the Status column for the same row says `Superseded (2026-04-19)`. A reader scanning only the Status column will conclude GLM-Coding-Plan routing is dead, which is false — it is live, shipped, and covered by ROUT-01/the new regression tests. `.planning/REQUIREMENTS.md` avoids this exact trap by splitting the same fact into two separate entries: a Historical `REQ-FR-11` bullet ("Native GLM (Z.AI) provider — superseded") and a distinct Baseline bullet ("GLM routing (current form of REQ-FR-11)"). `project-overview-pdr.md`'s single-row FR-11 does not have that luxury and ends up self-contradictory instead.
**Fix:** Split into two rows/statuses (matching the REQUIREMENTS.md pattern), or change the Status column to something like `Superseded as native provider (2026-04-19); current form Done` so the column doesn't flatly contradict the adjacent text.

### WR-02: "Phase 4" cross-reference has no matching phase in the cited document

**File:** `docs/project-overview-pdr.md:75-77` (Out of Scope section)
**Issue:** Three bullets were edited in the same commit (377ebcc):
```
- Request queuing or rate limiting (Rate limiting delivered — Phase 4; request queuing/backpressure remains N/A)
- Docker containerization (Delivered — Phase 3, see project-roadmap.md)
- Structured logging or observability (Prometheus, OpenTelemetry) (Delivered — Phase 4)
```
The Docker line explicitly cites its source (`project-roadmap.md`'s Phase 3), establishing the reader's expectation that "Phase N" means a phase number in that same doc. But `docs/project-roadmap.md` only defines three phases (1: Core Gateway, 2: Multi-Provider Routing & Analytics, 3: Production Readiness) — there is no Phase 4 anywhere in it; Rate limiting and Prometheus are in fact listed inside project-roadmap.md's own *Phase 3* table. "Phase 4" here is actually referring to `.planning/ROADMAP.md`'s GSD-internal phase numbering (Phase 4: Observability & Resilience) — a different, unrelated numbering scheme not mentioned or disambiguated anywhere in this doc. A reader who follows the Docker line's citation pattern and looks for "Phase 4" in `project-roadmap.md` will find nothing.
**Fix:** Either cite `.planning/ROADMAP.md` explicitly for the Phase 4 references (disambiguating the two numbering schemes), or align with `project-roadmap.md`'s own numbering and say "Phase 3" for all three bullets (matching that this project-roadmap.md's Phase 3 table already lists Docker, Prometheus, and Rate limiting side by side under one phase).

## Info

### IN-01: Stale `_ROLE_MAP` naming-convention example left uncorrected

**File:** `docs/code-standards.md:10`
**Issue:** The Constants row was edited in this phase (commit 7415920) to replace two of its three examples (`MODEL_PRICING` → `GLM_CANONICAL`, and the env-var row alongside it), but the first example, `_ROLE_MAP`, was left untouched: `| Constants | UPPER_SNAKE | `_ROLE_MAP`, `MODEL_ROUTING`, `GLM_CANONICAL` |`. `_ROLE_MAP` does not exist anywhere in the current codebase (confirmed by search across `analytics/`, `providers/`, `routes/`, and all top-level `.py` files) — it belonged to the old `providers/gemini.py`, which was removed in the Manifest cutover. Since this phase's explicit deliverable is a doc that "tells the truth about the shipped system," and this exact table row was already being edited, leaving one of its three examples pointing at a removed identifier is an inconsistency worth closing out.
**Fix:** Replace `_ROLE_MAP` with a constant that still exists, e.g. `GLM_CANONICAL_FLASH` or `AVAILABLE_MODELS` (both defined in `analytics/routing.py`).

---

_Reviewed: 2026-09-08_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
