from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Legacy single-provider config (backward compat fallback)
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_base_url: str | None = None

    # Per-provider API keys
    openai_api_key: str = ""
    deepseek_api_key: str = ""
    moonshot_api_key: str = ""
    bytedance_api_key: str = ""
    glm_api_key: str = ""

    # Gateway auth — MUST be set via APP_API_KEY env var
    app_api_key: str = ""

    # CORS
    cors_origins: str = ""  # Comma-separated allowed origins (empty = no CORS)

    # Rate limiting
    rate_limit: str = "60/minute"  # Max requests per window per client

    # Analytics
    analytics_db_path: str = "data/analytics.db"

    model_config = {"env_file": ".env"}

    def get_api_key(self, provider: str) -> str:
        """Return provider-specific API key, falling back to llm_api_key."""
        provider_keys = {
            "openai": self.openai_api_key,
            "deepseek": self.deepseek_api_key,
            "moonshot": self.moonshot_api_key,
            "bytedance": self.bytedance_api_key,
            "glm": self.glm_api_key,
        }
        return provider_keys.get(provider, "") or self.llm_api_key


settings = Settings()
