"""Cost calculation — simplified for Manifest provider."""


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return 0.0 — Manifest handles billing internally."""
    return 0.0
