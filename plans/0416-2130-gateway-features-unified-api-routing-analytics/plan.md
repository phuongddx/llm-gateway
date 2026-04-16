---
title: "LLM Gateway Enhancement: Unified API, Multi-Provider Routing, Analytics"
description: "Add model-based routing, 5 new providers, SQLite analytics, and usage monitoring endpoints"
status: pending
priority: P1
effort: 16h
branch: main
tags: [routing, analytics, providers, monitoring]
created: 2026-04-16
---

## Overview

Transform single-provider gateway into multi-model router with per-request provider selection, usage analytics (SQLite), and cost monitoring endpoints. Client specifies `model` in request; gateway resolves to correct provider.

## Phases

| # | Phase | Status | Effort | Files |
|---|-------|--------|--------|-------|
| 1 | [Config & Routing](./phase-01-config-and-routing.md) | `[ ]` | 3h | config.py, analytics/routing.py, main.py (ChatRequest) |
| 2 | [Provider Updates](./phase-02-provider-updates.md) | `[ ]` | 5h | providers/*.py (5 new + 3 updated) |
| 3 | [Analytics Engine](./phase-03-analytics-engine.md) | `[ ]` | 4h | analytics/db.py, analytics/cost.py, routes/chat.py |
| 4 | [Analytics Endpoints](./phase-04-analytics-endpoints.md) | `[ ]` | 2h | routes/analytics.py |
| 5 | [Integration & Testing](./phase-05-integration-and-testing.md) | `[ ]` | 2h | tests/, docs/, main.py |

## Dependency Graph

```
Phase 1 (config/routing)
  |
  v
Phase 2 (providers) ──> Phase 3 (analytics engine) ──> Phase 4 (analytics endpoints)
                                                                        |
                                                                        v
                                                              Phase 5 (integration)
```

Phases 1+2 are sequential (routing must exist before providers can use it).
Phase 3 depends on Phase 2 (providers must yield usage data).
Phase 4 depends on Phase 3 (endpoints query the DB).
Phase 5 validates everything end-to-end.

## Key Decisions

- **Model routing**: static Python dict, no DB lookup
- **Provider base class**: `chat_stream()` yields `(token, usage_dict | None)` tuples
- **Analytics**: generator wrapper pattern (tracked_stream), NOT middleware
- **Storage**: SQLite + aiosqlite, WAL mode, single file
- **Cost**: hardcoded pricing dict, no external price feed
- **Failover**: max 2 retries on transient errors, exclude failed provider
- **Model listing**: `GET /v1/models` endpoint from routing table
- **ZAI**: same as ZhipuAI (GLM) — no separate provider needed

## Verified Against

Reference: `/Users/ddphuong/Projects/next-labs/llmgateway/docs/project-overview-pdr.md`
- Aligned on: OpenAI-compat API, multi-provider routing, usage analytics, cost calc, performance metrics
- Added after gap analysis: provider retry/failover, GET /v1/models endpoint
- Deferred (YAGNI): Redis caching, rate limiting, hourly stats worker, IAM rules, billing

## File Ownership (no parallel phase overlap)

| Phase | Owns |
|-------|------|
| 1 | config.py, analytics/routing.py, main.py (ChatRequest only) |
| 2 | providers/*.py |
| 3 | analytics/db.py, analytics/cost.py, routes/chat.py |
| 4 | routes/analytics.py |
| 5 | tests/*, docs/* |

## Rollback

Each phase is a single commit. Revert via `git revert` on that commit. No DB migrations needed (SQLite created fresh if deleted). Old `LLM_PROVIDER` env var continues working as fallback.
