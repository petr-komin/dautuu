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

    # Web search
    tavily_api_key: str = ""

    # Embeddingy
    embedding_provider: str = "together"
    embedding_model: str = "intfloat/multilingual-e5-large-instruct"
    embedding_dim: int = 1024

    # Sumarizace konverzací
    summarization_provider: str = "together"
    summarization_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # Agent workspace
    agent_workspace: str = "/workspace"

    # Email DB — read-only připojení k externí databázi s emaily
    # Formát: postgresql://user:password@host:5432/dbname
    # Ponech prázdné pokud email integrace není potřeba.
    email_db_url: str = ""
    email_db_schema: str = "public"        # PostgreSQL schema kde jsou tabulky
    email_table: str = "messages"          # název tabulky s emaily
    email_col_id: str = "id"              # primární klíč
    email_col_subject: str = "subject"    # předmět
    email_col_body: str = "body_text"     # tělo emailu (plain text)
    email_col_from: str = "from_address"  # odesílatel
    email_col_from_name: str = "from_name"  # jméno odesílatele
    email_col_to: str = "to_addresses"    # příjemci (JSONB: [{name, address}])
    email_col_date: str = "date"          # datum (timestamp)
    email_col_preview: str = "preview"    # krátký preview (varchar)
    email_col_ai_summary: str = "ai_summary"  # AI shrnutí pokud existuje
    email_body_max_chars: int = 1500      # max znaků z těla emailu v jednom výsledku
    email_search_max_results: int = 5     # max emailů vrácených do kontextu

    # Seznam emailových účtů pro filtrování (mezera nebo čárka jako oddělovač)
    # Prázdné = žádný filtr (vrátí emaily ze všech účtů)
    email_accounts: str = ""

    @property
    def email_accounts_list(self) -> List[str]:
        """Parsuje email_accounts string na list (oddělovač: mezera nebo čárka)."""
        if not self.email_accounts:
            return []
        import re
        return [a.strip() for a in re.split(r"[\s,]+", self.email_accounts) if a.strip()]

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
