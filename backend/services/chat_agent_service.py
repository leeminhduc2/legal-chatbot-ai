from __future__ import annotations

import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict

from backend.config import Config
from backend.models.database import get_connection
from backend.services.auth_service import ROLE_ADMIN, ROLE_GUEST
from backend.services.document_import_service import VALIDITY_UNKNOWN
from backend.services.indexing_service import LocalEmbeddingProvider


logger = logging.getLogger(__name__)

MODE_LEGAL_LOOKUP = "legal_lookup"
MODE_STATUS_BASIC = "status_basic"
MODE_OUT_OF_SCOPE = "out_of_scope"
MODE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"

AGENT_MODE_LEGACY = "legacy"
AGENT_MODE_REACT = "react"

WARNING_NO_CITATION = "NO_CITATION"
WARNING_LOW_RELEVANCE = "LOW_RELEVANCE"
WARNING_UNKNOWN_VALIDITY = "UNKNOWN_VALIDITY"
WARNING_RETRIEVER_UNAVAILABLE = "RETRIEVER_UNAVAILABLE"
WARNING_STATUS_INCOMPLETE = "STATUS_INCOMPLETE"
WARNING_LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
WARNING_AGENT_TOOL_CALLING_UNAVAILABLE = "AGENT_TOOL_CALLING_UNAVAILABLE"
WARNING_AGENT_TIMEOUT_PARTIAL = "AGENT_TIMEOUT_PARTIAL"
WARNING_AGENT_FALLBACK = "AGENT_FALLBACK"
WARNING_CITATION_RELEVANCE_FILTER = "CITATION_RELEVANCE_FILTER"
WARNING_QUERY_CONTEXTUALIZATION = "QUERY_CONTEXTUALIZATION"

ACTIVE_STATUSES = {"active", "partially_effective", "partially_expired"}
INACTIVE_STATUSES = {"expired", "replaced", "abolished", "revoked", "suspended"}
STATUS_TERMS = (
    "hieu luc",
    "het hieu luc",
    "con hieu luc",
    "het han",
    "thay the",
    "bai bo",
    "status",
    "validity",
)
OUT_OF_SCOPE_TERMS = (
    "soan thao",
    "draft",
    "review hop dong",
    "ra soat hop dong",
    "upload hop dong",
)


class ChatAgentState(TypedDict, total=False):
    trace_id: str
    question: str
    normalized_query: str
    contextualized_query: str
    user_role: str
    top_k: int
    mode: str
    explicit_expired: bool
    filters: dict[str, str]
    warnings: list[dict[str, str]]
    status_records: list[dict[str, Any]]
    vector_hits: list["RetrievalHit"]
    bm25_hits: list["RetrievalHit"]
    fused_hits: list["RetrievalHit"]
    graph_context: dict[str, Any]
    citations: list[dict[str, Any]]
    citation_filter: dict[str, Any]
    confidence: float
    answer: str
    llm_check: dict[str, Any]
    conversation_context: dict[str, Any]
    agent_steps: list[dict[str, Any]]
    tool_trace: list[dict[str, Any]]
    memory_used: dict[str, Any]
    expanded_chunk_ids: list[str]
    status_sufficient: bool
    access_scope: "AccessScope"


class ChatLLM(Protocol):
    def contextualize_query(
        self,
        current_query: str,
        conversation_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        ...

    def classify(self, question: str) -> dict[str, Any]:
        ...

    def check_evidence(
        self,
        question: str,
        mode: str,
        hits: list["RetrievalHit"],
        status_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def filter_relevant_citations(
        self,
        question: str,
        mode: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        ...

    def generate_answer(
        self,
        question: str,
        mode: str,
        hits: list["RetrievalHit"],
        status_records: list[dict[str, Any]],
        graph_context: dict[str, Any],
        warnings: list[dict[str, str]],
        conversation_context: dict[str, Any] | None = None,
        expanded_chunk_ids: list[str] | None = None,
    ) -> str:
        ...


@dataclass
class AgentToolSpec:
    name: str
    description: str
    func: Callable[..., str]


@dataclass(frozen=True)
class AccessScope:
    unrestricted: bool = False
    field_ids: tuple[int, ...] = (0,)

    def allows(self, value: Any) -> bool:
        if self.unrestricted:
            return True
        field_id = normalize_field_id(value, default=0)
        return field_id in set(self.field_ids)


@dataclass
class RetrievalHit:
    chunk_id: str | None = None
    document_id: str | None = None
    document_number: str | None = None
    document_title: str | None = None
    content: str = ""
    article_number: str | None = None
    clause_number: str | None = None
    citation_label: str | None = None
    validity_status: str | None = None
    field_id: int | None = None
    is_published: bool = True
    score: float = 0.0
    source: str = ""
    sources: set[str] = field(default_factory=set)

    @property
    def key(self) -> str:
        if self.chunk_id:
            return self.chunk_id
        parts = [
            self.document_id or self.document_number or "",
            self.article_number or "",
            self.clause_number or "",
            self.citation_label or "",
        ]
        return "|".join(parts).strip("|") or str(uuid.uuid4())

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        source: str,
        score: float | None = None,
        content: str | None = None,
    ) -> "RetrievalHit":
        hit = cls(
            chunk_id=optional_text(payload.get("chunk_id")),
            document_id=optional_text(payload.get("document_id")),
            document_number=optional_text(payload.get("document_number")),
            document_title=optional_text(
                payload.get("document_title")
                or payload.get("title")
                or payload.get("document_name")
            ),
            content=content if content is not None else str(payload.get("content") or ""),
            article_number=optional_text(payload.get("article_number")),
            clause_number=optional_text(payload.get("clause_number")),
            citation_label=optional_text(payload.get("citation_label")),
            validity_status=normalize_validity_status(payload.get("validity_status")),
            field_id=normalize_field_id(payload.get("field_id"), default=0),
            is_published=coerce_bool(payload.get("is_published"), default=True),
            score=float(score if score is not None else payload.get("score") or 0.0),
            source=source,
            sources={source},
        )
        if not hit.citation_label and (hit.document_number or hit.article_number):
            label = hit.document_number or hit.document_title or "unknown"
            if hit.article_number:
                label = f"{label}, Dieu {hit.article_number}"
            if hit.clause_number:
                label = f"{label} Khoan {hit.clause_number}"
            hit.citation_label = label
        return hit

    def citation(self) -> dict[str, Any]:
        status = normalize_validity_status(self.validity_status)
        return {
            "citation_label": self.citation_label or "",
            "document_id": self.document_id or "",
            "document_title": self.document_title or "",
            "document_name": self.document_title or "",
            "document_number": self.document_number or "",
            "article_number": self.article_number,
            "clause_number": self.clause_number,
            "article": f"Dieu {self.article_number}" if self.article_number else None,
            "validity_status": status,
            "field_id": self.field_id if self.field_id is not None else 0,
            "is_active": is_active_status(status),
            "chunk_id": self.chunk_id,
        }


class DeepSeekChatClient:
    def __init__(self, config: Config):
        self.config = config
        self._client = None

    def contextualize_query(
        self,
        current_query: str,
        conversation_context: dict[str, Any],
    ) -> dict[str, Any] | None:
        memory = compact_conversation_context(conversation_context or {})
        if not memory.get("summary") and not memory.get("recent_messages"):
            return {
                "standalone_query": current_query,
                "used_memory": False,
                "reason": "no conversation memory",
            }
        payload = {
            "current_query": current_query,
            "conversation_memory": memory,
        }
        content = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite the current Vietnamese or English legal chatbot query into "
                        "a standalone query using conversation memory only when needed. "
                        "If the query is already standalone, return it unchanged. Do not answer, "
                        "do not add legal facts, and do not invent facts missing from memory. "
                        "Return JSON only with keys: standalone_query, used_memory, reason."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if not isinstance(content, dict):
            return None
        standalone_query = optional_text(content.get("standalone_query"))
        if not standalone_query:
            return None
        return {
            "standalone_query": standalone_query,
            "used_memory": bool(content.get("used_memory")),
            "reason": trim_words(str(content.get("reason") or ""), 24),
        }

    def classify(self, question: str) -> dict[str, Any]:
        fallback = classify_question_heuristically(question)
        content = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Classify a Vietnamese legal chatbot query. Return JSON only "
                        "with keys: mode, normalized_query, explicit_expired. mode must "
                        "be legal_lookup, status_basic, or out_of_scope. Do not answer."
                    ),
                },
                {"role": "user", "content": question},
            ]
        )
        if not isinstance(content, dict):
            return fallback
        mode = content.get("mode")
        if mode not in {MODE_LEGAL_LOOKUP, MODE_STATUS_BASIC, MODE_OUT_OF_SCOPE}:
            mode = fallback["mode"]
        normalized_query = optional_text(content.get("normalized_query")) or question
        return {
            "mode": mode,
            "normalized_query": normalized_query,
            "explicit_expired": bool(
                content.get("explicit_expired", fallback["explicit_expired"])
            ),
        }

    def check_evidence(
        self,
        question: str,
        mode: str,
        hits: list[RetrievalHit],
        status_records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "question": question,
            "mode": mode,
            "citations": [hit.citation() for hit in hits[:8]],
            "status_records": compact_status_records(status_records),
        }
        content = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Check whether retrieved legal evidence is relevant. Return JSON "
                        "only with keys: relevant, confidence_delta, warnings. "
                        "confidence_delta must be between -0.1 and 0.1. Do not add facts."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if not isinstance(content, dict):
            return {"relevant": bool(hits or status_records), "confidence_delta": 0.0}
        delta = safe_float(content.get("confidence_delta"), default=0.0)
        return {
            "relevant": bool(content.get("relevant", True)),
            "confidence_delta": max(-0.1, min(0.1, delta)),
            "warnings": content.get("warnings") if isinstance(content.get("warnings"), list) else [],
        }

    def filter_relevant_citations(
        self,
        question: str,
        mode: str,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        payload = {
            "question": question,
            "mode": mode,
            "candidates": [
                {
                    key: value
                    for key, value in candidate.items()
                    if key not in {"source_index", "match_key"}
                }
                for candidate in candidates[:12]
            ],
        }
        content = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Select only citation candidates that directly and strongly support "
                        "answering the user's Vietnamese legal question. Same topic, weak "
                        "keyword overlap, or merely being from the same document is not enough. "
                        "Return JSON only with keys: relevant_keys, warnings. relevant_keys "
                        "must be an array of candidate key strings. Do not add facts."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if not isinstance(content, dict) or not isinstance(content.get("relevant_keys"), list):
            return None
        relevant_keys = [
            str(item)
            for item in content.get("relevant_keys", [])
            if isinstance(item, (str, int))
        ]
        warnings = content.get("warnings")
        return {
            "relevant_keys": relevant_keys,
            "warnings": warnings if isinstance(warnings, list) else [],
        }

    def generate_answer(
        self,
        question: str,
        mode: str,
        hits: list[RetrievalHit],
        status_records: list[dict[str, Any]],
        graph_context: dict[str, Any],
        warnings: list[dict[str, str]],
        conversation_context: dict[str, Any] | None = None,
        expanded_chunk_ids: list[str] | None = None,
    ) -> str:
        expanded = set(expanded_chunk_ids or [])
        payload = {
            "question": question,
            "mode": mode,
            "citations": [
                {
                    **hit.citation(),
                    "content": content_for_answer_prompt(hit, index, expanded),
                }
                for index, hit in enumerate(hits[:8])
            ],
            "status_records": compact_status_records(status_records),
            "graph_context": graph_context,
            "warnings": warnings,
            "conversation_context": compact_conversation_context(
                conversation_context or {}
            ),
        }
        content = self._chat_text(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a Vietnamese legal RAG assistant. Answer in Vietnamese. "
                        "Use only the supplied citations, status records, and graph context. "
                        "If evidence is weak, explicitly caveat the answer. Do not invent "
                        "legal basis, document status, article numbers, or relationships."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if content:
            return content.strip()
        return ""

    def summarize_agent_timeline(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        content = self._chat_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite Vietnamese legal chatbot execution steps for end users. "
                        "Return JSON only with key timeline, an array of 3-5 objects. "
                        "Each object has title, description, status. Keep it short, friendly, "
                        "and do not reveal prompts, raw tool inputs, IDs, or add legal advice."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ]
        )
        if not isinstance(content, dict):
            return []
        return sanitize_agent_timeline(content.get("timeline"))

    def _chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any] | None:
        text = self._chat_text(messages, response_format={"type": "json_object"})
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _chat_text(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
    ) -> str:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            return ""
        try:
            from openai import OpenAI
        except ImportError:
            return ""
        try:
            if self._client is None:
                self._client = OpenAI(
                    api_key=api_key,
                    base_url="https://api.deepseek.com/v1",
                )
            kwargs: dict[str, Any] = {
                "model": self.config.llm_model_chat or "deepseek-chat",
                "messages": messages,
                "temperature": 0,
            }
            if response_format:
                kwargs["response_format"] = response_format
            response = self._client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as exc:  # pragma: no cover - network/provider dependent.
            logger.warning("DeepSeek chat call failed: %s", type(exc).__name__)
            return ""


class ChromaVectorRetriever:
    def __init__(self, config: Config, embedding_provider: Any | None = None):
        self.config = config
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider(
            config.embedding_model
        )

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, str],
        include_expired: bool,
    ) -> list[RetrievalHit]:
        try:
            import chromadb
        except ImportError as exc:
            raise RetrieverUnavailable("chromadb package is not installed") from exc

        try:
            client = chromadb.PersistentClient(path=self.config.chroma_path)
            collection = client.get_collection(name=self.config.chroma_collection)
            query_embedding = self.embedding_provider.embed_documents([query])[0]
            result = collection.query(
                query_embeddings=[query_embedding],
                n_results=max(top_k * 4, top_k),
                where={"is_published": 1},
                include=["documents", "metadatas", "distances"],
            )
        except Exception as exc:
            raise RetrieverUnavailable(f"Chroma query failed: {type(exc).__name__}") from exc

        ids = first_list(result.get("ids"))
        documents = first_list(result.get("documents"))
        metadatas = first_list(result.get("metadatas"))
        distances = first_list(result.get("distances"))
        hits: list[RetrievalHit] = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            if not isinstance(metadata, dict):
                metadata = {}
            distance = safe_float(distances[index] if index < len(distances) else None, 1.0)
            score = 1.0 / (1.0 + max(distance, 0.0))
            payload = {**metadata, "chunk_id": metadata.get("chunk_id") or chunk_id}
            hit = RetrievalHit.from_payload(
                payload,
                source="vector",
                score=score,
                content=documents[index] if index < len(documents) else "",
            )
            if hit_allowed(hit, filters, include_expired):
                hits.append(hit)
            if len(hits) >= top_k:
                break
        return hits


class ElasticsearchBM25Retriever:
    def __init__(self, config: Config):
        self.config = config
        self._client = None

    def search(
        self,
        query: str,
        top_k: int,
        filters: dict[str, str],
        include_expired: bool,
    ) -> list[RetrievalHit]:
        if self.config.bm25_provider != "elasticsearch":
            raise RetrieverUnavailable("BM25_PROVIDER is not elasticsearch")
        try:
            client = self._get_client()
            filter_clauses: list[dict[str, Any]] = [{"term": {"is_published": True}}]
            access_scope = access_scope_from_filters(filters)
            if not access_scope.unrestricted:
                field_should: list[dict[str, Any]] = [
                    {"terms": {"field_id": list(access_scope.field_ids)}}
                ]
                if 0 in access_scope.field_ids:
                    field_should.append(
                        {"bool": {"must_not": {"exists": {"field": "field_id"}}}}
                    )
                filter_clauses.append(
                    {"bool": {"should": field_should, "minimum_should_match": 1}}
                )
            if filters.get("document_number"):
                filter_clauses.append({"term": {"document_number": filters["document_number"]}})
            if filters.get("article_number"):
                filter_clauses.append({"term": {"article_number": filters["article_number"]}})
            response = client.search(
                index=self.config.elasticsearch_index,
                body={
                    "query": {
                        "bool": {
                            "must": [
                                {
                                    "multi_match": {
                                        "query": query,
                                        "fields": [
                                            "content^3",
                                            "document_title^2",
                                            "citation_label",
                                            "document_number",
                                        ],
                                    }
                                }
                            ],
                            "filter": filter_clauses,
                        }
                    },
                    "size": max(top_k * 2, top_k),
                },
            )
        except Exception as exc:
            raise RetrieverUnavailable(
                f"Elasticsearch query failed: {type(exc).__name__}"
            ) from exc

        hits: list[RetrievalHit] = []
        for raw in response.get("hits", {}).get("hits", []):
            source = raw.get("_source", {})
            if not isinstance(source, dict):
                continue
            hit = RetrievalHit.from_payload(
                source,
                source="bm25",
                score=safe_float(raw.get("_score"), 0.0),
            )
            if hit_allowed(hit, filters, include_expired):
                hits.append(hit)
            if len(hits) >= top_k:
                break
        return hits

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.config.elasticsearch_url:
            raise RetrieverUnavailable("ELASTICSEARCH_URL is empty")
        try:
            from elasticsearch import Elasticsearch
        except ImportError as exc:
            raise RetrieverUnavailable("elasticsearch package is not installed") from exc
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


class FixedNeo4jContextRetriever:
    def __init__(self, config: Config):
        self.config = config
        self._driver = None

    def enrich(
        self,
        hits: list[RetrievalHit],
        top_k: int,
        access_scope: AccessScope | None = None,
    ) -> dict[str, Any]:
        if not hits or not self.config.neo4j_password:
            return {"related_documents": [], "effectivity_relations": [], "support_score": 0.0}
        access_scope = access_scope or AccessScope()
        try:
            driver = self._get_driver()
            related: list[dict[str, Any]] = []
            structures = 0
            with driver.session(**self._session_kwargs()) as session:
                for hit in hits[:top_k]:
                    if hit.document_id and hit.article_number:
                        row = session.run(
                            """
                            MATCH (d:Document {document_id: $document_id})
                                  -[:HAS_ARTICLE]->(a:Article {article_number: $article_number})
                            OPTIONAL MATCH (a)-[:HAS_CLAUSE]->(c:Clause)
                            RETURN d.document_id AS document_id,
                                   a.article_number AS article_number,
                                   count(c) AS clause_count
                            LIMIT 1
                            """,
                            document_id=hit.document_id,
                            article_number=hit.article_number,
                        ).single()
                        if row:
                            structures += 1
                    if hit.document_id:
                        result = session.run(
                            """
                            MATCH (d:Document {document_id: $document_id})
                                  -[r:ADMIN_RELATION]->(target)
                            WHERE coalesce(r.is_published, false) = true
                              AND (
                                  $unrestricted = true
                                  OR coalesce(target.field_id, 0) IN $field_ids
                              )
                            RETURN r.relation_type AS relation_type,
                                   r.source_text AS source_text,
                                   target.document_number AS target_document_number,
                                   coalesce(target.field_id, 0) AS field_id
                            LIMIT 10
                            """,
                            document_id=hit.document_id,
                            unrestricted=access_scope.unrestricted,
                            field_ids=list(access_scope.field_ids),
                        )
                        related.extend(dict(record) for record in result)
            support = 0.0
            if structures and related:
                support = 1.0
            elif structures:
                support = 0.7
            elif hits:
                support = 0.5
            return {
                "related_documents": related,
                "effectivity_relations": related,
                "support_score": support,
            }
        except Exception as exc:
            logger.warning("Neo4j enrichment failed: %s", type(exc).__name__)
            return {"related_documents": [], "effectivity_relations": [], "support_score": 0.0}

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise RetrieverUnavailable("neo4j package is not installed") from exc
        self._driver = GraphDatabase.driver(
            self.config.neo4j_uri,
            auth=(self.config.neo4j_user, self.config.neo4j_password),
        )
        self._driver.verify_connectivity()
        return self._driver

    def _session_kwargs(self) -> dict[str, str]:
        return {"database": self.config.neo4j_database} if self.config.neo4j_database else {}


class DocumentStatusRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def find_status_records(self, query: str, filters: dict[str, str], limit: int) -> list[dict[str, Any]]:
        terms = [filters.get("document_number"), query]
        access_scope = access_scope_from_filters(filters)
        rows: list[dict[str, Any]] = []
        with get_connection(self.db_path) as connection:
            for term in terms:
                cleaned = optional_text(term)
                if not cleaned:
                    continue
                like = f"%{cleaned}%"
                records = connection.execute(
                    f"""
                    SELECT document_id, document_number, title, validity_status,
                           field_id, effective_date, expiry_date, is_published, active_version
                    FROM document_registry
                    WHERE is_published = 1
                      AND (document_number LIKE ? OR title LIKE ?)
                      {field_scope_sql(access_scope)}
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (like, like, *field_scope_params(access_scope), limit),
                ).fetchall()
                for row in records:
                    item = dict(row)
                    item["relations"] = self._relations_for(
                        connection,
                        item["document_id"],
                        access_scope,
                    )
                    if item["document_id"] not in {record["document_id"] for record in rows}:
                        rows.append(item)
                if len(rows) >= limit:
                    break
        return rows[:limit]

    def _relations_for(
        self,
        connection,
        document_id: str,
        access_scope: AccessScope,
    ) -> list[dict[str, Any]]:
        rows = connection.execute(
            f"""
            SELECT dr.relation_type,
                   dr.target_document_id,
                   dr.target_document_number,
                   dr.source_text
            FROM document_relations dr
            LEFT JOIN document_registry target
              ON target.document_id = dr.target_document_id
              OR (
                  dr.target_document_number IS NOT NULL
                  AND target.document_number = dr.target_document_number
                  AND target.is_deleted = 0
              )
            WHERE dr.source_document_id = ?
              AND dr.is_published = 1
              {field_scope_sql(access_scope, table_alias='target', allow_unresolved=True)}
            ORDER BY dr.created_at DESC
            LIMIT 10
            """,
            (document_id, *field_scope_params(access_scope)),
        ).fetchall()
        return [dict(row) for row in rows]


class RetrieverUnavailable(Exception):
    pass


class AgentUnavailable(Exception):
    pass


class AgentTimeout(Exception):
    pass


class ChatAgentService:
    def __init__(
        self,
        config: Config,
        *,
        llm: ChatLLM | None = None,
        vector_retriever: Any | None = None,
        bm25_retriever: Any | None = None,
        graph_retriever: Any | None = None,
        status_repository: DocumentStatusRepository | None = None,
        react_agent_factory: Callable[..., Any] | None = None,
    ):
        self.config = config
        self.llm = llm or DeepSeekChatClient(config)
        self.vector_retriever = vector_retriever or ChromaVectorRetriever(config)
        self.bm25_retriever = bm25_retriever or ElasticsearchBM25Retriever(config)
        self.graph_retriever = graph_retriever or FixedNeo4jContextRetriever(config)
        self.status_repository = status_repository or DocumentStatusRepository(
            config.sqlite_db_path
        )
        self.react_agent_factory = react_agent_factory
        self._graph = self._build_graph()

    def answer(
        self,
        message: str,
        *,
        user: dict[str, Any] | None = None,
        requested_top_k: Any = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trace_id = str(uuid.uuid4())
        user_role = user["role"] if user else ROLE_GUEST
        access_scope = access_scope_for_user(user)
        memory_used = build_memory_used(conversation_context or {})
        state: ChatAgentState = {
            "trace_id": trace_id,
            "question": message,
            "normalized_query": message,
            "contextualized_query": "",
            "user_role": user_role,
            "top_k": resolve_top_k(requested_top_k, user_role),
            "mode": MODE_LEGAL_LOOKUP,
            "explicit_expired": False,
            "filters": {},
            "warnings": [],
            "conversation_context": conversation_context or {},
            "agent_steps": [],
            "tool_trace": [],
            "memory_used": memory_used,
            "expanded_chunk_ids": [],
            "citation_filter": {},
            "status_sufficient": False,
            "access_scope": access_scope,
        }
        started = time.perf_counter()
        try:
            if self.config.chat_agent_mode == AGENT_MODE_REACT:
                try:
                    state = self._run_react_pipeline(state, started)
                except AgentUnavailable as exc:
                    state["warnings"] = append_warning(
                        state.get("warnings", []),
                        WARNING_AGENT_TOOL_CALLING_UNAVAILABLE,
                        f"Agent tool-calling unavailable: {exc}",
                    )
                    state["agent_steps"] = append_agent_step(
                        state.get("agent_steps", []),
                        "fallback",
                        "ReAct agent unavailable; legacy retrieval pipeline was used.",
                        "warning",
                    )
                    state = self._run_legacy_pipeline(state)
                except AgentTimeout:
                    if state.get("citations"):
                        state = self._partial_timeout_state(state)
                    else:
                        state["warnings"] = append_warning(
                            state.get("warnings", []),
                            WARNING_AGENT_TIMEOUT_PARTIAL,
                            "Agent reached the time budget before finding citations.",
                        )
                        state["mode"] = MODE_INSUFFICIENT_EVIDENCE
                        state["confidence"] = 0.0
                        state.update(self._generate_output(state))
                except Exception as exc:
                    logger.exception("ReAct chat agent failed trace_id=%s", trace_id)
                    state["warnings"] = append_warning(
                        state.get("warnings", []),
                        WARNING_AGENT_FALLBACK,
                        f"ReAct agent failed before producing final evidence: {type(exc).__name__}.",
                    )
                    state["agent_steps"] = append_agent_step(
                        state.get("agent_steps", []),
                        "fallback",
                        "ReAct agent failed; legacy retrieval pipeline was used.",
                        "warning",
                    )
                    state = self._run_legacy_pipeline(state)
            else:
                state = self._run_legacy_pipeline(state)
        except Exception as exc:
            logger.exception("Chat agent failed trace_id=%s", trace_id)
            return insufficient_evidence_response(
                message,
                trace_id,
                [
                    warning(
                        "CHAT_SERVICE_ERROR",
                        f"Chat service failed before producing evidence: {type(exc).__name__}.",
                    )
                ],
                agent_steps=state.get("agent_steps", []),
                tool_trace=state.get("tool_trace", []),
                memory_used=state.get("memory_used", memory_used),
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "chat_agent trace_id=%s mode=%s duration_ms=%s hits=%s warnings=%s model=%s",
            trace_id,
            state.get("mode"),
            duration_ms,
            len(state.get("fused_hits", [])),
            [item.get("code") for item in state.get("warnings", [])],
            self.config.llm_model_chat,
        )
        answer = state.get("answer") or ""
        agent_timeline = build_agent_timeline(
            self.llm,
            agent_steps=state.get("agent_steps", []),
            tool_trace=state.get("tool_trace", []),
            memory_used=state.get("memory_used", memory_used),
            warnings=state.get("warnings", []),
            retrieval_mode=str(state.get("mode", MODE_INSUFFICIENT_EVIDENCE)),
        )
        return {
            "answer": answer,
            "response": answer,
            "query": message,
            "retrieval_mode": state.get("mode", MODE_INSUFFICIENT_EVIDENCE),
            "confidence": round(float(state.get("confidence") or 0.0), 3),
            "warnings": state.get("warnings", []),
            "citations": state.get("citations", []),
            "trace_id": trace_id,
            "agent_steps": state.get("agent_steps", []),
            "tool_trace": state.get("tool_trace", []),
            "memory_used": state.get("memory_used", memory_used),
            "agent_timeline": agent_timeline,
        }

    def _run_legacy_pipeline(self, state: ChatAgentState) -> ChatAgentState:
        if self._graph is not None:
            return self._graph.invoke(state)
        return self._run_without_langgraph(state)

    def _build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError:
            return None
        builder = StateGraph(ChatAgentState)
        builder.add_node("contextualize_query", self._contextualize_query)
        builder.add_node("route_intent", self._route_intent)
        builder.add_node("resolve_exact_status", self._resolve_exact_status)
        builder.add_node("decide_status_sufficiency", self._decide_status_sufficiency)
        builder.add_node("vector_retrieve", self._vector_retrieve)
        builder.add_node("bm25_retrieve", self._bm25_retrieve)
        builder.add_node("fuse_and_rerank", self._fuse_and_rerank)
        builder.add_node("citation_relevance_filter", self._filter_citations_by_relevance)
        builder.add_node("graph_enrich", self._graph_enrich)
        builder.add_node("evidence_check", self._evidence_check)
        builder.add_node("generate_output", self._generate_output)
        builder.add_edge(START, "contextualize_query")
        builder.add_edge("contextualize_query", "route_intent")
        builder.add_edge("route_intent", "resolve_exact_status")
        builder.add_edge("resolve_exact_status", "decide_status_sufficiency")
        builder.add_edge("decide_status_sufficiency", "vector_retrieve")
        builder.add_edge("vector_retrieve", "bm25_retrieve")
        builder.add_edge("bm25_retrieve", "fuse_and_rerank")
        builder.add_edge("fuse_and_rerank", "citation_relevance_filter")
        builder.add_edge("citation_relevance_filter", "graph_enrich")
        builder.add_edge("graph_enrich", "evidence_check")
        builder.add_edge("evidence_check", "generate_output")
        builder.add_edge("generate_output", END)
        return builder.compile()

    def _run_without_langgraph(self, state: ChatAgentState) -> ChatAgentState:
        for node in (
            self._contextualize_query,
            self._route_intent,
            self._resolve_exact_status,
            self._decide_status_sufficiency,
            self._vector_retrieve,
            self._bm25_retrieve,
            self._fuse_and_rerank,
            self._filter_citations_by_relevance,
            self._graph_enrich,
            self._evidence_check,
            self._generate_output,
        ):
            state.update(node(state))
        return state

    def _run_react_pipeline(
        self,
        state: ChatAgentState,
        started: float,
    ) -> ChatAgentState:
        deadline = started + max(1, self.config.chat_agent_timeout_seconds)
        state.update(self._contextualize_query(state))
        state["agent_steps"] = append_agent_step(
            state.get("agent_steps", []),
            "route",
            "Classified query and extracted filters.",
            "ok",
        )
        state.update(self._route_intent(state))
        if state.get("mode") == MODE_OUT_OF_SCOPE:
            state.update(self._generate_output(state))
            return state

        self._raise_if_timed_out(deadline)
        self._invoke_react_agent_phase(
            state=state,
            phase="retrieval",
            tool_specs=self._retrieval_tool_specs(state),
            prompt=self._retrieval_agent_prompt(state),
            deadline=deadline,
        )
        self._ensure_retrieval_baseline(state)
        state.update(self._decide_status_sufficiency(state))
        state.update(self._fuse_and_rerank(state))
        state.update(self._filter_citations_by_relevance(state))
        if not state.get("citations"):
            state.update(self._evidence_check(state))
            state.update(self._generate_output(state))
            return state

        if self._timed_out(deadline):
            return self._partial_timeout_state(state)

        self._invoke_react_agent_phase(
            state=state,
            phase="expansion",
            tool_specs=self._expansion_tool_specs(state),
            prompt=self._expansion_agent_prompt(state),
            deadline=deadline,
        )
        self._ensure_expansion_baseline(state)
        state.update(self._evidence_check(state))
        if self._timed_out(deadline):
            return self._partial_timeout_state(state)
        state.update(self._generate_output(state))
        return state

    def _invoke_react_agent_phase(
        self,
        *,
        state: ChatAgentState,
        phase: str,
        tool_specs: list[AgentToolSpec],
        prompt: str,
        deadline: float,
    ) -> None:
        self._raise_if_timed_out(deadline)
        state["agent_steps"] = append_agent_step(
            state.get("agent_steps", []),
            phase,
            f"Started {phase} ReAct phase with {len(tool_specs)} tools.",
            "running",
        )
        if self.react_agent_factory is not None:
            self.react_agent_factory(
                phase=phase,
                prompt=prompt,
                tools=tool_specs,
                state=state,
            )
        else:
            self._invoke_langgraph_react_agent(
                phase=phase,
                prompt=prompt,
                tool_specs=tool_specs,
                state=state,
                deadline=deadline,
            )
        state["agent_steps"] = append_agent_step(
            state.get("agent_steps", []),
            phase,
            f"Completed {phase} ReAct phase.",
            "ok",
        )

    def _invoke_langgraph_react_agent(
        self,
        *,
        phase: str,
        prompt: str,
        tool_specs: list[AgentToolSpec],
        state: ChatAgentState,
        deadline: float,
    ) -> None:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise AgentUnavailable("DEEPSEEK_API_KEY is empty")
        try:
            from langchain_core.tools import StructuredTool
            from langchain_openai import ChatOpenAI
            from langgraph.prebuilt import create_react_agent
        except ImportError as exc:
            raise AgentUnavailable(type(exc).__name__) from exc

        tools = [
            StructuredTool.from_function(
                func=spec.func,
                name=spec.name,
                description=spec.description,
            )
            for spec in tool_specs
        ]
        timeout = max(1.0, deadline - time.perf_counter())
        model = ChatOpenAI(
            model=self.config.llm_model_chat or "deepseek-chat",
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
            temperature=0,
            timeout=timeout,
            max_retries=0,
        )
        try:
            agent = create_react_agent(
                model,
                tools=tools,
                prompt=prompt,
                version="v2",
            )
            agent.invoke(
                {
                    "messages": [
                        {"role": "user", "content": self._agent_user_content(state, phase)}
                    ]
                },
                config={"recursion_limit": max(4, self.config.chat_agent_max_iterations * 2)},
            )
        except Exception as exc:
            raise AgentUnavailable(type(exc).__name__) from exc

    def _retrieval_tool_specs(self, state: ChatAgentState) -> list[AgentToolSpec]:
        return [
            AgentToolSpec(
                "status_lookup",
                "Look up published document status metadata by query or document number.",
                lambda query="", document_number="", limit=0: self._agent_status_lookup(
                    state,
                    query,
                    document_number,
                    limit,
                ),
            ),
            AgentToolSpec(
                "vector_search",
                "Search published legal chunks semantically in the vector index.",
                lambda query="", top_k=0: self._agent_vector_search(state, query, top_k),
            ),
            AgentToolSpec(
                "bm25_search",
                "Search published legal chunks lexically in the BM25 index.",
                lambda query="", top_k=0: self._agent_bm25_search(state, query, top_k),
            ),
        ]

    def _ensure_retrieval_baseline(self, state: ChatAgentState) -> None:
        query = state.get("normalized_query") or state["question"]
        if state.get("mode") == MODE_STATUS_BASIC and not tool_was_called(
            state,
            "status_lookup",
        ):
            self._agent_status_lookup(state, query, "", state["top_k"])
        if not tool_was_called(state, "vector_search"):
            self._agent_vector_search(state, query, state["top_k"])
        if not tool_was_called(state, "bm25_search"):
            self._agent_bm25_search(state, query, state["top_k"])

    def _ensure_expansion_baseline(self, state: ChatAgentState) -> None:
        if state.get("fused_hits") and not tool_was_called(state, "graph_context"):
            self._agent_graph_context(state, "retrieved citations")

    def _expansion_tool_specs(self, state: ChatAgentState) -> list[AgentToolSpec]:
        return [
            AgentToolSpec(
                "graph_context",
                "Load published graph context for the retrieved citations only.",
                lambda focus="": self._agent_graph_context(state, focus),
            ),
            AgentToolSpec(
                "get_chunk_detail",
                "Open additional content for an already retrieved chunk_id.",
                lambda chunk_id: self._agent_chunk_detail(state, chunk_id),
            ),
        ]

    def _retrieval_agent_prompt(self, state: ChatAgentState) -> str:
        mode = state.get("mode", MODE_LEGAL_LOOKUP)
        return (
            "You are the retrieval phase of a Vietnamese legal RAG agent. "
            "Use only the provided tools. Call vector_search and bm25_search for "
            "legal_lookup questions. For status_basic questions, also call status_lookup. "
            "Do not answer the user. Do not infer legal relationships from content."
            f" Current mode: {mode}."
        )

    def _expansion_agent_prompt(self, state: ChatAgentState) -> str:
        return (
            "You are the evidence expansion phase of a Vietnamese legal RAG agent. "
            "Use graph_context for published database relationships and get_chunk_detail "
            "only for chunk_ids that were already retrieved. Do not answer the user. "
            "Do not infer legal relationships from content."
        )

    def _agent_user_content(self, state: ChatAgentState, phase: str) -> str:
        payload = {
            "phase": phase,
            "question": state["question"],
            "normalized_query": state.get("normalized_query"),
            "filters": state.get("filters", {}),
            "memory": compact_conversation_context(state.get("conversation_context", {})),
            "citations": state.get("citations", []),
        }
        return json.dumps(payload, ensure_ascii=False)

    def _agent_status_lookup(
        self,
        state: ChatAgentState,
        query: Any = "",
        document_number: Any = "",
        limit: Any = 0,
    ) -> str:
        started = time.perf_counter()
        filters = filters_with_access_scope(state)
        if optional_text(document_number):
            filters["document_number"] = str(document_number).strip()
        lookup_query = optional_text(query) or state.get("normalized_query") or state["question"]
        lookup_limit = max(1, min(state["top_k"], int_safe(limit, state["top_k"])))
        try:
            records = self.status_repository.find_status_records(
                lookup_query,
                filters,
                lookup_limit,
            )
            state["status_records"] = records
            result = {"records": compact_status_records(records), "count": len(records)}
            self._record_tool_trace(
                state,
                "status_lookup",
                "retrieval",
                summarize_tool_input({"query": lookup_query, "filters": filters}),
                len(records),
                started,
                "ok",
                [],
            )
            return json.dumps(result, ensure_ascii=False)
        except Exception as exc:
            return self._record_tool_error(state, "status_lookup", "retrieval", started, exc)

    def _agent_vector_search(self, state: ChatAgentState, query: Any = "", top_k: Any = 0) -> str:
        started = time.perf_counter()
        lookup_query = optional_text(query) or state.get("normalized_query") or state["question"]
        lookup_top_k = max(1, min(state["top_k"], int_safe(top_k, state["top_k"])))
        try:
            hits = self.vector_retriever.search(
                lookup_query,
                lookup_top_k,
                filters_with_access_scope(state),
                should_include_expired(state),
            )
            hits = filter_hits_for_access(hits, access_scope_from_state(state))
            state["vector_hits"] = hits
            result = {"hits": serialize_hits(hits), "count": len(hits)}
            self._record_tool_trace(
                state,
                "vector_search",
                "retrieval",
                summarize_tool_input({"query": lookup_query, "top_k": lookup_top_k}),
                len(hits),
                started,
                "ok",
                [],
            )
            return json.dumps(result, ensure_ascii=False)
        except RetrieverUnavailable as exc:
            return self._record_tool_error(state, "vector_search", "retrieval", started, exc)

    def _agent_bm25_search(self, state: ChatAgentState, query: Any = "", top_k: Any = 0) -> str:
        started = time.perf_counter()
        lookup_query = optional_text(query) or state.get("normalized_query") or state["question"]
        lookup_top_k = max(1, min(state["top_k"], int_safe(top_k, state["top_k"])))
        try:
            hits = self.bm25_retriever.search(
                lookup_query,
                lookup_top_k,
                filters_with_access_scope(state),
                should_include_expired(state),
            )
            hits = filter_hits_for_access(hits, access_scope_from_state(state))
            state["bm25_hits"] = hits
            result = {"hits": serialize_hits(hits), "count": len(hits)}
            self._record_tool_trace(
                state,
                "bm25_search",
                "retrieval",
                summarize_tool_input({"query": lookup_query, "top_k": lookup_top_k}),
                len(hits),
                started,
                "ok",
                [],
            )
            return json.dumps(result, ensure_ascii=False)
        except RetrieverUnavailable as exc:
            return self._record_tool_error(state, "bm25_search", "retrieval", started, exc)

    def _agent_graph_context(self, state: ChatAgentState, focus: Any = "") -> str:
        started = time.perf_counter()
        hits = state.get("fused_hits") or fuse_hits(
            [state.get("vector_hits", []), state.get("bm25_hits", [])],
            state["top_k"],
        )
        graph_context = graph_enrich_with_scope(
            self.graph_retriever,
            hits,
            state["top_k"],
            access_scope_from_state(state),
        )
        state["graph_context"] = graph_context
        result_count = len(graph_context.get("related_documents") or [])
        self._record_tool_trace(
            state,
            "graph_context",
            "expansion",
            summarize_tool_input({"focus": focus, "hit_count": len(hits)}),
            result_count,
            started,
            "ok",
            [],
        )
        return json.dumps(json_safe(graph_context), ensure_ascii=False)

    def _agent_chunk_detail(self, state: ChatAgentState, chunk_id: Any) -> str:
        started = time.perf_counter()
        requested = optional_text(chunk_id)
        hits = state.get("fused_hits", [])
        hit = next((item for item in hits if item.chunk_id == requested), None)
        if hit is None:
            result = {"error": "chunk_id_not_found", "chunk_id": requested}
            self._record_tool_trace(
                state,
                "get_chunk_detail",
                "expansion",
                summarize_tool_input({"chunk_id": requested}),
                0,
                started,
                "warning",
                ["chunk_id_not_found"],
            )
            return json.dumps(result, ensure_ascii=False)
        expanded = set(state.get("expanded_chunk_ids", []))
        if hit.chunk_id:
            expanded.add(hit.chunk_id)
            state["expanded_chunk_ids"] = sorted(expanded)
        result = {
            **hit.citation(),
            "content": trim_words(hit.content, 700),
        }
        self._record_tool_trace(
            state,
            "get_chunk_detail",
            "expansion",
            summarize_tool_input({"chunk_id": requested}),
            1,
            started,
            "ok",
            [],
        )
        return json.dumps(result, ensure_ascii=False)

    def _record_tool_error(
        self,
        state: ChatAgentState,
        tool_name: str,
        phase: str,
        started: float,
        exc: Exception,
    ) -> str:
        code = WARNING_RETRIEVER_UNAVAILABLE
        state["warnings"] = append_warning(
            state.get("warnings", []),
            code,
            f"{tool_name} unavailable: {exc}",
        )
        self._record_tool_trace(
            state,
            tool_name,
            phase,
            "",
            0,
            started,
            "error",
            [type(exc).__name__],
        )
        return json.dumps(
            {"error": type(exc).__name__, "message": str(exc)},
            ensure_ascii=False,
        )

    def _record_tool_trace(
        self,
        state: ChatAgentState,
        tool_name: str,
        phase: str,
        input_summary: str,
        result_count: int,
        started: float,
        status: str,
        warnings: list[str],
    ) -> None:
        trace = {
            "tool": tool_name,
            "phase": phase,
            "input_summary": input_summary,
            "result_count": int(result_count),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "status": status,
            "warnings": warnings,
        }
        state["tool_trace"] = [*state.get("tool_trace", []), trace]

    def _partial_timeout_state(self, state: ChatAgentState) -> ChatAgentState:
        state["warnings"] = append_warning(
            state.get("warnings", []),
            WARNING_AGENT_TIMEOUT_PARTIAL,
            "Agent reached the time budget; returning a partial answer from validated evidence.",
        )
        state["answer"] = build_extractive_answer(state)
        state["confidence"] = float(state.get("confidence") or 0.0)
        state["agent_steps"] = append_agent_step(
            state.get("agent_steps", []),
            "timeout",
            "Returned partial answer because the agent time budget was reached.",
            "warning",
        )
        return state

    def _timed_out(self, deadline: float) -> bool:
        return time.perf_counter() >= deadline

    def _raise_if_timed_out(self, deadline: float) -> None:
        if self._timed_out(deadline):
            raise AgentTimeout("chat agent time budget exceeded")

    def _contextualize_query(self, state: ChatAgentState) -> ChatAgentState:
        if state.get("contextualized_query"):
            return {}
        current_query = state.get("normalized_query") or state["question"]
        context = state.get("conversation_context", {})
        memory_used = dict(state.get("memory_used", build_memory_used(context)))
        if not has_conversation_memory(context):
            memory_used["contextualized_query_used"] = False
            return {
                "normalized_query": current_query,
                "contextualized_query": current_query,
                "memory_used": memory_used,
            }
        try:
            result = self.llm.contextualize_query(current_query, context)
        except Exception as exc:
            logger.warning(
                "Query contextualization failed trace_id=%s error=%s",
                state.get("trace_id"),
                type(exc).__name__,
            )
            result = None
        if not isinstance(result, dict) or not optional_text(result.get("standalone_query")):
            memory_used["contextualized_query_used"] = False
            warnings = append_warning(
                state.get("warnings", []),
                WARNING_QUERY_CONTEXTUALIZATION,
                "Conversation memory could not be applied to the current query; using the original query.",
            )
            return {
                "normalized_query": current_query,
                "contextualized_query": current_query,
                "memory_used": memory_used,
                "warnings": warnings,
                "agent_steps": append_agent_step(
                    state.get("agent_steps", []),
                    "contextualize_query",
                    "Conversation memory was unavailable for query contextualization.",
                    "warning",
                ),
            }
        standalone_query = optional_text(result.get("standalone_query")) or current_query
        used_memory = bool(result.get("used_memory")) or standalone_query != current_query
        memory_used["contextualized_query_used"] = used_memory
        reason = optional_text(result.get("reason"))
        message = (
            "Rewrote the current query using conversation memory."
            if used_memory
            else "Current query was already standalone; conversation memory was not applied."
        )
        if reason:
            message = f"{message} Reason: {trim_words(reason, 18)}"
        return {
            "normalized_query": standalone_query,
            "contextualized_query": standalone_query,
            "memory_used": memory_used,
            "agent_steps": append_agent_step(
                state.get("agent_steps", []),
                "contextualize_query",
                message,
                "ok",
            ),
        }

    def _route_intent(self, state: ChatAgentState) -> ChatAgentState:
        question = state.get("normalized_query") or state["question"]
        route = self.llm.classify(question)
        mode = route.get("mode") if route.get("mode") in {
            MODE_LEGAL_LOOKUP,
            MODE_STATUS_BASIC,
            MODE_OUT_OF_SCOPE,
        } else classify_question_heuristically(question)["mode"]
        filters = extract_filters(route.get("normalized_query") or question)
        return {
            "mode": mode,
            "normalized_query": optional_text(route.get("normalized_query")) or question,
            "explicit_expired": bool(route.get("explicit_expired")),
            "filters": filters,
        }

    def _resolve_exact_status(self, state: ChatAgentState) -> ChatAgentState:
        mode = state.get("mode", MODE_LEGAL_LOOKUP)
        if mode == MODE_OUT_OF_SCOPE:
            return {"status_records": []}
        records: list[dict[str, Any]] = []
        if mode == MODE_STATUS_BASIC:
            records = self.status_repository.find_status_records(
                state.get("normalized_query") or state["question"],
                filters_with_access_scope(state),
                state["top_k"],
            )
        return {"status_records": records}

    def _decide_status_sufficiency(self, state: ChatAgentState) -> ChatAgentState:
        records = state.get("status_records", [])
        sufficient = state.get("mode") == MODE_STATUS_BASIC and any(
            not is_unknown_status(record.get("validity_status"))
            or bool(record.get("relations"))
            for record in records
        )
        return {"status_sufficient": sufficient}

    def _vector_retrieve(self, state: ChatAgentState) -> ChatAgentState:
        if state.get("mode") == MODE_OUT_OF_SCOPE:
            return {"vector_hits": []}
        include_expired = should_include_expired(state)
        try:
            hits = self.vector_retriever.search(
                state.get("normalized_query") or state["question"],
                state["top_k"],
                filters_with_access_scope(state),
                include_expired,
            )
            hits = filter_hits_for_access(hits, access_scope_from_state(state))
            return {"vector_hits": hits}
        except RetrieverUnavailable as exc:
            return {
                "vector_hits": [],
                "warnings": append_warning(
                    state.get("warnings", []),
                    WARNING_RETRIEVER_UNAVAILABLE,
                    f"Vector retrieval unavailable: {exc}",
                ),
            }

    def _bm25_retrieve(self, state: ChatAgentState) -> ChatAgentState:
        if state.get("mode") == MODE_OUT_OF_SCOPE:
            return {"bm25_hits": []}
        include_expired = should_include_expired(state)
        try:
            hits = self.bm25_retriever.search(
                state.get("normalized_query") or state["question"],
                state["top_k"],
                filters_with_access_scope(state),
                include_expired,
            )
            hits = filter_hits_for_access(hits, access_scope_from_state(state))
            return {"bm25_hits": hits}
        except RetrieverUnavailable as exc:
            return {
                "bm25_hits": [],
                "warnings": append_warning(
                    state.get("warnings", []),
                    WARNING_RETRIEVER_UNAVAILABLE,
                    f"BM25 retrieval unavailable: {exc}",
                ),
            }

    def _graph_enrich(self, state: ChatAgentState) -> ChatAgentState:
        if state.get("mode") in {MODE_OUT_OF_SCOPE, MODE_INSUFFICIENT_EVIDENCE}:
            return {"graph_context": {}}
        hits = [*state.get("vector_hits", []), *state.get("bm25_hits", [])]
        if state.get("fused_hits") is not None:
            hits = state.get("fused_hits", [])
        graph_context = graph_enrich_with_scope(
            self.graph_retriever,
            hits,
            state["top_k"],
            access_scope_from_state(state),
        )
        return {"graph_context": graph_context}

    def _fuse_and_rerank(self, state: ChatAgentState) -> ChatAgentState:
        fused = fuse_hits(
            [state.get("vector_hits", []), state.get("bm25_hits", [])],
            top_k=state["top_k"],
        )
        warnings = state.get("warnings", [])
        if any(is_unknown_status(hit.validity_status) for hit in fused):
            warnings = append_warning(
                warnings,
                WARNING_UNKNOWN_VALIDITY,
                "Some retrieved documents have unknown validity status.",
            )
        citations = unique_citations([hit.citation() for hit in fused])
        status_records = state.get("status_records", [])
        for record in status_records:
            citations.append(citation_from_status_record(record))
        citations = unique_citations(citations)
        return {
            "fused_hits": fused,
            "citations": citations,
            "warnings": warnings,
        }

    def _filter_citations_by_relevance(self, state: ChatAgentState) -> ChatAgentState:
        if state.get("mode") == MODE_OUT_OF_SCOPE:
            return {"citations": []}
        started = time.perf_counter()
        hits = state.get("fused_hits", [])
        status_records = state.get("status_records", [])
        candidates = build_citation_relevance_candidates(hits, status_records)
        candidate_count = len(candidates)
        if not candidates:
            return self._citation_filter_result(
                state,
                started,
                candidates=[],
                relevant_keys=set(),
                status="warning",
                trace_warnings=["no_candidates"],
            )
        try:
            result = self.llm.filter_relevant_citations(
                state.get("normalized_query") or state["question"],
                state.get("mode", MODE_LEGAL_LOOKUP),
                candidates,
            )
        except Exception as exc:
            logger.warning(
                "Citation relevance gate failed trace_id=%s error=%s",
                state.get("trace_id"),
                type(exc).__name__,
            )
            result = None
        if not isinstance(result, dict) or not isinstance(result.get("relevant_keys"), list):
            warnings = append_warning(
                state.get("warnings", []),
                WARNING_CITATION_RELEVANCE_FILTER,
                "Citation relevance gate was unavailable; no citations were exposed.",
            )
            return self._citation_filter_result(
                {**state, "warnings": warnings},
                started,
                candidates=candidates,
                relevant_keys=set(),
                status="error",
                trace_warnings=["gate_unavailable"],
            )
        relevant_keys = {
            str(key)
            for key in result.get("relevant_keys", [])
            if str(key) in {candidate["key"] for candidate in candidates}
        }
        trace_warnings = [
            str(item)
            for item in result.get("warnings", [])
            if isinstance(item, (str, int))
        ]
        filter_status = "ok" if relevant_keys else "warning"
        if not relevant_keys:
            trace_warnings = [*trace_warnings, "no_high_relevance_citation"]
        return self._citation_filter_result(
            state,
            started,
            candidates=candidates,
            relevant_keys=relevant_keys,
            status=filter_status,
            trace_warnings=trace_warnings,
            candidate_count=candidate_count,
        )

    def _citation_filter_result(
        self,
        state: ChatAgentState,
        started: float,
        *,
        candidates: list[dict[str, Any]],
        relevant_keys: set[str],
        status: str,
        trace_warnings: list[str],
        candidate_count: int | None = None,
    ) -> ChatAgentState:
        candidate_count = len(candidates) if candidate_count is None else candidate_count
        filtered_hits = []
        for hit in state.get("fused_hits", []):
            index = candidate_index_by_kind(candidates, "hit", hit)
            if hit_candidate_key(hit, index) in relevant_keys:
                filtered_hits.append(hit)
        filtered_status_records = []
        for record in state.get("status_records", []):
            index = candidate_index_by_kind(candidates, "status_record", record)
            if status_candidate_key(record, index) in relevant_keys:
                filtered_status_records.append(record)
        citations = unique_citations(
            [hit.citation() for hit in filtered_hits]
            + [citation_from_status_record(record) for record in filtered_status_records]
        )
        warnings = state.get("warnings", [])
        mode = state.get("mode", MODE_LEGAL_LOOKUP)
        if candidate_count and not citations:
            warnings = append_warning(
                warnings,
                WARNING_LOW_RELEVANCE,
                "No retrieved citation was judged highly relevant to the question.",
            )
            mode = MODE_INSUFFICIENT_EVIDENCE
        agent_steps = append_agent_step(
            state.get("agent_steps", []),
            "citation_relevance_filter",
            f"Kept {len(citations)} of {candidate_count} candidate citations after relevance checking.",
            status if status in {"ok", "warning", "error"} else "warning",
        )
        trace = {
            "tool": "citation_relevance_filter",
            "phase": "evidence",
            "input_summary": summarize_tool_input({"candidate_count": candidate_count}),
            "result_count": len(citations),
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "status": status,
            "warnings": trace_warnings,
        }
        return {
            "mode": mode,
            "fused_hits": filtered_hits,
            "status_records": filtered_status_records,
            "citations": citations,
            "warnings": warnings,
            "agent_steps": agent_steps,
            "tool_trace": [*state.get("tool_trace", []), trace],
            "status_sufficient": bool(filtered_status_records) and bool(
                state.get("status_sufficient")
            ),
            "citation_filter": {
                "candidate_count": candidate_count,
                "kept_count": len(citations),
                "relevant_keys": sorted(relevant_keys),
            },
        }

    def _evidence_check(self, state: ChatAgentState) -> ChatAgentState:
        hits = state.get("fused_hits", [])
        status_records = state.get("status_records", [])
        warnings = state.get("warnings", [])
        citations = state.get("citations", [])
        if state.get("mode") == MODE_OUT_OF_SCOPE:
            return {
                "confidence": 0.0,
                "warnings": warnings,
                "llm_check": {},
            }
        if not citations:
            warnings = append_warning(
                warnings,
                WARNING_NO_CITATION,
                "No valid citation was found in the current knowledge base.",
            )
            return {
                "mode": MODE_INSUFFICIENT_EVIDENCE,
                "confidence": 0.0,
                "warnings": warnings,
                "llm_check": {},
            }
        llm_check = self.llm.check_evidence(
            state.get("normalized_query") or state["question"],
            state.get("mode", MODE_LEGAL_LOOKUP),
            hits,
            status_records,
        )
        if not llm_check:
            warnings = append_warning(
                warnings,
                WARNING_LLM_UNAVAILABLE,
                "LLM evidence check was unavailable; confidence uses retrieval signals only.",
            )
        if llm_check and not bool(llm_check.get("relevant", True)):
            warnings = append_warning(
                warnings,
                WARNING_LOW_RELEVANCE,
                "The retrieved evidence may not fully answer the question.",
            )
        confidence = compute_confidence(
            hits,
            citations,
            state.get("graph_context", {}),
            safe_float(llm_check.get("confidence_delta") if llm_check else 0.0, 0.0),
        )
        if any(is_unknown_status(citation.get("validity_status")) for citation in citations):
            warnings = append_warning(
                warnings,
                WARNING_UNKNOWN_VALIDITY,
                "At least one citation has unknown validity status.",
            )
        if state.get("mode") == MODE_STATUS_BASIC and any(
            is_unknown_status(record.get("validity_status")) for record in status_records
        ):
            warnings = append_warning(
                warnings,
                WARNING_STATUS_INCOMPLETE,
                "The system cannot fully confirm status because validity metadata is incomplete.",
            )
        return {
            "confidence": confidence,
            "warnings": warnings,
            "llm_check": llm_check,
        }

    def _generate_output(self, state: ChatAgentState) -> ChatAgentState:
        mode = state.get("mode", MODE_LEGAL_LOOKUP)
        if mode == MODE_OUT_OF_SCOPE:
            return {
                "answer": (
                    "V1 hien chi ho tro tra cuu phap luat va kiem tra hieu luc co ban "
                    "dua tren kho du lieu da publish. Chuc nang soan thao hoac ra soat "
                    "hop dong chua nam trong pham vi chat service nay."
                ),
                "confidence": 0.0,
            }
        if mode == MODE_INSUFFICIENT_EVIDENCE:
            return {
                "answer": (
                    "Khong du can cu trong kho du lieu hien tai de tra loi cau hoi nay. "
                    "Vui long kiem tra lai van ban da publish hoac bo sung citation/metadata."
                ),
                "confidence": 0.0,
            }
        answer = self.llm.generate_answer(
            state.get("normalized_query") or state["question"],
            mode,
            state.get("fused_hits", []),
            state.get("status_records", []),
            state.get("graph_context", {}),
            state.get("warnings", []),
            state.get("conversation_context", {}),
            state.get("expanded_chunk_ids", []),
        )
        if not answer:
            answer = build_extractive_answer(state)
        return {"answer": answer}


def resolve_top_k(raw_top_k: Any, user_role: str) -> int:
    default = 3 if user_role == ROLE_GUEST else 8
    maximum = 20 if user_role == ROLE_ADMIN else 12
    if user_role == ROLE_GUEST:
        maximum = 3
    try:
        value = int(raw_top_k) if raw_top_k is not None else default
    except (TypeError, ValueError):
        value = default
    return max(1, min(maximum, value))


def access_scope_for_user(user: dict[str, Any] | None) -> AccessScope:
    if user and user.get("role") == ROLE_ADMIN:
        return AccessScope(unrestricted=True, field_ids=())
    allowed = [0]
    if user:
        allowed.extend(user.get("allowed_field_ids") or [])
    field_ids = sorted(
        {
            normalize_field_id(field_id, default=0)
            for field_id in allowed
            if normalize_field_id(field_id, default=0) >= 0
        }
    )
    return AccessScope(unrestricted=False, field_ids=tuple(field_ids or [0]))


def access_scope_from_state(state: ChatAgentState) -> AccessScope:
    scope = state.get("access_scope")
    return scope if isinstance(scope, AccessScope) else AccessScope()


def filters_with_access_scope(state: ChatAgentState) -> dict[str, Any]:
    return {**state.get("filters", {}), "_access_scope": access_scope_from_state(state)}


def access_scope_from_filters(filters: dict[str, Any]) -> AccessScope:
    scope = filters.get("_access_scope") if isinstance(filters, dict) else None
    return scope if isinstance(scope, AccessScope) else AccessScope()


def field_scope_sql(
    access_scope: AccessScope,
    *,
    table_alias: str = "",
    allow_unresolved: bool = False,
) -> str:
    if access_scope.unrestricted:
        return ""
    prefix = f"{table_alias}." if table_alias else ""
    placeholders = ", ".join("?" for _ in access_scope.field_ids)
    field_expr = f"COALESCE({prefix}field_id, 0)"
    if allow_unresolved:
        resolved_expr = f"{prefix}document_id IS NULL" if table_alias else "document_id IS NULL"
        return f"AND ({resolved_expr} OR {field_expr} IN ({placeholders}))"
    return f"AND {field_expr} IN ({placeholders})"


def field_scope_params(access_scope: AccessScope) -> tuple[int, ...]:
    return () if access_scope.unrestricted else tuple(access_scope.field_ids)


def graph_enrich_with_scope(
    graph_retriever: Any,
    hits: list[RetrievalHit],
    top_k: int,
    access_scope: AccessScope,
) -> dict[str, Any]:
    try:
        return graph_retriever.enrich(hits, top_k, access_scope=access_scope)
    except TypeError:
        return graph_retriever.enrich(hits, top_k)


def filter_hits_for_access(
    hits: list[RetrievalHit],
    access_scope: AccessScope,
) -> list[RetrievalHit]:
    return [hit for hit in hits if access_scope.allows(hit.field_id)]


def classify_question_heuristically(question: str) -> dict[str, Any]:
    normalized = normalize_query_text(question)
    if any(term in normalized for term in OUT_OF_SCOPE_TERMS):
        mode = MODE_OUT_OF_SCOPE
    elif any(term in normalized for term in STATUS_TERMS):
        mode = MODE_STATUS_BASIC
    else:
        mode = MODE_LEGAL_LOOKUP
    return {
        "mode": mode,
        "normalized_query": question,
        "explicit_expired": any(term in normalized for term in ("het hieu luc", "expired", "thay the", "bai bo")),
    }


def extract_filters(query: str) -> dict[str, str]:
    filters: dict[str, str] = {}
    article = re.search(r"\b(?:dieu|article)\s+([0-9]+[a-zA-Z]?)\b", normalize_query_text(query))
    if article:
        filters["article_number"] = article.group(1)
    doc_number = re.search(
        r"\b([0-9]{1,4}/[0-9]{4}/[A-Z0-9.-]+)\b",
        query.upper(),
    )
    if doc_number:
        filters["document_number"] = doc_number.group(1)
    return filters


def should_include_expired(state: ChatAgentState) -> bool:
    return state.get("mode") == MODE_STATUS_BASIC or bool(state.get("explicit_expired"))


def hit_allowed(
    hit: RetrievalHit,
    filters: dict[str, str],
    include_expired: bool,
) -> bool:
    if not access_scope_from_filters(filters).allows(hit.field_id):
        return False
    if filters.get("document_number") and hit.document_number != filters["document_number"]:
        return False
    if filters.get("article_number") and hit.article_number != filters["article_number"]:
        return False
    status = normalize_validity_status(hit.validity_status)
    if include_expired:
        return True
    return status is None or is_active_status(status) or is_unknown_status(status)


def fuse_hits(hit_lists: list[list[RetrievalHit]], top_k: int, rrf_k: int = 60) -> list[RetrievalHit]:
    merged: dict[str, RetrievalHit] = {}
    scores: dict[str, float] = {}
    for hits in hit_lists:
        for rank, hit in enumerate(hits, start=1):
            key = hit.key
            scores[key] = scores.get(key, 0.0) + (1.0 / (rrf_k + rank))
            if key not in merged:
                merged[key] = hit
            else:
                existing = merged[key]
                existing.sources.update(hit.sources or {hit.source})
                if len(hit.content) > len(existing.content):
                    existing.content = hit.content
                existing.score = max(existing.score, hit.score)
    for key, hit in merged.items():
        hit.score = scores[key]
        hit.source = "+".join(sorted(hit.sources)) if hit.sources else hit.source
    return sorted(merged.values(), key=lambda item: item.score, reverse=True)[:top_k]


def compute_confidence(
    hits: list[RetrievalHit],
    citations: list[dict[str, Any]],
    graph_context: dict[str, Any],
    llm_delta: float,
) -> float:
    if not citations:
        return 0.0
    dense_score = 1.0 if any("vector" in hit.sources for hit in hits) else (0.3 if hits else 0.0)
    bm25_score = 1.0 if any("bm25" in hit.sources for hit in hits) else (0.3 if hits else 0.0)
    graph_score = safe_float(graph_context.get("support_score"), 0.0)
    citation_score = 1.0 if any(c.get("article_number") for c in citations) else 0.5
    statuses = [normalize_validity_status(c.get("validity_status")) for c in citations]
    if statuses and all(is_active_status(status) for status in statuses):
        validity_score = 1.0
    elif any(is_unknown_status(status) or status is None for status in statuses):
        validity_score = 0.5
    else:
        validity_score = 0.2
    confidence = (
        0.35 * dense_score
        + 0.25 * bm25_score
        + 0.20 * graph_score
        + 0.10 * citation_score
        + 0.10 * validity_score
        + llm_delta
    )
    return max(0.0, min(1.0, confidence))


def build_extractive_answer(state: ChatAgentState) -> str:
    warnings = state.get("warnings", [])
    warning_text = ""
    if warnings:
        warning_text = " Luu y: " + " ".join(item["message"] for item in warnings[:2])
    if state.get("mode") == MODE_STATUS_BASIC and state.get("status_records"):
        lines = ["Theo metadata hien co trong kho du lieu:"]
        for record in state["status_records"][:3]:
            label = record.get("document_number") or record.get("title") or record.get("document_id")
            status = record.get("validity_status") or VALIDITY_UNKNOWN
            lines.append(f"- {label}: validity_status={status}.")
            relations = record.get("relations") or []
            if relations:
                relation_text = "; ".join(
                    f"{item.get('relation_type')} -> {item.get('target_document_number') or item.get('target_document_id')}"
                    for item in relations[:3]
                )
                lines.append(f"  Quan he da nhap: {relation_text}.")
            elif is_unknown_status(status):
                lines.append("  Chua co du lieu quan he/hieu luc de ket luan chac chan.")
        return "\n".join(lines) + warning_text
    hits = state.get("fused_hits", [])
    if not hits:
        return (
            "Khong du can cu trong kho du lieu hien tai de tra loi cau hoi nay."
            + warning_text
        )
    lines = ["Dua tren cac can cu tim thay trong kho du lieu:"]
    for hit in hits[:3]:
        label = hit.citation_label or hit.document_number or hit.document_title or "Can cu"
        lines.append(f"- {label}: {trim_words(hit.content, 70)}")
    return "\n".join(lines) + warning_text


def insufficient_evidence_response(
    query: str,
    trace_id: str,
    warnings: list[dict[str, str]],
    *,
    agent_steps: list[dict[str, Any]] | None = None,
    tool_trace: list[dict[str, Any]] | None = None,
    memory_used: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = (
        "Khong du can cu trong kho du lieu hien tai de tra loi cau hoi nay. "
        "Vui long kiem tra lai van ban da publish hoac bo sung citation/metadata."
    )
    return {
        "answer": answer,
        "response": answer,
        "query": query,
        "retrieval_mode": MODE_INSUFFICIENT_EVIDENCE,
        "confidence": 0.0,
        "warnings": warnings,
        "citations": [],
        "trace_id": trace_id,
        "agent_steps": agent_steps or [],
        "tool_trace": tool_trace or [],
        "memory_used": memory_used
        or {
            "recent_message_count": 0,
            "summary_used": False,
            "contextualized_query_used": False,
        },
        "agent_timeline": heuristic_agent_timeline(
            agent_steps or [],
            tool_trace or [],
            memory_used
            or {
                "recent_message_count": 0,
                "summary_used": False,
                "contextualized_query_used": False,
            },
            warnings,
            MODE_INSUFFICIENT_EVIDENCE,
        ),
    }


def citation_from_status_record(record: dict[str, Any]) -> dict[str, Any]:
    status = normalize_validity_status(record.get("validity_status"))
    title = record.get("title") or ""
    return {
        "citation_label": record.get("document_number") or title,
        "document_id": record.get("document_id") or "",
        "document_title": title,
        "document_name": title,
        "document_number": record.get("document_number") or "",
        "article_number": None,
        "clause_number": None,
        "article": None,
        "validity_status": status,
        "field_id": normalize_field_id(record.get("field_id"), default=0),
        "is_active": is_active_status(status),
        "chunk_id": None,
    }


def unique_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for citation in citations:
        key = "|".join(
            str(citation.get(field) or "")
            for field in ("chunk_id", "document_id", "document_number", "article_number", "clause_number")
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
    return unique


def build_citation_relevance_candidates(
    hits: list[RetrievalHit],
    status_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, hit in enumerate(hits):
        candidates.append(
            {
                "key": hit_candidate_key(hit, index),
                "kind": "hit",
                "source_index": index,
                "match_key": hit_relevance_match_key(hit),
                "citation": hit.citation(),
                "source": hit.source,
                "sources": sorted(hit.sources),
                "content": trim_words(hit.content, 180),
            }
        )
    for index, record in enumerate(status_records):
        compact = compact_status_records([record])
        candidates.append(
            {
                "key": status_candidate_key(record, index),
                "kind": "status_record",
                "source_index": index,
                "match_key": status_record_relevance_match_key(record),
                "citation": citation_from_status_record(record),
                "status_record": compact[0] if compact else {},
            }
        )
    return candidates


def hit_candidate_key(hit: RetrievalHit, index: int) -> str:
    label = (
        optional_text(hit.chunk_id)
        or optional_text(hit.document_id)
        or optional_text(hit.document_number)
        or f"rank-{index}"
    )
    if hit.article_number:
        label = f"{label}:article-{hit.article_number}"
    if hit.clause_number:
        label = f"{label}:clause-{hit.clause_number}"
    return f"hit:{index}:{label}"


def status_candidate_key(record: dict[str, Any], index: int) -> str:
    label = (
        optional_text(record.get("document_id"))
        or optional_text(record.get("document_number"))
        or optional_text(record.get("title"))
        or f"rank-{index}"
    )
    return f"status:{index}:{label}"


def candidate_index_by_kind(
    candidates: list[dict[str, Any]],
    kind: str,
    item: RetrievalHit | dict[str, Any],
) -> int:
    match_key = (
        hit_relevance_match_key(item)
        if isinstance(item, RetrievalHit)
        else status_record_relevance_match_key(item)
    )
    for candidate in candidates:
        if candidate.get("kind") == kind and candidate.get("match_key") == match_key:
            return int_safe(candidate.get("source_index"), -1)
    return -1


def hit_relevance_match_key(hit: RetrievalHit) -> str:
    parts = [
        hit.chunk_id,
        hit.document_id,
        hit.document_number,
        hit.article_number,
        hit.clause_number,
        hit.citation_label,
    ]
    key = "|".join(str(part or "") for part in parts).strip("|")
    return key or trim_words(hit.content, 24)


def status_record_relevance_match_key(record: dict[str, Any]) -> str:
    parts = [
        record.get("document_id"),
        record.get("document_number"),
        record.get("title"),
        record.get("validity_status"),
    ]
    return "|".join(str(part or "") for part in parts).strip("|")


def compact_status_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": record.get("document_id"),
            "document_number": record.get("document_number"),
            "title": record.get("title"),
            "validity_status": record.get("validity_status"),
            "field_id": normalize_field_id(record.get("field_id"), default=0),
            "effective_date": record.get("effective_date"),
            "expiry_date": record.get("expiry_date"),
            "relations": record.get("relations") or [],
        }
        for record in records[:8]
    ]


def compact_conversation_context(context: dict[str, Any]) -> dict[str, Any]:
    recent = context.get("recent_messages") if isinstance(context, dict) else []
    if not isinstance(recent, list):
        recent = []
    return {
        "summary": trim_words(str(context.get("summary") or ""), 160)
        if isinstance(context, dict)
        else "",
        "recent_messages": [
            {
                "role": str(item.get("role") or ""),
                "content": trim_words(str(item.get("content") or ""), 120),
            }
            for item in recent[:5]
            if isinstance(item, dict)
        ],
    }


def has_conversation_memory(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    recent = context.get("recent_messages")
    return bool(context.get("summary")) or bool(recent if isinstance(recent, list) else [])


def build_memory_used(context: dict[str, Any]) -> dict[str, Any]:
    recent = context.get("recent_messages") if isinstance(context, dict) else []
    return {
        "recent_message_count": len(recent) if isinstance(recent, list) else 0,
        "summary_used": bool(context.get("summary")) if isinstance(context, dict) else False,
        "contextualized_query_used": False,
    }


def build_agent_timeline(
    llm: Any,
    *,
    agent_steps: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
    memory_used: dict[str, Any],
    warnings: list[dict[str, str]],
    retrieval_mode: str,
) -> list[dict[str, str]]:
    fallback = heuristic_agent_timeline(
        agent_steps,
        tool_trace,
        memory_used,
        warnings,
        retrieval_mode,
    )
    summarize = getattr(llm, "summarize_agent_timeline", None)
    if not callable(summarize):
        return fallback
    payload = {
        "retrieval_mode": retrieval_mode,
        "memory_used": memory_used,
        "warnings": [
            {"code": item.get("code"), "message": trim_words(item.get("message", ""), 24)}
            for item in warnings[:5]
        ],
        "agent_steps": [
            {
                "phase": item.get("phase"),
                "status": item.get("status"),
                "message": trim_words(str(item.get("message") or ""), 24),
            }
            for item in agent_steps[:8]
        ],
        "tool_trace": [
            {
                "tool": item.get("tool"),
                "phase": item.get("phase"),
                "status": item.get("status"),
                "result_count": item.get("result_count"),
                "duration_ms": item.get("duration_ms"),
                "warning_count": len(item.get("warnings") or []),
            }
            for item in tool_trace[:8]
        ],
    }
    try:
        timeline = sanitize_agent_timeline(summarize(payload))
    except Exception:
        return fallback
    return timeline or fallback


def heuristic_agent_timeline(
    agent_steps: list[dict[str, Any]],
    tool_trace: list[dict[str, Any]],
    memory_used: dict[str, Any],
    warnings: list[dict[str, str]],
    retrieval_mode: str,
) -> list[dict[str, str]]:
    has_errors = any(item.get("status") == "error" for item in tool_trace)
    has_warnings = bool(warnings) or any(
        item.get("status") == "warning" for item in [*agent_steps, *tool_trace]
    )
    retrieval_count = sum(
        int(item.get("result_count") or 0)
        for item in tool_trace
        if item.get("phase") == "retrieval"
    )
    expansion_count = sum(
        int(item.get("result_count") or 0)
        for item in tool_trace
        if item.get("phase") == "expansion"
    )
    context_text = "Không dùng lịch sử hội thoại trước đó."
    if memory_used.get("recent_message_count") or memory_used.get("summary_used"):
        context_text = "Có dùng ngữ cảnh hội thoại gần đây để hiểu câu hỏi."
    evidence_status = (
        "warning" if retrieval_mode == MODE_INSUFFICIENT_EVIDENCE or has_warnings else "ok"
    )
    retrieval_status = "error" if has_errors else ("warning" if retrieval_count == 0 else "ok")
    return [
        {
            "title": "Hiểu câu hỏi",
            "description": context_text,
            "status": "ok",
        },
        {
            "title": "Tìm văn bản liên quan",
            "description": f"Đã kiểm tra các nguồn tìm kiếm và thấy {retrieval_count} kết quả phù hợp.",
            "status": retrieval_status,
        },
        {
            "title": "Mở rộng ngữ cảnh",
            "description": (
                f"Đã bổ sung {expansion_count} mẩu ngữ cảnh từ quan hệ hoặc chi tiết văn bản."
                if expansion_count
                else "Không có thêm quan hệ hoặc chi tiết bổ sung đáng tin cậy."
            ),
            "status": "ok" if expansion_count else "warning",
        },
        {
            "title": "Kiểm tra căn cứ",
            "description": "Đã đánh giá mức độ đủ căn cứ trước khi soạn câu trả lời.",
            "status": evidence_status,
        },
        {
            "title": "Soạn câu trả lời",
            "description": "Câu trả lời được tạo từ phần căn cứ đã tìm thấy và các cảnh báo liên quan.",
            "status": evidence_status,
        },
    ]


def sanitize_agent_timeline(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    timeline = []
    allowed_statuses = {"ok", "warning", "error", "running"}
    for item in value[:5]:
        if not isinstance(item, dict):
            continue
        title = optional_text(item.get("title"))
        description = optional_text(item.get("description"))
        if not title or not description:
            continue
        status = optional_text(item.get("status")) or "ok"
        if status not in allowed_statuses:
            status = "ok"
        timeline.append(
            {
                "title": trim_words(title, 10),
                "description": trim_words(description, 32),
                "status": status,
            }
        )
    return timeline


def content_for_answer_prompt(
    hit: RetrievalHit,
    index: int,
    expanded_chunk_ids: set[str],
) -> str:
    if hit.chunk_id and hit.chunk_id in expanded_chunk_ids:
        return trim_words(hit.content, 700)
    if index < 2:
        return trim_words(hit.content, 360)
    return trim_words(hit.content, 160)


def serialize_hits(hits: list[RetrievalHit]) -> list[dict[str, Any]]:
    return [
        {
            **hit.citation(),
            "score": round(float(hit.score or 0.0), 6),
            "source": hit.source,
            "sources": sorted(hit.sources),
            "content_preview": trim_words(hit.content, 120),
        }
        for hit in hits
    ]


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def summarize_tool_input(payload: dict[str, Any]) -> str:
    summary = json.dumps(json_safe(payload), ensure_ascii=False)
    return trim_words(summary, 36)


def append_agent_step(
    steps: list[dict[str, Any]],
    phase: str,
    message: str,
    status: str,
) -> list[dict[str, Any]]:
    return [
        *steps,
        {
            "phase": phase,
            "message": message,
            "status": status,
        },
    ]


def tool_was_called(state: ChatAgentState, tool_name: str) -> bool:
    return any(item.get("tool") == tool_name for item in state.get("tool_trace", []))


def int_safe(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def append_warning(
    warnings: list[dict[str, str]],
    code: str,
    message: str,
) -> list[dict[str, str]]:
    if any(item.get("code") == code for item in warnings):
        return warnings
    return [*warnings, warning(code, message)]


def warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def normalize_validity_status(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    return text.lower()


def normalize_field_id(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, float):
        return int(value) if value.is_integer() and value >= 0 else default
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
    return default


def is_active_status(status: Any) -> bool:
    normalized = normalize_validity_status(status)
    return normalized in ACTIVE_STATUSES


def is_unknown_status(status: Any) -> bool:
    normalized = normalize_validity_status(status)
    return normalized in {None, "", VALIDITY_UNKNOWN}


def normalize_query_text(value: str) -> str:
    text = value.lower()
    replacements = {
        "đ": "d",
        "Đ": "d",
        "á": "a",
        "à": "a",
        "ả": "a",
        "ã": "a",
        "ạ": "a",
        "ă": "a",
        "ắ": "a",
        "ằ": "a",
        "ẳ": "a",
        "ẵ": "a",
        "ặ": "a",
        "â": "a",
        "ấ": "a",
        "ầ": "a",
        "ẩ": "a",
        "ẫ": "a",
        "ậ": "a",
        "é": "e",
        "è": "e",
        "ẻ": "e",
        "ẽ": "e",
        "ẹ": "e",
        "ê": "e",
        "ế": "e",
        "ề": "e",
        "ể": "e",
        "ễ": "e",
        "ệ": "e",
        "í": "i",
        "ì": "i",
        "ỉ": "i",
        "ĩ": "i",
        "ị": "i",
        "ó": "o",
        "ò": "o",
        "ỏ": "o",
        "õ": "o",
        "ọ": "o",
        "ô": "o",
        "ố": "o",
        "ồ": "o",
        "ổ": "o",
        "ỗ": "o",
        "ộ": "o",
        "ơ": "o",
        "ớ": "o",
        "ờ": "o",
        "ở": "o",
        "ỡ": "o",
        "ợ": "o",
        "ú": "u",
        "ù": "u",
        "ủ": "u",
        "ũ": "u",
        "ụ": "u",
        "ư": "u",
        "ứ": "u",
        "ừ": "u",
        "ử": "u",
        "ữ": "u",
        "ự": "u",
        "ý": "y",
        "ỳ": "y",
        "ỷ": "y",
        "ỹ": "y",
        "ỵ": "y",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def first_list(value: Any) -> list[Any]:
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    if isinstance(value, list):
        return value
    return []


def trim_words(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "..."
