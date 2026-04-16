# Code Standards

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python files | kebab-case | `providers/openai-provider.py`, `analytics/routing.py` |
| Classes | PascalCase | `GeminiProvider`, `LLMProvider`, `AnalyticsDB` |
| Functions/methods | snake_case | `chat_stream()`, `create_provider()`, `resolve_provider()` |
| Constants | UPPER_SNAKE | `_ROLE_MAP`, `MODEL_ROUTING`, `MODEL_PRICING` |
| Environment variables | UPPER_SNAKE | `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `ANALYTICS_DB_PATH` |
| Pydantic fields | snake_case | `openai_api_key`, `analytics_db_path` |
| Route prefixes | kebab-case | `/v1/analytics/summary` |

## File Organization

```
llm-gateway/
+-- main.py                      # FastAPI app, lifespan, CORS, health
+-- config.py                    # Settings (pydantic BaseSettings)
+-- providers/
|   +-- __init__.py              # Factory create_provider()
|   +-- base.py                  # ABC LLMProvider, UsageData, StreamChunk
|   +-- openai_compatible_base.py # Shared base for OpenAI-protocol providers
|   +-- gemini.py                # GeminiProvider (native SDK)
|   +-- openai_provider.py       # OpenAIProvider
|   +-- deepseek.py              # DeepSeekProvider
|   +-- moonshot.py              # MoonshotProvider
|   +-- bytedance.py             # ByteDanceProvider
|   +-- glm.py                   # GLMProvider
|   +-- minimax.py               # MiniMaxProvider
+-- routes/
|   +-- __init__.py              # (empty)
|   +-- chat.py                  # POST /v1/chat/completions, auth, SSE
|   +-- analytics.py             # GET /v1/models, /v1/analytics/*
+-- analytics/
|   +-- __init__.py              # Re-exports
|   +-- db.py                    # AnalyticsDB (SQLite async)
|   +-- cost.py                  # calculate_cost(), MODEL_PRICING
|   +-- routing.py               # MODEL_ROUTING, resolve_provider()
+-- tests/
|   +-- conftest.py              # Shared fixtures
|   +-- test_chat_endpoint.py
|   +-- test_analytics_endpoints.py
|   +-- test_analytics_db.py
|   +-- test_cost.py
|   +-- test_routing.py
+-- requirements.txt
+-- .env.example
+-- Makefile
+-- .gitignore
```

Rules:
- One provider per file in `providers/`
- Provider file names match class purpose (e.g., `openai_provider.py` -> `OpenAIProvider`)
- Routes split into `routes/chat.py` and `routes/analytics.py`
- Analytics logic in `analytics/` package (db, cost, routing)
- Keep `main.py` minimal: app creation, lifespan, health endpoint, router mounting

## Code Style

- Python 3.12+ features (match statements, `str | None` type unions)
- `async/await` for all I/O operations
- `from __future__ import annotations` if forward references needed
- Type hints on all function signatures
- Logging via `logging.getLogger(__name__)` pattern
- Tests under `tests/` using pytest + pytest-asyncio + httpx

## Adding a New Provider

Steps to add a new provider (e.g., "mistral"):

### 1. Create the provider file

If OpenAI-compatible, create `providers/mistral.py`:

```python
from providers.openai_compatible_base import OpenAICompatibleProvider

class MistralProvider(OpenAICompatibleProvider):
    base_url = "https://api.mistral.ai/v1"
    default_model = "mistral-large-latest"
```

If custom SDK needed, inherit from `LLMProvider` directly and implement `chat_stream()` yielding `(token_str, UsageData | None)` tuples.

### 2. Register in factory

Edit `providers/__init__.py`, add case to match statement:

```python
case "mistral":
    from providers.mistral import MistralProvider
    return MistralProvider(api_key=key, model=model)
```

### 3. Add routing entries

Edit `analytics/routing.py`, add model entries to `MODEL_ROUTING`:

```python
"mistral-large-latest": ("mistral", "mistral-large-latest"),
```

### 4. Add pricing

Edit `analytics/cost.py`, add entry to `MODEL_PRICING`:

```python
"mistral-large-latest": (2.00, 6.00),
```

### 5. Add per-provider API key (optional)

Edit `config.py`, add field to `Settings` and to `get_api_key()` provider_keys dict.

### 6. Test

```bash
make test
```

## Error Handling

- Provider errors: caught in `_tracked_stream()`, emitted as `{"error": "..."}` SSE events
- Auth errors: raised as `HTTPException(401)` via FastAPI dependency
- Unknown model: `ValueError` from `resolve_provider()` -- caught, returns 400
- Unknown provider: `ValueError` from `create_provider()` -- returns 500
- Analytics DB errors: caught and logged, never block the response stream

Pattern for provider errors in `_tracked_stream()`:
```python
except Exception as e:
    error_msg = str(e)
    yield f"data: {json.dumps({'error': error_msg})}\n\n"
finally:
    # Log to analytics regardless of success/error
    asyncio.create_task(db.log_request({...}))
```

## Testing Guidelines

- `make test` runs all tests via pytest
- `make test-unit` runs unit tests only (no FastAPI client)
- `make test-integration` runs integration tests using test client
- Tests use httpx `AsyncClient` with FastAPI's `TestClient` transport
- Auth bypassed in tests via dependency override
- Analytics DB uses in-memory SQLite for test isolation

Test structure:
```
tests/
+-- conftest.py              # Shared fixtures, mock settings, test client
+-- test_chat_endpoint.py    # Route tests (auth, chat, error cases)
+-- test_analytics_endpoints.py # Analytics endpoint tests
+-- test_analytics_db.py     # AnalyticsDB unit tests
+-- test_cost.py             # Cost calculation tests
+-- test_routing.py          # Routing resolution tests
```

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [System Architecture](./system-architecture.md)
- [Deployment Guide](./deployment-guide.md)
