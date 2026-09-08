# Phase 3: Containerized Deployment & CI - Context

**Gathered:** 2026-09-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Single-container Docker deployment (the PROJECT.md target runtime) + GitHub Actions CI. Delivers DEPL-01, DEPL-02, DEPL-03. Local Makefile dev flow stays untouched. No observability (Phase 4), no docs-refresh beyond the deployment quickstart (Phase 5).

</domain>

<decisions>
## Implementation Decisions

### Container + Compose
- `Dockerfile`: python:3.12-slim multi-stage — builder stage installs requirements into a venv, runtime stage copies venv + app; non-root user; HEALTHCHECK hitting `/health`
- `.dockerignore`: .venv, .git, data/, .planning/, plans/, docs/, __pycache__, repomix artifacts, server.log
- `docker-compose.yml`: ONE service, `env_file: .env`, port 8000, named volume for `data/` (analytics.db survives recreates), `restart: unless-stopped`. No profiles, no override files (YAGNI)

### GitHub Actions CI
- `.github/workflows/ci.yml` on push + PR to main
- Matrix Python [3.12, 3.14]: pip install -r requirements.txt → pytest -q
- One `docker build` smoke job (no push, no registry credentials)

### Local Workflow + Docs
- Makefile keeps dev flow untouched; ADD `docker-build`, `docker-up`, `docker-down` targets
- README gains a short deployment quickstart (compose up + env pointer); nothing else

### Claude's Discretion
None — all areas resolved.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `requirements.txt` (unpinned `>=` deps — container build pins implicitly by build time)
- `Makefile` target conventions; `/health` endpoint (no auth) as container healthcheck target
- `main.py` lifespan (DB init incl. Phase-2 auto_vacuum + startup purge; writer lifecycle) — container start runs it; shutdown drains (SIGTERM → uvicorn lifespan shutdown)
- `.env.example` as the documented env surface (APP_API_KEY required)

### Established Patterns
- data/ created at startup by lifespan; SQLite WAL — named volume keeps it across recreates
- Tests: 117 passed; CI just runs them

### Integration Points
- New files: Dockerfile, .dockerignore, docker-compose.yml, .github/workflows/ci.yml
- Modified: Makefile (3 targets), README.md (deployment quickstart section)

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

### Post-Research Decisions (user, 2026-09-08)
- CI adds a tiny ruff lint job (ruff stays OUT of requirements.txt — CI-only dep) and the 4 existing findings are fixed (F821 AsyncGenerator import in providers/openai_compatible_base.py — a real Python-3.12 crasher — plus 3 dead symbols). Satisfies DEPL-03 "lint + tests".
- DEPL-02 runtime acceptance is proven LOCALLY: operator starts Rancher Desktop; acceptance runs compose up + /health + volume persistence live.
