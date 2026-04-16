# Phase 1: Config & Model Routing

## Context Links

- [Plan Overview](./plan.md)
- Current config: `config.py` (14 LOC)
- Current factory: `providers/__init__.py` (18 LOC)
- Current request model: `main.py` lines 20-23

## Overview

- **Priority**: P1 (blocks all other phases)
- **Status**: `[ ]`
- **Description**: Add per-provider API key config, model routing table, and update ChatRequest to require `model` field.

## Key Insights

1. Current `LLM_PROVIDER` + `LLM_API_KEY` is single-provider. Must support N providers simultaneously.
2. Each provider needs its own API key env var (e.g., `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`).
3. Model routing is a static dict lookup — model name maps to `(provider_name, actual_model_id)`.
4. The `model` field in request becomes the primary routing mechanism. `LLM_PROVIDER` env var becomes a fallback default.
5. Gemini models need special handling (different SDK) but still appear in the same routing table.
6. **ZAI = ZhipuAI** (same as GLM provider). No separate provider needed. ZAI models route to GLM provider.

## Requirements

### Functional

- FR-1.1: `ChatRequest.model` field is required; gateway returns 422 if missing
- FR-1.2: Gateway resolves model name to provider via `MODEL_ROUTING` dict
- FR-1.3: Unknown model name returns HTTP 400 with helpful error listing available models
- FR-1.4: Each provider reads its own API key from settings (e.g., `settings.openai_api_key`)
- FR-1.5: Backward compatible: if `model` not provided but `LLM_PROVIDER` env var set, use legacy behavior (default model for that provider)

### Non-Functional

- NFR-1.1: Routing lookup is O(1) dict lookup, no external service call
- NFR-1.2: All new env vars documented in `.env.example`
- NFR-1.3: No breaking changes to existing `.env` configuration

## Architecture

### Data Flow

```
Client request {model: "gpt-4o", messages: [...]}
       |
       v
 ChatRequest validation (Pydantic)
       |
       v
 resolve_provider("gpt-4o")
       |
       v
 MODEL_ROUTING["gpt-4o"] -> ("openai", "gpt-4o")
       |
       v
 create_provider("openai") -> OpenAIProvider(api_key=settings.openai_api_key, model="gpt-4o")
```

### Component Interactions

```
config.py  ──>  Settings (per-provider keys)
                  |
analytics/routing.py ──> MODEL_ROUTING dict
                  |                        resolve_provider(model_name) -> (provider, model)
                  v
providers/__init__.py ──> create_provider(provider_name, model, api_key) -> LLMProvider
```

## Related Code Files

### Modify

| File | Change |
|------|--------|
| `config.py` | Add per-provider API key fields |
| `main.py` | Update `ChatRequest` to require `model` field |
| `providers/__init__.py` | Change `create_provider()` signature to accept `provider_name`, `model`, `api_key` |
| `.env.example` | Add all new env vars |

### Create

| File | Purpose |
|------|---------|
| `analytics/__init__.py` | Package init, empty |
| `analytics/routing.py` | `MODEL_ROUTING` dict + `resolve_provider()` function |

### Delete

None.

## Implementation Steps

1. **Create `analytics/__init__.py`** — empty file, just package marker

2. **Create `analytics/routing.py`** (~60 LOC):
   ```python
   # MODEL_ROUTING: dict[str, tuple[str, str]] = {}
   #   key = model name as client sends it
   #   value = (provider_name, actual_model_id)
   #
   # resolve_provider(model: str) -> tuple[str, str]:
   #   lookup model in MODEL_ROUTING
   #   raise ValueError with available models list if not found
   #
   # AVAILABLE_MODELS: list[str] — derived from MODEL_ROUTING.keys()
   ```
   Include all models from spec: gpt-4o, gpt-4o-mini, o3, deepseek-chat, deepseek-reasoner, kimi-k2.5, kimi-k2-thinking, moonshot-v1-128k, gemini-2.5-flash, glm-4-flash, MiniMax-Text-01, and bytedance endpoint ID pattern.

3. **Update `config.py`** (~30 LOC):
   - Add fields: `openai_api_key`, `deepseek_api_key`, `moonshot_api_key`, `bytedance_api_key`
   - Keep existing `llm_api_key` as generic fallback (also used for ZAI/ZhipuAI since ZAI = GLM)
   - Keep existing `llm_provider` for legacy default behavior
   - Add helper method `get_api_key(provider: str) -> str` that returns provider-specific key or falls back to `llm_api_key`

4. **Update `main.py` ChatRequest** — add `model: str` field (required), keep `messages`, `system_prompt`, `stream`

5. **Update `providers/__init__.py`** (~30 LOC):
   - Change `create_provider(provider_name: str, model: str | None = None) -> LLMProvider`
   - Each case reads the correct API key from settings via `settings.get_api_key(provider_name)`
   - Pass `model` to provider constructor (override default)

6. **Update `.env.example`** — add all new API key env vars with comments

## Todo Checklist

- [ ] Create `analytics/__init__.py`
- [ ] Create `analytics/routing.py` with MODEL_ROUTING and resolve_provider()
- [ ] Update `config.py` with per-provider API keys + get_api_key() helper
- [ ] Update `ChatRequest` in `main.py` to require `model` field
- [ ] Update `providers/__init__.py` factory signature
- [ ] Update `.env.example` with all new env vars
- [ ] Verify existing tests still pass (backward compat with LLM_PROVIDER)

## Success Criteria

- [ ] `resolve_provider("gpt-4o")` returns `("openai", "gpt-4o")`
- [ ] `resolve_provider("unknown-model")` raises `ValueError` listing available models
- [ ] `Settings.get_api_key("openai")` returns `OPENAI_API_KEY` env var or falls back to `LLM_API_KEY`
- [ ] Request without `model` field returns 422 validation error
- [ ] Existing behavior preserved: `LLM_PROVIDER=gemini` still works as default

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Breaking existing clients that omit `model` | High | High | Make `model` optional with fallback to `LLM_PROVIDER` + `LLM_MODEL` env vars |
| Model name collisions across providers | Low | Medium | Use provider-prefixed aliases (e.g., `deepseek-chat` is unambiguous) |
| Missing API key for requested provider | Medium | Medium | Validate key exists before creating provider; return 400 with clear message |

## Security Considerations

- API keys never logged or returned in error messages
- `get_api_key()` returns empty string (not None) for unset keys — provider will fail with auth error at API call time
- No new attack surface; same Bearer token auth on gateway

## Next Steps

- Phase 2 depends on this phase's routing table and config changes
- Phase 2 will update `LLMProvider` base class (which affects factory return types)
