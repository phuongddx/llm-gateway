## Conflict Detection Report

Ingest 2026-09-08 · MODE=new (bootstrap, no existing .planning context) ·
PRECEDENCE=ADR > SPEC > PRD > DOC · 26 docs: 0 ADR, 2 SPEC, 1 PRD, 23 DOC ·
0 UNKNOWN / 0 low-confidence classifications.

### BLOCKERS (0)

None.

### WARNINGS (0)

None. Only one PRD in the set — no competing acceptance variants. All
contradictions resolve cleanly by precedence (SPEC > PRD/DOC; no ADRs, no
locked decisions, so no LOCKED-vs-LOCKED or merge-mode checks apply).

### INFO (9)

[INFO] Cross-reference cycles are mutual navigation links — synthesis proceeded
  Found: DFS three-color cycle detection over the 26-doc cross-ref graph found cycles: parent plan ↔ phase fragments in plans/0416-2130-gateway-features-unified-api-routing-analytics/ (plan.md ↔ phase-01/02/03/04/05) and mutual "Related Docs" links among docs/project-overview-pdr.md, codebase-summary.md, system-architecture.md, code-standards.md, deployment-guide.md, project-roadmap.md
  Note: Cycles are bidirectional see-also navigation, not recursive content inclusion; synthesis is single-pass per document (cross_refs used for provenance only), so no synthesis loop is possible. Orchestrator directive for this ingest explicitly assigns the 0416/0417/0419 plan sets and the docs/ set for mining. All 26 docs synthesized. Graph depth well under the 50-traversal cap.

[INFO] Auto-resolved: SPEC > PRD on provider architecture
  Found: docs/project-overview-pdr.md (PRD) Goal 2 + FR-7..FR-13 require 8 native providers, incl. Gemini via google-genai SDK
  Note: docs/system-architecture.md (SPEC) and docs/codebase-summary.md show all non-GLM providers replaced 2026-04-19 by a single ManifestProvider — plans/0419-2337-manifest-provider-integration/phase-03 deleted 7 provider files and dropped google-genai; current state is 2 providers (manifest, zai-coding; zai-coding added 2026-09-07 for GLM). PRD entries are carried into intel/requirements.md marked SUPERSEDED (historical traceability, not current scope).

[INFO] Auto-resolved: SPEC > PRD on cost calculation
  Found: PRD FR-19 (+ FR-15 "cost", Goal 4) require per-request cost from a model pricing table; docs/project-roadmap.md Phase 2 lists "model pricing table with cost calculation" as delivered
  Note: docs/system-architecture.md (SPEC): calculate_cost() always returns 0.0 — Manifest handles billing internally; plans/0419-2337/.../phase-03-cleanup-old-providers-and-cost.md reduced it to a 0.0-stub preserving the signature for analytics compatibility; the 2026-09-07 zai-coding spec adds estimate_credits() as the only monetary metric (plan credits, not USD). PRD/roadmap cost claims recorded as historical.

[INFO] Auto-resolved: unknown-model handling — passthrough wins
  Found: PRD FR-2 and plans/0416-2130/.../phase-01-config-and-routing.md FR-1.3 specify strict routing-table lookup with HTTP 400 / ValueError listing available models for unknown names
  Note: plans/0419-2337/.../phase-02-routing-and-factory.md and docs/system-architecture.md (SPEC) mandate passthrough — unknown non-GLM → ("manifest", name-as-given); unknown glm-* → ("zai-coding", name) under the effective-key gate. No 400 for unknown models in the current architecture.

[INFO] Auto-resolved: SPEC > DOC on configuration surface
  Found: docs/deployment-guide.md documents per-provider env keys (OPENAI_API_KEY, DEEPSEEK_API_KEY, MOONSHOT_API_KEY, BYTEDANCE_API_KEY, GLM_API_KEY) and a 7-provider default-model/base-URL table
  Note: current config layer per docs/system-architecture.md (SPEC): MANIFEST_API_KEY + ZAI_CODING_API_KEY (+ ZAI_CREDITS_5H/WEEK), LLM_API_KEY as universal fallback, legacy LLM_PROVIDER/LLM_MODEL/LLM_BASE_URL retained. Deployment guide flagged stale (see intel/context.md "Documentation staleness map").

[INFO] Auto-resolved: code-standards provider-extension recipe stale
  Found: docs/code-standards.md file tree lists 8 provider files; "Adding a New Provider" step 4 instructs adding a MODEL_PRICING entry and step 3 a ("provider", model) routing entry
  Note: MODEL_PRICING was removed in the 2026-04-19 Manifest cutover; providers/ now contains base.py, openai_compatible_base.py, manifest.py, zai_coding.py. Naming/style/testing/error-handling sections remain valid. Doc-refresh backlog.

[INFO] Historical: provider failover/retry never landed in current architecture
  Found: plans/0416-2130/.../plan.md Key Decision "Failover: max 2 retries on transient errors, exclude failed provider" and phase-03-analytics-engine.md FR-3.7 (retry with alternative provider)
  Note: no retry/failover layer exists in the current architecture (docs/system-architecture.md request flow has none); docs/project-roadmap.md Phase 3 lists "Error retry" as planned future scope, and the zai-coding design (2026-09-07) locks no-fallback for GLM explicitly. Recorded as historical decision + future scope, not a current constraint.

[INFO] Temporal supersession within DOC tier: ChatRequest.model optionality
  Found: plans/0416-2130/.../phase-01-config-and-routing.md FR-1.1 makes the `model` field required (422 if missing)
  Note: current ChatRequest.model defaults to "auto" (docs/codebase-summary.md; corroborated by the 0419 plan's auto-routing examples and the SPEC routing model). Equal-precedence conflict resolved by recency of implemented state; no user action needed.

[INFO] Open item inherited from zai-coding spec: Manifest "auto" deprecation
  Found: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md §1.4 — Manifest deprecated its auto prompt-complexity router on 2026-09-01; this gateway's "auto" routing entry rides the deprecated feature and may behave differently; explicitly out of scope there, flagged for a future decision
  Note: surfaced in intel/context.md ("Manifest context and auto deprecation flag") and intel/SYNTHESIS.md open items for the roadmapper; not an ingest conflict.
