# Phase 5: Routing Decision & Documentation Refresh - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning

<domain>
## Phase Boundary

The last open routing decision (`model="auto"` fate) is closed and 4 named docs tell the truth about the shipped two-provider (Manifest + zai-coding), containerized, observable system. Delivers ROUT-01, DOCS-01, DOCS-02. Strictly scoped to the 4 ROADMAP-named docs + PROJECT.md decision record — deferred doc-staleness items from earlier phase reviews (AGENTS.md test-list, REQUIREMENTS.md Baseline text) are explicitly OUT of scope for this phase.

</domain>

<decisions>
## ROUT-01: model="auto" Fate

- **KEEP** `model="auto"` in `MODEL_ROUTING` exactly as-is — no routing code change (the entry already forwards `"auto"` verbatim to Manifest)
- **Rationale (verified against current Manifest docs, 2026-09-08):** the deprecated feature (2026-09-01) was specifically Manifest's *prompt-complexity classifier*. `auto` was NOT removed — it was redesigned: it now routes to the harness's Manifest-dashboard-configured **Default tier** (one model + up to 5 fallbacks), with automatic fallback recovery on any 4xx/5xx from the primary. This is a different mechanism than before (dashboard-tier routing vs. prompt-based classification) but is fully functional and adds automatic multi-model fallback our gateway didn't have before for `auto` traffic.
- Record this decision + rationale in `PROJECT.md` Key Decisions (locked, dated)
- Add/update a test asserting `resolve_provider("auto") == ("manifest", "auto")` is unchanged behavior (regression-proofing the decision, not new routing logic)

## DOCS-01 / DOCS-02: Doc Refresh Scope

Strictly the 4 ROADMAP-named docs, brought current with the shipped two-provider architecture:
- `docs/project-overview-pdr.md` — describe Manifest + zai-coding (not 8-native-provider); mark superseded FR/pricing requirements explicitly historical (do not delete — traceability)
- `docs/project-roadmap.md` — same current-architecture correction
- `docs/deployment-guide.md` — Docker/Compose deployment (Phase 3) + current env surface (`MANIFEST_API_KEY`, `ZAI_CODING_API_KEY`, `ZAI_CREDITS_5H/WEEK`, `LLM_API_KEY` fallback, `RATE_LIMIT_PER_KEY`, `ANALYTICS_RETENTION_DAYS`) — remove stale per-provider key/base-URL tables entirely
- `docs/code-standards.md` — file tree + "Adding a New Provider" recipe match shipped providers (`base.py`, `openai_compatible_base.py`, `manifest.py`, `zai_coding.py`) — no `MODEL_PRICING` step (removed in the 2026-04-19 Manifest cutover)

Out of scope: AGENTS.md test-list/mocking-bullet correction (Phase-2-deferred), REQUIREMENTS.md Baseline `/health` text (Phase-4-deferred) — left for a future pass per explicit user decision.

### Claude's Discretion
Doc-refresh prose style/organization — match each doc's existing structure, correct facts only, no rewrites beyond what's stale.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `analytics/routing.py` `MODEL_ROUTING["auto"] = ("manifest", "auto")`, `resolve_provider()` — unchanged, only a regression test added
- `.planning/PROJECT.md` existing `<decisions>` block format (ZAI-1..4) — ROUT-01 follows the same shape
- `docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md` §1.4 — original source of the "auto rides deprecated router" flag, now superseded by this phase's research

### Established Patterns
- Docs-only phase; no test infra changes beyond one routing regression test

### Integration Points
- PROJECT.md (new locked decision), analytics/routing.py + tests/test_routing.py (regression test only), 4 named docs

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

AGENTS.md test-file-list/mocking-bullet correction (from Phase 2 review) and REQUIREMENTS.md Baseline `/health` text (from Phase 4 review) — explicitly deferred to a future pass per user decision (strict ROADMAP scope for Phase 5).

</deferred>
