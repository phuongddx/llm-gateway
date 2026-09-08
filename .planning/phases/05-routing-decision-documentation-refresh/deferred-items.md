# Deferred Items — Phase 5

Out-of-scope discoveries found during plan execution, logged per the executor's scope-boundary rule (not auto-fixed; pre-existing, unrelated to the current task's changes).

## 05-03 (docs/deployment-guide.md + docs/code-standards.md)

- **docs/deployment-guide.md:186** ("### 401 Unauthorized" section) claims "Default `APP_API_KEY` is `changeme` -- change it in production". The real `config.py` `Settings.app_api_key` default is `""` (empty string), not `"changeme"` — `tests/conftest.py`'s `client` fixture explicitly monkeypatches `settings.app_api_key` to `"changeme"` for test convenience, with a comment noting "no `.env` exists in CI -- default is `\"\"`". This line was not one of plan 05-03's six required corrections (Environment Variables Reference, Docker section, troubleshooting provider-key names) and pre-dates this plan's edits. Deferred rather than fixed under this plan's scope boundary.
