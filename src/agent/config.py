from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["anthropic", "google_genai"] = "google_genai"
    llm_model: str = "gemini-3.1-flash-lite-preview"
    llm_temperature: float = 0.0

    classifier_provider: str | None = None
    classifier_model: str | None = None

    executor_provider: str | None = None
    executor_model: str | None = None

    embeddings_provider: Literal["huggingface", "google_genai", "openai"] = "huggingface"
    embeddings_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # Hybrid retrieval tuning
    top_k: int = 8
    semantic_weight: float = 0.7  # bm25_weight = 1 - semantic_weight
    use_reranking: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    openai_api_key: str | None = None

    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/payments"
    db_schema: str = "public"

    vectorstore_dir: Path = Field(default=Path("./vectorstore/policies"))
    vectorstore_collection: str = "policies"
    policies_dir: Path = Field(default=Path("./policies"))

    checkpointer: Literal["memory", "postgres"] = "memory"
    checkpointer_postgres_url: str | None = None


settings = Settings()
