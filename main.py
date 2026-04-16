import json

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from providers import create_provider

app = FastAPI(title="LLM Gateway")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    messages: list[dict]
    system_prompt: str = ""
    stream: bool = True


def verify_auth(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    if token != settings.app_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.post("/v1/chat/completions")
async def chat(request: ChatRequest, _auth=Depends(verify_auth)):
    provider = create_provider()
    return StreamingResponse(
        _stream_tokens(provider, request),
        media_type="text/event-stream",
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _stream_tokens(provider, request: ChatRequest):
    try:
        async for token in provider.chat_stream(request.messages, request.system_prompt):
            yield f"data: {json.dumps({'token': token})}\n\n"
    except Exception as e:
        error_payload = json.dumps({"error": str(e)})
        yield f"data: {error_payload}\n\n"
    yield "data: [DONE]\n\n"
