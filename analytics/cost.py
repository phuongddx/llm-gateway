"""Cost/credit calculations — Manifest bills internally; z.ai coding plan meters in credits."""

from datetime import datetime, timedelta, timezone

# z.ai GLM Coding Plan credit multipliers, per token, before the /10_000 divisor
_CREDIT_MULTIPLIERS: dict[str, dict[str, float]] = {
    "glm-5.3": {"input": 6.9, "cached": 1.7, "output": 24.0},
    "glm-5.3-flash": {"input": 2.3, "cached": 0.56, "output": 8.0},
}

_SGT = timezone(timedelta(hours=8))


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return 0.0 — Manifest handles billing internally."""
    return 0.0


def is_peak(ts: datetime) -> bool:
    """True during z.ai peak window: Mon–Fri 14:00–18:00 Singapore time (UTC+8)."""
    local = ts.astimezone(_SGT)
    return local.weekday() < 5 and 14 <= local.hour < 18


def estimate_credits(provider: str, model: str, usage: dict, ts: datetime) -> float:
    """Estimate GLM Coding Plan credits for one request; 0.0 for other providers/models."""
    if provider != "zai-coding":
        return 0.0
    multipliers = _CREDIT_MULTIPLIERS.get(model)
    if multipliers is None:
        return 0.0
    cached = usage.get("cached_tokens") or 0
    fresh_input = max(usage.get("prompt_tokens", 0) - cached, 0)
    raw = (
        fresh_input * multipliers["input"]
        + cached * multipliers["cached"]
        + usage.get("completion_tokens", 0) * multipliers["output"]
    )
    credits = raw / 10_000
    if not is_peak(ts):
        credits *= 0.5  # Off-peak hours are charged at 50%
    return round(credits, 4)
