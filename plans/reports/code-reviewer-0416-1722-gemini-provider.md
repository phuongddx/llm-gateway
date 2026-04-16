# Code Review: providers/gemini.py (typed SDK migration)

## Scope
- Files: providers/gemini.py, providers/base.py, main.py, config.py
- LOC: ~50 (gemini.py)
- Focus: google-genai typed SDK correctness, async streaming, error handling, security

## Overall Assessment
Clean, focused refactor. SDK usage is correct. No blocking issues. Minor items below.

## Critical Issues
None.

## High Priority
1. **`msg["content"]` can raise KeyError** (line 48) -- if caller passes a message without `content` key, unhandled KeyError propagates as generic 500. Use `msg.get("content", "")` or validate at the request boundary (main.py `ChatRequest` accepts `list[dict]` with no schema enforcement).
2. **`chunk.text` may not exist on all stream chunks** (line 35) -- some chunks have only `usage_metadata` or `candidates` without text. Attribute access `chunk.text` should be safe if SDK provides a default empty string, but verify against google-genai SDK version. Defensive: `getattr(chunk, "text", None)`.

## Medium Priority
1. **No error handling in `chat_stream`** -- SDK exceptions (quota, invalid key, safety blocks) propagate unhandled. The caller in main.py catches via a bare `except Exception` and leaks `str(e)` to the client (line 51). Consider catching specific SDK errors and sanitizing the message.
2. **`system_prompt` injected as `user` role fallback** in `_ROLE_MAP` (line 12) -- system messages become `user` role. This is documented Gemini behavior but worth a code comment explaining why.

## Low Priority
1. **CORS `allow_origins=["*"]`** (main.py:16) -- acceptable for dev, tighten before production.
2. **Provider instantiated per request** (`create_provider()` called every request in main.py:34) -- if this creates a new `genai.Client` each time, it defeats the singleton intent. Verify `create_provider()` returns a cached instance.

## Positive Observations
- Clean typed SDK usage: `types.GenerateContentConfig`, `types.Content`, `types.Part.from_text()`
- Role mapping with unknown-role logging is good defensive practice
- Config as `None` when no system_prompt avoids sending unnecessary config
- Async streaming with `aio.models.generate_content_stream` is correct

## Metrics
- Type Coverage: Good (typed SDK objects throughout)
- Test Coverage: Not observed (no test files reviewed)
- Linting Issues: None apparent
