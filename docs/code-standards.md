# Code Standards

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python files | kebab-case | `providers/gemini.py` (module name matches class) |
| Classes | PascalCase | `GeminiProvider`, `LLMProvider` |
| Functions/methods | snake_case | `chat_stream()`, `create_provider()` |
| Constants | UPPER_SNAKE | `_ROLE_MAP` |
| Environment variables | UPPER_SNAKE | `LLM_PROVIDER`, `APP_API_KEY` |
| Pydantic fields | snake_case | `llm_api_key`, `app_api_key` |

## File Organization

```
llm-gateway/
├── main.py              # FastAPI app, routes, request/response logic
├── config.py            # Settings (pydantic BaseSettings)
├── providers/
│   ├── __init__.py      # Factory function create_provider()
│   ├── base.py          # Abstract base class LLMProvider
│   ├── gemini.py        # GeminiProvider
│   ├── glm.py           # GLMProvider
│   └── minimax.py       # MiniMaxProvider
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── Makefile             # Task automation
└── .gitignore           # Git ignore rules
```

Rules:
- One provider per file in `providers/` directory
- Provider file names match the class name (lowercase): `gemini.py` -> `GeminiProvider`
- Keep `main.py` focused on HTTP concerns (routing, auth, SSE formatting)
- Keep provider files focused on LLM API integration

## Code Style

- Python 3.12+ features are acceptable (match statements, `str | None` type unions)
- Use `async/await` for all I/O operations
- Use `from __future__ import annotations` if forward references needed
- Type hints on all function signatures
- No separate `tests/` directory yet -- use `make test` for endpoint smoke test
- Logging via standard `logging.getLogger(__name__)` pattern

## Adding a New Provider

Follow these steps to add a new LLM provider (e.g., "claude"):

### 1. Create the provider file

Create `providers/claude.py`:

```python
from providers.base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self):
        # Initialize client with settings.llm_api_key, settings.llm_base_url
        # Set self.model to settings.llm_model or a sensible default
        ...

    async def chat_stream(self, messages: list[dict], system_prompt: str):
        # Call the provider API
        # Yield token strings one at a time
        ...
            yield token
```

### 2. Register in the factory

Edit `providers/__init__.py`, add a new `case` to the match statement:

```python
case "claude":
    from providers.claude import ClaudeProvider
    return ClaudeProvider()
```

### 3. Update .env.example

Add the provider name to the `LLM_PROVIDER` comment:

```env
# LLM_PROVIDER=gemini | glm | minimax | claude
```

### 4. Add dependencies

If the provider needs a new SDK, add it to `requirements.txt`.

### 5. Test

```bash
LLM_PROVIDER=claude make test
```

## Error Handling

- Provider errors: caught in `_stream_tokens()`, emitted as `{"error": "..."}` SSE events
- Auth errors: raised as `HTTPException(401)` via FastAPI dependency
- Unknown provider: `ValueError` raised in `create_provider()` -- results in 500

Pattern for provider errors:
```python
async def chat_stream(self, messages, system_prompt):
    try:
        # API call
        async for chunk in response:
            yield chunk
    except ProviderSpecificError as e:
        raise RuntimeError(f"Provider error: {e}") from e
```

## Testing Guidelines

- **Current**: `make test` runs a live curl against the chat endpoint
- **Unit tests** (future): Test each provider in isolation by mocking the SDK client
- **Integration tests** (future): Test the full request-to-SSE pipeline

Test structure when added:
```
tests/
├── test_main.py           # Route tests (auth, health, chat)
├── test_providers.py      # Provider factory and individual providers
└── conftest.py            # Shared fixtures, mock settings
```

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [System Architecture](./system-architecture.md)
- [Deployment Guide](./deployment-guide.md)
