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

    model_config = {"env_file": ".env", "extra": "ignore"}

    def get_api_key(self, provider: str) -> str:
        """Return API key for provider. Dedicated key with llm_api_key fallback."""
        if provider == "manifest":
            return self.manifest_api_key or self.llm_api_key
        if provider == "zai-coding":
            return self.zai_coding_api_key or self.llm_api_key
        return self.llm_api_key


settings = Settings()
