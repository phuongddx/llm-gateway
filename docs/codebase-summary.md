# Codebase Summary

Total: 205 LOC across 7 Python files.

## File Breakdown

### `config.py` (14 LOC)

Settings module using `pydantic_settings.BaseSettings`. Reads configuration from `.env` file.

**Settings fields:**

| Field | Type | Default | Source |
|-------|------|---------|--------|
| `llm_provider` | `str` | `gemini` | `LLM_PROVIDER` |
| `llm_api_key` | `str` | `""` | `LLM_API_KEY` |
| `llm_model` | `str` | `""` | `LLM_MODEL` |
| `app_api_key` | `str` | `changeme` | `APP_API_KEY` |
| `llm_base_url` | `str \| None` | `None` | `LLM_BASE_URL` |

Singleton instance: `settings = Settings()`.

### `main.py` (53 LOC)

FastAPI application entry point.

- Creates `FastAPI(title="LLM Gateway")` with CORS middleware (allow all origins)
- Defines `ChatRequest` Pydantic model: `messages`, `system_prompt`, `stream`
- `verify_auth()` dependency -- Bearer token check against `settings.app_api_key`
- `POST /v1/chat/completions` -- creates provider, returns `StreamingResponse`
- `GET /health` -- returns `{"status": "ok"}`
- `_stream_tokens()` -- async generator wrapping `provider.chat_stream()`, formats SSE

### `providers/__init__.py` (18 LOC)

Factory function `create_provider() -> LLMProvider`.

Uses Python `match` statement on `settings.llm_provider`:
- `"gemini"` -- imports and returns `GeminiProvider`
- `"glm"` -- imports and returns `GLMProvider`
- `"minimax"` -- imports and returns `MiniMaxProvider`
- Otherwise -- raises `ValueError`

Lazy imports inside the match cases avoid loading unused SDKs.

### `providers/base.py` (11 LOC)

Abstract base class `LLMProvider(ABC)`.

Single abstract method:
```python
async def chat_stream(self, messages: list[dict], system_prompt: str) -> AsyncGenerator[str, None]
```

All providers must implement this async generator that yields token strings.

### `providers/gemini.py` (51 LOC)

`GeminiProvider` using the `google-genai` SDK.

Key details:
- Uses `google.genai.Client` with `api_key`
- Default model: `gemini-2.5-flash`
- Role mapping: `{"user": "user", "assistant": "model", "system": "user"}`
- System prompt passed via `GenerateContentConfig(system_instruction=...)`
- Uses `client.aio.models.generate_content_stream()` for async streaming
- `_to_contents()` converts OpenAI-style messages to Gemini `types.Content` objects

### `providers/glm.py` (29 LOC)

`GLMProvider` for ZhipuAI using `openai.AsyncOpenAI` client.

- Default base URL: `https://open.bigmodel.cn/api/paas/v4`
- Default model: `glm-4-flash`
- Prepends system prompt as a `system` role message
- Streams via `client.chat.completions.create(stream=True)`

### `providers/minimax.py` (29 LOC)

`MiniMaxProvider` using `openai.AsyncOpenAI` client.

- Default base URL: `https://api.minimax.chat/v1`
- Default model: `MiniMax-Text-01`
- Identical implementation to `GLMProvider` (only default URL and model differ)

## Supporting Files

| File | Purpose |
|------|---------|
| `requirements.txt` | 6 dependencies: fastapi, uvicorn, pydantic-settings, google-genai, openai, python-dotenv |
| `.env.example` | Template with all config variables and defaults |
| `Makefile` | Task automation: install, start, dev, stop, health, test, clean |
| `.gitignore` | Excludes `__pycache__`, `.env`, `.venv`, build artifacts |

## Key Patterns

### Provider Pattern
Abstract `LLMProvider` base class with `chat_stream()` async generator. Each provider implements provider-specific API calls while exposing a uniform interface.

### Factory Pattern
`create_provider()` dispatches to the correct provider class based on `LLM_PROVIDER` env var. Lazy imports keep SDK loading minimal.

### SSE Streaming
All responses flow through `_stream_tokens()` which wraps provider output in `data: {...}\n\n` SSE format. Terminal `data: [DONE]\n\n` signals completion.

### OpenAI-Compatible Providers
GLM and MiniMax share identical code structure because both expose OpenAI-compatible APIs. The `AsyncOpenAI` client works with any server implementing the OpenAI chat completions protocol.

## Related Docs

- [Code Standards](./code-standards.md)
- [System Architecture](./system-architecture.md)
- [Project Overview & PDR](./project-overview-pdr.md)
