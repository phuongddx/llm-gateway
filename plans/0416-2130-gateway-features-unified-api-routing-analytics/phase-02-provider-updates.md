# Phase 2: Provider Updates — Base Class + 5 New Providers

## Context Links

- [Plan Overview](./plan.md)
- [Phase 1: Config & Routing](./phase-01-config-and-routing.md) (prerequisite)
- Current base class: `providers/base.py` (11 LOC)
- Current providers: `providers/gemini.py` (51 LOC), `providers/glm.py` (29 LOC), `providers/minimax.py` (29 LOC)

## Overview

- **Priority**: P1 (blocks Phase 3 — analytics needs usage data from providers)
- **Status**: `[ ]`
- **Description**: Update base class to yield `(token, usage_dict | None)` tuples. Update 3 existing providers to extract usage metadata. Add 5 new OpenAI-compatible providers (OpenAI, DeepSeek, MoonshotAI, ByteDance Doubao). Extract shared OpenAI-compatible logic into a base class.

## Key Insights

1. **DRY opportunity**: GLM, MiniMax, and all 5 new providers are OpenAI-compatible. They share identical streaming logic — only `base_url` and `model` differ. Extract into `OpenAICompatibleProvider` base class.
2. **Usage extraction varies by provider**:
   - OpenAI-compatible: `stream_options={"include_usage": True}` adds a final chunk with `chunk.usage` populated
   - Gemini: `usage_metadata` attribute on response chunks
3. **Provider constructors change**: accept `api_key` and `model` as params (from routing), not from global settings
4. **ByteDance special case**: uses endpoint IDs (ep-xxx) as model names, not standard model names

## Requirements

### Functional

- FR-2.1: `chat_stream()` yields `AsyncGenerator[tuple[str, dict | None], None]`
- FR-2.2: OpenAI-compatible providers pass `stream_options={"include_usage": True}` to get token counts
- FR-2.3: Gemini provider extracts `usage_metadata` from chunks
- FR-2.4: Usage dict schema: `{"prompt_tokens": int, "completion_tokens": int, "total_tokens": int}`
- FR-2.5: All providers accept `api_key: str` and `model: str` in `__init__`

### Non-Functional

- NFR-2.1: Each provider file stays under 100 LOC
- NFR-2.2: OpenAI-compatible providers share a single base class — no duplicate streaming logic
- NFR-2.3: Provider instantiation is cheap (no I/O in `__init__`)

## Architecture

### Provider Hierarchy

```
LLMProvider (ABC)
├── OpenAICompatibleProvider (ABC)
│   ├── OpenAIProvider
│   ├── DeepSeekProvider
│   ├── MoonshotProvider
│   ├── ByteDanceProvider
│   ├── GLMProvider
│   └── MiniMaxProvider
└── GeminiProvider
```

### Usage Data Flow

```
OpenAI-compatible:
  client.chat.completions.create(
      stream=True,
      stream_options={"include_usage": True}  # key addition
  )
  -> chunks stream in, usage=None on token chunks
  -> final chunk has chunk.usage populated
  -> yield (token, None) for each token chunk
  -> yield ("", usage_dict) for the final usage chunk

Gemini:
  client.aio.models.generate_content_stream()
  -> chunk has usage_metadata attribute on final chunk
  -> yield (token, None) for text chunks
  -> yield ("", usage_dict) on chunk with usage_metadata
```

## Related Code Files

### Modify

| File | Change |
|------|--------|
| `providers/base.py` | Change return type to yield tuples; add `UsageData` TypedDict |
| `providers/gemini.py` | Extract usage_metadata; accept api_key/model params |
| `providers/glm.py` | Refactor to extend OpenAICompatibleProvider; add stream_options |
| `providers/minimax.py` | Refactor to extend OpenAICompatibleProvider; add stream_options |

### Create

| File | Purpose | LOC est. |
|------|---------|----------|
| `providers/openai-compatible-base.py` | Shared base for OpenAI-compatible providers | ~50 |
| `providers/openai-provider.py` | OpenAI provider (gpt-4o, gpt-4o-mini, o3) | ~20 |
| `providers/deepseek.py` | DeepSeek provider (deepseek-chat, deepseek-reasoner) | ~20 |
| `providers/moonshot.py` | MoonshotAI provider (kimi-k2.5, moonshot-v1-128k) | ~20 |
| `providers/bytedance.py` | ByteDance Doubao provider (endpoint IDs) | ~20 |

### Delete

None.

## Implementation Steps

1. **Update `providers/base.py`** (~20 LOC):
   ```python
   from typing import AsyncGenerator, TypedDict

   class UsageData(TypedDict):
       prompt_tokens: int
       completion_tokens: int
       total_tokens: int

   StreamChunk = tuple[str, UsageData | None]

   class LLMProvider(ABC):
       @abstractmethod
       async def chat_stream(
           self, messages: list[dict], system_prompt: str
       ) -> AsyncGenerator[StreamChunk, None]:
           """Yield (token, usage_dict | None) tuples from the LLM."""
           ...
   ```

2. **Create `providers/openai-compatible-base.py`** (~60 LOC):
   ```python
   class OpenAICompatibleProvider(LLMProvider):
       """Base for providers using OpenAI-compatible API."""
       base_url: str  # subclass sets this
       default_model: str  # subclass sets this

       def __init__(self, api_key: str, model: str | None = None):
           self.client = AsyncOpenAI(api_key=api_key, base_url=self.base_url)
           self.model = model or self.default_model

       async def chat_stream(self, messages, system_prompt):
           all_messages = []
           if system_prompt:
               all_messages.append({"role": "system", "content": system_prompt})
           all_messages.extend(messages)

           stream = await self.client.chat.completions.create(
               model=self.model,
               messages=all_messages,
               stream=True,
               stream_options={"include_usage": True},
           )

           async for chunk in stream:
               # Extract usage from final chunk
               if chunk.usage:
                   usage = UsageData(
                       prompt_tokens=chunk.usage.prompt_tokens,
                       completion_tokens=chunk.usage.completion_tokens,
                       total_tokens=chunk.usage.total_tokens,
                   )
                   yield ("", usage)
               # Extract text content
               elif chunk.choices:
                   delta = chunk.choices[0].delta.content
                   if delta:
                       yield (delta, None)
   ```

3. **Create `providers/openai-provider.py`** (~20 LOC):
   ```python
   class OpenAIProvider(OpenAICompatibleProvider):
       base_url = "https://api.openai.com/v1"
       default_model = "gpt-4o"
   ```

4. **Create `providers/deepseek.py`** (~20 LOC):
   ```python
   class DeepSeekProvider(OpenAICompatibleProvider):
       base_url = "https://api.deepseek.com"
       default_model = "deepseek-chat"
   ```

5. **Create `providers/moonshot.py`** (~20 LOC):
   ```python
   class MoonshotProvider(OpenAICompatibleProvider):
       base_url = "https://api.moonshot.cn/v1"
       default_model = "kimi-k2.5"
   ```

6. **Create `providers/bytedance.py`** (~20 LOC):
   ```python
   class ByteDanceProvider(OpenAICompatibleProvider):
       base_url = "https://ark.cn-beijing.volces.com/api/v3"
       default_model = ""  # must be endpoint ID
   ```

7. **Update `providers/gemini.py`** (~55 LOC):
   - Accept `api_key: str, model: str | None` in `__init__`
   - Extract `usage_metadata` from chunks: check `chunk.usage_metadata`
   - Map Gemini usage fields to `UsageData` schema
   - Yield `(text, None)` for text chunks, `("", usage)` for usage chunk

8. **Update `providers/glm.py`** (~15 LOC):
   - Refactor to extend `OpenAICompatibleProvider`
   - Set `base_url = "https://open.bigmodel.cn/api/paas/v4"`
   - Set `default_model = "glm-4-flash"`
   - Remove duplicated streaming logic

9. **Update `providers/minimax.py`** (~15 LOC):
   - Refactor to extend `OpenAICompatibleProvider`
   - Set `base_url = "https://api.minimax.chat/v1"`
   - Set `default_model = "MiniMax-Text-01"`
   - Remove duplicated streaming logic

10. **Update `providers/__init__.py`** factory:
    - Add cases for: `openai`, `deepseek`, `moonshot`, `bytedance`
    - Pass `api_key` and `model` from routing resolution to each provider constructor

## Todo Checklist

- [ ] Update `providers/base.py` — UsageData TypedDict, StreamChunk type, new return type
- [ ] Create `providers/openai-compatible-base.py` — shared OpenAI streaming logic
- [ ] Create `providers/openai-provider.py`
- [ ] Create `providers/deepseek.py`
- [ ] Create `providers/moonshot.py`
- [ ] Create `providers/bytedance.py`
- [ ] Update `providers/gemini.py` — usage_metadata extraction
- [ ] Refactor `providers/glm.py` to extend OpenAICompatibleProvider
- [ ] Refactor `providers/minimax.py` to extend OpenAICompatibleProvider
- [ ] Update `providers/__init__.py` factory with new providers
- [ ] Verify each provider file is under 100 LOC

## Success Criteria

- [ ] `OpenAIProvider("key", "gpt-4o").chat_stream(msgs, "")` yields `(token, None)` chunks and final `("", UsageData)` chunk
- [ ] `GeminiProvider("key", "gemini-2.5-flash").chat_stream(msgs, "")` yields text chunks and usage chunk
- [ ] GLM and MiniMax providers work identically to before (backward compat)
- [ ] All 8 providers registered in factory and importable
- [ ] No provider file exceeds 100 LOC
- [ ] `OpenAICompatibleProvider` base class eliminates all streaming duplication

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| OpenAI `stream_options` not supported by some compatible APIs | Medium | High | Test each provider; if `include_usage` causes errors, catch and degrade gracefully (yield usage=None) |
| Gemini usage_metadata field name/version differs | Medium | Medium | Use `getattr(chunk, 'usage_metadata', None)` with fallback; log warning if missing |
| ByteDance endpoint ID auth differs from standard API key | Medium | Medium | Test early; ByteDance may need different auth header format |
| GLM/MiniMax breakage from refactor | Low | High | Keep existing test passing; refactor is structural only, same runtime behavior |

## Security Considerations

- API keys passed as constructor args, not stored globally beyond settings
- No keys in logs or error messages
- Provider errors wrapped in RuntimeError, original exception chained

## Next Steps

- Phase 3 (Analytics Engine) consumes the `UsageData` from providers via `tracked_stream()` wrapper
