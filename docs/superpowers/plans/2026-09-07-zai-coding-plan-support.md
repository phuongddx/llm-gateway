# Z.AI GLM Coding Plan Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all GLM traffic through the z.ai GLM Coding Plan endpoint (`https://api.z.ai/api/coding/paas/v4`) when a key is configured, with credit-burn analytics against the Max plan quota.

**Architecture:** A new `ZAICodingProvider` subclasses the existing `OpenAICompatibleProvider` (zero new streaming logic). `resolve_provider()` canonicalizes GLM model names and gates routing on the effective z.ai key — key absent ⇒ behavior identical to today (Manifest). Credit estimation lives in `analytics/cost.py`, is persisted in a new `credits_used` column, and is exposed via `GET /v1/analytics/credits`. No fallback to Manifest for GLM, by explicit user decision.

**Tech Stack:** FastAPI, openai (AsyncOpenAI), aiosqlite, pytest + pytest-asyncio + httpx.AsyncClient over ASGITransport. Spec: `docs/superpowers/specs/2026-09-07-zai-coding-plan-support-design.md`.

## Global Constraints

- Python 3.12+ floor (`typing.NotRequired` allowed; no 3.13-only syntax).
- No new dependencies — reuse installed `openai`, `aiosqlite`, `pytest`, `httpx`.
- Naming: snake_case functions/modules, PascalCase classes, UPPER_SNAKE constants.
- Type hints: PEP 604 unions (`str | None`), builtin generics, TypedDict for payloads.
- Every async test carries `@pytest.mark.asyncio` even though `asyncio_mode = auto` (repo convention).
- Mocking pattern: `unittest.mock.patch("routes.chat.create_provider", ...)` — no `app.dependency_overrides`.
- One-line module docstring on every new/changed file explaining purpose.
- Errors returned to clients must not leak internal exception text.
- Commits after every green task; `git commit --no-verify -q` pattern is fine.
- Single shared `settings` singleton from `config.py` — never construct a second one in app code.

---

### Task 1: Config — z.ai coding plan settings

**Files:**
- Modify: `config.py`
- Modify: `.env.example`
- Test: `tests/test_config.py` (create)

**Interfaces:**
- Consumes: existing `Settings.get_api_key(provider: str) -> str`.
- Produces: `Settings.zai_coding_api_key: str`, `Settings.zai_credits_5h: int` (default 28000), `Settings.zai_credits_week: int` (default 140000); `get_api_key("zai-coding") -> str` returns `zai_coding_api_key or llm_api_key`. Later tasks rely on exactly these names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py`:

```python
"""Unit tests for config.Settings — zai-coding key resolution."""

from config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_zai_coding_key_dedicated():
    s = _settings(zai_coding_api_key="zai-key", llm_api_key="fallback")
    assert s.get_api_key("zai-coding") == "zai-key"


def test_zai_coding_key_falls_back_to_llm_api_key():
    s = _settings(zai_coding_api_key="", llm_api_key="fallback")
    assert s.get_api_key("zai-coding") == "fallback"


def test_zai_coding_key_absent_everywhere():
    s = _settings(zai_coding_api_key="", llm_api_key="")
    assert s.get_api_key("zai-coding") == ""


def test_credits_defaults_are_max_plan():
    s = _settings()
    assert s.zai_credits_5h == 28000
    assert s.zai_credits_week == 140000


def test_manifest_resolution_unchanged():
    s = _settings(manifest_api_key="m", llm_api_key="f")
    assert s.get_api_key("manifest") == "m"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `Settings` has no field `zai_coding_api_key` (pydantic ValidationError on `_settings(zai_coding_api_key=...)`).

- [ ] **Step 3: Write minimal implementation**

In `config.py`, add fields to `Settings` after `manifest_api_key`:

```python
    # Z.AI GLM Coding Plan provider (endpoint: https://api.z.ai/api/coding/paas/v4)
    zai_coding_api_key: str = ""

    # GLM Coding Plan credit quotas (defaults = Max tier; adjust per tier)
    zai_credits_5h: int = 28000
    zai_credits_week: int = 140000
```

And extend `get_api_key`:

```python
    def get_api_key(self, provider: str) -> str:
        """Return API key for provider. Dedicated key with llm_api_key fallback."""
        if provider == "manifest":
            return self.manifest_api_key or self.llm_api_key
        if provider == "zai-coding":
            return self.zai_coding_api_key or self.llm_api_key
        return self.llm_api_key
```

In `.env.example`, append after the `MANIFEST_API_KEY` block:

```
# Z.AI GLM Coding Plan key — routes glm-* models to https://api.z.ai/api/coding/paas/v4
# Unset to keep all GLM routing on Manifest
ZAI_CODING_API_KEY=

# GLM Coding Plan credit quotas (defaults = Max tier: 28000/5h, 140000/week)
ZAI_CREDITS_5H=28000
ZAI_CREDITS_WEEK=140000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py .env.example tests/test_config.py
git commit -m "feat: add zai-coding provider settings and key resolution"
```

---

### Task 2: Provider — ZAICodingProvider + factory dispatch

**Files:**
- Create: `providers/zai_coding.py`
- Modify: `providers/__init__.py`
- Test: `tests/test_providers.py` (create)

**Interfaces:**
- Consumes: `OpenAICompatibleProvider` from `providers/openai_compatible_base.py`; `settings.get_api_key` from Task 1.
- Produces: `providers.zai_coding.ZAICodingProvider` with `base_url = "https://api.z.ai/api/coding/paas/v4"`, `default_model = "glm-5.3"`; `create_provider("zai-coding", model_id)` returns it. Any other `provider_name` still returns `ManifestProvider`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers.py`:

```python
"""Unit tests for providers.create_provider factory dispatch."""

from providers import create_provider
from providers.manifest import ManifestProvider
from providers.zai_coding import ZAICodingProvider


def test_factory_returns_zai_coding_provider():
    p = create_provider("zai-coding", "glm-5.3")
    assert isinstance(p, ZAICodingProvider)
    assert p.model == "glm-5.3"


def test_factory_falls_back_to_manifest_for_other_names():
    p = create_provider("anything-else", "gpt-4o")
    assert isinstance(p, ManifestProvider)


def test_zai_coding_endpoint_config():
    assert ZAICodingProvider.base_url == "https://api.z.ai/api/coding/paas/v4"
    assert ZAICodingProvider.default_model == "glm-5.3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_providers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'providers.zai_coding'`.

- [ ] **Step 3: Write minimal implementation**

Create `providers/zai_coding.py`:

```python
"""Z.AI GLM Coding Plan provider — flat-rate subscription endpoint."""

from providers.openai_compatible_base import OpenAICompatibleProvider


class ZAICodingProvider(OpenAICompatibleProvider):
    """api.z.ai coding endpoint — serves glm-5.3 / glm-5.3-flash on plan quota."""

    base_url = "https://api.z.ai/api/coding/paas/v4"
    default_model = "glm-5.3"
```

Replace `providers/__init__.py` contents with:

```python
from config import settings
from providers.base import LLMProvider


def create_provider(provider_name: str, model: str | None = None, api_key: str | None = None) -> LLMProvider:
    """Factory: create provider by name with optional model override and API key."""
    key = api_key or settings.get_api_key(provider_name)

    if provider_name == "zai-coding":
        from providers.zai_coding import ZAICodingProvider
        return ZAICodingProvider(api_key=key, model=model)

    # Everything else routes through Manifest
    from providers.manifest import ManifestProvider
    return ManifestProvider(api_key=key, model=model)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_providers.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add providers/zai_coding.py providers/__init__.py tests/test_providers.py
git commit -m "feat: add ZAICodingProvider and factory dispatch"
```

---

### Task 3: Routing — GLM canonicalization + effective-key gate

**Files:**
- Modify: `analytics/routing.py`
- Test: `tests/test_routing.py` (rewrite parts)

**Interfaces:**
- Consumes: `settings.get_api_key("zai-coding")` from Task 1 (effective-key gate — `zai_coding_api_key or llm_api_key`).
- Produces: `resolve_provider(model: str) -> tuple[str, str]` with new contract:
  - Known GLM entries (incl. new `glm-5.3`, `glm-5.3-flash` and all existing `glm-*` aliases) → `("zai-coding", canonical)` when effective key non-empty, else `("manifest", canonical)`.
  - Canonicalization: `glm-4.5-flash`, `glm-4.7-flash`, `glm-4.7-flashx` → `glm-5.3-flash`; every other GLM alias (incl. `glm-5-turbo`) → `glm-5.3`.
  - Unknown `glm-*` (case-insensitive prefix) → `("zai-coding", model_as_given)` when key set, else `("manifest", model_as_given)`.
  - Unknown non-GLM → `("manifest", model_as_given)` (unchanged).
  - Non-GLM table entries → unchanged (`("manifest", ...)`).
- Constants consumed by tests: none new exported; `MODEL_ROUTING` still exported and gains `glm-5.3`/`glm-5.3-flash`.

- [ ] **Step 1: Rewrite the tests to the new contract**

Replace the full contents of `tests/test_routing.py` with:

```python
"""Unit tests for analytics.routing — resolve_provider() GLM/zai-coding routing."""

import pytest

from analytics.routing import MODEL_ROUTING, resolve_provider




@pytest.fixture
def with_zai_key(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "test-zai-key")


@pytest.fixture
def without_zai_key(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "")


def test_resolve_known_non_glm_models(without_zai_key):
    """Every non-GLM entry resolves exactly as the table says."""
    for model_name, (expected_provider, expected_model_id) in MODEL_ROUTING.items():
        if expected_provider != "manifest":
            continue
        provider, model_id = resolve_provider(model_name)
        assert provider == "manifest", f"{model_name}: provider mismatch"
        assert model_id == expected_model_id, f"{model_name}: model_id mismatch"


def test_glm_canonical_pair_routes_to_zai(with_zai_key):
    assert resolve_provider("glm-5.3") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5.3-flash") == ("zai-coding", "glm-5.3-flash")


def test_glm_aliases_canonicalize(with_zai_key):
    assert resolve_provider("glm-5.1") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-5-turbo") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.6") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.5") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.5-flash") == ("zai-coding", "glm-5.3-flash")
    assert resolve_provider("glm-4.7") == ("zai-coding", "glm-5.3")
    assert resolve_provider("glm-4.7-flash") == ("zai-coding", "glm-5.3-flash")
    assert resolve_provider("glm-4.7-flashx") == ("zai-coding", "glm-5.3-flash")


def test_glm_routes_degrade_to_manifest_without_key(without_zai_key):
    assert resolve_provider("glm-5.3") == ("manifest", "glm-5.3")
    assert resolve_provider("glm-4.5-flash") == ("manifest", "glm-5.3-flash")


def test_llm_api_key_fallback_enables_zai_routing(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "zai_coding_api_key", "")
    monkeypatch.setattr(settings, "llm_api_key", "shared-key")
    assert resolve_provider("glm-5.3") == ("zai-coding", "glm-5.3")


def test_unknown_glm_prefix_routes_to_zai(with_zai_key):
    assert resolve_provider("glm-99") == ("zai-coding", "glm-99")
    assert resolve_provider("GLM-99") == ("zai-coding", "GLM-99")


def test_unknown_glm_prefix_degrades_without_key(without_zai_key):
    assert resolve_provider("glm-99") == ("manifest", "glm-99")


def test_unknown_non_glm_passthrough_unchanged(without_zai_key):
    assert resolve_provider("nonexistent-model-xyz") == ("manifest", "nonexistent-model-xyz")
    assert resolve_provider("nonexistent-model-xyz") == resolve_provider("nonexistent-model-xyz")


def test_routing_table_has_expected_models():
    assert "auto" in MODEL_ROUTING
    assert "gpt-4o" in MODEL_ROUTING
    assert "glm-5.3" in MODEL_ROUTING
    assert "glm-5.3-flash" in MODEL_ROUTING
    assert "glm-4.7-flash" in MODEL_ROUTING
    assert "MiniMax-Text-01" in MODEL_ROUTING


def test_resolve_auto(without_zai_key):
    assert resolve_provider("auto") == ("manifest", "auto")
```

Delete the old `test_all_routes_use_manifest` and old `test_resolve_known_models`/`test_routing_table_has_expected_models` — they pinned the Manifest-only contract this task replaces.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_routing.py -v`
Expected: FAIL — GLM entries still resolve to `("manifest", ...)`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `analytics/routing.py` with:

```python
"""Model routing table — maps model names to (provider, actual_model_id) tuples."""

from config import settings

# Canonical models served by the z.ai GLM Coding Plan endpoint
GLM_CANONICAL = "glm-5.3"
GLM_CANONICAL_FLASH = "glm-5.3-flash"

# Flash-class aliases (speed-tier names) — everything else GLM maps to the strong model
_GLM_FLASH_ALIASES = frozenset({"glm-4.5-flash", "glm-4.7-flash", "glm-4.7-flashx"})


def _canonical_glm(model: str) -> str:
    """Map a GLM name onto the two models the coding plan serves."""
    if model in (GLM_CANONICAL, GLM_CANONICAL_FLASH):
        return model
    if model in _GLM_FLASH_ALIASES:
        return GLM_CANONICAL_FLASH
    return GLM_CANONICAL


def _zai_key_present() -> bool:
    """Effective key check so the llm_api_key fallback stays live (spec §2.1)."""
    return bool(settings.get_api_key("zai-coding"))


# model_name -> (provider_name, actual_model_id)
# Non-GLM models route through Manifest. GLM entries carry their canonical z.ai
# model id; resolve_provider() downgrades them to Manifest when no key is set.
MODEL_ROUTING: dict[str, tuple[str, str]] = {
    # Auto-routing
    "auto": ("manifest", "auto"),
    # OpenAI
    "gpt-5.4": ("manifest", "gpt-5.4"),
    "gpt-4o": ("manifest", "gpt-4o"),
    "gpt-4o-mini": ("manifest", "gpt-4o-mini"),
    "o3": ("manifest", "o3"),
    # Anthropic
    "claude-sonnet": ("manifest", "claude-sonnet-4-6"),
    "claude-haiku": ("manifest", "claude-haiku-4-5-20251001"),
    # Google
    "gemini-2.5-flash": ("manifest", "gemini-2.5-flash"),
    "gemini-2.0-flash": ("manifest", "gemini-2.0-flash"),
    "gemini-2.0-flash-lite": ("manifest", "gemini-2.0-flash-lite"),
    # DeepSeek
    "deepseek-chat": ("manifest", "deepseek-chat"),
    "deepseek-reasoner": ("manifest", "deepseek-reasoner"),
    # MoonshotAI (Kimi)
    "kimi-k2.5": ("manifest", "kimi-k2.5"),
    "kimi-k2-thinking": ("manifest", "kimi-k2-thinking"),
    "moonshot-v1-128k": ("manifest", "moonshot-v1-128k"),
    # Z.AI GLM Coding Plan — canonical pair + aliases (flash-named -> flash, rest -> glm-5.3)
    GLM_CANONICAL: ("zai-coding", GLM_CANONICAL),
    GLM_CANONICAL_FLASH: ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-5.1": ("zai-coding", GLM_CANONICAL),
    "glm-5-turbo": ("zai-coding", GLM_CANONICAL),
    "glm-5": ("zai-coding", GLM_CANONICAL),
    "glm-4.7": ("zai-coding", GLM_CANONICAL),
    "glm-4.7-flash": ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-4.7-flashx": ("zai-coding", GLM_CANONICAL_FLASH),
    "glm-4.6": ("zai-coding", GLM_CANONICAL),
    "glm-4.5": ("zai-coding", GLM_CANONICAL),
    "glm-4.5-flash": ("zai-coding", GLM_CANONICAL_FLASH),
    # MiniMax
    "MiniMax-Text-01": ("manifest", "MiniMax-Text-01"),
    # ByteDance Doubao
    "doubao-pro-32k": ("manifest", "doubao-pro-32k"),
    "doubao-pro-128k": ("manifest", "doubao-pro-128k"),
}

AVAILABLE_MODELS: list[str] = list(MODEL_ROUTING.keys())


def resolve_provider(model: str) -> tuple[str, str]:
    """Resolve a model name to (provider_name, actual_model_id).

    GLM models go to the z.ai coding endpoint when an effective key is
    configured; without one they degrade to Manifest with canonical ids.
    Unknown glm-* names follow the same rule with the name passed through;
    all other unknown models pass through to Manifest as-is.
    """
    entry = MODEL_ROUTING.get(model)
    if entry:
        provider_name, model_id = entry
        if provider_name != "zai-coding" or _zai_key_present():
            return entry
        return ("manifest", model_id)

    if model.lower().startswith("glm-") and _zai_key_present():
        return ("zai-coding", model)

    # Passthrough: unknown models go to Manifest as-is
    return ("manifest", model)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_routing.py -v`
Expected: 10 PASS.

- [ ] **Step 5: Run the full suite for regressions**

Run: `make test-unit`
Expected: all PASS except possibly `tests/test_analytics_endpoints.py` model-list assertions — if any test asserted the exact model count or that every `owned_by` is `manifest`, update it to the new contract (GLM entries now `owned_by: zai-coding`) and re-run. Do not weaken auth assertions.

- [ ] **Step 6: Commit**

```bash
git add analytics/routing.py tests/test_routing.py tests/test_analytics_endpoints.py
git commit -m "feat: route GLM models to zai-coding with effective-key gate"
```

---

### Task 4: UsageData.cached_tokens + provider extraction

**Files:**
- Modify: `providers/base.py:1-8`
- Modify: `providers/openai_compatible_base.py:49-61`
- Test: `tests/test_openai_compatible_base.py` (create)

**Interfaces:**
- Consumes: existing `UsageData` TypedDict, `StreamChunk`.
- Produces: `UsageData` gains `cached_tokens: NotRequired[int]` (consumers must use `usage.get("cached_tokens", 0)`); `OpenAICompatibleProvider.chat_stream` populates it from `chunk.usage.prompt_tokens_details.cached_tokens` when present. Task 5's `estimate_credits` reads this key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_openai_compatible_base.py`:

```python
"""Unit tests for OpenAICompatibleProvider usage extraction (cached tokens)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from providers.openai_compatible_base import OpenAICompatibleProvider


def _chunk(content: str | None = None, usage=None):
    delta = SimpleNamespace(content=content)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)


def _usage(prompt=10, completion=3, total=13, cached=None):
    details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion,
                           total_tokens=total, prompt_tokens_details=details)


def _provider_with_chunks(chunks):
    provider = OpenAICompatibleProvider(api_key="test", model="glm-5.3")
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=_aiter(chunks))))
    )
    return provider


def _aiter(chunks):
    async def gen():
        for c in chunks:
            yield c
    return gen()


@pytest.mark.asyncio
async def test_usage_chunk_includes_cached_tokens():
    provider = _provider_with_chunks([
        _chunk(content="Hi"),
        _chunk(usage=_usage(prompt=100, completion=5, total=105, cached=95)),
    ])
    collected = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")]
    assert collected[0] == ("Hi", None)
    token, usage = collected[1]
    assert token == ""
    assert usage["prompt_tokens"] == 100
    assert usage["cached_tokens"] == 95


@pytest.mark.asyncio
async def test_usage_without_cache_details_omits_key():
    provider = _provider_with_chunks([
        _chunk(usage=_usage(prompt=10, completion=3, total=13, cached=None)),
    ])
    _, usage = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")][0]
    assert "cached_tokens" not in usage


@pytest.mark.asyncio
async def test_zero_cached_tokens_omitted():
    provider = _provider_with_chunks([
        _chunk(usage=_usage(cached=0)),
    ])
    _, usage = [c async for c in provider.chat_stream([{"role": "user", "content": "x"}], "")][0]
    assert "cached_tokens" not in usage
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_openai_compatible_base.py -v`
Expected: FAIL — `usage["cached_tokens"]` KeyError (extraction not implemented).

- [ ] **Step 3: Write minimal implementation**

In `providers/base.py`, change the imports and `UsageData`:

```python
from abc import ABC, abstractmethod
from typing import AsyncGenerator, NotRequired, TypedDict


class UsageData(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: NotRequired[int]
```

In `providers/openai_compatible_base.py`, replace the `if chunk.usage:` block:

```python
            # Final chunk carries usage stats
            if chunk.usage:
                usage = UsageData(
                    prompt_tokens=chunk.usage.prompt_tokens,
                    completion_tokens=chunk.usage.completion_tokens,
                    total_tokens=chunk.usage.total_tokens,
                )
                details = getattr(chunk.usage, "prompt_tokens_details", None)
                cached = getattr(details, "cached_tokens", None)
                if cached:
                    usage["cached_tokens"] = cached
                yield ("", usage)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_openai_compatible_base.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add providers/base.py providers/openai_compatible_base.py tests/test_openai_compatible_base.py
git commit -m "feat: extract cached_tokens into UsageData"
```

---

### Task 5: Credit estimation — estimate_credits

**Files:**
- Modify: `analytics/cost.py`
- Test: `tests/test_cost.py` (extend)

**Interfaces:**
- Consumes: `UsageData` from Task 4 (reads `prompt_tokens`, `completion_tokens`, `cached_tokens` via `.get`).
- Produces:
  - `estimate_credits(provider: str, model: str, usage: dict, ts: datetime) -> float` — z.ai formula `(fresh_input×I + cached×C + output×O) / 10_000`, halved off-peak; `0.0` for non-`zai-coding` providers or non-canonical models.
  - `is_peak(ts: datetime) -> bool` — True Mon–Fri 14:00–18:00 UTC+8. Task 6 imports this for off-peak share.
- Multipliers (canonical ids only): `glm-5.3` → 6.9/1.7/24.0; `glm-5.3-flash` → 2.3/0.56/8.0.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cost.py`:

```python
"""Unit tests for analytics.cost — calculate_cost() + estimate_credits()."""

from datetime import datetime, timezone

import pytest

from analytics.cost import estimate_credits, is_peak

# 2026-09-07 is a Monday. 07:00 UTC = 15:00 SGT (peak); 23:00 UTC = 07:00 SGT Tue (off-peak).
PEAK_TS = datetime(2026, 9, 7, 7, 0, tzinfo=timezone.utc)
OFF_PEAK_TS = datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc)


def test_is_peak_monday_afternoon_sgt():
    assert is_peak(PEAK_TS) is True


def test_is_not_peak_overnight_sgt():
    assert is_peak(OFF_PEAK_TS) is False


def test_is_not_peak_weekend():
    assert is_peak(datetime(2026, 9, 5, 7, 0, tzinfo=timezone.utc)) is False  # Saturday


def test_estimate_credits_glm53_peak():
    usage = {"prompt_tokens": 150000, "completion_tokens": 3000, "cached_tokens": 142500}
    # fresh 7500*6.9 + cached 142500*1.7 + 3000*24 = 366000 -> 36.6
    assert estimate_credits("zai-coding", "glm-5.3", usage, PEAK_TS) == pytest.approx(36.6)


def test_estimate_credits_off_peak_halved():
    usage = {"prompt_tokens": 150000, "completion_tokens": 3000, "cached_tokens": 142500}
    assert estimate_credits("zai-coding", "glm-5.3", usage, OFF_PEAK_TS) == pytest.approx(18.3)


def test_estimate_credits_flash_multipliers():
    usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
    # 10000*2.3 + 0 + 1000*8 = 31000 -> 3.1
    assert estimate_credits("zai-coding", "glm-5.3-flash", usage, PEAK_TS) == pytest.approx(3.1)


def test_estimate_credits_no_cache_field():
    usage = {"prompt_tokens": 10000, "completion_tokens": 1000}
    assert estimate_credits("zai-coding", "glm-5.3", usage, PEAK_TS) == pytest.approx(
        (10000 * 6.9 + 1000 * 24) / 10_000
    )


def test_estimate_credits_zero_for_manifest():
    assert estimate_credits("manifest", "glm-5.3", {"prompt_tokens": 1, "completion_tokens": 1}, PEAK_TS) == 0.0


def test_estimate_credits_zero_for_unknown_model():
    assert estimate_credits("zai-coding", "glm-99", {"prompt_tokens": 1, "completion_tokens": 1}, PEAK_TS) == 0.0


def test_calculate_cost_still_zero():
    assert calculate_cost("glm-5.3", 1000, 500) == 0.0
```

Also update the module docstring line at the top of the file to reflect both functions (shown above), keeping the existing four `calculate_cost` tests as-is.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cost.py -v`
Expected: FAIL — `ImportError: cannot import name 'estimate_credits'`.

- [ ] **Step 3: Write minimal implementation**

Replace the full contents of `analytics/cost.py`:

```python
"""Cost/credit calculations — Manifest bills internally; z.ai coding plan meters in credits."""

from datetime import datetime, timedelta, timezone

# z.ai GLM Coding Plan credit multipliers, per token, before the /10_000 divisor
_CREDIT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "glm-5.3": {"input": 6.9, "cached": 1.7, "output": 24.0},
    "glm-5.3-flash": {"input": 2.3, "cached": 0.56, "output": 8.0},
}

_SGT = timezone(timedelta(hours=8))


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return 0.0 — Manifest handles billing internally."""
    return 0.0


def is_peak(ts: datetime) -> bool:
    """True during z.ai peak window: Mon–Fri 14:00–18:00 Singapore time (UTC+8)."""
    local = ts.astimezone(_SGT)
    return local.weekday() < 5 and 14 <= local.hour < 18


def estimate_credits(provider: str, model: str, usage: dict, ts: datetime) -> float:
    """Estimate GLM Coding Plan credits for one request; 0.0 for other providers/models."""
    if provider != "zai-coding":
        return 0.0
    multipliers = _CREDIT_MULTIPLIERS.get(model)
    if multipliers is None:
        return 0.0
    cached = usage.get("cached_tokens") or 0
    fresh_input = max(usage.get("prompt_tokens", 0) - cached, 0)
    raw = (
        fresh_input * multipliers["input"]
        + cached * multipliers["cached"]
        + usage.get("completion_tokens", 0) * multipliers["output"]
    )
    credits = raw / 10_000
    if not is_peak(ts):
        credits *= 0.5  # Off-peak hours are charged at 50%
    return round(credits, 4)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cost.py -v`
Expected: 14 PASS (4 old + 10 new).

- [ ] **Step 5: Commit**

```bash
git add analytics/cost.py tests/test_cost.py
git commit -m "feat: credit estimation for zai-coding requests"
```

---

### Task 6: Storage — credits_used column, migration, summary query

**Files:**
- Modify: `analytics/db.py`
- Test: `tests/test_analytics_db.py` (extend)

**Interfaces:**
- Consumes: `is_peak(ts)` from Task 5 (off-peak share).
- Produces:
  - `request_logs.credits_used REAL NOT NULL DEFAULT 0.0` — present on both fresh and pre-existing databases; `log_request(record)` reads `record.get("credits_used", 0.0)`.
  - `get_credits_summary() -> dict` returning `{"credits_5h": float, "credits_7d": float, "by_model": dict[str, dict], "off_peak_share": float | None}` — `by_model` maps canonical model → `{"credits_used": float, "requests": int}` over the 7-day window; `off_peak_share` is the fraction of zai-coding requests (7-day window) that started off-peak, `None` when no requests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_db.py` (reuse the module's existing `db` fixture if present; if the module defines `db(tmp_path)` keep using it — it yields an initialized in-memory `AnalyticsDB`):

```python
# --- credits_used column + get_credits_summary ---

from datetime import datetime, timedelta, timezone


def _credit_record(model="glm-5.3", credits=36.6, minutes_ago=0, provider="zai-coding"):
    created = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "id": f"row-{model}-{minutes_ago}-{credits}",
        "provider": provider,
        "model": model,
        "prompt_tokens": 150000,
        "completion_tokens": 3000,
        "total_tokens": 153000,
        "credits_used": credits,
        "created_at": created.isoformat(),
    }


@pytest.mark.asyncio
async def test_log_request_persists_credits(db):
    await db.log_request(_credit_record(credits=12.5))
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == pytest.approx(12.5)
    assert summary["credits_7d"] == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_credits_summary_windows(db):
    await db.log_request(_credit_record(credits=10, minutes_ago=60))       # inside 5h
    await db.log_request(_credit_record(credits=20, minutes_ago=8 * 60))   # outside 5h, inside 7d
    await db.log_request(_credit_record(credits=40, minutes_ago=8 * 24 * 60))  # outside both
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == pytest.approx(10)
    assert summary["credits_7d"] == pytest.approx(30)
    assert summary["by_model"]["glm-5.3"]["credits_used"] == pytest.approx(30)
    assert summary["by_model"]["glm-5.3"]["requests"] == 2


@pytest.mark.asyncio
async def test_credits_summary_excludes_manifest_rows(db):
    await db.log_request(_credit_record(provider="manifest", credits=99))
    summary = await db.get_credits_summary()
    assert summary["credits_5h"] == 0.0
    assert summary["by_model"] == {}


@pytest.mark.asyncio
async def test_credits_summary_off_peak_share_and_empty(db):
    assert (await db.get_credits_summary())["off_peak_share"] is None


@pytest.mark.asyncio
async def test_migration_adds_column_to_preexisting_schema(tmp_path):
    import sqlite3

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE request_logs (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0, latency_ms INTEGER DEFAULT 0,
            ttft_ms INTEGER DEFAULT 0, cost_usd REAL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'success', error_message TEXT,
            created_at TEXT NOT NULL)"""
    )
    conn.commit()
    conn.close()

    db = AnalyticsDB(path)
    await db.initialize()
    await db.log_request(_credit_record(credits=5.0))
    summary = await db.get_credits_summary()
    await db.close()
    assert summary["credits_7d"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_initialize_is_idempotent_for_credits_column(tmp_path):
    db = AnalyticsDB(str(tmp_path / "fresh.db"))
    await db.initialize()
    await db.close()
    db = AnalyticsDB(str(tmp_path / "fresh.db"))
    await db.initialize()  # second init: CREATE IF NOT EXISTS + ALTER must not raise
    await db.close()
```

Ensure the module's imports include `pytest` and `from analytics.db import AnalyticsDB`; if the file already has a local `db(tmp_path)` fixture, keep it and let these tests use it (the last two manage their own DB).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analytics_db.py -v`
Expected: FAIL — `credits_used` not persisted (schema lacks column / `get_credits_summary` missing).

- [ ] **Step 3: Write minimal implementation**

In `analytics/db.py`:

1. Add to imports: `from datetime import timedelta` (keep existing `datetime, timezone`) and `from analytics.cost import is_peak`.
2. In `_SCHEMA`, add after the `cost_usd` line: `credits_used REAL NOT NULL DEFAULT 0.0,`.
3. In `initialize()`, after `await self._db.executescript(_SCHEMA)` and before `commit()`, add the idempotent migration:

```python
        # Migration: older databases predate the credits_used column
        try:
            await self._db.execute(
                "ALTER TABLE request_logs ADD COLUMN credits_used REAL NOT NULL DEFAULT 0.0"
            )
        except sqlite3.OperationalError as e:
            if "duplicate column" not in str(e):
                raise
```

Add `import sqlite3` to the stdlib imports.

4. In `log_request()`, add `credits_used` to the column list, the `VALUES` placeholders (one more `?`), and the tuple: `record.get("credits_used", 0.0),` placed after `record.get("cost_usd", 0.0),`.

5. Add the new query method after `get_recent()`:

```python
    async def get_credits_summary(self) -> dict:
        """Rolling 5h/7d zai-coding credit totals (estimates; spec §2.4)."""
        now = datetime.now(timezone.utc)
        since_7d = (now - timedelta(days=7)).isoformat()
        since_5h = (now - timedelta(hours=5)).isoformat()
        async with self._db.execute(
            """SELECT model, credits_used, created_at FROM request_logs
               WHERE provider = 'zai-coding' AND created_at >= ?""",
            (since_7d,),
        ) as cursor:
            rows = await cursor.fetchall()

        credits_5h = 0.0
        credits_7d = 0.0
        by_model: dict[str, dict] = {}
        off_peak = 0
        for model, credits_used, created_at in rows:
            credits_7d += credits_used
            if created_at >= since_5h:
                credits_5h += credits_used
            entry = by_model.setdefault(model, {"credits_used": 0.0, "requests": 0})
            entry["credits_used"] += credits_used
            entry["requests"] += 1
            if not is_peak(datetime.fromisoformat(created_at)):
                off_peak += 1

        return {
            "credits_5h": round(credits_5h, 4),
            "credits_7d": round(credits_7d, 4),
            "by_model": by_model,
            "off_peak_share": (off_peak / len(rows)) if rows else None,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_db.py -v`
Expected: all PASS (existing + 6 new).

- [ ] **Step 5: Commit**

```bash
git add analytics/db.py tests/test_analytics_db.py
git commit -m "feat: persist credits_used with idempotent migration and summary query"
```

---

### Task 7: Chat route — credit logging + zai-coding error mapping

**Files:**
- Modify: `routes/chat.py`
- Test: `tests/test_chat_endpoint.py` (extend)

**Interfaces:**
- Consumes: `estimate_credits` (Task 5), `usage.get("cached_tokens")` (Task 4), `log_request(record["credits_used"])` (Task 6), `provider_name == "zai-coding"` from Task 3.
- Produces: SSE error frames for zai-coding failures — quota (HTTP 429 or error text containing `1113`) → `{"error": "zai-coding quota exhausted — resets within the 5-hour window"}`; auth (401/403) → `{"error": "zai-coding authentication failed"}`; everything else unchanged (`{"error": "Internal error processing request"}`). Note: with the current architecture the first upstream call happens inside the SSE stream, so these mappings surface as SSE frames, not pre-stream HTTP statuses.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_chat_endpoint.py`:

```python
# --- zai-coding credit logging + error mapping ---


class ZaiQuotaError(Exception):
    status_code = 429


class ZaiAuthError(Exception):
    status_code = 401


def _zai_stream_request():
    return {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "hi"}],
    }


@pytest.mark.asyncio
async def test_zai_coding_quota_error_frame(client, auth_headers):
    class QuotaProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("tok", None)
            raise ZaiQuotaError("429 too many requests")

    with patch("routes.chat.create_provider", return_value=QuotaProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding quota exhausted" in response.text
    assert "Internal error" not in response.text


@pytest.mark.asyncio
async def test_zai_coding_auth_error_frame(client, auth_headers):
    class AuthFailProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            raise ZaiAuthError("401 unauthorized")

    with patch("routes.chat.create_provider", return_value=AuthFailProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding authentication failed" in response.text


@pytest.mark.asyncio
async def test_zai_coding_1113_code_maps_to_quota(client, auth_headers):
    class BalanceError(Exception):
        status_code = 402

    class BalanceProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            raise BalanceError("1113 Insufficient Balance")

    with patch("routes.chat.create_provider", return_value=BalanceProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        response = await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )
    assert "zai-coding quota exhausted" in response.text


@pytest.mark.asyncio
async def test_generic_provider_error_unaffected(client, auth_headers):
    class GenericFailProvider:
        async def chat_stream(self, messages, system_prompt, params=None):
            yield ("start", None)
            raise RuntimeError("Provider failed")

    with patch("routes.chat.create_provider", return_value=GenericFailProvider()), \
         patch("routes.chat.resolve_provider", return_value=("manifest", "gpt-4o")):
        response = await client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
            headers=auth_headers,
        )
    assert "Internal error processing request" in response.text


@pytest.mark.asyncio
async def test_zai_coding_request_logs_credits(client, auth_headers, analytics_db):
    # 3-arg-tolerant signature: the route calls chat_stream(messages, system_prompt, gen_params)
    class CreditUsageProvider:
        async def chat_stream(self, *args, **kwargs):
            yield ("tok", None)
            yield ("", {
                "prompt_tokens": 150000,
                "completion_tokens": 3000,
                "total_tokens": 153000,
                "cached_tokens": 142500,
            })

    with patch("routes.chat.create_provider", return_value=CreditUsageProvider()), \
         patch("routes.chat.resolve_provider", return_value=("zai-coding", "glm-5.3")):
        await client.post(
            "/v1/chat/completions", json=_zai_stream_request(), headers=auth_headers
        )

    await asyncio.sleep(0.1)  # fire-and-forget log task
    summary = await analytics_db.get_credits_summary()
    # 36.6 peak / 18.3 off-peak depending on wall clock — accept either
    assert summary["credits_7d"] in (pytest.approx(36.6), pytest.approx(18.3))
```

The test file already imports `patch` and `pytest`; add `import asyncio` at the top. Do not use `conftest.MockProvider`/`FailingProvider` here — their `chat_stream` signatures take only `(messages, system_prompt)` and the route calls with a third `gen_params` argument.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_chat_endpoint.py -v -k "zai or generic_provider"`
Expected: FAIL — zai tests see `Internal error processing request`; credits test sees `credits_7d == 0`.

- [ ] **Step 3: Write minimal implementation**

In `routes/chat.py`:

1. Extend imports: `from datetime import datetime, timezone` and change the cost import to `from analytics.cost import calculate_cost, estimate_credits`.
2. Replace the `except Exception as e:` block inside `_tracked_stream`:

```python
    except Exception as e:
        error_msg = str(e)
        logger.error("Provider stream error: %s", error_msg)
        client_msg = "Internal error processing request"
        if provider_name == "zai-coding":
            status = getattr(e, "status_code", None)
            if status == 429 or "1113" in error_msg:
                client_msg = "zai-coding quota exhausted — resets within the 5-hour window"
            elif status in (401, 403):
                client_msg = "zai-coding authentication failed"
        yield f"data: {json.dumps({'error': client_msg})}\n\n"
```

3. In the `finally:` block, after the `cost_usd = ...` line add:

```python
        credits_used = estimate_credits(
            provider_name, model_id, usage_data or {}, datetime.now(timezone.utc)
        )
```

and add `"credits_used": credits_used,` to the `log_request({...})` dict after `"cost_usd": cost_usd,`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_chat_endpoint.py -v`
Expected: all PASS (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add routes/chat.py tests/test_chat_endpoint.py
git commit -m "feat: log estimated credits and map zai-coding stream errors"
```

---

### Task 8: API — GET /v1/analytics/credits

**Files:**
- Modify: `routes/analytics.py`
- Test: `tests/test_analytics_endpoints.py` (extend)

**Interfaces:**
- Consumes: `db.get_credits_summary()` (Task 6); `settings.zai_credits_5h` / `settings.zai_credits_week` (Task 1); `verify_auth`, `_get_db` (existing).
- Produces: `GET /v1/analytics/credits` (auth required) returning exactly:

```json
{
  "window_5h": {"credits_used": 0.0, "quota": 28000},
  "window_7d_rolling": {"credits_used": 0.0, "quota": 140000, "note": "rolling estimate; z.ai weekly reset anchored to subscription date"},
  "by_model": {},
  "off_peak_share": null
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_analytics_endpoints.py`:

```python
# --- GET /v1/analytics/credits ---


@pytest.mark.asyncio
async def test_credits_endpoint_requires_auth(client):
    response = await client.get("/v1/analytics/credits")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_credits_endpoint_empty(client, auth_headers):
    response = await client.get("/v1/analytics/credits", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["window_5h"] == {"credits_used": 0.0, "quota": 28000}
    assert body["window_7d_rolling"]["quota"] == 140000
    assert "rolling estimate" in body["window_7d_rolling"]["note"]
    assert body["by_model"] == {}
    assert body["off_peak_share"] is None


@pytest.mark.asyncio
async def test_credits_endpoint_aggregates_rows(client, auth_headers, analytics_db):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    for credits in (10.0, 25.5):
        await analytics_db.log_request({
            "id": f"c-{credits}",
            "provider": "zai-coding",
            "model": "glm-5.3",
            "credits_used": credits,
            "created_at": (now - timedelta(minutes=30)).isoformat(),
        })
    response = await client.get("/v1/analytics/credits", headers=auth_headers)
    body = response.json()
    assert body["window_5h"]["credits_used"] == pytest.approx(35.5)
    assert body["by_model"]["glm-5.3"]["requests"] == 2
```

(If the file lacks imports for `pytest`, add them; `client`/`auth_headers`/`analytics_db` come from `conftest.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analytics_endpoints.py -v -k credits`
Expected: FAIL — 404 Not Found (route doesn't exist).

- [ ] **Step 3: Write minimal implementation**

In `routes/analytics.py`, add `from config import settings` to imports, then append after the `/requests` endpoint:

```python
@analytics_router.get("/credits")
async def get_credits(request: Request, _auth=Depends(verify_auth)):
    """Estimated z.ai coding-plan credit burn vs configured quota."""
    db = _get_db(request)
    summary = await db.get_credits_summary()
    return {
        "window_5h": {"credits_used": summary["credits_5h"], "quota": settings.zai_credits_5h},
        "window_7d_rolling": {
            "credits_used": summary["credits_7d"],
            "quota": settings.zai_credits_week,
            "note": "rolling estimate; z.ai weekly reset anchored to subscription date",
        },
        "by_model": summary["by_model"],
        "off_peak_share": summary["off_peak_share"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_endpoints.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add routes/analytics.py tests/test_analytics_endpoints.py
git commit -m "feat: expose credit burn via GET /v1/analytics/credits"
```

---

### Task 9: Docs, full suite, manual smoke test

**Files:**
- Modify: `README.md` (models/env sections only)

**Interfaces:**
- Consumes: everything above.
- Produces: documented feature; verified suite; recorded smoke-test result.

- [ ] **Step 1: Update README**

In `README.md`, wherever env vars or providers are listed (mirror `.env.example`'s canonical list): add `ZAI_CODING_API_KEY` (routes `glm-*` to the z.ai coding endpoint; unset = Manifest), `ZAI_CREDITS_5H`, `ZAI_CREDITS_WEEK`, and a short "GLM Coding Plan" paragraph: endpoint, canonical models (`glm-5.3`, `glm-5.3-flash`), alias remapping, no-fallback quota behavior, and `GET /v1/analytics/credits`. Keep it under 15 lines — README is an authoritative current-state doc.

- [ ] **Step 2: Run the full test suite**

Run: `make test`
Expected: all PASS, zero failures. If anything fails, fix before committing — do not skip.

- [ ] **Step 3: Manual smoke test (requires real key)**

With `ZAI_CODING_API_KEY` set in `.env` and the server running (`make dev`):

```bash
# 1. Streaming completion through the coding endpoint
curl -N http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $APP_API_KEY" -H "Content-Type: application/json" \
  -d '{"model": "glm-5.3", "messages": [{"role": "user", "content": "Say OK"}]}'
# Expect: SSE token frames then data: [DONE]

# 2. Alias remap
curl -s http://localhost:8000/v1/models -H "Authorization: Bearer $APP_API_KEY" | grep glm
# Expect: glm-5.3 and glm-5.3-flash present

# 3. Credits recorded
curl -s http://localhost:8000/v1/analytics/credits -H "Authorization: Bearer $APP_API_KEY"
# Expect: window_5h.credits_used > 0 after step 1
```

Record pass/fail of each in the task's commit message body. If no key is available at execution time, record "smoke deferred — no key" and stop after Step 2's commit.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document zai-coding provider and credits endpoint

smoke: glm-5.3 stream=PASS models=PASS credits=PASS"
```

---

## Self-Review (completed during planning)

- **Spec coverage**: §2.1 provider/factory/routing → Tasks 2–3; §2.2 config → Task 1; §2.3 data flow + credit estimation → Tasks 4–5, 7; §2.4 storage/migration → Task 6; §2.5 API → Task 8; §2.6 error handling → Task 7; §2.7 testing → per-task TDD + Task 9 full suite; §2.8 out-of-scope respected (no Anthropic endpoint, no fallback, no `auto` change, no live quota API).
- **Placeholder scan**: every step carries actual code/commands; no TBD/TODO.
- **Type consistency**: `estimate_credits(provider, model, usage, ts)` matches across Tasks 5/7; `get_credits_summary()` keys (`credits_5h`, `credits_7d`, `by_model`, `off_peak_share`) match between Task 6 and Task 8; `cached_tokens: NotRequired[int]` consumed via `.get()` in Tasks 5/7; `("zai-coding", ...)` tuple shape consistent across Tasks 2/3/7.
