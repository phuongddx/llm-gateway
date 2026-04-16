# LLM Provider API Compatibility Research

**Date:** 2026-04-16
**Scope:** OpenAI-compatible providers for gateway integration
**Context:** FastAPI LLM gateway with `openai.AsyncOpenAI` client reuse pattern

---

## Provider Compatibility Matrix

| Provider | Base URL | Top Models | OpenAI-compatible? | SDK | Auth | Notes |
|----------|----------|------------|---------------------|-----|------|-------|
| **OpenAI** | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini, o3 | Native | `openai` | `Authorization: Bearer <key>` | Baseline. o3 is reasoning model. |
| **MoonshotAI (Kimi)** | `https://api.moonshot.cn/v1` | kimi-k2.5, kimi-k2-thinking, moonshot-v1-128k | Yes - full | `openai` | `Authorization: Bearer <key>` | k2-thinking adds reasoning tokens. Vision support on k2.5. `stream_options.include_usage` supported. |
| **DeepSeek** | `https://api.deepseek.com` | deepseek-chat (V3.2), deepseek-reasoner (V3.2) | Yes - full | `openai` | `Authorization: Bearer <key>` | Reasoner outputs `reasoning_content` field. Prompt caching returns `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens` in usage. `stream_options.include_usage` supported. |
| **ByteDance Doubao** | `https://ark.cn-beijing.volces.com/api/v3` | Endpoint IDs (e.g. `ep-xxxxxxxx`) | Yes - full | `openai` | `Authorization: Bearer <key>` | Model names are **endpoint IDs** created in Volcano Engine console, not model names directly. Pre-built endpoints: doubao-pro-32k, doubao-lite-32k. |
| **ZhipuAI** | `https://open.bigmodel.cn/api/paas/v4/` | glm-4-plus, glm-4-flash, glm-4-long | Yes - full | `openai` or `zhipuai` | `Authorization: Bearer <key>` | Can use `openai.AsyncOpenAI(base_url=...)` directly. Also has `zhipuai` SDK with extra features (web search, function calling). Usage in last streaming chunk. |

## Integration Verdict

**All 5 providers are fully OpenAI-compatible** - they can be integrated using `openai.AsyncOpenAI` with `base_url` override. No provider-specific SDKs needed.

The existing provider factory pattern in this codebase (`providers/glm.py`, `providers/minimax.py`) already demonstrates this pattern. New providers follow the same approach:
1. Instantiate `AsyncOpenAI(api_key=..., base_url=...)`
2. Call `client.chat.completions.create(stream=True, ...)`
3. Yield SSE tokens

### Key Differences to Handle

| Concern | Providers Affected | Handling |
|---------|--------------------|----------|
| Reasoning tokens in stream | DeepSeek, Kimi K2 | `reasoning_content` field in delta - optionally surface or suppress |
| Model naming via endpoint IDs | ByteDance Doubao | User must provide endpoint ID as `model` param, not a model name |
| Prompt cache usage stats | DeepSeek | Extra fields in usage: `prompt_cache_hit_tokens`, `prompt_cache_miss_tokens` |
| Vision/multimodal | Kimi K2.5, OpenAI | Requires image content blocks in messages - gateway passes through |

---

## Streaming Token Usage Extraction

**Pattern:** Pass `stream_options={"include_usage": True}` to the create call.

```python
stream = await client.chat.completions.create(
    model=model,
    messages=messages,
    stream=True,
    stream_options={"include_usage": True},
)
```

**Behavior:**
- Final chunk before `data: [DONE]` contains `usage` field
- Structure: `usage.prompt_tokens`, `usage.completion_tokens`, `usage.total_tokens`
- Supported by: OpenAI, MoonshotAI, DeepSeek
- ZhipuAI returns usage in last chunk automatically (no `stream_options` needed)
- ByteDance Doubao: unconfirmed for `stream_options` - may return usage by default

**Gateway implementation note:** Accumulate usage from the final chunk in the SSE generator to log per-request token counts.

---

## aiosqlite + FastAPI Patterns

For token usage logging or request history in the gateway:

### Connection Management via Dependency Injection

```python
# database.py
import aiosqlite
from fastapi import Depends

DB_PATH = "gateway.db"

async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db

# In routes:
@app.post("/v1/chat/completions")
async def chat(db: aiosqlite.Connection = Depends(get_db)):
    await db.execute(
        "INSERT INTO usage_log (model, prompt_tokens, completion_tokens) VALUES (?, ?, ?)",
        (model, usage.prompt_tokens, usage.completion_tokens),
    )
    await db.commit()
```

### Key Patterns
- Use `async with aiosqlite.connect()` for connection lifecycle
- `db.row_factory = aiosqlite.Row` for dict-like access
- Parameterized queries with `?` placeholders (no string interpolation)
- `await db.commit()` after writes (no autocommit)
- Schema init at app startup: `@app.on_event("startup")` or lifespan context manager

---

## Adoption Risk Assessment

| Provider | Risk Level | Rationale |
|----------|------------|-----------|
| OpenAI | **Low** | Baseline, largest ecosystem |
| DeepSeek | **Low** | Well-documented, stable API, strong community |
| MoonshotAI | **Low-Medium** | Good docs, but China-focused - latency concerns from outside mainland |
| ZhipuAI | **Low-Medium** | Already integrated in codebase as `glm` provider, proven |
| ByteDance Doubao | **Medium** | Volcano Engine console dependency for endpoint IDs adds operational complexity; docs are SPA-only (hard to scrape), less community guidance |

## Recommendation Priority

For gateway expansion, integrate in this order:

1. **DeepSeek** - lowest effort (pure OpenAI compatible), high developer demand, reasoning mode differentiation
2. **OpenAI** - baseline necessity, trivial integration
3. **MoonshotAI** - strong context window (128k), reasoning mode on k2-thinking
4. **ByteDance Doubao** - useful for China market but endpoint ID friction adds config complexity
5. **ZhipuAI** - already partially integrated (glm provider), just needs model expansion

---

## Limitations

- ByteDance Doubao details partially from training data (Volcano Engine docs are SPA, unscrapable)
- No latency/benchmark testing performed - only API compatibility assessed
- Rate limits, pricing tiers, and SLAs not covered
- `stream_options.include_usage` support for Doubao unconfirmed via live docs
