# Phase 4: Docs & Testing

**Priority:** P1 | **Effort:** 1.5h | **Status:** `[x]`

## Context Links

- Phase 3 must be complete (all old providers removed)
- `docs/` directory — README, system-architecture, codebase-summary
- `tests/` directory — existing tests

## Overview

Update all documentation to reflect Manifest-only architecture. Run and fix tests. Verify end-to-end streaming works.

## Requirements

- Update README.md: provider list, config env vars, examples
- Update docs/system-architecture.md: new architecture diagram
- Update docs/codebase-summary.md: file list, provider structure
- Fix/update existing tests for new provider
- Manual e2e test: stream a chat completion through gateway

## Related Code Files

| Action | File |
|--------|------|
| Modify | `README.md` |
| Modify | `docs/system-architecture.md` |
| Modify | `docs/codebase-summary.md` |
| Modify | `tests/` (existing tests) |
| Modify | `.env.example` |

## Implementation Steps

1. Update `README.md`:
   - Provider table: single Manifest entry
   - Config table: `MANIFEST_API_KEY` only
   - Example: use `model: "auto"`
   - Remove per-provider env var docs

2. Update `docs/system-architecture.md`:
   - Architecture diagram: Client → Gateway → Manifest → 500+ models
   - Provider hierarchy: LLMProvider → OpenAICompatibleProvider → ManifestProvider
   - Remove all old provider details

3. Update `docs/codebase-summary.md`:
   - File list reflects deleted files
   - Provider structure shows single provider

4. Update `.env.example`:
   - Remove per-provider keys
   - Add `MANIFEST_API_KEY=your-manifest-key`

5. Fix tests:
   - Update any tests referencing old providers
   - Add test for ManifestProvider instantiation
   - Test passthrough routing (unknown model → manifest)

6. Manual e2e test:
```bash
# Start gateway
make dev

# Test auto-routing
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "auto", "messages": [{"role": "user", "content": "Hello"}]}'

# Test named model
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "gpt-5.4", "messages": [{"role": "user", "content": "Hello"}]}'

# Test unknown model passthrough
curl -N -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer $APP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "some-unknown-model", "messages": [{"role": "user", "content": "Hello"}]}'

# Test models endpoint
curl -H "Authorization: Bearer $APP_API_KEY" http://localhost:8000/v1/models
```

## Todo List

- [x] Update README.md
- [x] Update docs/system-architecture.md
- [x] Update docs/codebase-summary.md
- [x] Update .env.example
- [x] Fix/update existing tests
- [x] Add test for ManifestProvider
- [x] Add test for passthrough routing
- [x] Manual e2e test: auto-routing
- [x] Manual e2e test: named model
- [x] Manual e2e test: unknown model passthrough

## Success Criteria

- All docs reflect Manifest-only architecture
- All tests pass (`make test`)
- Manual e2e streaming works with model="auto"
- `/v1/models` returns curated model list
- Analytics logs token usage correctly
