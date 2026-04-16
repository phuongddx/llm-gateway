# Phase 5: Integration, Testing & Docs Update

## Context Links

- [Plan Overview](./plan.md)
- [Phase 1: Config & Routing](./phase-01-config-and-routing.md)
- [Phase 2: Provider Updates](./phase-02-provider-updates.md)
- [Phase 3: Analytics Engine](./phase-03-analytics-engine.md)
- [Phase 4: Analytics Endpoints](./phase-04-analytics-endpoints.md)

## Overview

- **Priority**: P2 (final validation phase)
- **Status**: `[ ]`
- **Description**: End-to-end integration testing, unit tests for routing/cost/analytics, and update project documentation to reflect new architecture.

## Key Insights

1. **Integration test first**: verify the full request flow works (model routing -> provider -> tracked stream -> DB log -> analytics query) before writing unit tests.
2. **Unit tests are scoped**: test routing logic, cost calculation, and DB queries in isolation. Do NOT mock providers for unit tests — use real provider behavior or skip.
3. **Docs update is non-trivial**: system-architecture, codebase-summary, code-standards, and README all need updates for new providers, routing, analytics.

## Requirements

### Functional

- FR-5.1: Full integration test: send chat request with specific model, verify SSE response, verify DB record created, verify analytics endpoint returns the record
- FR-5.2: Unit tests for `resolve_provider()` — valid models, unknown models, edge cases
- FR-5.3: Unit tests for `calculate_cost()` — known pricing, unknown model, zero tokens
- FR-5.4: Unit tests for `AnalyticsDB` — insert, query summary, query models, query recent
- FR-5.5: Backward compat test: request without `model` field using `LLM_PROVIDER` env var still works

### Non-Functional

- NFR-5.1: Tests runnable via `make test` (update Makefile)
- NFR-5.2: No live API calls in tests — use mock providers or pre-seeded DB data
- NFR-5.3: Test suite completes under 30 seconds

## Architecture

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures: mock settings, test DB, test client
├── test-routing.py          # resolve_provider() tests
├── test-cost.py             # calculate_cost() tests
├── test-analytics-db.py     # AnalyticsDB CRUD tests
├── test-chat-endpoint.py    # Integration: chat -> SSE -> DB record
└── test-analytics-endpoints.py  # Integration: query analytics
```

### Test Matrix

| Component | Type | What to test |
|-----------|------|-------------|
| `resolve_provider()` | Unit | All models in MODEL_ROUTING map correctly |
| `resolve_provider()` | Unit | Unknown model raises ValueError with model list |
| `resolve_provider()` | Unit | Case sensitivity |
| `calculate_cost()` | Unit | Known model + tokens = correct cost |
| `calculate_cost()` | Unit | Unknown model returns 0.0 |
| `calculate_cost()` | Unit | Zero tokens returns 0.0 |
| `AnalyticsDB.log_request()` | Unit | Insert record, verify all fields |
| `AnalyticsDB.get_summary()` | Unit | Aggregate over seeded data |
| `AnalyticsDB.get_model_stats()` | Unit | Group by model, filter by provider |
| `AnalyticsDB.get_recent()` | Unit | Pagination, `since` filter |
| `POST /v1/chat/completions` | Integration | Model routing + SSE + DB record |
| `POST /v1/chat/completions` | Integration | Backward compat (no model field) |
| `GET /v1/analytics/*` | Integration | Returns data from prior chat request |
| Auth | Integration | All endpoints reject without Bearer token |

## Related Code Files

### Create

| File | Purpose | LOC est. |
|------|---------|----------|
| `tests/conftest.py` | Fixtures: test client, mock provider, in-memory DB | ~60 |
| `tests/test-routing.py` | resolve_provider() unit tests | ~50 |
| `tests/test-cost.py` | calculate_cost() unit tests | ~40 |
| `tests/test-analytics-db.py` | AnalyticsDB CRUD tests | ~80 |
| `tests/test-chat-endpoint.py` | Chat endpoint integration tests | ~80 |
| `tests/test-analytics-endpoints.py` | Analytics endpoints integration tests | ~60 |

### Modify

| File | Change |
|------|--------|
| `Makefile` | Add `test-unit` and `test-integration` targets |
| `requirements.txt` | Add `pytest`, `pytest-asyncio`, `httpx` (for TestClient) |
| `docs/system-architecture.md` | Update architecture diagrams and data flows |
| `docs/codebase-summary.md` | Add new files, update LOC counts |
| `docs/code-standards.md` | Update provider addition guide, new file structure |
| `docs/project-roadmap.md` | Update feature status |
| `README.md` | Update API reference, supported providers, config table |

## Implementation Steps

1. **Update `requirements.txt`** — add:
   ```
   pytest>=8.0.0
   pytest-asyncio>=0.24.0
   httpx>=0.28.0
   aiosqlite>=0.20.0
   ```

2. **Create `tests/conftest.py`** (~60 LOC):
   - `@pytest.fixture` — `test_client`: FastAPI TestClient with mock provider registered
   - `@pytest.fixture` — `analytics_db`: in-memory SQLite AnalyticsDB instance (initialized)
   - `@pytest.fixture` — `mock_provider`: LLMProvider that yields predetermined tokens + usage
   - `@pytest.fixture` — `auth_headers`: `{"Authorization": "Bearer changeme"}`

3. **Create `tests/test-routing.py`** (~50 LOC):
   - Test each model in `MODEL_ROUTING` resolves to correct (provider, model) tuple
   - Test `resolve_provider("nonexistent-model")` raises `ValueError`
   - Test `resolve_provider("GPT-4O")` case sensitivity behavior

4. **Create `tests/test-cost.py`** (~40 LOC):
   - `calculate_cost("gpt-4o", 1000, 500)` == `0.0075`
   - `calculate_cost("deepseek-chat", 1000000, 1000000)` == `1.37`
   - `calculate_cost("unknown-model", 1000, 500)` == `0.0`
   - `calculate_cost("gpt-4o", 0, 0)` == `0.0`

5. **Create `tests/test-analytics-db.py`** (~80 LOC):
   - Insert a record, verify all fields readable
   - Insert 5 records across 2 models, verify summary aggregates
   - Verify `get_model_stats()` groups by model correctly
   - Verify `get_recent(limit=2, offset=0)` returns 2 records
   - Verify `get_recent(since=...)` filters by date
   - Verify error records have status="error" and error_message set

6. **Create `tests/test-chat-endpoint.py`** (~80 LOC):
   - Mock provider in test app, send chat request with model="gpt-4o"
   - Verify SSE response contains expected tokens
   - Verify DB has a logged request record for "gpt-4o"
   - Test backward compat: request without model field + `LLM_PROVIDER=gemini` setting
   - Test 401 without auth header
   - Test 400 for unknown model name

7. **Create `tests/test-analytics-endpoints.py`** (~60 LOC):
   - Seed DB with test records
   - `GET /v1/analytics/summary` returns correct totals
   - `GET /v1/analytics/models` returns per-model breakdown
   - `GET /v1/analytics/requests?limit=10` returns paginated results
   - All endpoints return 401 without auth

8. **Update `Makefile`**:
   ```makefile
   test-unit:
       python -m pytest tests/ -v -k "not integration"

   test-integration:
       python -m pytest tests/ -v -k "integration"

   test:
       python -m pytest tests/ -v
   ```

9. **Update documentation**:
   - `docs/system-architecture.md` — new routing layer, analytics data flow, provider hierarchy diagram
   - `docs/codebase-summary.md` — all new files, updated LOC counts
   - `docs/code-standards.md` — updated provider addition guide (extends OpenAICompatibleProvider), new file structure
   - `README.md` — updated API reference (model field, analytics endpoints), supported providers table, new config vars
   - `docs/project-roadmap.md` — mark features complete

## Todo Checklist

- [ ] Update `requirements.txt` with test dependencies + aiosqlite
- [ ] Create `tests/conftest.py` with shared fixtures
- [ ] Create `tests/test-routing.py`
- [ ] Create `tests/test-cost.py`
- [ ] Create `tests/test-analytics-db.py`
- [ ] Create `tests/test-chat-endpoint.py`
- [ ] Create `tests/test-analytics-endpoints.py`
- [ ] Update `Makefile` test targets
- [ ] Run full test suite, all pass
- [ ] Update `docs/system-architecture.md`
- [ ] Update `docs/codebase-summary.md`
- [ ] Update `docs/code-standards.md`
- [ ] Update `README.md`
- [ ] Update `docs/project-roadmap.md`

## Success Criteria

- [ ] All tests pass via `make test`
- [ ] Test coverage includes routing, cost, DB CRUD, chat endpoint, analytics endpoints
- [ ] Backward compatibility verified: old `LLM_PROVIDER` env var still works
- [ ] No test makes live API calls (all mocked or in-memory)
- [ ] Test suite runs under 30 seconds
- [ ] All docs updated and internally consistent
- [ ] README API reference matches actual endpoint behavior

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Mock provider doesn't match real behavior | Medium | Medium | Keep mock simple (yield fixed tokens); integration validation happens manually |
| Tests flaky due to async timing | Low | Medium | Use `pytest-asyncio` with `auto` mode; no time-dependent assertions |
| Docs drift from implementation | Medium | Low | Docs update is a checklist item; review as final step |
| Missing aiosqlite in requirements | Low | Medium | Added in step 1, verified by test runner |

## Rollback Plan

Each phase is a single commit. If Phase 5 reveals issues:
1. Fix the specific issue in the failing phase's files
2. Re-run tests
3. If unfixable: revert the failing phase commit, previous phases remain intact

Full rollback: revert all 5 commits in reverse order. SQLite DB file is disposable (auto-created on next startup).

## Unresolved Questions

1. **ZAI provider**: Base URL and models TBD. User needs to clarify. Placeholder in routing table can be added later.
2. **ByteDance auth**: May require different auth format than standard Bearer token. Needs testing with real credentials.
3. **`model` field backward compat**: Should `model` be required (breaking change) or optional with fallback? Plan assumes optional with `LLM_PROVIDER` fallback. User may prefer strict required.
4. **Analytics retention**: No data cleanup/purge strategy defined. DB will grow unbounded. Consider adding TTL or purge endpoint later.
5. **Token counting accuracy**: Approximate counting (chars/4) when provider doesn't return usage. Is this acceptable, or should we use tiktoken for accurate counting?
