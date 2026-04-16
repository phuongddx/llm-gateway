# System Architecture

## High-Level Architecture

```
+--------+        HTTP/SSE         +--------------+
| Client | <---------------------> | LLM Gateway  |
| (curl, |    POST /v1/chat/       | (FastAPI)    |
|  app)  |    completions          |              |
+--------+         |               | config.py    |
                   |               | main.py      |
                   |               +------+-------+
                   |                      |
                   |              create_provider()
                   |                      |
          +--------+--------+------------+
          |        |        |            |
          v        v        v            v
   +----------+ +------+ +--------+ +---------+
   | Gemini   | | GLM  | |MiniMax | | Future  |
   | Provider | |Provider| |Provider| |Provider |
   +----------+ +------+ +--------+ +---------+
       |            |         |          |
       v            v         v          v
   Google AI    ZhipuAI    MiniMax     TBD
   API          API        API
```

## Request Flow

```
1. Client sends POST /v1/chat/completions
   with Authorization: Bearer <token>
   and JSON body {messages, system_prompt, stream}

2. FastAPI middleware
   ├── CORS middleware (allow all)
   └── Route to chat endpoint

3. verify_auth() dependency
   ├── Extracts token from Authorization header
   ├── Compares against settings.app_api_key
   └── Rejects with 401 if mismatch

4. Endpoint handler
   ├── Creates provider via create_provider()
   ├── Returns StreamingResponse with _stream_tokens() generator
   └── Media type: text/event-stream

5. _stream_tokens() generator
   ├── Calls provider.chat_stream(messages, system_prompt)
   ├── Yields "data: {json}\n\n" for each token
   ├── On error: yields "data: {"error": "..."}\n\n"
   └── Final: yields "data: [DONE]\n\n"
```

## Provider Abstraction

### Base Class

```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat_stream(
        self, messages: list[dict], system_prompt: str
    ) -> AsyncGenerator[str, None]:
        """Yield tokens from the LLM."""
```

All providers implement the same interface: accept messages and system prompt, yield token strings asynchronously.

### Factory Dispatch

```python
def create_provider() -> LLMProvider:
    match settings.llm_provider:
        case "gemini"   -> GeminiProvider()
        case "glm"      -> GLMProvider()
        case "minimax"  -> MiniMaxProvider()
        case _          -> ValueError
```

Provider selection happens at request time via `LLM_PROVIDER` env var. Lazy imports avoid loading unused SDKs.

### Provider Implementations

#### GeminiProvider

- SDK: `google-genai` (native)
- Role mapping: `user->user`, `assistant->model`, `system->user`
- System prompt: `GenerateContentConfig(system_instruction=...)`
- Streaming: `client.aio.models.generate_content_stream()`

#### GLMProvider / MiniMaxProvider

- SDK: `openai.AsyncOpenAI` (both providers expose OpenAI-compatible APIs)
- No role mapping needed (native OpenAI format)
- System prompt: prepended as `{"role": "system", "content": ...}` message
- Streaming: `client.chat.completions.create(stream=True)`

### Data Flow: Message Transformation

```
OpenAI format (input)
  {"role": "user", "content": "Hello"}

  ┌─────────────┬──────────────────────────────────────┐
  │ Gemini      │ Convert to types.Content             │
  │             │ role="user", parts=[Part.from_text()] │
  │             │ system_prompt -> GenerateContentConfig│
  ├─────────────┼──────────────────────────────────────┤
  │ GLM/MiniMax │ Pass through as-is (already compatible)│
  │             │ Prepend system_prompt as system message│
  └─────────────┴──────────────────────────────────────┘
```

## Authentication Flow

```
Request Header: Authorization: Bearer <token>
                    |
                    v
            verify_auth() dependency
                    |
            token == settings.app_api_key?
            /                \
          Yes                No
           |                  |
    Continue to          HTTP 401
    endpoint handler     {"detail": "Invalid API key"}
```

Note: `GET /health` does not require authentication.

## Configuration Layer

```
.env file ──> pydantic BaseSettings ──> settings singleton
                  |
         +--------+--------+----------+
         |        |        |          |
    llm_provider  |   app_api_key   llm_base_url
         |   llm_api_key
         v
    create_provider()
    Provider __init__() reads settings for API key, model, base URL
```

All configuration is read at import time. Changing settings requires a server restart.

## Related Docs

- [Codebase Summary](./codebase-summary.md)
- [Code Standards](./code-standards.md)
- [Deployment Guide](./deployment-guide.md)
