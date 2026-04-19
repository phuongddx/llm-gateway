---
title: "Manifest Provider Integration — Replace All Providers"
description: "Replace 8 LLM providers with single Manifest smart router. OpenAI-compatible, auto-routing + named models."
status: complete
priority: P1
effort: 4h
branch: main
tags: [manifest, provider, routing, simplification]
created: 2026-04-19
blockedBy: []
blocks: []
supersedes: [0416-2130-gateway-features-unified-api-routing-analytics]
---

## Overview

Replace all 8 existing LLM providers with a single Manifest provider. Manifest is an OpenAI-compatible smart model router that handles tier-based routing (simple/standard/complex/reasoning) across 500+ models. Gateway becomes a thin auth/analytics layer over Manifest.

**Approach B from brainstorm:** Keep `LLMProvider` ABC, add `ManifestProvider(OpenAICompatibleProvider)`, remove old providers, simplify routing.

## Phases

| # | Phase | Status | Effort | Files |
|---|-------|--------|--------|-------|
| 1 | [Manifest Provider & Config](./phase-01-manifest-provider-and-config.md) | `[x]` | 1h | providers/manifest.py, config.py |
| 2 | [Routing & Factory](./phase-02-routing-and-factory.md) | `[x]` | 1h | analytics/routing.py, providers/__init__.py |
| 3 | [Cleanup Old Providers & Cost](./phase-03-cleanup-old-providers-and-cost.md) | `[x]` | 0.5h | Remove providers/*, update analytics/cost.py |
| 4 | [Docs & Testing](./phase-04-docs-and-testing.md) | `[x]` | 1.5h | docs/*, README.md, tests/* |

## Dependency Graph

```
Phase 1 (manifest provider + config)
  |
  v
Phase 2 (routing + factory)
  |
  v
Phase 3 (cleanup + cost)
  |
  v
Phase 4 (docs + testing)
```

Strictly sequential. Each phase depends on the previous.

## Key Decisions

- **ManifestProvider** extends `OpenAICompatibleProvider` — base_url=`https://app.manifest.build/v1`, default_model=`auto`
- **Routing table**: curated list of popular models + `"auto"` for smart routing. Unknown models passed through to Manifest (passthrough mode)
- **Config**: Single `MANIFEST_API_KEY` env var. Remove all per-provider keys. Keep `llm_api_key` as fallback alias
- **Cost**: Simplify — Manifest doesn't expose per-model pricing. Use Manifest-reported usage tokens, set cost to 0.0 (Manifest handles billing)
- **GeminiProvider**: Remove. Manifest handles Gemini models natively
- **Passthrough**: If model not in routing table, still send to Manifest (don't raise ValueError). Routing table is curated list for `/v1/models` endpoint

## Architecture After

```
Client --> POST /v1/chat/completions {model: "auto", messages: [...]}
              |
              v
        Bearer Auth Check
              |
              v
        resolve_provider(model)
              |-- known model -> ("manifest", model_id)
              |-- unknown model -> ("manifest", model_name) [passthrough]
              |
              v
        ManifestProvider.chat_stream()
              |
              v
        Manifest API (app.manifest.build/v1)
              |
              v
        500+ models (auto-routed by tier)
```

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Manifest API downtime | All requests fail | Single point of failure — acceptable for personal use. Can add direct provider later via ABC |
| Model name mismatch | Wrong model or error | Passthrough mode sends name as-is. Manifest returns error if invalid |
| Cost tracking lost | No per-model pricing | Manifest handles billing. Analytics tracks token usage for monitoring |
| Breaking change for clients | Old model names invalid | Map old names in routing table where possible |

## Rollback

Each phase is a single commit. Old provider files kept in git history. Revert via `git revert`.
