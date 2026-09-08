from limits import parse_many
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Fallback API key (used if MANIFEST_API_KEY is not set)
    llm_api_key: str = ""

    # Manifest provider
    manifest_api_key: str = ""

    # Z.AI GLM Coding Plan provider (endpoint: https://api.z.ai/api/coding/paas/v4)
    zai_coding_api_key: str = ""

    # GLM Coding Plan credit quotas (defaults = Max tier; adjust per tier)
    zai_credits_5h: int = 28000
    zai_credits_week: int = 140000

    # Gateway auth — MUST be set via APP_API_KEY env var
    app_api_key: str = ""

    # CORS
    cors_origins: str = ""  # Comma-separated allowed origins (empty = no CORS)

    # Rate limiting
    rate_limit: str = "60/minute"  # Max requests per window per client

    # Analytics
    analytics_db_path: str = "data/analytics.db"
    analytics_queue_size: int = 1000  # Bounded analytics write queue (drop-newest when full)

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
        "hide_input_in_errors": True,  # never echo key values in ValidationErrors
    }

    @model_validator(mode="after")
    def _validate_rate_limit(self) -> "Settings":
        """Fail fast on malformed RATE_LIMIT — slowapi would defer it to request time."""
        try:
            parsed = list(parse_many(self.rate_limit))
        except ValueError as e:
            raise ValueError(
                f"RATE_LIMIT is not a valid rate string (expected e.g. '60/minute'): "
                f"{self.rate_limit!r} ({e})"
            ) from e
        if not parsed:
            raise ValueError(f"RATE_LIMIT parsed to zero limits: {self.rate_limit!r}")
        return self

    @model_validator(mode="after")
    def _validate_analytics_queue_size(self) -> "Settings":
        """Fail fast on an unbounding queue size — asyncio.Queue treats maxsize<=0 as unbounded."""
        if self.analytics_queue_size < 1:
            raise ValueError(
                f"ANALYTICS_QUEUE_SIZE must be >= 1 (got {self.analytics_queue_size}); "
                "0 or negative would disable the queue bound"
            )
        return self

    def get_api_key(self, provider: str) -> str:
        """Return API key for provider. Dedicated key with llm_api_key fallback."""
        if provider == "manifest":
            return self.manifest_api_key or self.llm_api_key
        if provider == "zai-coding":
            return self.zai_coding_api_key or self.llm_api_key
        return self.llm_api_key


settings = Settings()
