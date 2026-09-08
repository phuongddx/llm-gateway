---
phase: 01-gateway-runtime-hardening
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - analytics/writer.py
  - config.py
  - .env.example
  - main.py
  - AGENTS.md
  - routes/chat.py
  - tests/conftest.py
  - tests/test_analytics_writer.py
  - tests/test_chat_endpoint.py
  - static/playground/playground.js
autonomous: true
requirements:
  - RELI-02
  - RELI-03
estimate:
  tokens: 32000
  raw_tokens: 32000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - 'TR1 (RELI-03): A chat request whose provider raises mid-stream returns HTTP 200 with the already-streamed token frames, then exactly one SSE error frame whose parsed JSON is an OpenAI-style nested object {"error": {"message", "type", optional "code"}} per the locked mapping — zai 429 or "1113" in error text: message "zai-coding quota exhausted — resets within the 5-hour window", type "rate_limit_error", code "zai_quota_exhausted"; zai 401/403: message "zai-coding authentication failed", type "authentication_error", code "zai_auth_failed"; anything else: message "Internal error processing request", type "server_error", NO code key — terminated by the "data: [DONE]" frame (message strings byte-identical to current, ZAI-3 preserved).'
    - 'TR2 (RELI-03, ZAI-3): A z.ai quota event (HTTP 429 or error code 1113) surfaces to the client within the single request round-trip — the dedicated quota message is delivered in the same SSE response; no retry loop, no Manifest reroute.'
    - 'TR3 (RELI-02): Exactly one request_logs row is written per completed stream, flowing through AnalyticsWriter.enqueue (non-blocking put_nowait) to the single consumer task calling AnalyticsDB.log_request; the record dict keeps exactly the 12 existing keys (id, provider, model, prompt_tokens, completion_tokens, total_tokens, latency_ms, ttft_ms, cost_usd, credits_used, status, error_message) — unchanged shape.'
    - 'TR4 (RELI-03): Internal exception text never reaches clients — tests assert the triggering exception message is absent from response.text; it still goes to logs and the DB error_message column.'
    - 'TR5 (RELI-02): lifespan creates AnalyticsWriter after db.initialize(), sets app.state.analytics_writer (app.state.analytics_db unchanged), and on shutdown awaits writer.stop() (bounded 5s drain, drop-total logged) strictly BEFORE db.close().'
    - 'TR6 (RELI-03d): Both playground SSE parse sites read parsed.error?.message — the UI error bubble shows the human message, never "[object Object]".'
    - 'TR7 (config): Settings gains analytics_queue_size: int = 1000 and .env.example documents ANALYTICS_QUEUE_SIZE=1000 (mirror contract per AGENTS.md).'
    - 'TR8 (edge RELI-03/empty, explicit): A provider exception whose str(e) is empty still yields the generic frame with message exactly "Internal error processing request" and type "server_error" — client messages are never derived from exception text.'
    - 'TR9 (edge RELI-03/encoding, explicit): Frame equality is defined at the parsed-JSON level (Unicode code points): the U+2014 em dash in the quota message survives the json.dumps/json.loads round-trip unchanged and tests assert full-object equality on parsed frames, never raw-wire substring equality of the full message.'
    - 'TR10 (locked): Gateway auth failures stay plain 401 JSON {"detail": "Invalid API key"} — verify_auth is untouched and never emits SSE error frames.'
    - 'TR11 (edge RELI-02/empty, explicit): stop() on an idle or never-started writer returns immediately without error; a single enqueued record produces exactly one row.'
  artifacts:
    - analytics/writer.py
    - tests/test_analytics_writer.py
    - config.py
    - main.py
    - routes/chat.py
    - tests/conftest.py
    - tests/test_chat_endpoint.py
    - .env.example
    - static/playground/playground.js
  key_links:
    - 'main.py lifespan → AnalyticsWriter(db, queue_size=settings.analytics_queue_size).start() after AnalyticsDB.initialize(); shutdown order writer.stop() THEN db.close() (reversed order silently drops the drained tail — AnalyticsDB.log_request no-ops on a closed connection)'
    - 'routes/chat.py _tracked_stream finally-block → analytics_writer.enqueue(record) exactly once per generator (including client-disconnect GeneratorExit); replaces asyncio.create_task + add_done_callback'
    - 'SSE error yield site in _tracked_stream → nested {"error": {message, type[, code]}} object; static/playground/playground.js both parse sites → parsed.error?.message'
    - 'tests/conftest.py client fixture → analytics_writer fixture (httpx.ASGITransport never runs the ASGI lifespan — the writer must be manually started and injected)'
  prohibitions:
    - requirement_id: RELI-03
      category: privacy
      status: resolved
      verification: test
      resolution: null
      reason: null
      statement: 'MUST NOT embed user request content (submitted messages, system prompts, model input text) in SSE error frames or any client-facing payload — frames carry only the curated message/type/code objects; tests assert exact parsed-object equality so no echo of prompt text can ride along.'
    - requirement_id: RELI-02
      category: privacy
      status: resolved
      verification: test
      resolution: null
      reason: null
      statement: 'MUST NOT persist or queue request CONTENT (prompt/completion/message text) anywhere in the analytics path — records carry counts, timing, status, credits only; the record dict keeps exactly the 12 existing keys and gains no messages/content field (specless-probe kept prohibition, descriptor-less / flagged-unverified).'
---

<objective>
Tracer slice for Phase 1: ONE end-to-end path — a streaming chat request that errors mid-stream — wired through every layer this phase modifies: the new bounded AnalyticsWriter (analytics/writer.py), the config knob (config.py + .env.example), lifespan wiring (main.py), the queue producer swap and OpenAI-style SSE error frame (routes/chat.py), the test-lifespan bridge (tests/conftest.py), its end-to-end proof (tests/test_analytics_writer.py), and the client renderer (static/playground/playground.js).

Implements locked CONTEXT decisions "Bounded Analytics Write Path" and "OpenAI-Style SSE Error Frames" (01-CONTEXT.md `<decisions>`) — the decisions are LOCKED; this plan implements them exactly, it does not redesign them.

Purpose: Prove the phase's two riskiest seams (queue/lifecycle ordering; frame change + client compatibility) on the earliest commit instead of after ten committed layers. All mechanics are probe-verified in 01-RESEARCH.md (Patterns 1/3/4/5) — this plan is assembly, not invention. Zero new dependencies (REQ-NFR-02).

Output: working bounded write path + nested error frames, proven by a new end-to-end test, with the existing suite green.
</objective>

<execution_context>
@~/.claude/gsd-core/workflows/execute-plan.md
@~/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@AGENTS.md
@.planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md
@.planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md
@.planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end error-path tracer — bounded writer + nested SSE error frame (one path only)</name>
  <files>analytics/writer.py, config.py, .env.example, main.py, routes/chat.py, tests/conftest.py, tests/test_analytics_writer.py, AGENTS.md</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-CONTEXT.md — locked decisions "Bounded Analytics Write Path" and "OpenAI-Style SSE Error Frames"
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "Pattern 1: AnalyticsWriter", "Pattern 3: SSE error frame mapping", "Pattern 5: Lifespan wiring and ordering", "Anti-Patterns to Avoid", "Pitfalls 1/4/5/6/9"
  - .planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md — sections "analytics/writer.py", "routes/chat.py", "tests/conftest.py", ".env.example", "Shared Patterns"
  - routes/chat.py (current _tracked_stream finally-block, lines 101-135; error mapping lines 89-99; route fetch line 50)
  - main.py (lifespan lines 19-35)
  - config.py (Analytics block lines 27-30)
  - tests/conftest.py (analytics_db + client fixtures, lines 49-68)
  - tests/test_chat_endpoint.py (lines 86-114: ZaiQuotaError + quota-frame test conventions)
  - AGENTS.md — Architecture & Data Flow step 6, Code Conventions (Async bullet), Testing & QA fixtures list (binding; action step 8 updates these three analytics-path references to the bounded-queue + single-writer pattern)
  </read_first>
  <behavior>
  - Test (write FIRST, must fail before implementation): test_error_stream_delivers_nested_frame_and_logs_row in tests/test_analytics_writer.py — inline QuotaProvider (class raising an exception with status_code = 429 after yielding one token, signature chat_stream(self, messages, system_prompt, params=None)), patch routes.chat.create_provider + routes.chat.resolve_provider to ("zai-coding", "glm-5.3") per tests/test_chat_endpoint.py:102-114 conventions; POST /v1/chat/completions via client fixture; assert 200; parse every "data: " frame (skip [DONE]); assert a token frame exists; assert the error frame parses to exactly {"message": "zai-coding quota exhausted — resets within the 5-hour window", "type": "rate_limit_error", "code": "zai_quota_exhausted"}; assert the body ends with the [DONE] frame; then await analytics_writer.wait_drained(5.0) and assert (await analytics_db.get_recent(limit=10))["total"] == 1 with status "error" (test takes client, auth_headers, analytics_writer, analytics_db fixtures; carries @pytest.mark.asyncio).
  </behavior>
  <action>
  RED: write the behavior test first; run it; it must fail (today the frame is flat and no writer exists). Then GREEN, implementing per the probe-verified patterns:

  1. Create analytics/writer.py — module one-line docstring (e.g. "Serial analytics writer — bounds fire-and-forget DB writes."), imports asyncio + logging only, per-module logger. Class AnalyticsWriter (PascalCase, PEP 604 hints): __init__(self, db, queue_size: int = 1000) storing self._db, self._queue = asyncio.Queue(maxsize=queue_size), self._task: asyncio.Task | None = None, public counter self.dropped: int = 0, and a module constant _DRAIN_TIMEOUT_S = 5.0. Methods per 01-RESEARCH.md "Pattern 1" verbatim mechanics: start() creates the consumer task named "analytics-writer"; enqueue(record: dict) -> None calls self._queue.put_nowait(record), on asyncio.QueueFull increments self.dropped and logs logger.warning("Analytics queue full — %d records dropped so far", self.dropped) exactly when self.dropped % 50 == 0 (drop-NEWEST: the incoming record is dropped, queued records are never evicted); private async _run() loops record = await self._queue.get(), try: await self._db.log_request(record) except Exception: logger.exception(...) finally: self._queue.task_done() (task_done in finally prevents join() deadlock — Pitfall 5); qsize() -> int returns self._queue.qsize(); async wait_drained(timeout: float = 5.0) -> None wraps asyncio.wait_for(self._queue.join(), timeout) (public helper so tests never reach into _queue); async stop(timeout: float = _DRAIN_TIMEOUT_S) -> None returns immediately if never started, otherwise await asyncio.wait_for(self._queue.join(), timeout), on asyncio.TimeoutError logger.warning naming the timeout and self._queue.qsize() residue, then cancel the task, await it suppressing asyncio.CancelledError, and logger.info the drop total (self.dropped + self._queue.qsize()). NEVER use asyncio.Queue.shutdown() (Python 3.13-only; repo floor is 3.12) and NEVER await queue.put() from producer paths (would block token streaming — REQ-NFR-05).
  2. config.py — add analytics_queue_size: int = 1000 in the Analytics block with comment "# Bounded analytics write queue (drop-newest when full)". Do NOT add validate_assignment to model_config (tests monkeypatch the singleton). No validator in this task (that is Plan 02).
  3. .env.example — append after the ANALYTICS_DB_PATH block, same comment+KEY=value shape: "# Analytics write queue size (drops newest + logs when full)" then "ANALYTICS_QUEUE_SIZE=1000" (mirrors the Settings field per AGENTS.md).
  4. main.py — extend the existing lifespan (do not redesign). Import os (stdlib group) and from analytics.writer import AnalyticsWriter beside the analytics.db import. After await db.initialize(): writer = AnalyticsWriter(db, queue_size=settings.analytics_queue_size); writer.start(); app.state.analytics_writer = writer (keep app.state.analytics_db = db unchanged — read endpoints use it directly). Shutdown ordering IS the contract: await writer.stop() THEN await db.close() (reversed order silently drops the drained tail because AnalyticsDB.log_request no-ops on a closed connection — Pitfall 4).
  5. routes/chat.py — two surgical edits, clean cutover. (a) Producer swap: in chat(), replace the analytics_db getattr fetch with analytics_writer = getattr(request.app.state, "analytics_writer", None); change _tracked_stream's parameter analytics_db to analytics_writer; in the finally-block replace the asyncio.create_task(...) + add_done_callback(...) try/except block with a single guarded call: if analytics_writer: analytics_writer.enqueue({ ...the identical 12-key record dict currently at lines 118-129... }) — keep the finally placement EXACTLY (the finally runs exactly once per generator, including client-disconnect GeneratorExit — Pitfall 9; moving it would double-enqueue or lose rows); enqueue must not be wrapped in code that can raise into the generator. Delete the now-dead module-level done-callback helper function (its docstring says it handles fire-and-forget analytics log tasks) and its call site; remove the asyncio import if nothing else in the module uses it. (b) Error frame: inside the except block keep the classification conditions and message strings byte-identical (em dash U+2014 intact); derive err_type/err_code alongside client_msg — zai 429 or "1113" in error text: ("rate_limit_error", "zai_quota_exhausted"); zai 401/403: ("authentication_error", "zai_auth_failed"); else ("server_error", None); build error_obj = {"message": client_msg, "type": err_type} and add "code" only when err_code is not None; yield the frame as data: {json.dumps({'error': error_obj})} followed by two newlines. The data: [DONE] terminator after the error frame stays; verify_auth stays untouched (401 stays plain JSON).
  6. tests/conftest.py — add an analytics_writer fixture in the exact style of analytics_db (per 01-PATTERNS.md snippet): @pytest_asyncio.fixture async def analytics_writer(analytics_db): construct AnalyticsWriter(analytics_db, queue_size=1000), writer.start(), set app.state.analytics_writer = writer (import main.app and AnalyticsWriter following the file's lazy-import style), yield writer, then await writer.stop(). Change client to depend on (analytics_db, analytics_writer) and keep both app.state injections — httpx.ASGITransport never runs the lifespan (Pitfall 1), so without manual injection every HTTP test would silently lose rows.
  7. tests/test_analytics_writer.py — new file, one-line module docstring "Unit tests for analytics.writer — bounded queue, drop-newest, drain/stop.", the behavior test above (define the 429-status exception class inline like tests/test_chat_endpoint.py:86-87), @pytest.mark.asyncio on the async test, unittest.mock.patch for providers. Further queue/burst tests come in Plan 03 — this task ships ONLY the one end-to-end test.
  8. AGENTS.md — keep project instructions true after the cutover: the route pattern this task deletes is documented in three places there. Three surgical prose edits, nothing else: (a) Architecture & Data Flow step 6 — replace the two sentences describing the per-stream fire-and-forget log task (held reference + done-callback) with: the row is enqueued via analytics_writer.enqueue(record) — non-blocking on the bounded queue sized by ANALYTICS_QUEUE_SIZE, drop-newest when full — and drained by the single lifespan-owned consumer task that serially calls AnalyticsDB.log_request; failures are logged by the writer, never silently lost. (b) Code Conventions, Async bullet — replace the per-write background-task + held-reference + done-callback prescription with: analytics writes go through the lifespan-owned bounded AnalyticsWriter queue (producers enqueue non-blocking; one consumer task serially drains, its task reference held on app.state.analytics_writer) — never a per-request background task per stream; keep the bullet's closing "never a bare unawaited coroutine" rule. (c) Testing & QA, fixtures list — add an analytics_writer(analytics_db) entry (constructs + starts a real AnalyticsWriter over the in-memory DB, injects app.state.analytics_writer, stops it on teardown) beside analytics_db, and change client(analytics_db) to client(analytics_db, analytics_writer), injecting both app.state handles (ASGITransport never runs the lifespan). Same commit as the code cutover.

  Commit after green per AGENTS.md conventions (tracer commit: feat(01-01)).
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/ -v</automated>
    <fails_when>non-zero exit code, or any test reports FAIL/ERROR in the summary — in particular tests/test_analytics_writer.py::test_error_stream_delivers_nested_frame_and_logs_row must pass (asserting the nested error object, the [DONE] terminator, and exactly one request_logs row with status "error" after wait_drained)</fails_when>
  </verify>
  <acceptance_criteria>
  - tests/test_analytics_writer.py exists and tests/test_analytics_writer.py::test_error_stream_delivers_nested_frame_and_logs_row passes; the test asserts the parsed error object equals exactly {"message": "zai-coding quota exhausted — resets within the 5-hour window", "type": "rate_limit_error", "code": "zai_quota_exhausted"}.
  - analytics/writer.py defines class AnalyticsWriter with public members: __init__(db, queue_size: int = 1000), enqueue(record: dict) -> None, qsize() -> int, wait_drained(timeout: float = 5.0), start() -> None, stop(timeout: float = 5.0), dropped: int (source assertion: python -c "from analytics.writer import AnalyticsWriter; assert all(hasattr(AnalyticsWriter, m) for m in ['enqueue','qsize','start','stop','wait_drained'])").
  - grep -c "put_nowait" analytics/writer.py returns >= 1 and grep -c "task_done" analytics/writer.py returns >= 1; the words Queue.shutdown do not appear in analytics/writer.py.
  - grep -c "analytics_queue_size" config.py returns 1 and grep -c "ANALYTICS_QUEUE_SIZE" .env.example returns 1.
  - grep -c "AnalyticsWriter" main.py returns >= 2 (import line from analytics.writer + construction after db.initialize()) and grep -c "app.state.analytics_writer" main.py returns 1; the shutdown block calls writer stop before db close (source order assertion: the stop call line number is less than the db close call line number in main.py).
  - routes/chat.py: .venv/bin/python -c "import ast, sys; tree = ast.parse(open('routes/chat.py').read()); names = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]; assert '_on_log_task_done' not in names, names" passes (dead callback deleted); grep -c "add_done_callback" routes/chat.py returns 0; grep -c "create_task" routes/chat.py returns 0; grep -c "analytics_writer.enqueue" routes/chat.py returns 1.
  - routes/chat.py error yield produces a nested object: grep -c "json.dumps({'error': error_obj})" routes/chat.py returns 1, and the em-dash quota message string is byte-identical to the current one (grep -F "zai-coding quota exhausted — resets within the 5-hour window" routes/chat.py matches exactly 1 line).
  - tests/conftest.py: grep -c "analytics_writer" tests/conftest.py returns >= 3 (fixture + client dependency + app.state injection) and the client fixture signature includes analytics_writer.
  - AGENTS.md instructions stay true post-cutover: grep -c "add_done_callback" AGENTS.md returns 0 (stale fire-and-forget pattern removed from step 6 and the Async bullet) and grep -c "analytics_writer" AGENTS.md returns >= 3 (Architecture step 6 enqueue + analytics_writer fixture entry + client(analytics_db, analytics_writer) fixture).
  - Full suite (.venv/bin/python -m pytest tests/ -v) exits 0 — existing substring assertions in tests/test_chat_endpoint.py (lines 113, 129, 147, 164) keep passing unchanged (message strings preserved).
  </acceptance_criteria>
  <done>One mid-stream provider failure delivers: token frames, one nested OpenAI-style SSE error object with the locked message/type/code mapping, the [DONE] terminator, and exactly one request_logs row via the bounded AnalyticsWriter — full suite green, tracer committed.</done>
  <reversibility rating="reversible">Pure code addition/edit plus one helper deletion — single git revert restores the create_task path; no data or schema changes.</reversibility>
</task>

<task type="auto">
  <name>Task 2: Playground renders error.message at both SSE parse sites (RELI-03d)</name>
  <files>static/playground/playground.js</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "Pattern 4: Playground renderer fix (both parse sites)" + Pitfall 8
  - .planning/phases/01-gateway-runtime-hardening/01-PATTERNS.md — section "static/playground/playground.js" (verbatim current lines 126-131 and 144-148)
  - static/playground/playground.js lines 120-150 (both parse sites) and 250-290 (sendMessage catch — unchanged, read to confirm the rendering path)
  </read_first>
  <action>
  Change BOTH SSE parse sites identically — the main read loop (around line 128) and the tail-buffer handler for [DONE] frames split across chunks (around line 145). At each site the throw of the freshly parsed error value must instead throw a new Error reading the nested message field with a fallback: use optional chaining on the parsed error object and fall back to the literal string 'Unknown gateway error' when the field is absent. Do not touch the surrounding rethrow guard that skips JSON parse errors (its message-includes check still works — human messages do not contain "JSON"), and do not touch the downstream catch in sendMessage that renders err.message into the chat bubble. This file is currently UNTRACKED (not gitignored) — explicitly git add static/playground/playground.js in this task's commit so it lands in the phase history. No JS test harness exists by locked project decision (zero-build vanilla JS); automated proof is the source assertion below, and the browser check is documented in the plan verification section.
  </action>
  <verify>
    <automated>.venv/bin/python -c "import re; src = open('static/playground/playground.js').read(); assert src.count('parsed.error?.message') == 2, src.count('parsed.error?.message'); assert len(re.findall(r'throw new Error\(parsed\.error\)', src)) == 0, 'bare-object throw still present'"</automated>
    <fails_when>AssertionError — the optional-chained message read does not appear exactly twice, or any bare throw of the raw parsed error object remains</fails_when>
  </verify>
  <acceptance_criteria>
  - static/playground/playground.js contains the optional-chained error-message read at exactly 2 sites (main loop + tail-buffer handler) per the verify command.
  - No line in static/playground/playground.js throws the raw parsed error object any more (regex throw new Error(parsed.error) matches 0 lines).
  - The fallback literal 'Unknown gateway error' is present exactly 2 times.
  - git status after commit shows static/playground/playground.js tracked (git ls-files -- static/playground/playground.js prints the path).
  </acceptance_criteria>
  <done>Both playground SSE parse sites unwrap the nested error object; an SSE error frame renders its human message in the chat bubble instead of [object Object]; the file is git-tracked.</done>
  <reversibility rating="reversible">Two one-line JS edits, trivially revertible.</reversibility>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Full frame-shape test coverage for all four error variants (RELI-03a/b/c)</name>
  <files>tests/test_chat_endpoint.py</files>
  <read_first>
  - .planning/phases/01-gateway-runtime-hardening/01-RESEARCH.md — "RELI-03 frame assertion upgrade" code example + Pattern 3 mapping table
  - tests/test_chat_endpoint.py lines 86-189 (the four error tests + the credits test with its timing-based wait at line 186)
  - AGENTS.md — Testing & QA conventions
  </read_first>
  <behavior>
  - test_zai_coding_quota_error_frame: additionally parse all "data: " frames (skipping [DONE]) and assert the error frame equals exactly {"message": "zai-coding quota exhausted — resets within the 5-hour window", "type": "rate_limit_error", "code": "zai_quota_exhausted"}; assert the response text ends with the [DONE] frame.
  - test_zai_coding_1113_code_maps_to_quota: same exact-object assertion (the 1113 path must produce the identical quota object).
  - test_zai_coding_auth_error_frame: assert the error frame equals exactly {"message": "zai-coding authentication failed", "type": "authentication_error", "code": "zai_auth_failed"}.
  - test_generic_provider_error_unaffected: assert the error frame equals exactly {"message": "Internal error processing request", "type": "server_error"} with NO "code" key; assert the string "Provider failed" (the triggering exception text) does not appear in response.text; assert [DONE] still terminates the body.
  - New test for the empty-message exception: a provider raising an exception whose str() is empty yields the same generic object (message never derived from exception text).
  - test_zai_coding_request_logs_credits: replace the timing-based wait with an explicit drain via the analytics_writer fixture (test gains the fixture param) before asserting DB rows.
  </behavior>
  <action>
  Write the behavior assertions first (they must pass against Task 1's implementation — if any fails, the implementation is wrong, not the test). Add a small module-local helper that splits response text into parsed SSE frames: take lines starting with the data-prefix, strip the prefix, skip the done-sentinel, json.loads the rest — then reuse it across the four extended tests instead of copy-pasting parsing. Extend each of the four existing error tests with the exact parsed-object equality from the behavior block (substring assertions stay — they document the human-readable contract). Add the empty-message-exception test using the same inline-fake-provider + patch conventions (raise an exception constructed with no message text). In test_zai_coding_request_logs_credits, take the analytics_writer fixture and replace the fixed 0.1-second sleep (line 186) with awaiting its public drain helper (timeout 5.0) so row visibility is deterministic rather than timing-based. Keep @pytest.mark.asyncio on every async test; no monkeypatch for providers; no app.dependency_overrides.
  </action>
  <verify>
    <automated>.venv/bin/python -m pytest tests/test_chat_endpoint.py -v</automated>
    <fails_when>non-zero exit code, or any test reports FAIL in the summary — in particular the exact-object assertions for quota (429 AND 1113), auth, generic (no code key, exception text absent), and the empty-message-exception test</fails_when>
  </verify>
  <acceptance_criteria>
  - All four error tests assert full parsed-object equality (not only substrings); the generic variant asserts "code" is not a key of the error object.
  - The generic and empty-message tests assert the triggering exception text is absent from response.text.
  - grep -c "asyncio.sleep(0.1)" tests/test_chat_endpoint.py returns 0 (timing wait replaced by explicit drain).
  - grep -c "wait_drained" tests/test_chat_endpoint.py returns >= 1.
  - tests/test_chat_endpoint.py -v run exits 0 with zero failures.
  </acceptance_criteria>
  <done>Quota (429 + 1113), auth, generic, and empty-message exception paths all assert the exact nested OpenAI error object; internal exception text proven absent; DB-row waits are deterministic.</done>
  <reversibility rating="reversible">Test-only edits; revertible in isolation.</reversibility>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| provider→gateway stream | upstream provider exceptions cross into _tracked_stream (untrusted text in str(e)) |
| gateway→client SSE | error frames cross to the browser/client (only curated content may cross) |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-01-01 | Information Disclosure | SSE error yield site in routes/chat.py | high | mitigate | Curated message/type/code table only; tests assert triggering exception text absent from response.text (Task 3); internal text goes to logs + DB error_message column only |
| T-01-02 | DoS | analytics write path under provider lag / SQLite slowdown | high | mitigate | Bounded asyncio.Queue (ANALYTICS_QUEUE_SIZE, default 1000) + drop-newest + counted drops; producers never block (put_nowait); proof tests in 01-PLAN-03 |
| T-01-03 | Tampering | client-disconnect (GeneratorExit) vs analytics accounting | low | mitigate | Enqueue stays in the generator finally-block — runs exactly once per stream; disconnect covered by 01-PLAN-03 Task 2 |

No package installs this phase (REQ-NFR-02 holds; `limits` is an existing transitive dependency of slowapi, used read-only) — no supply-chain row required.
</threat_model>

<verification>
- Full suite green: .venv/bin/python -m pytest tests/ -v (exit 0; any FAIL blocks the plan).
- Tracer proof: tests/test_analytics_writer.py::test_error_stream_delivers_nested_frame_and_logs_row passes (nested frame + [DONE] + exactly one row after drain).
- Manual-only (RELI-03d, justified: zero-build vanilla-JS playground — locked PROJECT.md decision, no JS harness): run make dev, open http://localhost:8000/playground, send a request against a failing/fake provider, confirm the error bubble shows the human message (e.g. the quota string), not "[object Object]". Server-side frame shape is fully automated; only the visual bubble is manual.
- Config mirror: ANALYTICS_QUEUE_SIZE present in .env.example and analytics_queue_size in config.py.
</verification>

<success_criteria>
- A mid-stream provider failure produces the locked nested OpenAI error object (all three mappings), terminated by [DONE], with no internal exception text client-side.
- The same request's record reaches request_logs exactly once through the bounded writer; lifespan starts/stops the writer in the correct order.
- Playground unwraps error.message at both parse sites; the file is git-tracked.
- Full existing suite plus the new tests pass; zero new dependencies.
</success_criteria>

## Artifacts this phase produces

Full phase inventory (updated by 01-PLAN-02 and 01-PLAN-03; union is authoritative):

- NEW analytics/writer.py — class AnalyticsWriter: __init__(db, queue_size: int = 1000), enqueue(record: dict) -> None, qsize() -> int, async wait_drained(timeout: float = 5.0), start() -> None, async stop(timeout: float = 5.0), private async _run(); public attribute dropped: int; module constant _DRAIN_TIMEOUT_S = 5.0.
- config.py — new Settings field analytics_queue_size: int = 1000 (Plan 02 adds @model_validator _validate_rate_limit).
- main.py — lifespan gains: writer construction/start, app.state.analytics_writer, ordered shutdown writer.stop() → db.close(); (Plan 02 adds writable-check + key notices + os import).
- routes/chat.py — _tracked_stream parameter analytics_db replaced by analytics_writer; finally-block producer enqueue; nested error-object yield; deleted: the fire-and-forget done-callback helper and the create_task block.
- ENV VAR: ANALYTICS_QUEUE_SIZE (default 1000, documented in .env.example).
- static/playground/playground.js — both parse sites read parsed.error?.message with 'Unknown gateway error' fallback.
- tests/conftest.py — new analytics_writer fixture; client now depends on it.
- NEW tests/test_analytics_writer.py (this plan: end-to-end tracer test; Plan 03 extends with queue-unit + burst tests).
- tests/test_chat_endpoint.py — four error tests extended with exact frame-object assertions; deterministic drain replaces the 0.1s sleep.
- NEW tests/test_startup_validation.py (Plan 02).

<output>
Create `.planning/phases/01-gateway-runtime-hardening/01-PLAN-01-SUMMARY.md` when done.
</output>
