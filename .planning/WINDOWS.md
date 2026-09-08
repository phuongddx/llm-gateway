---
schema_version: 1
open_count: 2
waived_count: 0
fixed_count: 0
total_count: 2
last_updated: 2026-09-08T09:59:57.531Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01 | unrun-verify | static/playground/playground.js |  | Manual browser check of playground error bubble (RELI-03d) deferred to end-of-phase UAT — zero-build vanilla JS, no JS harness | open |  | 2026-09-08T04:53:49.880Z |  |
| 2 | 03 | deviation | tests/test_providers.py |  | Pre-existing, unrelated to AsyncGenerator fix: openai SDK >=2.34.0 (unpinned floor in requirements.txt) changed AsyncOpenAI credential-fallback semantics — explicit empty-string api_key no longer falls back to OPENAI_API_KEY env var (only None does). test_factory_returns_zai_coding_provider and test_factory_falls_back_to_manifest_for_other_names fail in a fresh 3.12 venv (2 failed, 115 passed) when no zai/llm key is configured. Root cause is in providers/openai_compatible_base.py __init__ passing api_key='' explicitly; fixing it is out of scope for 03-01's drift guard (one import line only). Real production routing never hits this (routing.py always passes a real configured manifest/zai-coding key), so the container itself is unaffected — confirmed compose up reaches healthy. Does not block DEPL-01/DEPL-02. | open |  | 2026-09-08T09:59:57.531Z |  |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "01",
    "file": "static/playground/playground.js",
    "line": null,
    "description": "Manual browser check of playground error bubble (RELI-03d) deferred to end-of-phase UAT — zero-build vanilla JS, no JS harness",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-08T04:53:49.880Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "deviation",
    "phase": "03",
    "file": "tests/test_providers.py",
    "line": null,
    "description": "Pre-existing, unrelated to AsyncGenerator fix: openai SDK >=2.34.0 (unpinned floor in requirements.txt) changed AsyncOpenAI credential-fallback semantics — explicit empty-string api_key no longer falls back to OPENAI_API_KEY env var (only None does). test_factory_returns_zai_coding_provider and test_factory_falls_back_to_manifest_for_other_names fail in a fresh 3.12 venv (2 failed, 115 passed) when no zai/llm key is configured. Root cause is in providers/openai_compatible_base.py __init__ passing api_key='' explicitly; fixing it is out of scope for 03-01's drift guard (one import line only). Real production routing never hits this (routing.py always passes a real configured manifest/zai-coding key), so the container itself is unaffected — confirmed compose up reaches healthy. Does not block DEPL-01/DEPL-02.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-09-08T09:59:57.531Z",
    "resolved_at": null
  }
]
````
