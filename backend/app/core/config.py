from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "CyberMind API"
    app_env: str = "development"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    frontend_origin: str = "http://localhost:5173"
    auth_secret: str = "development-only-change-me"
    rate_limit_per_minute: int = 120
    database_url: str = "postgresql+psycopg://cybermind:cybermind@localhost:5432/cybermind"
    correlation_predictor: str = "trained_evidence"
    correlation_model_artifact: str = "data/correlation/experiments/f1_improvement_v3/models/random_forest.joblib"
    correlation_model_metadata: str = "data/correlation/experiments/f1_improvement_v3/config.json"
    correlation_model_metrics: str = "data/correlation/experiments/f1_improvement_v3/metrics.json"
    correlation_threshold: float = 0.35
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cybermind"
    neo4j_database: str = "neo4j"
    neo4j_sync_retries: int = 3
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "cti_documents_v1"
    qdrant_timeout: float = 10.0
    embedding_model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_model_version: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    embedding_batch_size: int = 32
    embedding_chunk_size: int = 1200
    embedding_chunk_overlap: int = 150
    genai_provider: str = "disabled"
    genai_api_key: str | None = None
    genai_base_url: str = "https://api.openai.com/v1"
    genai_model: str = "gpt-4o-mini"
    genai_timeout: float = 30.0

    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    def validate_production_security(self) -> None:
        if self.app_env.lower() in {"production", "prod"}:
            if self.auth_secret == "development-only-change-me" or len(self.auth_secret) < 32:
                raise ValueError("AUTH_SECRET must be a high-entropy value in production")
            if self.database_url.endswith("@localhost:5432/cybermind"):
                raise ValueError("DATABASE_URL must be explicitly configured in production")
            if self.neo4j_password == "cybermind":
                raise ValueError("NEO4J_PASSWORD must be explicitly configured in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
