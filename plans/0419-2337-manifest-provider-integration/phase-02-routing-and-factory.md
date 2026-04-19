# Phase 2: Routing & Factory

**Priority:** P1 | **Effort:** 1h | **Status:** `[x]`

## Context Links

- Phase 1 must be complete (ManifestProvider must exist)
- `analytics/routing.py` — current MODEL_ROUTING dict
- `providers/__init__.py` — current create_provider factory

## Overview

Replace routing table with Manifest models. Update factory to only create ManifestProvider. Add passthrough for unknown models.

## Requirements

- Routing table: `"auto"` + curated popular models, all mapped to `("manifest", model_id)`
- Factory: only `"manifest"` case, all others removed
- Passthrough: unknown model names still route to Manifest (no ValueError for unknown models)
- `/v1/models` endpoint shows curated list from routing table

## Architecture

```
MODEL_ROUTING = {
    # Auto-routing
    "auto":             ("manifest", "auto"),
    # Popular models
    "gpt-5.4":          ("manifest", "gpt-5.4"),
    "gpt-4o":           ("manifest", "gpt-4o"),
    "claude-sonnet":    ("manifest", "claude-sonnet-4-6"),
    "claude-haiku":     ("manifest", "claude-haiku-4-5-20251001"),
    "gemini-2.5-flash": ("manifest", "gemini-2.5-flash"),
    "deepseek-chat":    ("manifest", "deepseek-chat"),
    "kimi-k2.5":        ("manifest", "kimi-k2.5"),
    # ... add more as needed
}

resolve_provider("auto")       -> ("manifest", "auto")
resolve_provider("gpt-5.4")    -> ("manifest", "gpt-5.4")
resolve_provider("some-model") -> ("manifest", "some-model")  # passthrough
```

## Related Code Files

| Action | File |
|--------|------|
| Modify | `analytics/routing.py` |
| Modify | `providers/__init__.py` |

## Implementation Steps

1. Update `analytics/routing.py`:
   - Replace entire `MODEL_ROUTING` with Manifest entries
   - Update `resolve_provider()`: if model not in routing table, return `("manifest", model)` instead of raising ValueError
   - Keep `AVAILABLE_MODELS` list for `/v1/models` endpoint

2. Update `providers/__init__.py`:
   - Remove all provider cases except `"manifest"`
   - Import `ManifestProvider` lazily
   - Default/unknown case: create ManifestProvider (not raise ValueError)

```python
def create_provider(provider_name: str, model: str | None = None, api_key: str | None = None) -> LLMProvider:
    key = api_key or settings.get_api_key(provider_name)
    match provider_name:
        case "manifest" | _:
            from providers.manifest import ManifestProvider
            return ManifestProvider(api_key=key, model=model)
```

## Todo List

- [x] Rewrite `MODEL_ROUTING` in routing.py with Manifest models
- [x] Update `resolve_provider()` with passthrough for unknown models
- [x] Simplify `create_provider()` factory to manifest-only
- [x] Verify `/v1/models` returns correct list

## Success Criteria

- `resolve_provider("auto")` returns `("manifest", "auto")`
- `resolve_provider("unknown-model")` returns `("manifest", "unknown-model")` (passthrough)
- `create_provider("manifest", "auto")` returns ManifestProvider instance
- `/v1/models` lists curated models
