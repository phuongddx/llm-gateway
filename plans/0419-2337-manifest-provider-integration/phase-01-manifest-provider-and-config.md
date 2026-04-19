# Phase 1: Manifest Provider & Config

**Priority:** P1 | **Effort:** 1h | **Status:** `[x]`

## Context Links

- Brainstorm session: Approach B (keep ABC, single ManifestProvider)
- `providers/openai_compatible_base.py` — base class to inherit from
- `config.py` — current Settings with per-provider keys

## Overview

Create `ManifestProvider` extending `OpenAICompatibleProvider`. Update `config.py` to add `manifest_api_key` and remove per-provider keys.

## Requirements

- ManifestProvider inherits from OpenAICompatibleProvider
- base_url = `https://app.manifest.build/v1`
- default_model = `auto`
- Single `MANIFEST_API_KEY` env var replaces all per-provider keys
- `get_api_key("manifest")` returns manifest_api_key or llm_api_key fallback
- Remove: openai_api_key, deepseek_api_key, moonshot_api_key, bytedance_api_key, glm_api_key

## Architecture

```
OpenAICompatibleProvider
  base_url, default_model, client (AsyncOpenAI)
  chat_stream(messages, system_prompt, params) -> AsyncGenerator
       |
       v
ManifestProvider
  base_url = "https://app.manifest.build/v1"
  default_model = "auto"
  (no overrides needed — inherits everything)
```

## Related Code Files

| Action | File |
|--------|------|
| Create | `providers/manifest.py` |
| Modify | `config.py` |

## Implementation Steps

1. Create `providers/manifest.py`:
```python
"""Manifest smart model router provider."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class ManifestProvider(OpenAICompatibleProvider):
    """Manifest.build — smart model routing across 500+ models."""

    base_url = "https://app.manifest.build/v1"
    default_model = "auto"
```

2. Update `config.py`:
   - Add `manifest_api_key: str = ""`
   - Remove per-provider keys: openai_api_key, deepseek_api_key, moonshot_api_key, bytedance_api_key, glm_api_key
   - Update `get_api_key()` to handle "manifest" → manifest_api_key or llm_api_key

## Todo List

- [x] Create `providers/manifest.py` with ManifestProvider class
- [x] Update `config.py`: add manifest_api_key, remove per-provider keys
- [x] Update `get_api_key()` method for manifest provider
- [x] Verify no import errors

## Success Criteria

- `ManifestProvider` instantiates with api_key, creates AsyncOpenAI client pointing at Manifest
- `config.py` loads MANIFEST_API_KEY from .env
- No references to removed provider keys anywhere
