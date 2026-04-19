# Phase 3: Cleanup Old Providers & Cost

**Priority:** P1 | **Effort:** 0.5h | **Status:** `[x]`

## Context Links

- Phase 2 must be complete (routing + factory updated)
- `providers/` directory — old provider files to remove
- `analytics/cost.py` — current per-model pricing table

## Overview

Remove all old provider files. Simplify cost calculation — Manifest handles billing, gateway just tracks token usage.

## Requirements

- Delete all provider files except: `base.py`, `openai_compatible_base.py`, `manifest.py`, `__init__.py`
- Remove old model pricing from `cost.py` (Manifest handles billing internally)
- Keep `calculate_cost()` function signature for analytics compatibility, return 0.0 always
- Remove `google-genai` from dependencies (no longer needed)

## Files to Delete

| File | Reason |
|------|--------|
| `providers/gemini.py` | GeminiProvider no longer used |
| `providers/openai_provider.py` | Direct OpenAI access via Manifest now |
| `providers/deepseek.py` | Via Manifest now |
| `providers/moonshot.py` | Via Manifest now |
| `providers/bytedance.py` | Via Manifest now |
| `providers/glm.py` | Via Manifest now |
| `providers/minimax.py` | Via Manifest now |

## Related Code Files

| Action | File |
|--------|------|
| Delete | `providers/gemini.py` |
| Delete | `providers/openai_provider.py` |
| Delete | `providers/deepseek.py` |
| Delete | `providers/moonshot.py` |
| Delete | `providers/bytedance.py` |
| Delete | `providers/glm.py` |
| Delete | `providers/minimax.py` |
| Modify | `analytics/cost.py` |

## Implementation Steps

1. Delete old provider files (7 files)
2. Simplify `analytics/cost.py`:
```python
"""Cost calculation — simplified for Manifest provider."""

def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return 0.0 — Manifest handles billing internally."""
    return 0.0
```
3. Check `requirements.txt` / `pyproject.toml` — remove `google-genai` if present
4. Verify no remaining imports of deleted modules

## Todo List

- [x] Delete 7 old provider files
- [x] Simplify `analytics/cost.py`
- [x] Remove `google-genai` from dependencies if present
- [x] Grep for any remaining imports of deleted providers
- [x] Verify app starts without import errors

## Success Criteria

- `python -c "from providers import create_provider"` works
- `python -c "from providers.manifest import ManifestProvider"` works
- No import errors for deleted modules
- `calculate_cost("any-model", 100, 50)` returns 0.0
