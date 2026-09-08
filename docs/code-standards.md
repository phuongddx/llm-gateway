# Code Standards

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Python files | snake_case | `providers/manifest.py`, `providers/zai_coding.py`, `analytics/routing.py` |
| Classes | PascalCase | `GeminiProvider`, `LLMProvider`, `AnalyticsDB` |
| Functions/methods | snake_case | `chat_stream()`, `create_provider()`, `resolve_provider()` |
| Constants | UPPER_SNAKE | `_ROLE_MAP`, `MODEL_ROUTING`, `GLM_CANONICAL` |
| Environment variables | UPPER_SNAKE | `MANIFEST_API_KEY`, `ZAI_CODING_API_KEY`, `ANALYTICS_DB_PATH` |
| Pydantic fields | snake_case | `openai_api_key`, `analytics_db_path` |
| Route prefixes | kebab-case | `/v1/analytics/summary` |

## File Organization

```
llm-gateway/
+-- main.py                      # FastAPI app, lifespan, CORS, health
+-- config.py                    # Settings (pydantic BaseSettings)
+-- providers/
|   +-- __init__.py              # Factory create_provider()
|   +-- base.py                  # ABC LLMProvider, UsageData/GenParams TypedDicts
|   +-- openai_compatible_base.py # Shared base for OpenAI-protocol providers
|   +-- manifest.py              # ManifestProvider (Manifest.build; 6 lines)
|   +-- zai_coding.py            # ZAICodingProvider (z.ai coding endpoint; ~10 lines)
+-- routes/
|   +-- __init__.py              # (empty)
|   +-- chat.py                  # POST /v1/chat/completions, auth, SSE
|   +-- analytics.py             # GET /v1/models, /v1/analytics/*
+-- analytics/
|   +-- __init__.py              # Re-exports
|   +-- db.py                    # AnalyticsDB (SQLite async)
|   +-- cost.py                  # calculate_cost() (stub, returns 0.0), estimate_credits() (z.ai credit estimation)
|   +-- routing.py               # MODEL_ROUTING, resolve_provider()
+-- tests/
|   +-- conftest.py              # Shared fixtures
|   +-- test_analytics_db.py
|   +-- test_analytics_endpoints.py
|   +-- test_analytics_retention.py
|   +-- test_analytics_writer.py
|   +-- test_chat_endpoint.py
|   +-- test_config.py
|   +-- test_cost.py
|   +-- test_metrics.py
|   +-- test_openai_compatible_base.py
|   +-- test_playground.py
|   +-- test_providers.py
|   +-- test_rate_limiting.py
|   +-- test_routing.py
|   +-- test_startup_validation.py
+-- requirements.txt
+-- .env.example
+-- Makefile
+-- .gitignore
```

Rules:
- Provider files in `providers/` -- currently 4 files: `base.py` (ABC), `openai_compatible_base.py` (shared impl), `manifest.py`, `zai_coding.py`
- Provider file names match class purpose (e.g., `manifest.py` -> `ManifestProvider`)
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

Edit `providers/__init__.py`, add a branch to the `if`/`else` dispatch (a plain
`if`/`elif`/`else` chain, not a `match` statement):

```python
if provider_name == "mistral":
    from providers.mistral import MistralProvider
    return MistralProvider(api_key=key, model=model)
```

### 3. Add routing entries

Edit `analytics/routing.py`, add model entries to `MODEL_ROUTING`:

```python
"mistral-large-latest": ("mistral", "mistral-large-latest"),
```

### 4. Add per-provider API key (optional)

Edit `config.py`, add field to `Settings` and to `get_api_key()` provider_keys dict.

### 5. Test

```bash
make test
```

## Error Handling

- Provider errors: caught in `_tracked_stream()`, emitted as a nested OpenAI-style
  `{"error": {"message": "...", "type": "..."[, "code": "..."]}}` SSE event
- Auth errors: raised as `HTTPException(401)` via FastAPI dependency
- Unknown model: `resolve_provider()` never raises -- unknown non-GLM models passthrough
  to Manifest as-is; unknown `glm-*` models passthrough to `zai-coding` under the key
  gate (no 400 for this case)
- Unknown provider: `create_provider()` never raises either -- its `if`/`else` dispatch
  always returns a provider (no 500 for this case)
- Analytics DB errors: caught and logged, never block the response stream

Pattern for provider errors in `_tracked_stream()`:
```python
except Exception as e:
    error_msg = str(e)
    error_obj = {"message": client_msg, "type": err_type}
    if err_code is not None:
        error_obj["code"] = err_code
    yield f"data: {json.dumps({'error': error_obj})}\n\n"
finally:
    # Enqueue to the bounded analytics write queue (non-blocking)
    if analytics_writer:
        analytics_writer.enqueue({...})
```

## Testing Guidelines

- `make test` runs all tests via pytest
- `make test-unit` runs unit tests only (no FastAPI client)
- `make test-integration` runs integration tests using test client
- Tests use httpx `AsyncClient` over `ASGITransport` (not FastAPI's sync `TestClient`)
- Auth uses a real matching Bearer token via the `auth_headers()` fixture (`{"Authorization": "Bearer changeme"}`, matching `settings.app_api_key`) -- no `app.dependency_overrides` usage
- Analytics DB uses in-memory SQLite for test isolation

Test structure:
```
tests/
|   +-- conftest.py              # Shared fixtures
|   +-- test_analytics_db.py
|   +-- test_analytics_endpoints.py
|   +-- test_analytics_retention.py
|   +-- test_analytics_writer.py
|   +-- test_chat_endpoint.py
|   +-- test_config.py
|   +-- test_cost.py
|   +-- test_metrics.py
|   +-- test_openai_compatible_base.py
|   +-- test_playground.py
|   +-- test_providers.py
|   +-- test_rate_limiting.py
|   +-- test_routing.py
|   +-- test_startup_validation.py
```

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [System Architecture](./system-architecture.md)
- [Deployment Guide](./deployment-guide.md)
