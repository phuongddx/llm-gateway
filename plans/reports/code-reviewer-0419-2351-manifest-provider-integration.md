## Code Review Summary

### Scope
- Files: providers/manifest.py, config.py, analytics/routing.py, analytics/cost.py, analytics/__init__.py, providers/__init__.py, routes/chat.py, requirements.txt, .env.example, providers/base.py, openai_compatible_base.py
- Deleted: providers/gemini.py, openai_provider.py, deepseek.py, moonshot.py, bytedance.py, glm.py, minimax.py
- Tests: tests/test_routing.py, test_cost.py, test_chat_endpoint.py
- LOC: ~120 changed, ~400 deleted
- Focus: security, correctness, edge cases, import hygiene
- All 30 tests pass

### Overall Assessment
Clean, minimal integration. The Manifest provider replaces 8 specialized providers with a single `OpenAICompatibleProvider` subclass. The code is simple, the factory is correctly simplified, and the passthrough routing for unknown models is a sound design. No critical security or correctness bugs found. Issues below are medium-to-low priority.

### Critical Issues
None.

### High Priority

**H1. Stale docs -- codebase-summary.md and system-architecture.md still reference deleted providers and old config**

`docs/codebase-summary.md` references `google-genai`, `MODEL_PRICING`, per-provider API keys (`openai_api_key`, `deepseek_api_key`, etc.), `GeminiProvider`, and the old 7-provider factory. `docs/system-architecture.md` has the full multi-provider diagram with Gemini native SDK, individual provider boxes, and per-provider env vars. Both docs will mislead anyone onboarding.

Impact: confusion, wrong mental model for future contributors.
Fix: Update both docs to reflect the single ManifestProvider architecture.

**H2. `docs/code-standards.md` references deleted files and removed patterns**

The code-standards doc lists deleted files (`providers/gemini.py`, `providers/openai_provider.py`, etc.) in file organization, references `MODEL_PRICING` in the "Adding a New Provider" walkthrough, and documents `ValueError` for unknown models (now passthrough). The "Adding a New Provider" section's 6-step process is obsolete -- adding a model is now just a routing table entry.

Fix: Rewrite the "Adding a New Provider" section to reflect Manifest passthrough model. Remove deleted file references.

### Medium Priority

**M1. `create_provider()` ignores `provider_name` parameter entirely**

`providers/__init__.py` always creates `ManifestProvider` regardless of what `provider_name` is passed. The parameter is accepted but unused. This is not a bug (since everything routes to manifest), but the API contract is misleading -- a caller passing `provider_name="openai"` gets Manifest silently.

```python
def create_provider(provider_name: str, model: str | None = None, api_key: str | None = None) -> LLMProvider:
    key = api_key or settings.get_api_key(provider_name)
    from providers.manifest import ManifestProvider
    return ManifestProvider(api_key=key, model=model)  # provider_name unused
```

Fix: Either remove the parameter (breaking change to external callers) or add an assertion/log if a non-"manifest" provider_name is passed. Recommend logging a warning for now.

**M2. `config.py` still has `llm_provider` and `llm_model` fields -- dead config**

The `Settings` class retains `llm_provider: str = "gemini"` and `llm_model: str = "gemini-2.0-flash-lite"` which are no longer consumed anywhere. `get_api_key()` still has a branch for non-"manifest" providers that returns `self.llm_api_key`, but no code path can produce a non-"manifest" provider name.

Impact: Confusing for operators. `.env.example` still documents `LLM_PROVIDER` and `LLM_MODEL` via the Settings class defaults, suggesting they are functional.
Fix: Remove unused fields in a follow-up, or add a comment marking them as deprecated.

**M3. `stream_options={"include_usage": True}` may not be supported by Manifest**

`openai_compatible_base.py` passes `stream_options` in the API call. If Manifest's API does not support this parameter, it may either silently ignore it (fine) or reject the request with a 400 (breaking).

Impact: Requests fail if Manifest rejects unknown parameters.
Fix: Verify Manifest API compatibility. If uncertain, wrap in a try/except that retries without `stream_options`.

**M4. No health check or validation that `manifest_api_key` is configured**

`main.py` validates `app_api_key` is set on startup but does not check `manifest_api_key`. If the key is empty or missing, the first chat request will fail at the Manifest API level with an opaque auth error propagated back through the SSE stream.

Impact: Bad UX -- server starts successfully but all chat requests fail.
Fix: Add a startup warning if `manifest_api_key` is empty, or a `GET /v1/models` health check on startup.

**M5. `analytics/__init__.py` still exports `calculate_cost` even though it always returns 0.0**

The `calculate_cost` function is now a stub that always returns `0.0`. The analytics logging still records `cost_usd: 0.0` for every request, and the analytics endpoints still return cost data. This is correct (Manifest handles billing) but the schema and API surface imply per-request cost tracking that does not exist.

Impact: Analytics consumers may see $0.00 costs and assume a bug rather than expected behavior.
Fix: Add a comment in `cost.py` and/or in analytics response schema noting that cost is always 0 with Manifest.

### Low Priority

**L1. `conftest.py` uses hardcoded `auth_headers` value `"changeme"`**

The `auth_headers` fixture hardcodes `Bearer changeme` which matches the old default. This works because `Settings` reads env vars and falls back to defaults. Not a bug but fragile if `app_api_key` default changes.

**L2. `routes/chat.py` imports `os` and `asyncio` but `os` is unused**

Line 6: `import os` is imported but never used in the file.

**L3. `providers/base.py` defines `GenParams` TypedDict but it is unused**

`GenParams` is defined in `base.py` but `routes/chat.py` builds a plain dict instead of using the TypedDict. The type annotation on `chat_stream()` references it but nothing constructs it. Minor type safety gap.

**L4. `_tracked_stream` approximates token count with `len(token) // 4`**

Line 86 of `routes/chat.py`: `token_count += len(token) // 4` is a rough approximation when usage data is not available. This is existing behavior, not introduced by this change, but worth noting.

### Edge Cases Found by Scout

1. **Passthrough model names are not validated at all** -- any string is sent to Manifest. This is intentional design but means typos (`"gpt4o"` instead of `"gpt-4o"`) will silently route to Manifest and fail at the API level with a non-obvious error. The old code raised `ValueError` with a helpful list of available models.

2. **`get_api_key("manifest")` falls back to `llm_api_key`** -- this is correct for migration (old key still works) but means a stale `LLM_API_KEY` with a different provider's key would be silently sent to Manifest. Low risk but worth documenting.

3. **No test for Manifest auth error propagation** -- tests mock `create_provider` entirely, so there is no test covering what happens when Manifest rejects the API key. The SSE error path (`Internal error processing request`) is tested but the specific auth-failure case is not.

4. **`analytics/routing.py` provider name is always `"manifest"` for DB logging** -- the `provider_name` in the routing table is always `"manifest"`, so the analytics `provider` column will always contain `"manifest"`. The `get_model_stats` endpoint accepts a `provider` query param filter that is now useless (every record has `provider="manifest"`). This is a minor API surface regression.

### Positive Observations

- Clean deletion of 7 provider files with no orphaned imports
- `requirements.txt` correctly removes `google-genai` dependency
- `config.py` adds `extra="ignore"` which is necessary since old `.env` files with per-provider keys would cause pydantic validation errors otherwise
- Passthrough routing for unknown models is a good DX decision
- The `_on_log_task_done` callback properly handles fire-and-forget task errors
- Error messages in `_tracked_stream` are sanitized (`Internal error processing request`) -- no stack trace leakage
- Test coverage is adequate for the new behavior (unknown model passthrough, all-manifest routing)

### Recommended Actions
1. **[High]** Update `docs/codebase-summary.md` and `docs/system-architecture.md` to reflect Manifest architecture
2. **[High]** Update `docs/code-standards.md` -- remove deleted file references, rewrite "Adding a New Provider" section
3. **[Medium]** Add startup warning for missing `manifest_api_key`
4. **[Medium]** Verify Manifest API supports `stream_options` parameter
5. **[Medium]** Log a warning in `create_provider` when `provider_name != "manifest"`
6. **[Low]** Remove unused `import os` from `routes/chat.py`
7. **[Low]** Add comment in `analytics/cost.py` explaining the 0.0 return value

### Metrics
- Type Coverage: Full (type hints on all signatures)
- Test Coverage: 30/30 pass -- covers routing, cost, chat endpoint, unknown model passthrough
- Linting Issues: 1 unused import (`os` in `routes/chat.py`)
- Deleted Files Clean: No orphaned imports found in active code

### Unresolved Questions
- Does Manifest API support `stream_options={"include_usage": True}`? If not, usage tracking will be broken and all analytics will show 0 tokens.
- Should the `provider` field in analytics be repurposed to store the original model name prefix or category, given it is now always `"manifest"`?
- Is the plan to eventually remove the legacy `llm_provider`, `llm_model`, `llm_api_key` config fields entirely?
