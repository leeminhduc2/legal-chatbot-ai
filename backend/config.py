from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

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
    neo4j_database: str = ""
    chroma_path: str = "data/chroma/legal"
    chroma_collection: str = "legal_chunks"
    bm25_provider: str = "elasticsearch"
    elasticsearch_url: str = "http://localhost:9200"
    elasticsearch_index: str = "legal_chunks_bm25"
    elasticsearch_api_key: str = ""
    elasticsearch_username: str = ""
    elasticsearch_password: str = ""
    elasticsearch_verify_certs: bool = True
    llm_provider: str = "deepseek"
    llm_model_chat: str = ""
    llm_model_chunking: str = ""
    llm_model_metadata: str = "deepseek-v4-flash"
    llm_chunking_enabled: bool = False
    embedding_model: str = "BAAI/bge-m3"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            app_env=os.getenv("APP_ENV", cls.app_env),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", cls.flask_secret_key),
            sqlite_db_path=_sqlite_db_path_from_env("SQLITE_DB_PATH", cls.sqlite_db_path),
            admin_username=os.getenv("ADMIN_USERNAME", cls.admin_username),
            admin_password=os.getenv("ADMIN_PASSWORD", cls.admin_password),
            token_ttl_hours=_int_from_env("TOKEN_TTL_HOURS", cls.token_ttl_hours),
            neo4j_uri=os.getenv("NEO4J_URI", cls.neo4j_uri),
            neo4j_user=os.getenv(
                "NEO4J_USER",
                os.getenv("NEO4J_USERNAME", cls.neo4j_user),
            ),
            neo4j_password=os.getenv("NEO4J_PASSWORD", cls.neo4j_password),
            neo4j_database=os.getenv("NEO4J_DATABASE", cls.neo4j_database),
            chroma_path=os.getenv("CHROMA_PATH", cls.chroma_path),
            chroma_collection=os.getenv("CHROMA_COLLECTION", cls.chroma_collection),
            bm25_provider=os.getenv("BM25_PROVIDER", cls.bm25_provider),
            elasticsearch_url=os.getenv("ELASTICSEARCH_URL", cls.elasticsearch_url),
            elasticsearch_index=os.getenv(
                "ELASTICSEARCH_INDEX",
                cls.elasticsearch_index,
            ),
            elasticsearch_api_key=os.getenv(
                "ELASTICSEARCH_API_KEY",
                cls.elasticsearch_api_key,
            ),
            elasticsearch_username=os.getenv(
                "ELASTICSEARCH_USERNAME",
                cls.elasticsearch_username,
            ),
            elasticsearch_password=os.getenv(
                "ELASTICSEARCH_PASSWORD",
                cls.elasticsearch_password,
            ),
            elasticsearch_verify_certs=_bool_from_env(
                "ELASTICSEARCH_VERIFY_CERTS",
                cls.elasticsearch_verify_certs,
            ),
            llm_provider=os.getenv("LLM_PROVIDER", cls.llm_provider),
            llm_model_chat=os.getenv("LLM_MODEL_CHAT", cls.llm_model_chat),
            llm_model_chunking=os.getenv("LLM_MODEL_CHUNKING", cls.llm_model_chunking),
            llm_model_metadata=os.getenv(
                "LLM_MODEL_METADATA",
                os.getenv("DEEPSEEK_MODEL_METADATA", cls.llm_model_metadata),
            ),
            llm_chunking_enabled=_bool_from_env(
                "LLM_CHUNKING_ENABLED",
                cls.llm_chunking_enabled,
            ),
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


def _bool_from_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _sqlite_db_path_from_env(name: str, default: str) -> str:
    raw_value = os.getenv(name)
    if not raw_value:
        return default
    if raw_value == ":memory:":
        return raw_value

    path = Path(raw_value)
    if raw_value.endswith(("/", "\\")) or path.exists() and path.is_dir():
        return str(path / "app.sqlite3")
    if path.suffix:
        return str(path)
    return str(path / "app.sqlite3")
