from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    llm_provider: str = "gemini"
    llm_api_key: str = ""
    llm_model: str = ""
    app_api_key: str = "changeme"
    llm_base_url: str | None = None

    model_config = {"env_file": ".env"}


settings = Settings()
