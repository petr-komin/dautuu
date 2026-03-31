from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://dautuu:dautuu@localhost:5432/dautuu"

    # JWT
    secret_key: str = "insecure_dev_key_change_in_production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 10080  # 7 dní

    # LLM providers
    together_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://host.docker.internal:11434"

    # Embeddingy
    embedding_provider: str = "together"
    embedding_model: str = "intfloat/multilingual-e5-large-instruct"
    embedding_dim: int = 1024

    # Sumarizace konverzací
    summarization_provider: str = "together"
    summarization_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # CORS
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str) -> str:
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
