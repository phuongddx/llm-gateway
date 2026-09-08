---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-09-08T04:53:49.880Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 01 | unrun-verify | static/playground/playground.js |  | Manual browser check of playground error bubble (RELI-03d) deferred to end-of-phase UAT — zero-build vanilla JS, no JS harness | open |  | 2026-09-08T04:53:49.880Z |  |

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
  }
]
````
