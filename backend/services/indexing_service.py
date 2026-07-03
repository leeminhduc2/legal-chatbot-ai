from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from backend.config import Config
from backend.models.database import get_connection, row_to_dict
from backend.services.document_import_service import (
    STATUS_READY_FOR_REVIEW,
    VALIDITY_UNKNOWN,
    optional_str,
    validate_chunks,
)


PIPELINE_PUBLISH_DOCUMENT = "publish_document"
PIPELINE_ROLLBACK = "rollback_indexes"
STATUS_FAILED = "failed"
STATUS_PENDING = "pending"
STATUS_PUBLISH_STARTED = "publish_started"
STATUS_GRAPH_INDEXED = "graph_indexed"
STATUS_VECTOR_INDEXED = "vector_indexed"
STATUS_BM25_INDEXED = "bm25_indexed"
STATUS_PUBLISHED = "published"
STATUS_ROLLBACK_STARTED = "rollback_started"
STATUS_ROLLED_BACK = "rolled_back"
STATUS_SUPERSEDED = "superseded"


class IndexingError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    document_id: str
    import_batch_id: str
    document_number: str
    document_title: str
    content: str
    article_number: str
    hierarchy_path: str
    chunk_level: str
    is_published: bool
    published_version: int
    document_type: str | None = None
    source_url: str | None = None
    validity_status: str = VALIDITY_UNKNOWN
    effective_date: str | None = None
    expiry_date: str | None = None
    article_title: str | None = None
    clause_number: str | None = None
    citation_label: str | None = None
    ordinal: int | None = None
    neo4j_node_id: str | None = None

    @classmethod
    def from_raw(
        cls,
        raw_chunk: dict[str, Any],
        *,
        version: int,
        force_published: bool,
    ) -> "ChunkRecord":
        record = cls(
            chunk_id=str(raw_chunk.get("chunk_id") or "").strip(),
            document_id=str(raw_chunk.get("document_id") or "").strip(),
            import_batch_id=str(raw_chunk.get("import_batch_id") or "").strip(),
            document_number=str(raw_chunk.get("document_number") or "").strip(),
            document_title=str(raw_chunk.get("document_title") or "").strip(),
            content=str(raw_chunk.get("content") or "").strip(),
            article_number=str(raw_chunk.get("article_number") or "").strip(),
            hierarchy_path=str(raw_chunk.get("hierarchy_path") or "").strip(),
            chunk_level=str(raw_chunk.get("chunk_level") or "").strip() or "article",
            is_published=force_published,
            published_version=version,
            document_type=optional_str(raw_chunk.get("document_type")),
            source_url=optional_str(raw_chunk.get("source_url")),
            validity_status=optional_str(raw_chunk.get("validity_status"))
            or VALIDITY_UNKNOWN,
            effective_date=optional_str(raw_chunk.get("effective_date")),
            expiry_date=optional_str(raw_chunk.get("expiry_date")),
            article_title=optional_str(raw_chunk.get("article_title")),
            clause_number=optional_str(raw_chunk.get("clause_number")),
            citation_label=optional_str(raw_chunk.get("citation_label")),
            ordinal=int(raw_chunk["ordinal"]) if raw_chunk.get("ordinal") else None,
        )
        node_kind = "Clause" if record.chunk_level == "clause" else "Article"
        object.__setattr__(
            record,
            "neo4j_node_id",
            make_neo4j_node_id(record.document_id, node_kind, record.chunk_id),
        )
        return record

    def to_index_document(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["is_published"] = bool(self.is_published)
        return payload

    def to_scalar_metadata(self) -> dict[str, str | int | float | bool]:
        return sanitize_scalar_metadata(
            {
                "chunk_id": self.chunk_id,
                "document_id": self.document_id,
                "import_batch_id": self.import_batch_id,
                "document_number": self.document_number,
                "document_title": self.document_title,
                "article_number": self.article_number,
                "clause_number": self.clause_number,
                "citation_label": self.citation_label,
                "validity_status": self.validity_status,
                "is_published": 1 if self.is_published else 0,
                "published_version": self.published_version,
                "chunk_level": self.chunk_level,
                "neo4j_node_id": self.neo4j_node_id,
            }
        )


class IndexWriter(Protocol):
    name: str

    def index_chunks(
        self,
        chunks: list[ChunkRecord],
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        ...

    def delete_by_batch(self, import_batch_id: str) -> None:
        ...


class ElasticsearchBM25Provider:
    name = "elasticsearch"

    def __init__(self, config: Config):
        self.config = config
        self.index_name = config.elasticsearch_index
        self._client = None

    def index_chunks(
        self,
        chunks: list[ChunkRecord],
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        del relations
        if not chunks:
            return
        client = self._get_client()
        self.ensure_index()
        try:
            from elasticsearch.helpers import bulk
        except ImportError as exc:  # pragma: no cover - depends on local env.
            raise IndexingError(
                "ELASTICSEARCH_DEPENDENCY_MISSING",
                "The elasticsearch Python package is not installed.",
            ) from exc

        actions = [
            {
                "_op_type": "index",
                "_index": self.index_name,
                "_id": chunk.chunk_id,
                "_source": chunk.to_index_document(),
            }
            for chunk in chunks
        ]
        bulk(client, actions)

    def ensure_index(self) -> None:
        client = self._get_client()
        if client.indices.exists(index=self.index_name):
            return
        client.indices.create(index=self.index_name, body=elasticsearch_index_mapping())

    def delete_by_batch(self, import_batch_id: str) -> None:
        client = self._get_client()
        if not client.indices.exists(index=self.index_name):
            return
        client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"import_batch_id": import_batch_id}}},
            refresh=True,
            conflicts="proceed",
        )

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        client = self._get_client()
        must: list[dict[str, Any]] = [
            {
                "multi_match": {
                    "query": query,
                    "fields": ["content^3", "document_title^2", "citation_label"],
                }
            }
        ]
        filter_clauses = [
            {"term": {key: value}}
            for key, value in (filters or {}).items()
            if value is not None
        ]
        response = client.search(
            index=self.index_name,
            body={
                "query": {"bool": {"must": must, "filter": filter_clauses}},
                "size": top_k,
            },
        )
        return [
            {
                "score": hit.get("_score"),
                **hit.get("_source", {}),
            }
            for hit in response.get("hits", {}).get("hits", [])
        ]

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self.config.bm25_provider != "elasticsearch":
            raise IndexingError(
                "BM25_PROVIDER_NOT_ELASTICSEARCH",
                "BM25_PROVIDER must be set to elasticsearch before publishing.",
            )
        if not self.config.elasticsearch_url:
            raise IndexingError(
                "ELASTICSEARCH_CONFIG_MISSING",
                "ELASTICSEARCH_URL is required for BM25 indexing.",
            )
        try:
            from elasticsearch import Elasticsearch
        except ImportError as exc:  # pragma: no cover - depends on local env.
            raise IndexingError(
                "ELASTICSEARCH_DEPENDENCY_MISSING",
                "The elasticsearch Python package is not installed.",
            ) from exc

        kwargs: dict[str, Any] = {
            "hosts": [self.config.elasticsearch_url],
            "verify_certs": self.config.elasticsearch_verify_certs,
        }
        if self.config.elasticsearch_api_key:
            kwargs["api_key"] = self.config.elasticsearch_api_key
        elif self.config.elasticsearch_username or self.config.elasticsearch_password:
            kwargs["basic_auth"] = (
                self.config.elasticsearch_username,
                self.config.elasticsearch_password,
            )
        self._client = Elasticsearch(**kwargs)
        return self._client


class ChromaVectorProvider:
    name = "chroma"

    def __init__(self, config: Config, embedding_provider: Any | None = None):
        self.config = config
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider(
            config.embedding_model
        )

    def index_chunks(
        self,
        chunks: list[ChunkRecord],
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        del relations
        if not chunks:
            return
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - depends on local env.
            raise IndexingError(
                "CHROMA_DEPENDENCY_MISSING",
                "The chromadb Python package is not installed.",
            ) from exc

        client = chromadb.PersistentClient(path=self.config.chroma_path)
        collection = client.get_or_create_collection(name=self.config.chroma_collection)
        documents = [chunk.content for chunk in chunks]
        collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=documents,
            metadatas=[chunk.to_scalar_metadata() for chunk in chunks],
            embeddings=self.embedding_provider.embed_documents(documents),
        )

    def delete_by_batch(self, import_batch_id: str) -> None:
        try:
            import chromadb
        except ImportError as exc:  # pragma: no cover - depends on local env.
            raise IndexingError(
                "CHROMA_DEPENDENCY_MISSING",
                "The chromadb Python package is not installed.",
            ) from exc

        client = chromadb.PersistentClient(path=self.config.chroma_path)
        collection = client.get_or_create_collection(name=self.config.chroma_collection)
        collection.delete(where={"import_batch_id": import_batch_id})


class LocalEmbeddingProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._model = None
        self.quality_warning: str | None = None

    def embed_documents(self, documents: list[str]) -> list[list[float]]:
        model = self._load_bge_model()
        if model is not None:
            output = model.encode(
                documents,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            return output["dense_vecs"].tolist()

        self.quality_warning = (
            "FlagEmbedding is not installed; Chroma used deterministic hash "
            "embeddings instead of BGE-M3 semantic embeddings."
        )
        return [hash_embedding(document) for document in documents]

    def _load_bge_model(self):
        if self._model is not None:
            return self._model
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError:
            return None
        self._model = BGEM3FlagModel(self.model_name, use_fp16=True)
        return self._model


class Neo4jGraphWriter:
    name = "neo4j"

    def __init__(self, config: Config):
        self.config = config
        self._driver = None

    def index_chunks(
        self,
        chunks: list[ChunkRecord],
        relations: list[dict[str, Any]] | None = None,
    ) -> None:
        if not chunks:
            return
        driver = self._get_driver()
        document = chunks[0]
        with driver.session(**self._session_kwargs()) as session:
            session.run(
                """
                MERGE (d:Document {document_id: $document_id})
                SET d.document_number = $document_number,
                    d.title = $document_title,
                    d.import_batch_id = $import_batch_id,
                    d.validity_status = $validity_status,
                    d.is_published = true,
                    d.published_version = $published_version
                """,
                document_id=document.document_id,
                document_number=document.document_number,
                document_title=document.document_title,
                import_batch_id=document.import_batch_id,
                validity_status=document.validity_status,
                published_version=document.published_version,
            )
            article_numbers = sorted({chunk.article_number for chunk in chunks})
            for article_number in article_numbers:
                article_chunks = [
                    chunk for chunk in chunks if chunk.article_number == article_number
                ]
                article_id = make_neo4j_node_id(
                    document.document_id,
                    "Article",
                    article_number,
                )
                article_content = next(
                    (
                        chunk.content
                        for chunk in article_chunks
                        if chunk.chunk_level == "article"
                    ),
                    "",
                )
                session.run(
                    """
                    MATCH (d:Document {document_id: $document_id})
                    MERGE (a:Article {node_id: $article_id})
                    SET a.document_id = $document_id,
                        a.article_number = $article_number,
                        a.content = $content,
                        a.import_batch_id = $import_batch_id,
                        a.is_published = true,
                        a.published_version = $published_version
                    MERGE (d)-[:HAS_ARTICLE]->(a)
                    """,
                    document_id=document.document_id,
                    article_id=article_id,
                    article_number=article_number,
                    content=article_content,
                    import_batch_id=document.import_batch_id,
                    published_version=document.published_version,
                )
            for chunk in chunks:
                if chunk.chunk_level != "clause":
                    continue
                article_id = make_neo4j_node_id(
                    chunk.document_id,
                    "Article",
                    chunk.article_number,
                )
                session.run(
                    """
                    MATCH (a:Article {node_id: $article_id})
                    MERGE (c:Clause {node_id: $clause_id})
                    SET c.chunk_id = $chunk_id,
                        c.document_id = $document_id,
                        c.article_number = $article_number,
                        c.clause_number = $clause_number,
                        c.content = $content,
                        c.citation_label = $citation_label,
                        c.import_batch_id = $import_batch_id,
                        c.is_published = true,
                        c.published_version = $published_version
                    MERGE (a)-[:HAS_CLAUSE]->(c)
                    """,
                    article_id=article_id,
                    clause_id=chunk.neo4j_node_id,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    article_number=chunk.article_number,
                    clause_number=chunk.clause_number,
                    content=chunk.content,
                    citation_label=chunk.citation_label,
                    import_batch_id=chunk.import_batch_id,
                    published_version=chunk.published_version,
                )
            for relation in relations or []:
                session.run(
                    """
                    MATCH (source:Document {document_id: $source_document_id})
                    MERGE (target:DocumentReference {
                        document_number: $target_document_number
                    })
                    MERGE (source)-[r:ADMIN_RELATION {
                        relation_id: $relation_id
                    }]->(target)
                    SET r.relation_type = $relation_type,
                        r.source_text = $source_text,
                        r.import_batch_id = $import_batch_id,
                        r.is_published = true
                    """,
                    relation_id=relation["id"],
                    source_document_id=relation["source_document_id"],
                    target_document_number=relation.get("target_document_number")
                    or relation.get("target_document_id"),
                    relation_type=relation["relation_type"],
                    source_text=relation.get("source_text"),
                    import_batch_id=relation["import_batch_id"],
                )

    def delete_by_batch(self, import_batch_id: str) -> None:
        self.unpublish_by_batch(import_batch_id)

    def unpublish_by_batch(self, import_batch_id: str) -> None:
        driver = self._get_driver()
        with driver.session(**self._session_kwargs()) as session:
            session.run(
                """
                MATCH (n)
                WHERE n.import_batch_id = $import_batch_id
                SET n.is_published = false
                """,
                import_batch_id=import_batch_id,
            )
            session.run(
                """
                MATCH ()-[r]->()
                WHERE r.import_batch_id = $import_batch_id
                SET r.is_published = false
                """,
                import_batch_id=import_batch_id,
            )

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        if not self.config.neo4j_password:
            raise IndexingError(
                "NEO4J_CONFIG_MISSING",
                "NEO4J_PASSWORD is required for graph indexing.",
            )
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:  # pragma: no cover - depends on local env.
            raise IndexingError(
                "NEO4J_DEPENDENCY_MISSING",
                "The neo4j Python package is not installed.",
            ) from exc
        self._driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_user, self.config.neo4j_password),
        )
        self._driver.verify_connectivity()
        return self._driver

    def _session_kwargs(self) -> dict[str, str]:
        if not self.config.neo4j_database:
            return {}
        return {"database": self.config.neo4j_database}


class DocumentIndexingService:
    def __init__(
        self,
        config: Config,
        providers: list[IndexWriter] | None = None,
    ):
        self.config = config
        self.db_path = config.sqlite_db_path
        self.providers = providers

    def publish_document(
        self,
        document_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        version = self._get_latest_version(document_id)
        if version is None:
            raise IndexingError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        if version["status"] != STATUS_READY_FOR_REVIEW:
            raise IndexingError(
                "DOCUMENT_NOT_READY",
                "Only ready_for_review documents can be published.",
                409,
                {"current_status": version["status"]},
            )

        pipeline_run_id = str(uuid.uuid4())
        import_batch_id = version["import_batch_id"]
        self._create_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            pipeline_type=PIPELINE_PUBLISH_DOCUMENT,
            requested_by_user_id=requested_by_user_id,
            status=STATUS_PENDING,
            input_json={
                "document_id": document_id,
                "version": version["version"],
                "import_batch_id": import_batch_id,
            },
        )

        indexed_providers: list[IndexWriter] = []
        try:
            raw_chunks = load_chunk_json(Path(version["chunk_json_path"]))
            validate_chunks(raw_chunks)
            chunks = normalize_chunk_records(
                raw_chunks,
                version=int(version["version"]),
                force_published=True,
            )
            warnings = collect_publish_warnings(version, chunks)
            relations = self._get_relations(import_batch_id)
            old_batches = self._get_published_batches_for_document(
                document_id=document_id,
                exclude_import_batch_id=import_batch_id,
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_PUBLISH_STARTED,
                "Publish validation completed.",
                {
                    "chunks_count": len(chunks),
                    "warnings": warnings,
                    "old_batches": old_batches,
                },
            )

            writer_statuses: dict[str, str] = {}
            providers = self.providers or build_default_indexing_providers(self.config)
            for provider, state in [
                (providers[0], STATUS_GRAPH_INDEXED),
                (providers[1], STATUS_VECTOR_INDEXED),
                (providers[2], STATUS_BM25_INDEXED),
            ]:
                provider.index_chunks(chunks, relations)
                indexed_providers.append(provider)
                writer_statuses[provider.name] = "indexed"
                self._mark_pipeline(
                    pipeline_run_id,
                    state,
                    f"{provider.name} indexing completed.",
                    {"provider": provider.name, "chunks_count": len(chunks)},
                )

            self._unpublish_old_batches(providers, old_batches)
            self._mark_sqlite_published(
                document_id=document_id,
                version=int(version["version"]),
                import_batch_id=import_batch_id,
                superseded_batches=old_batches,
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_PUBLISHED,
                "Document published and indexes are ready.",
                {"writer_statuses": writer_statuses, "warnings": warnings},
            )
            return {
                "document_id": document_id,
                "version": version["version"],
                "import_batch_id": import_batch_id,
                "pipeline_run_id": pipeline_run_id,
                "status": STATUS_PUBLISHED,
                "writers": writer_statuses,
                "warnings": warnings,
            }
        except Exception as exc:
            cleanup_errors = cleanup_indexed_batch(indexed_providers, import_batch_id)
            details = exception_details(exc)
            if cleanup_errors:
                details["cleanup_errors"] = cleanup_errors
            self._fail_pipeline(
                pipeline_run_id,
                "Publish failed.",
                details,
            )
            if isinstance(exc, IndexingError):
                raise
            if hasattr(exc, "code") and hasattr(exc, "message"):
                raise IndexingError(
                    str(getattr(exc, "code")),
                    str(getattr(exc, "message")),
                    int(getattr(exc, "status_code", 400)),
                    details=details,
                ) from exc
            raise IndexingError(
                "PUBLISH_FAILED",
                "Publish failed.",
                details=details,
            ) from exc

    def rollback_pipeline(
        self,
        run_id: str,
        requested_by_user_id: str,
    ) -> dict[str, Any]:
        source_run = self._get_pipeline_run(run_id)
        if source_run is None:
            raise IndexingError("DOCUMENT_NOT_FOUND", "Pipeline run not found.", 404)
        input_json = parse_json(source_run.get("input_json"))
        import_batch_id = optional_str(input_json.get("import_batch_id"))
        if not import_batch_id:
            raise IndexingError(
                "ROLLBACK_UNAVAILABLE",
                "Selected pipeline run does not have an import_batch_id.",
                409,
            )
        version = self._get_version_by_batch(import_batch_id)
        if version is None:
            raise IndexingError(
                "ROLLBACK_UNAVAILABLE",
                "No document version found for the selected pipeline batch.",
                409,
            )

        pipeline_run_id = str(uuid.uuid4())
        self._create_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            pipeline_type=PIPELINE_ROLLBACK,
            requested_by_user_id=requested_by_user_id,
            status=STATUS_PENDING,
            input_json={
                "source_pipeline_run_id": run_id,
                "document_id": version["document_id"],
                "version": version["version"],
                "import_batch_id": import_batch_id,
            },
        )
        self._mark_pipeline(
            pipeline_run_id,
            STATUS_ROLLBACK_STARTED,
            "Rollback started.",
            {"import_batch_id": import_batch_id},
        )

        try:
            providers = self.providers or build_default_indexing_providers(self.config)
            cleanup_errors = cleanup_indexed_batch(providers, import_batch_id)
            if cleanup_errors:
                self._fail_pipeline(
                    pipeline_run_id,
                    "Rollback index cleanup failed.",
                    {"cleanup_errors": cleanup_errors},
                )
                raise IndexingError(
                    "ROLLBACK_FAILED",
                    "Rollback index cleanup failed.",
                    details={"cleanup_errors": cleanup_errors},
                )

            restored_version = self._get_previous_restorable_version(
                document_id=version["document_id"],
                before_version=int(version["version"]),
            )
            restored_batch = None
            restored_writers: dict[str, str] = {}
            if restored_version is not None:
                raw_chunks = load_chunk_json(Path(restored_version["chunk_json_path"]))
                validate_chunks(raw_chunks)
                restored_chunks = normalize_chunk_records(
                    raw_chunks,
                    version=int(restored_version["version"]),
                    force_published=True,
                )
                relations = self._get_relations(restored_version["import_batch_id"])
                for provider in providers:
                    provider.index_chunks(restored_chunks, relations)
                    restored_writers[provider.name] = "restored"
                restored_batch = restored_version["import_batch_id"]

            self._mark_sqlite_rolled_back(
                document_id=version["document_id"],
                rolled_back_version=int(version["version"]),
                restored_version=(
                    int(restored_version["version"]) if restored_version else None
                ),
                import_batch_id=import_batch_id,
                restored_import_batch_id=restored_batch,
            )
            self._mark_pipeline(
                pipeline_run_id,
                STATUS_ROLLED_BACK,
                "Rollback completed.",
                {
                    "rolled_back_import_batch_id": import_batch_id,
                    "restored_import_batch_id": restored_batch,
                    "writers": restored_writers,
                },
            )
            return {
                "pipeline_run_id": pipeline_run_id,
                "status": STATUS_ROLLED_BACK,
                "rolled_back_import_batch_id": import_batch_id,
                "restored_import_batch_id": restored_batch,
                "writers": restored_writers,
            }
        except Exception as exc:
            if not isinstance(exc, IndexingError) or exc.code != "ROLLBACK_FAILED":
                self._fail_pipeline(
                    pipeline_run_id,
                    "Rollback failed.",
                    exception_details(exc),
                )
            if isinstance(exc, IndexingError):
                raise
            raise IndexingError(
                "ROLLBACK_FAILED",
                "Rollback failed.",
                details=exception_details(exc),
            ) from exc

    def _get_latest_version(self, document_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            return row_to_dict(
                connection.execute(
                    """
                    SELECT *
                    FROM document_versions
                    WHERE document_id = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (document_id,),
                ).fetchone()
            )

    def _get_version_by_batch(self, import_batch_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            return row_to_dict(
                connection.execute(
                    """
                    SELECT *
                    FROM document_versions
                    WHERE import_batch_id = ?
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (import_batch_id,),
                ).fetchone()
            )

    def _get_pipeline_run(self, run_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            return row_to_dict(
                connection.execute(
                    "SELECT * FROM pipeline_runs WHERE id = ?",
                    (run_id,),
                ).fetchone()
            )

    def _get_relations(self, import_batch_id: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM document_relations
                WHERE import_batch_id = ?
                ORDER BY created_at ASC
                """,
                (import_batch_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_published_batches_for_document(
        self,
        document_id: str,
        exclude_import_batch_id: str,
    ) -> list[str]:
        with get_connection(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT import_batch_id
                FROM document_versions
                WHERE document_id = ?
                  AND status = ?
                  AND import_batch_id IS NOT NULL
                  AND import_batch_id != ?
                """,
                (document_id, STATUS_PUBLISHED, exclude_import_batch_id),
            ).fetchall()
        return [row["import_batch_id"] for row in rows]

    def _get_previous_restorable_version(
        self,
        document_id: str,
        before_version: int,
    ) -> dict[str, Any] | None:
        with get_connection(self.db_path) as connection:
            return row_to_dict(
                connection.execute(
                    """
                    SELECT *
                    FROM document_versions
                    WHERE document_id = ?
                      AND version < ?
                      AND status != ?
                      AND chunk_json_path IS NOT NULL
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (document_id, before_version, STATUS_ROLLED_BACK),
                ).fetchone()
            )

    def _mark_sqlite_published(
        self,
        document_id: str,
        version: int,
        import_batch_id: str,
        superseded_batches: list[str],
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            if superseded_batches:
                connection.execute(
                    f"""
                    UPDATE document_versions
                    SET status = ?
                    WHERE import_batch_id IN ({','.join('?' for _ in superseded_batches)})
                    """,
                    (STATUS_SUPERSEDED, *superseded_batches),
                )
                connection.execute(
                    f"""
                    UPDATE document_relations
                    SET is_published = 0
                    WHERE import_batch_id IN ({','.join('?' for _ in superseded_batches)})
                    """,
                    tuple(superseded_batches),
                )
            connection.execute(
                """
                UPDATE document_versions
                SET status = ?
                WHERE document_id = ? AND version = ?
                """,
                (STATUS_PUBLISHED, document_id, version),
            )
            connection.execute(
                """
                UPDATE document_registry
                SET active_version = ?, is_published = 1, updated_at = ?
                WHERE document_id = ?
                """,
                (version, now, document_id),
            )
            connection.execute(
                """
                UPDATE document_relations
                SET is_published = 1
                WHERE import_batch_id = ?
                """,
                (import_batch_id,),
            )
            connection.commit()

    def _mark_sqlite_rolled_back(
        self,
        document_id: str,
        rolled_back_version: int,
        restored_version: int | None,
        import_batch_id: str,
        restored_import_batch_id: str | None,
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE document_versions
                SET status = ?
                WHERE document_id = ? AND version = ?
                """,
                (STATUS_ROLLED_BACK, document_id, rolled_back_version),
            )
            connection.execute(
                """
                UPDATE document_relations
                SET is_published = 0
                WHERE import_batch_id = ?
                """,
                (import_batch_id,),
            )
            if restored_version is None:
                connection.execute(
                    """
                    UPDATE document_registry
                    SET active_version = NULL, is_published = 0, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (now, document_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE document_versions
                    SET status = ?
                    WHERE document_id = ? AND version = ?
                    """,
                    (STATUS_PUBLISHED, document_id, restored_version),
                )
                connection.execute(
                    """
                    UPDATE document_registry
                    SET active_version = ?, is_published = 1, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (restored_version, now, document_id),
                )
                if restored_import_batch_id:
                    connection.execute(
                        """
                        UPDATE document_relations
                        SET is_published = 1
                        WHERE import_batch_id = ?
                        """,
                        (restored_import_batch_id,),
                    )
            connection.commit()

    def _create_pipeline_run(
        self,
        pipeline_run_id: str,
        pipeline_type: str,
        requested_by_user_id: str,
        status: str,
        input_json: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO pipeline_runs (
                    id, pipeline_type, requested_by_user_id, input_json,
                    status, error_message, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    pipeline_run_id,
                    pipeline_type,
                    requested_by_user_id,
                    json.dumps(input_json, ensure_ascii=False),
                    status,
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    status,
                    "Pipeline created.",
                    json.dumps(input_json, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

    def _mark_pipeline(
        self,
        pipeline_run_id: str,
        status: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, pipeline_run_id),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    status,
                    message,
                    json.dumps(payload or {}, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

    def _fail_pipeline(
        self,
        pipeline_run_id: str,
        message: str,
        payload: dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                UPDATE pipeline_runs
                SET status = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (STATUS_FAILED, message, now, pipeline_run_id),
            )
            connection.execute(
                """
                INSERT INTO pipeline_events (
                    id, pipeline_run_id, state, message, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    pipeline_run_id,
                    STATUS_FAILED,
                    message,
                    json.dumps(payload, ensure_ascii=False),
                    now,
                ),
            )
            connection.commit()

    def _unpublish_old_batches(
        self,
        providers: list[IndexWriter],
        old_batches: list[str],
    ) -> None:
        for old_batch in old_batches:
            cleanup_indexed_batch(providers, old_batch)


def build_default_indexing_providers(config: Config) -> list[IndexWriter]:
    return [
        Neo4jGraphWriter(config),
        ChromaVectorProvider(config),
        ElasticsearchBM25Provider(config),
    ]


def load_chunk_json(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise IndexingError(
            "CHUNK_JSON_MISSING",
            "Chunk JSON file does not exist.",
            details={"chunk_json_path": str(path)},
        )
    try:
        chunks = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexingError(
            "CHUNK_VALIDATION_FAILED",
            "Chunk JSON is not valid JSON.",
            details={"chunk_json_path": str(path), "reason": str(exc)},
        ) from exc
    if not isinstance(chunks, list):
        raise IndexingError(
            "CHUNK_VALIDATION_FAILED",
            "Chunk JSON must contain an array of chunk records.",
            details={"chunk_json_path": str(path)},
        )
    return chunks


def normalize_chunk_records(
    raw_chunks: list[dict[str, Any]],
    *,
    version: int,
    force_published: bool,
) -> list[ChunkRecord]:
    records = [
        ChunkRecord.from_raw(
            raw_chunk,
            version=version,
            force_published=force_published,
        )
        for raw_chunk in raw_chunks
    ]
    missing = [
        index
        for index, record in enumerate(records, start=1)
        if not record.chunk_id
        or not record.document_id
        or not record.import_batch_id
        or not record.document_number
        or not record.document_title
        or not record.content
        or not record.article_number
        or not record.hierarchy_path
        or (record.chunk_level == "clause" and not record.clause_number)
    ]
    if missing:
        raise IndexingError(
            "CHUNK_VALIDATION_FAILED",
            "Chunk records are missing required indexing fields.",
            details={"invalid_chunk_indexes": missing[:20]},
        )
    return records


def collect_publish_warnings(
    version: dict[str, Any],
    chunks: list[ChunkRecord],
) -> list[str]:
    warnings = []
    if any(chunk.validity_status == VALIDITY_UNKNOWN for chunk in chunks):
        warnings.append(
            "validity_status is unknown; default active-only retrieval may exclude this document."
        )
    if not any(chunk.effective_date for chunk in chunks):
        warnings.append("effective_date is missing from chunk metadata.")
    metadata = parse_json(version.get("metadata_json"))
    if metadata.get("relations_unavailable"):
        warnings.append("No admin-curated document relations are available.")
    return warnings


def cleanup_indexed_batch(
    providers: list[IndexWriter],
    import_batch_id: str,
) -> list[dict[str, str]]:
    errors = []
    for provider in providers:
        try:
            provider.delete_by_batch(import_batch_id)
        except Exception as exc:  # Best-effort cleanup must keep all errors.
            errors.append(
                {
                    "provider": provider.name,
                    "error": str(exc),
                }
            )
    return errors


def exception_details(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, IndexingError):
        return {"code": exc.code, **exc.details}
    if hasattr(exc, "code"):
        return {"code": str(getattr(exc, "code"))}
    return {"code": exc.__class__.__name__, "reason": str(exc)}


def parse_json(raw_value: Any) -> dict[str, Any]:
    if not raw_value:
        return {}
    if isinstance(raw_value, dict):
        return raw_value
    try:
        parsed = json.loads(str(raw_value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def sanitize_scalar_metadata(
    metadata: dict[str, Any],
) -> dict[str, str | int | float | bool]:
    sanitized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            sanitized[key] = value
        else:
            sanitized[key] = str(value)
    return sanitized


def hash_embedding(document: str, dimensions: int = 384) -> list[float]:
    vector = [0.0] * dimensions
    tokens = document.lower().split()
    for token in tokens or [document]:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def make_neo4j_node_id(document_id: str, node_kind: str, local_id: str) -> str:
    return f"{document_id}:{node_kind}:{local_id}"


def elasticsearch_index_mapping() -> dict[str, Any]:
    return {
        "settings": {
            "analysis": {
                "filter": {
                    "vietnamese_ascii_folding": {
                        "type": "asciifolding",
                        "preserve_original": True,
                    }
                },
                "analyzer": {
                    "vi_text": {
                        "tokenizer": "standard",
                        "filter": ["lowercase", "vietnamese_ascii_folding"],
                    }
                },
            }
        },
        "mappings": {
            "properties": {
                "chunk_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "import_batch_id": {"type": "keyword"},
                "document_number": {"type": "keyword"},
                "document_title": {"type": "text", "analyzer": "vi_text"},
                "document_type": {"type": "keyword"},
                "source_url": {"type": "keyword"},
                "content": {"type": "text", "analyzer": "vi_text"},
                "article_number": {"type": "keyword"},
                "clause_number": {"type": "keyword"},
                "citation_label": {"type": "text", "analyzer": "vi_text"},
                "hierarchy_path": {"type": "keyword"},
                "chunk_level": {"type": "keyword"},
                "validity_status": {"type": "keyword"},
                "effective_date": {"type": "date", "ignore_malformed": True},
                "expiry_date": {"type": "date", "ignore_malformed": True},
                "is_published": {"type": "boolean"},
                "published_version": {"type": "integer"},
                "ordinal": {"type": "integer"},
                "neo4j_node_id": {"type": "keyword"},
            }
        },
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
