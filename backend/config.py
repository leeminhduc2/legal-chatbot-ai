from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()



@dataclass(frozen=True)
class Config:
    app_env: str = "local"
    flask_secret_key: str = "dev-secret-key"
    sqlite_db_path: str = "data/app.sqlite3"
    admin_username: str = ""
    admin_password: str = ""
    token_ttl_hours: int = 24
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""
    chroma_path: str = "data/chroma/legal"
    chroma_collection: str = "legal_chunks"
    bm25_provider: str = "local"
    elasticsearch_url: str = ""
    llm_provider: str = "deepseek"
    llm_model_chat: str = ""
    llm_model_chunking: str = ""
    embedding_model: str = "BAAI/bge-m3"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            app_env=os.getenv("APP_ENV", cls.app_env),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", cls.flask_secret_key),
            sqlite_db_path=os.getenv("SQLITE_DB_PATH", cls.sqlite_db_path),
            admin_username=os.getenv("ADMIN_USERNAME", cls.admin_username),
            admin_password=os.getenv("ADMIN_PASSWORD", cls.admin_password),
            token_ttl_hours=_int_from_env("TOKEN_TTL_HOURS", cls.token_ttl_hours),
            neo4j_uri=os.getenv("NEO4J_URI", cls.neo4j_uri),
            neo4j_user=os.getenv("NEO4J_USER", cls.neo4j_user),
            neo4j_password=os.getenv("NEO4J_PASSWORD", cls.neo4j_password),
            chroma_path=os.getenv("CHROMA_PATH", cls.chroma_path),
            chroma_collection=os.getenv("CHROMA_COLLECTION", cls.chroma_collection),
            bm25_provider=os.getenv("BM25_PROVIDER", cls.bm25_provider),
            elasticsearch_url=os.getenv("ELASTICSEARCH_URL", cls.elasticsearch_url),
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            llm_model_chat=os.getenv("LLM_MODEL_CHAT", cls.llm_model_chat),
            llm_model_chunking=os.getenv("LLM_MODEL_CHUNKING", cls.llm_model_chunking),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
        )


def _int_from_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default
