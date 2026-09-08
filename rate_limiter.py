"""Rate limiter instance — shared across modules to avoid circular imports."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from config import settings

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


def extract_bearer_key(request: Request) -> str:
    """Per-key rate-limit identity: the Bearer token itself, falling back to
    remote IP when missing/malformed (same removeprefix idiom as verify_auth
    in routes/chat.py) — locked decision: a missing/malformed token still
    gets an IP-scoped limit rather than being exempt from per-key limiting."""
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").removeprefix("bearer ")
    return token or get_remote_address(request)
