# Multi-Provider Router and Analytics: From Single-Provider to 7-Model Gateway

**Date**: 2026-04-16 22:51
**Severity**: High (major architectural change)
**Component**: Provider system, analytics pipeline, REST API surface
**Status**: Resolved

## What Happened

Transformed the LLM Gateway from a single-provider (Gemini-only) proxy into a multi-model router supporting 7 providers with per-request model selection. Added SQLite-backed analytics for request logging, cost tracking, TTFT, and latency. 16 new files created, 7 modified. 28/28 tests green in 0.27s. Code review caught 4 critical issues, all fixed before merge.

## The Brutal Truth

This was a big-bang feature: routing, analytics, 5 new providers, REST endpoints, cost calculation -- all in one session. The code review saved us from shipping broken auth (token extraction was wrong), missing null guards that would have crashed on empty streaming responses, and route guards that left analytics endpoints unprotected. Without that review pass, this would have been a production incident. The decision to do everything at once worked because the codebase is small (~1200 LOC), but it would not scale to a larger project.

## Technical Details

**Provider hierarchy:**
- `LLMProvider` (ABC) -> `GeminiProvider` (native SDK) + `OpenAICompatibleProvider` (shared base)
- 6 concrete providers inherit from `OpenAICompatibleProvider` -- each is 8 LOC (just `base_url` + `default_model`)
- Lazy imports in factory `create_provider()` avoid loading unused SDKs

**Routing:**
- Static `MODEL_ROUTING` dict: `model_name -> (provider_name, actual_model_id)`
- 13 model entries across 7 providers
- `resolve_provider()` raises `ValueError` with available models list on unknown input

**Analytics:**
- SQLite via `aiosqlite`, WAL mode for concurrent reads
- `request_logs` table: provider, model, tokens, latency_ms, ttft_ms, cost_usd, status, error_message
- Fire-and-forget logging via `asyncio.create_task()`

**Code review fixes (4 critical):**
1. Auth token extraction -- `verify_auth()` was not correctly parsing Bearer token from header
2. Null guards -- streaming response crashed when provider returned no text chunks
3. Task cleanup -- `asyncio.create_task` calls without exception handling could silently swallow errors
4. Route guards -- analytics endpoints were missing `verify_auth` dependency, accessible without auth

**Test suite:** 28 tests across 5 files (chat endpoint, analytics endpoints, analytics DB, cost calculation, routing).

## What We Tried

- **OpenAICompatibleProvider base class** -- rejected per-provider duplicate implementations in favor of shared base. Each new OpenAI-protocol provider is now 8 lines.
- **Generator wrapper (`_tracked_stream`)** -- rejected middleware-based analytics in favor of wrapping the async generator directly. Simpler, fewer indirection layers, and we control exactly when metrics are captured.
- **Static routing dict** -- rejected DB-backed routing. No admin UI exists to manage it, no dynamic model addition needed. A Python dict is easier to audit and deploy.
- **Hardcoded pricing** -- same reasoning. `MODEL_PRICING` dict maps model to `(input_per_1m, output_per_1m)`. No external pricing API dependency.

## Root Cause Analysis

The original single-provider design was a prototype that worked for one use case. The gap was not technical debt -- it was missing infrastructure: no routing layer, no provider abstraction, no observability. The big-bang approach was chosen because each piece (routing, providers, analytics, endpoints) was small enough to hold in context simultaneously, and cross-cutting concerns (cost calculation needs routing info, analytics needs provider name) made incremental delivery awkward.

## Lessons Learned

1. **`OpenAICompatibleProvider` was the single best decision.** Adding a 6th or 7th OpenAI-protocol provider takes 8 lines and a routing entry. The 54-line base class paid for itself immediately.
2. **Generator wrapper over middleware for analytics.** Middleware adds indirection, makes error handling harder, and obscures the data flow. A plain async generator wrapping the provider stream is obvious, testable, and captures exactly the metrics we need.
3. **Code review caught real breakage.** Four critical issues found in review -- auth, null guards, task cleanup, route protection. None were cosmetic. Review is not optional.
4. **Static config is fine when there is no admin UI.** A routing dict and pricing dict in Python files are deployable, auditable, and change-controlled through git. Do not add a database for configuration that changes with releases.
5. **SQLite + WAL is the right call for single-instance analytics.** No Postgres dependency, no connection pool tuning, no migrations framework. WAL mode handles concurrent reads from analytics queries while writes come from request logging.

## Next Steps

- **Load test with concurrent streaming requests** -- fire-and-forget `asyncio.create_task` logging has not been stress-tested. If tasks accumulate faster than SQLite writes, we need a bounded queue.
- **Per-provider API key validation on startup** -- currently fails at request time with a cryptic SDK error if a key is missing. Fail fast on startup.
- **Streaming error format alignment** -- error chunks use `{"error": "..."}` but no standard error schema exists. Align with OpenAI error format for client compatibility.
- **Analytics retention / cleanup** -- SQLite will grow unbounded. Add a TTL or periodic cleanup job.
