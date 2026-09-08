# Z.AI GLM Coding Plan Support — Design Spec

Date: 2026-09-07
Status: Approved (analysis + provider implementation)
Decisions locked with user: Max plan tier · coding endpoint with ToS risk accepted ·
all GLM → coding, **no fallback** · credit estimation included in analytics.

---

## 1. Analysis

### 1.1 What the GLM Coding Plan (Max) provides

Source: z.ai official docs (docs.z.ai/devpack), retrieved 2026-09-07.

- **Price**: ~$80/month, billed quarterly.
- **Quota (credits)**: 28,000 per rolling 5-hour window; 140,000 per week
  (weekly anchor = subscription date). Quota exhaustion does **not** fall back
  to account balance — calls simply fail until the window resets.
- **Concurrency**: up to ~30 concurrent requests on Max.
- **Models**: exactly two — `GLM-5.3` and `GLM-5.3-Flash`. z.ai auto-maps
  5.1/5.2 → 5.3 and 4.7 → 5.3-Flash; the gateway will canonicalize itself so
  routing is explicit and observable.
- **Endpoints**:
  - OpenAI Chat Completions: `https://api.z.ai/api/coding/paas/v4` ← **we use this**
  - Anthropic Messages: `https://api.z.ai/api/anthropic` (unused — gateway speaks OpenAI wire format)
  - OpenAI Responses: `https://api.z.ai/api/v1` (unused)

### 1.2 Credit economics

Credit formula: `(input × I + cached_input × C + output × O) / 10,000`, charged at
50% outside peak hours (peak = Mon–Fri 14:00–18:00 UTC+8).

| Model | I | C | O |
|---|---|---|---|
| GLM-5.3 | 6.9 | 1.7 | 24 |
| GLM-5.3-Flash | 2.3 | 0.56 | 8 |

Typical agentic coding turn (150k input @ 95% cache hit, 3k output) on GLM-5.3:
≈ 36.6 credits → Max weekly quota ≈ **3,800 heavy turns** (≈ 15,000+ Flash turns).

Pay-as-you-go equivalent (GLM-5.3 at $1.40/$4.40, cached $0.26 per 1M): ≈ $0.061
per heavy turn → same volume ≈ **$230/week (~$930/month)** vs $80/month flat.
**Breakeven ≈ 300 heavy turns/week.** High cache-hit coding-agent traffic makes
Max a ~5–10× cost reduction; light chat traffic would favor a lower tier.

### 1.3 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| **ToS**: plan "strictly limited to officially supported tools" (Claude Code, Codex, Cline, …); a custom gateway is not on the list. Stated enforcement = endpoint/model restrictions (misuse → error 1113 / balance billing); account-level action possible. **User explicitly accepted this risk.** | Medium | Correct endpoint, only valid canonical model IDs, no non-GLM traffic sent to z.ai, hard-fail (no silent fallback) so any misuse surfaces immediately |
| Quota exhaustion mid-session → GLM unavailable up to 5h | Medium | Distinct client-visible quota error; `/v1/analytics/credits` burn tracking for visibility ahead of exhaustion |
| z.ai revises quota model/endpoint (plan has been re-launched before: prompts → credits) | Low–Medium | Endpoint + model IDs + multipliers confined to one provider module and one constants block; quotas configurable via env |
| No balance fallback (by design) — quota out = GLM down; other providers unaffected | Accepted | Explicit user decision: never silently pay Manifest for GLM |

### 1.4 Manifest context

Manifest deprecated only its **auto prompt-complexity router** on 2026-09-01; the
gateway product and pinned-model routing continue. Incidental finding: this
gateway's `"auto"` routing entry rides that deprecated feature and may behave
differently — out of scope here, flagged for a future decision. GLM models remain
reachable via Manifest pay-per-token; unsetting `ZAI_CODING_API_KEY` reverts all
GLM routing to Manifest (exact current behavior).

---

## 2. Design

### 2.1 Components

Three units, each following existing repo patterns:

1. **`providers/zai_coding.py`** — `ZAICodingProvider(OpenAICompatibleProvider)`.
   Class attrs only, mirroring `ManifestProvider`:
   `base_url = "https://api.z.ai/api/coding/paas/v4"`, `default_model = "glm-5.3"`.
   No new streaming logic; `OpenAICompatibleProvider.chat_stream` already handles
   SSE + `stream_options.include_usage`.
2. **`providers/__init__.py`** — `create_provider()` gains real dispatch:
   `provider_name == "zai-coding"` → `ZAICodingProvider`; otherwise
   `ManifestProvider` (unchanged default; unknown provider names still get
   Manifest, preserving current passthrough semantics).
3. **`analytics/routing.py`** — canonicalization + conditional routing in
   `resolve_provider()`:
   - New table entries `glm-5.3` / `glm-5.3-flash` → `("zai-coding", canonical)`.
   - All existing `glm-*` aliases remap to the canonical pair: flash-named
     variants (`glm-4.5-flash`, `glm-4.7-flash`, `glm-4.7-flashx`) →
     `glm-5.3-flash`; every other alias — including `glm-5-turbo`, which is
     not flash-named — → `glm-5.3` (never downgrade a request's quality tier:
     turbo-class traffic pays more credits but gets the stronger model).
   - Prefix rule: unknown `glm-*` models (not in table) also route to
     `zai-coding` with the name passed through (z.ai auto-maps or errors
     clearly). All other unknown models stay Manifest-passthrough (current
     behavior).
   - **Key gate**: when the effective key — `settings.get_api_key("zai-coding")`,
     i.e. `zai_coding_api_key or llm_api_key` — is empty, every GLM route —
     table entry or prefix match — resolves to `("manifest", canonical_model)`
     instead. Gating on the effective key (not the dedicated env var alone)
     keeps the `llm_api_key` fallback live and consistent with the Manifest
     pattern. Behavior with no key is identical to today's Manifest-only
     gateway; the feature is opt-in via env config; rollback = unset it.
   - Non-GLM entries are untouched.

### 2.2 Config (`config.py`, `.env.example`)

- `zai_coding_api_key: str = ""` — env `ZAI_CODING_API_KEY`.
- `zai_credits_5h: int = 28000`, `zai_credits_week: int = 140000` — Max-plan
  defaults; adjust per tier.
- `get_api_key("zai-coding")` returns `zai_coding_api_key or llm_api_key`
  (same fallback pattern as Manifest).

### 2.3 Data flow

Unchanged request shape: `resolve_provider()` → `create_provider()` →
`chat_stream()` → `_tracked_stream()` logs a row with `provider="zai-coding"`
(existing provider column; analytics already split by provider).

New: **credit estimation** in `analytics/cost.py` —

```python
def estimate_credits(provider: str, model: str, usage: UsageData,
                     ts: datetime) -> float

- Applies the multiplier table above per canonical model; 0.5× when `ts` is
  outside Mon–Fri 14:00–18:00 UTC+8; returns `0.0` for non-`zai-coding`
  providers (`calculate_cost()` unchanged, still `0.0`).
- Cached tokens read from the final usage chunk's
  `prompt_tokens_details.cached_tokens` when the field is present, else 0
  (conservative overestimate). `OpenAICompatibleProvider` passes it through on
  the existing `StreamChunk` usage path: `UsageData` (a `TypedDict`) gains
  `cached_tokens: NotRequired[int]` — TypedDict fields cannot carry defaults,
  so consumers read it with `usage.get("cached_tokens", 0)`; the construction
  site in `openai_compatible_base.py` is updated in the same change.

### 2.4 Storage

`request_logs` gains one column: `credits_used REAL NOT NULL DEFAULT 0`.
Migration is idempotent, run in `AnalyticsDB.init()`:
`ALTER TABLE request_logs ADD COLUMN credits_used REAL NOT NULL DEFAULT 0`,
swallowing the duplicate-column error (SQLite has no `IF NOT EXISTS` for
columns). Existing rows are valid (0.0 = pre-feature or non-zai requests).

New query `get_credits_summary()`: rolling 5-hour and rolling 7-day sums of
`credits_used` (both anchored to *now*), grouped per model, plus off-peak share.
Neither window can exactly match z.ai's reset behavior (5-hour credits refresh
dynamically 5 hours after consumption; weekly resets on the subscription
anniversary) — both figures are **rolling estimates**, labeled as such in the
API response.

### 2.5 API

`GET /v1/analytics/credits` — auth-required (`Depends(verify_auth)`), same
family as `/v1/analytics/{summary,models,requests}`. Response:

```json
{
  "window_5h": {"credits_used": 1234.5, "quota": 28000},
  "window_7d_rolling": {"credits_used": 45678.9, "quota": 140000, "note": "rolling estimate; z.ai weekly reset anchored to subscription date"},
  "by_model": {"glm-5.3": {"credits_used": 1200.0, "requests": 42}, "glm-5.3-flash": {"credits_used": 34.5, "requests": 9}},
  "off_peak_share": 0.62
}
```

### 2.6 Error handling

No fallback, by design. `_tracked_stream()` (and the pre-stream path) map z.ai
failures to distinguishable, non-leaking client errors:

- Quota exhaustion (HTTP 429 or z.ai error code 1113) → SSE frame
  `{"error": "zai-coding quota exhausted — resets within the 5-hour window"}`
  (or HTTP 429 before the stream opens).
- Auth failure (401/403) → `{"error": "zai-coding authentication failed"}` /
  HTTP 502 pre-stream.
- Any other failure → existing generic internal-error frame; internal exception
  text is never leaked.

### 2.7 Testing

Extends existing patterns (mocked `create_provider` via
`unittest.mock.patch`, `httpx.AsyncClient` over `ASGITransport`, `@pytest.mark.asyncio`
on async tests):

- `tests/test_routing.py` — alias canonicalization; prefix rule for unknown
  `glm-*`; key-gate degradation to Manifest; non-GLM entries and unknown-model
  passthrough unchanged.
- `tests/test_cost.py` — credit math: base, cached-token discount, off-peak
  50%, Flash multipliers, non-zai → 0.0.
- `tests/test_analytics_db.py` — column migration on fresh and pre-existing
  schema; `get_credits_summary()` window boundaries and per-model grouping.
- `tests/test_chat_endpoint.py` — zai-coding quota error → distinct SSE error
  frame; auth error mapping; pre-stream HTTP failures.
- No live z.ai calls in the suite. One manual smoke test (real key, single
  `glm-5.3` completion + one quota-state check) documented in the
  implementation plan and run at implementation time.

### 2.8 Out of scope

- Anthropic-Messages or Responses endpoints.
- Fallback routing of GLM to Manifest on any condition (explicit user decision).
- Changes to the deprecated-Manifest-`auto` entry.
- Real-time quota queries against z.ai's dashboard API (if one exists publicly);
  burn tracking is estimate-based from logged usage only.
