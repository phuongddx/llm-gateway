"""Model pricing table and cost calculation."""

# model -> (input_price_per_1m_tokens_usd, output_price_per_1m_tokens_usd)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3": (2.00, 8.00),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-flash-lite": (0.075, 0.30),
    "glm-5.1": (0.50, 0.50),
    "glm-5-turbo": (0.50, 0.50),
    "glm-5": (0.50, 0.50),
    "glm-4.7": (0.50, 0.50),
    "glm-4.7-flash": (0.10, 0.10),
    "glm-4.7-flashx": (0.10, 0.10),
    "glm-4.6": (0.50, 0.50),
    "glm-4.5": (0.50, 0.50),
    "glm-4.5-flash": (0.10, 0.10),
    "MiniMax-Text-01": (0.01, 0.01),
    "deepseek-chat": (0.27, 1.10),
    "deepseek-reasoner": (0.55, 2.19),
    "kimi-k2.5": (0.60, 2.50),
    "kimi-k2-thinking": (0.60, 2.50),
    "moonshot-v1-128k": (0.02, 0.02),
}


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD for a request. Returns 0.0 for unknown models."""
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        return 0.0
    input_price, output_price = pricing
    return (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
