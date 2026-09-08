# Context Intel (ingest 2026-09-08)

Topic-keyed running notes with source attribution. Historical/superseded claims
are marked as such and are NOT current requirements.

## Project identity and purpose
- LLM Gateway: FastAPI-based API gateway exposing an OpenAI-compatible chat
  completions endpoint; clients specify a `model`, the gateway resolves the
  provider; all responses stream via SSE; request analytics (latency, TTFT,
  tokens) logged to SQLite. Goal: avoid vendor lock-in through a single
  consistent interface with usage visibility. Zero infrastructure dependencies,
  single `.env` config.
- source: docs/project-overview-pdr.md

## Architecture evolution timeline
- Era 0 — single-provider prototype: Gemini-only proxy (`LLM_PROVIDER` +
  `LLM_API_KEY`), ~1200 LOC; identified gap was missing infrastructure
  (routing, provider abstraction, observability), not technical debt.
- Era 1 (2026-04-16) — multi-provider router: model-based routing, 6–7 native
  OpenAI-compatible providers + native-SDK Gemini, SQLite analytics, REST
  analytics endpoints, cost table. Big-bang delivery; code review caught 4
  critical issues (auth token extraction, null guards on empty streams,
  create_task exception handling, missing route guards on analytics endpoints).
- Era 2 (2026-04-17) — playground web UI (static HTML/JS served by FastAPI).
- Era 3 (2026-04-19) — Manifest cutover: ALL native providers replaced by a
  single ManifestProvider smart router; per-provider keys collapsed to
  `MANIFEST_API_KEY`; cost calc stubbed to 0.0; `google-genai` dropped.
  Explicitly `supersedes: 0416-2130-gateway-features-unified-api-routing-analytics`.
- Era 4 (2026-09-07) — zai-coding: GLM traffic routed to the z.ai GLM Coding
  Plan endpoint (opt-in via `ZAI_CODING_API_KEY`) with credit-burn analytics.
- source: docs/journals/2026-04-16-multi-provider-router-and-analytics.md;
  plans/0416-2130-gateway-features-unified-api-routing-analytics/plan.md;
  plans/0419-2337-manifest-provider-integration/plan.md;
  docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md

## Current architecture state (pointer)
- Two providers (manifest default, zai-coding key-gated for `glm-*`), two
  SPEC-grade sources agree: `docs/system-architecture.md` and
  `docs/codebase-summary.md` (~1,800 LOC, ~24 Python files + 3 static).
  Full contracts live in `constraints.md` (same ingest). Notable current
  surface: `GET /v1/analytics/credits`, `credits_used` column, 29-entry
  routing table with canonicalized GLM aliases, `model` default `"auto"`.
- source: docs/system-architecture.md; docs/codebase-summary.md

## Superseded 8-provider architecture (historical reference only)
- HISTORICAL (replaced 2026-04-19): per-provider classes with base URLs —
  openai `https://api.openai.com/v1` (gpt-4o default), deepseek
  `https://api.deepseek.com`, moonshot `https://api.moonshot.cn/v1` (kimi-k2.5),
  glm `https://api.z.ai/api/paas/v4` (glm-4.7-flash), minimax
  `https://api.minimax.chat/v1` (MiniMax-Text-01), bytedance
  `https://ark.cn-beijing.volces.com/api/v3` (endpoint-ID models), gemini via
  native google-genai SDK. Per-provider env keys `OPENAI_API_KEY`,
  `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `BYTEDANCE_API_KEY`, `GLM_API_KEY`
  (Gemini/MiniMax rode `LLM_API_KEY`).
- HISTORICAL pricing table `MODEL_PRICING` (USD per 1M in/out): gpt-4o
  2.50/10.00, gpt-4o-mini 0.15/0.60, o3 2.00/8.00, gemini-2.5-flash 0.15/0.60,
  glm-4-flash 0.01/0.01, MiniMax-Text-01 0.01/0.01, deepseek-chat 0.27/1.10,
  deepseek-reasoner 0.55/2.19, kimi-k2.5 0.60/2.50, kimi-k2-thinking 0.60/2.50,
  moonshot-v1-128k 0.02/0.02. Useful only if direct providers are ever
  re-added.
- source: docs/deployment-guide.md; docs/code-standards.md;
  plans/0416-2130-gateway-features-unified-api-routing-analytics/phase-03-analytics-engine.md

## Playground web UI — decisions and non-goals
- Key decisions: static HTML + vanilla JS (YAGNI — playground, not product);
  fetch + ReadableStream for POST-based SSE; API key held in JS memory only
  (session-only login, dev-grade); CDN marked.js/highlight.js/DOMPurify (no
  build step, no npm); localStorage conversation persistence. Design: dark
  terminal aesthetic (bg #1a1a2e, accent #00d4aa, monospace), collapsible
  280px sidebar, mobile <768px overlay. Mount-order constraint: `/playground`
  route registered BEFORE the catch-all `/static` StaticFiles mount, which
  comes AFTER all API routers.
- Explicit non-goals: cookie/session auth (defer until playground goes
  public), conversation sharing/export, file upload/multimodal, user accounts,
  light-mode toggle.
- source: plans/0417-2203-playground-web-ui/plan.md;
  plans/0417-2203-playground-web-ui/phase-01.md;
  plans/0417-2203-playground-web-ui/phase-02.md

## z.ai GLM Coding Plan economics and risks
- Max plan: ~$80/month billed quarterly; 28,000 credits per rolling 5-hour
  window, 140,000/week; ~30 concurrent requests; exactly two models (GLM-5.3,
  GLM-5.3-Flash); quota exhaustion does NOT fall back to account balance —
  calls fail until reset. Credit formula `(input×I + cached×C + output×O)/10k`,
  50% off-peak (peak Mon–Fri 14:00–18:00 UTC+8). Heavy agentic turn ≈36.6
  credits; Max weekly quota ≈3,800 heavy turns; breakeven ≈300 heavy turns/week
  vs pay-as-you-go (~$230/wk equivalent); cache-hit coding traffic ≈5–10× cost
  reduction; light chat traffic would favor a lower tier.
- Risks: ToS — plan "strictly limited to officially supported tools"; custom
  gateway not on list (enforcement stated as endpoint/model restrictions,
  error 1113 / balance billing; account-level action possible) — user
  explicitly accepted. Quota exhaustion mid-session → GLM unavailable up to 5h
  (mitigated by distinct client-visible quota error + credits analytics).
  z.ai may revise quota model/endpoint — endpoint/model IDs/multipliers
  confined to one provider module + constants block; quotas env-configurable.
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md

## Manifest context and "auto" deprecation flag
- Manifest deprecated only its auto prompt-complexity router on 2026-09-01;
  the gateway product and pinned-model routing continue. Open item: this
  gateway's `"auto"` routing entry rides the deprecated feature and may behave
  differently — explicitly out of scope for zai-coding work, flagged for a
  future decision. GLM remains reachable via Manifest pay-per-token; unsetting
  `ZAI_CODING_API_KEY` reverts all GLM routing to Manifest.
- Manifest cutover accepted risk: Manifest API downtime = all requests fail —
  single point of failure acceptable for personal use; direct provider can be
  re-added later via the ABC.
- source: docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md;
  plans/0419-2337-manifest-provider-integration/plan.md

## Stress-support chatbot — future direction (not gateway scope)
- Planned product-specific MVP on top of llm-gateway (plan folder
  `plans/260418-1132-stress-support-chatbot-rag-mvp/`, NOT in this ingest set):
  self-hosted Gemma 4 E4B instruct via vLLM (matches OpenAI-compatible provider
  design), local document retrieval (RAG), dedicated `/v1/stress/chat` route,
  rule-first crisis gating. Decisions: keep generic `/v1/chat/completions`
  unchanged; product orchestration in a new route; MVP stateless and text-only.
  Risks: safety quality (not token cost) is the real problem; bilingual
  retrieval needs the right embedding model early; cheap hosting may be too
  weak for latency. Preconditions before implementation: target language,
  hosting target, crisis jurisdiction, source document formats.
- source: docs/journals/2026-04-18-stress-chatbot-plan.md

## Production readiness backlog (planned, not started)
- Roadmap Phase 3: Docker image (multi-stage, non-root) + Compose (High);
  CI/CD GitHub Actions lint/test/build/push (High); Prometheus metrics —
  request count, latency histogram, error rate (Medium); liveness/readiness
  health checks (Medium); per-key rate limiting (Medium); automatic retry with
  backoff on transient provider errors (Medium); secrets management beyond
  .env (Low); horizontal scaling — stateless design (Low); API versioning (Low).
- Deployment guide (partially stale on provider config, still current on
  ops): uvicorn + systemd/supervisord, reverse proxy TLS termination,
  `GET /health` for LB checks, analytics DB on persistent volume, ngrok static
  domain `hyperpolysyllabically-saronic-mee.ngrok-free.app` via
  `bash .ngrok/expose.sh`, Docker planned but not implemented.
- PRD "Out of Scope (Phase 2)" matches: queuing/rate limiting, conversation
  persistence, Docker, structured logging/observability, horizontal scaling,
  API versioning.
- source: docs/project-roadmap.md; docs/deployment-guide.md;
  docs/project-overview-pdr.md

## Lessons learned (2026-04-16 retrospective)
- `OpenAICompatibleProvider` was the single best decision — each new
  OpenAI-protocol provider is ~8-11 lines (base_url + default_model).
- Generator wrapper (`_tracked_stream`) over middleware for analytics —
  simpler, fewer indirections, exact control of metric capture points.
- Code review caught real breakage (4 critical issues) — review is not optional.
- Static config (routing/pricing dicts in Python) is fine when there is no
  admin UI — auditable, change-controlled through git; do not add a DB for
  release-scoped configuration.
- SQLite + WAL is the right call for single-instance analytics — no Postgres,
  no pool tuning, no migration framework.
- Big-bang delivery worked only because the codebase was small (~1200 LOC);
  would not scale to a larger project.
- source: docs/journals/2026-04-16-multi-provider-router-and-analytics.md

## Open engineering items carried forward
- Load-test fire-and-forget `asyncio.create_task` logging under concurrent
  streaming — if tasks accumulate faster than SQLite writes, a bounded queue
  is needed (never stress-tested).
- Per-provider API key validation on startup — currently fails at request time
  with a cryptic SDK error when a key is missing; fail fast instead.
- Streaming error format alignment — SSE `{"error": "..."}` frames have no
  standard schema; align with the OpenAI error format for client compatibility.
- Analytics retention/cleanup — SQLite grows unbounded; no TTL or purge
  strategy defined (recurring open question since 0416 phase-05).
- Resolved-in-hindsight questions from 0416 phase-05: ZAI base URL/models
  (resolved by zai-coding spec), ByteDance auth format (moot after Manifest),
  `model` required vs optional (resolved: default `"auto"`), approximate token
  counting (moot — usage comes from final chunk).
- source: docs/journals/2026-04-16-multi-provider-router-and-analytics.md;
  plans/0416-2130-gateway-features-unified-api-routing-analytics/phase-05-integration-and-testing.md

## Code standards and conventions (current parts)
- Naming: kebab-case Python filenames, PascalCase classes, snake_case
  functions, UPPER_SNAKE constants/env vars, kebab-ish route prefixes
  (`/v1/analytics/summary`). One provider per file; routes split
  `routes/chat.py` + `routes/analytics.py`; analytics logic in `analytics/`
  (db, cost, routing); keep `main.py` minimal (app, lifespan, health, mounts).
- Style: Python 3.12+ features OK; `async/await` for all I/O; type hints on
  all signatures; `logging.getLogger(__name__)`; tests via pytest +
  pytest-asyncio + httpx with auth dependency override and in-memory SQLite.
- Error handling: provider errors → `{"error": "..."}` SSE events; auth → 401;
  analytics DB errors caught + logged, never block the stream.
- STALE sections of `docs/code-standards.md`: file tree still lists 8 provider
  files (now manifest.py + zai_coding.py); "Adding a New Provider" step 4
  (MODEL_PRICING entry) no longer applies.
- source: docs/code-standards.md; docs/codebase-summary.md

## Documentation staleness map
- Current: `docs/system-architecture.md`, `docs/codebase-summary.md` (both
  reflect the zai-coding era).
- Stale (describe the superseded 8-native-provider architecture; refresh
  backlog): `docs/project-overview-pdr.md` (Goals 2/4, FR-7..FR-13, FR-19),
  `docs/deployment-guide.md` (per-provider keys, provider base-URL table),
  `docs/code-standards.md` (provider file tree, pricing step),
  `docs/project-roadmap.md` (Phase 2 "8 providers" / "model pricing table"
  deliverables — the underlying capabilities exist but in Manifest/zai form).
- source: docs/project-overview-pdr.md; docs/deployment-guide.md;
  docs/code-standards.md; docs/project-roadmap.md; docs/system-architecture.md
