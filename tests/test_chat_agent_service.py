from __future__ import annotations

import unittest

from backend.config import Config
from backend.services.chat_agent_service import (
    AGENT_MODE_LEGACY,
    AGENT_MODE_REACT,
    AgentTimeout,
    AccessScope,
    ChatAgentService,
    ElasticsearchBM25Retriever,
    MODE_INSUFFICIENT_EVIDENCE,
    MODE_LEGAL_LOOKUP,
    MODE_STATUS_BASIC,
    RetrievalHit,
    WARNING_AGENT_TIMEOUT_PARTIAL,
    WARNING_CITATION_RELEVANCE_FILTER,
    WARNING_QUERY_CONTEXTUALIZATION,
    WARNING_STATUS_INCOMPLETE,
    WARNING_UNKNOWN_VALIDITY,
    fuse_hits,
)


class FakeLLM:
    def __init__(
        self,
        mode: str = MODE_LEGAL_LOOKUP,
        timeline: list[dict[str, str]] | None = None,
        timeline_raises: bool = False,
        relevant_keys: list[str] | None = None,
        filter_raises: bool = False,
        contextualized_query: str | None = None,
        contextualize_raises: bool = False,
    ):
        self.mode = mode
        self.timeline = timeline
        self.timeline_raises = timeline_raises
        self.relevant_keys = relevant_keys
        self.filter_raises = filter_raises
        self.contextualized_query = contextualized_query
        self.contextualize_raises = contextualize_raises
        self.contextualize_inputs = []
        self.classified_questions = []
        self.filter_candidates = []
        self.generated_hits = []
        self.generated_status_records = []
        self.generated_question = ""

    def contextualize_query(self, current_query, conversation_context):
        self.contextualize_inputs.append(
            {"query": current_query, "context": conversation_context}
        )
        if self.contextualize_raises:
            raise RuntimeError("contextualize failed")
        if self.contextualized_query is None:
            return {
                "standalone_query": current_query,
                "used_memory": False,
                "reason": "already standalone",
            }
        return {
            "standalone_query": self.contextualized_query,
            "used_memory": self.contextualized_query != current_query,
            "reason": "resolved follow-up",
        }

    def classify(self, question: str) -> dict:
        self.classified_questions.append(question)
        return {
            "mode": self.mode,
            "normalized_query": question,
            "explicit_expired": False,
        }

    def check_evidence(self, question, mode, hits, status_records):
        return {"relevant": True, "confidence_delta": 0.0, "warnings": []}

    def filter_relevant_citations(self, question, mode, candidates):
        self.filter_candidates = candidates
        if self.filter_raises:
            raise RuntimeError("citation filter failed")
        relevant_keys = self.relevant_keys
        if relevant_keys is None:
            relevant_keys = [candidate["key"] for candidate in candidates]
        return {"relevant_keys": relevant_keys, "warnings": []}

    def generate_answer(
        self,
        question,
        mode,
        hits,
        status_records,
        graph_context,
        warnings,
        conversation_context=None,
        expanded_chunk_ids=None,
    ):
        self.generated_question = question
        self.generated_hits = hits
        self.generated_status_records = status_records
        return "Generated answer from supplied evidence."

    def summarize_agent_timeline(self, payload):
        if self.timeline_raises:
            raise RuntimeError("timeline failed")
        return self.timeline or []


class FakeRetriever:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.calls = []

    def search(self, query, top_k, filters, include_expired):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "filters": filters,
                "include_expired": include_expired,
            }
        )
        return self.hits[:top_k]


class FakeElasticsearchClient:
    def __init__(self):
        self.search_body = {}

    def search(self, index, body):
        self.search_body = body
        return {"hits": {"hits": []}}


class FakeGraphRetriever:
    def __init__(self):
        self.calls = []

    def enrich(self, hits, top_k):
        self.calls.append({"hits": hits, "top_k": top_k})
        return {"related_documents": [], "effectivity_relations": [], "support_score": 0.7}


class FakeStatusRepository:
    def __init__(self, records=None):
        self.records = records or []

    def find_status_records(self, query, filters, limit):
        return self.records[:limit]


class ChatAgentServiceTest(unittest.TestCase):
    def test_unknown_validity_is_included_with_warning(self) -> None:
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung can cu.",
            article_number="1",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="unknown",
            source="vector",
            sources={"vector"},
        )
        service = self._service(vector_hits=[hit])

        response = service.answer("Dieu 1 quy dinh gi?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)
        self.assertEqual(len(response["citations"]), 1)
        self.assertIn(
            WARNING_UNKNOWN_VALIDITY,
            [item["code"] for item in response["warnings"]],
        )
        self.assertGreater(response["confidence"], 0)

    def test_no_citation_returns_insufficient_evidence(self) -> None:
        service = self._service()

        response = service.answer("Khong co trong kho?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_INSUFFICIENT_EVIDENCE)
        self.assertEqual(response["citations"], [])
        self.assertEqual(response["confidence"], 0.0)

    def test_guest_top_k_is_limited_to_three(self) -> None:
        vector = FakeRetriever(
            [
                RetrievalHit(
                    chunk_id=str(index),
                    document_id="doc",
                    document_number="01/2026/QH",
                    document_title="Luat test",
                    content="Noi dung",
                    article_number=str(index),
                    citation_label=f"Dieu {index}",
                    validity_status="active",
                    source="vector",
                    sources={"vector"},
                )
                for index in range(10)
            ]
        )
        service = self._service(vector_retriever=vector)

        response = service.answer("Hoi thu", user=None, requested_top_k=20)

        self.assertEqual(vector.calls[0]["top_k"], 3)
        self.assertLessEqual(len(response["citations"]), 3)

    def test_retrieval_hits_are_filtered_by_field_scope(self) -> None:
        restricted = RetrievalHit(
            chunk_id="restricted",
            document_id="doc-restricted",
            document_number="99/2026/QH",
            document_title="Restricted",
            content="Restricted content",
            citation_label="Restricted",
            validity_status="active",
            field_id=2,
            source="vector",
            sources={"vector"},
        )
        public = RetrievalHit(
            chunk_id="public",
            document_id="doc-public",
            document_number="01/2026/QH",
            document_title="Public",
            content="Public content",
            citation_label="Public",
            validity_status="active",
            field_id=0,
            source="vector",
            sources={"vector"},
        )
        service = self._service(vector_hits=[restricted, public])

        response = service.answer("Can cu nao?", user={"role": "business_user"})

        self.assertEqual([item["chunk_id"] for item in response["citations"]], ["public"])
        self.assertEqual(response["citations"][0]["field_id"], 0)

    def test_bm25_filter_treats_missing_field_id_as_public_legacy_index(self) -> None:
        config = Config(
            bm25_provider="elasticsearch",
            elasticsearch_url="http://example.test",
            elasticsearch_index="legal",
        )
        retriever = ElasticsearchBM25Retriever(config)
        client = FakeElasticsearchClient()
        retriever._client = client

        retriever.search(
            "bao hiem",
            3,
            {"_access_scope": AccessScope(unrestricted=False, field_ids=(0, 2))},
            True,
        )

        filters = client.search_body["query"]["bool"]["filter"]
        field_filter = filters[1]["bool"]
        self.assertEqual(field_filter["minimum_should_match"], 1)
        self.assertIn({"terms": {"field_id": [0, 2]}}, field_filter["should"])
        self.assertIn(
            {"bool": {"must_not": {"exists": {"field": "field_id"}}}},
            field_filter["should"],
        )

    def test_followup_query_is_contextualized_before_classification_and_retrieval(self) -> None:
        standalone = "I am working under a four-year contract. How should I pay health insurance?"
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung ve bao hiem y te.",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        vector = FakeRetriever([hit])
        llm = FakeLLM(contextualized_query=standalone)
        service = self._service(llm=llm, vector_retriever=vector)

        response = service.answer(
            "Hay tra loi lai cau hoi toi vua hoi",
            user={"role": "business_user"},
            conversation_context={
                "summary": "",
                "recent_messages": [{"role": "user", "content": standalone}],
            },
        )

        self.assertEqual(llm.classified_questions[0], standalone)
        self.assertEqual(vector.calls[0]["query"], standalone)
        self.assertEqual(llm.generated_question, standalone)
        self.assertTrue(response["memory_used"]["contextualized_query_used"])
        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)

    def test_standalone_query_is_not_rewritten_by_conversation_memory(self) -> None:
        query = "Dieu 1 quy dinh gi ve bao hiem y te?"
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung ve bao hiem y te.",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        vector = FakeRetriever([hit])
        llm = FakeLLM()
        service = self._service(llm=llm, vector_retriever=vector)

        response = service.answer(
            query,
            user={"role": "business_user"},
            conversation_context={
                "summary": "Hoi truoc ve hop dong lao dong.",
                "recent_messages": [{"role": "user", "content": "Cau hoi cu"}],
            },
        )

        self.assertEqual(llm.classified_questions[0], query)
        self.assertEqual(vector.calls[0]["query"], query)
        self.assertEqual(llm.generated_question, query)
        self.assertFalse(response["memory_used"]["contextualized_query_used"])

    def test_contextualization_failure_fails_open_with_original_query(self) -> None:
        query = "Dieu 1 quy dinh gi ve bao hiem y te?"
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung ve bao hiem y te.",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        vector = FakeRetriever([hit])
        llm = FakeLLM(contextualize_raises=True)
        service = self._service(llm=llm, vector_retriever=vector)

        response = service.answer(
            query,
            user={"role": "business_user"},
            conversation_context={
                "summary": "Hoi truoc ve hop dong lao dong.",
                "recent_messages": [{"role": "user", "content": "Cau hoi cu"}],
            },
        )

        self.assertEqual(llm.classified_questions[0], query)
        self.assertEqual(vector.calls[0]["query"], query)
        self.assertFalse(response["memory_used"]["contextualized_query_used"])
        self.assertIn(
            WARNING_QUERY_CONTEXTUALIZATION,
            [item["code"] for item in response["warnings"]],
        )

    def test_citation_relevance_filter_removes_unrelated_hits_before_answer(self) -> None:
        unrelated = RetrievalHit(
            chunk_id="chunk-drop",
            document_id="doc-drop",
            document_number="01/2026/QH",
            document_title="Luat test drop",
            content="Noi dung khong tra loi cau hoi.",
            citation_label="Drop",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        relevant = RetrievalHit(
            chunk_id="chunk-keep",
            document_id="doc-keep",
            document_number="02/2026/QH",
            document_title="Luat test keep",
            content="Noi dung truc tiep tra loi cau hoi.",
            citation_label="Keep",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        llm = FakeLLM(relevant_keys=["hit:1:chunk-keep"])
        service = self._service(llm=llm, vector_hits=[unrelated, relevant])

        response = service.answer("Can cu nao tra loi cau hoi?", user={"role": "business_user"})

        self.assertEqual([item["chunk_id"] for item in response["citations"]], ["chunk-keep"])
        self.assertEqual([hit.chunk_id for hit in llm.generated_hits], ["chunk-keep"])
        self.assertTrue(
            any(trace["tool"] == "citation_relevance_filter" for trace in response["tool_trace"])
        )

    def test_citation_relevance_filter_fail_closed_when_llm_fails(self) -> None:
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung co ve lien quan.",
            citation_label="01/2026/QH",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        llm = FakeLLM(filter_raises=True)
        service = self._service(llm=llm, vector_hits=[hit])

        response = service.answer("Cau hoi can can cu?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_INSUFFICIENT_EVIDENCE)
        self.assertEqual(response["citations"], [])
        self.assertEqual(llm.generated_hits, [])
        self.assertIn(
            WARNING_CITATION_RELEVANCE_FILTER,
            [item["code"] for item in response["warnings"]],
        )

    def test_status_basic_can_answer_from_metadata_without_chunks(self) -> None:
        service = self._service(
            llm=FakeLLM(MODE_STATUS_BASIC),
            status_records=[
                {
                    "document_id": "doc-1",
                    "document_number": "01/2026/QH",
                    "title": "Luat test",
                    "validity_status": "unknown",
                    "effective_date": None,
                    "expiry_date": None,
                    "relations": [],
                }
            ],
        )

        response = service.answer("01/2026/QH con hieu luc khong?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_STATUS_BASIC)
        self.assertEqual(response["citations"][0]["document_number"], "01/2026/QH")
        self.assertIn(
            WARNING_STATUS_INCOMPLETE,
            [item["code"] for item in response["warnings"]],
        )

    def test_status_basic_unrelated_metadata_is_not_exposed(self) -> None:
        llm = FakeLLM(MODE_STATUS_BASIC, relevant_keys=[])
        service = self._service(
            llm=llm,
            status_records=[
                {
                    "document_id": "doc-1",
                    "document_number": "01/2026/QH",
                    "title": "Luat test",
                    "validity_status": "active",
                    "effective_date": None,
                    "expiry_date": None,
                    "relations": [],
                }
            ],
        )

        response = service.answer("Van ban khac con hieu luc khong?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_INSUFFICIENT_EVIDENCE)
        self.assertEqual(response["citations"], [])
        self.assertEqual(llm.generated_status_records, [])

    def test_react_path_records_tool_trace_with_valid_citation(self) -> None:
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung can cu chi tiet.",
            article_number="1",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            vector_hits=[hit],
            react_agent_factory=call_all_tools_agent,
        )

        response = service.answer(
            "Dieu 1 quy dinh gi?",
            user={"role": "business_user"},
            conversation_context={
                "summary": "Hoi ve van ban bao hiem truoc do.",
                "recent_messages": [{"role": "user", "content": "Cau hoi cu"}],
            },
        )

        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)
        self.assertEqual(len(response["citations"]), 1)
        self.assertGreaterEqual(len(response["tool_trace"]), 2)
        self.assertTrue(response["memory_used"]["summary_used"])
        self.assertEqual(response["memory_used"]["recent_message_count"], 1)

    def test_react_expansion_uses_only_relevance_filtered_hits(self) -> None:
        unrelated = RetrievalHit(
            chunk_id="chunk-drop",
            document_id="doc-drop",
            document_number="01/2026/QH",
            document_title="Luat test drop",
            content="Noi dung khong tra loi cau hoi.",
            citation_label="Drop",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        relevant = RetrievalHit(
            chunk_id="chunk-keep",
            document_id="doc-keep",
            document_number="02/2026/QH",
            document_title="Luat test keep",
            content="Noi dung truc tiep tra loi cau hoi.",
            citation_label="Keep",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        graph = FakeGraphRetriever()
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            llm=FakeLLM(relevant_keys=["hit:1:chunk-keep"]),
            vector_hits=[unrelated, relevant],
            graph_retriever=graph,
            react_agent_factory=call_all_tools_agent,
        )

        response = service.answer("Can cu nao tra loi cau hoi?", user={"role": "business_user"})

        self.assertEqual([item["chunk_id"] for item in response["citations"]], ["chunk-keep"])
        self.assertEqual([hit.chunk_id for hit in graph.calls[0]["hits"]], ["chunk-keep"])

    def test_react_retrieval_uses_contextualized_query(self) -> None:
        standalone = "I am working under a four-year contract. How should I pay health insurance?"
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung ve bao hiem y te.",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        vector = FakeRetriever([hit])
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            llm=FakeLLM(contextualized_query=standalone),
            vector_retriever=vector,
            react_agent_factory=call_all_tools_agent,
        )

        response = service.answer(
            "Hay tra loi lai cau hoi toi vua hoi",
            user={"role": "business_user"},
            conversation_context={
                "summary": "",
                "recent_messages": [{"role": "user", "content": standalone}],
            },
        )

        self.assertEqual(vector.calls[0]["query"], standalone)
        self.assertTrue(response["memory_used"]["contextualized_query_used"])

    def test_react_path_without_citation_is_insufficient_evidence(self) -> None:
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            react_agent_factory=call_all_tools_agent,
        )

        response = service.answer("Khong co citation?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_INSUFFICIENT_EVIDENCE)
        self.assertEqual(response["citations"], [])

    def test_react_timeout_with_citation_returns_partial_answer(self) -> None:
        hit = RetrievalHit(
            chunk_id="chunk-1",
            document_id="doc-1",
            document_number="01/2026/QH",
            document_title="Luat test",
            content="Noi dung can cu chi tiet.",
            article_number="1",
            citation_label="01/2026/QH, Dieu 1",
            validity_status="active",
            source="vector",
            sources={"vector"},
        )
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            vector_hits=[hit],
            react_agent_factory=timeout_after_retrieval_agent,
        )

        response = service.answer("Dieu 1 quy dinh gi?", user={"role": "business_user"})

        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)
        self.assertEqual(len(response["citations"]), 1)
        self.assertIn(
            WARNING_AGENT_TIMEOUT_PARTIAL,
            [item["code"] for item in response["warnings"]],
        )

    def test_agent_timeline_uses_llm_summary_when_available(self) -> None:
        service = self._service(
            llm=FakeLLM(
                timeline=[
                    {
                        "title": "Tim can cu",
                        "description": "Da tim thay dieu khoan lien quan.",
                        "status": "ok",
                    }
                ]
            )
        )

        response = service.answer("Dieu 1 quy dinh gi?", user={"role": "business_user"})

        self.assertEqual(response["agent_timeline"][0]["title"], "Tim can cu")

    def test_agent_timeline_falls_back_when_llm_summary_fails(self) -> None:
        service = self._service(llm=FakeLLM(timeline_raises=True))

        response = service.answer("Khong co trong kho?", user={"role": "business_user"})

        self.assertGreaterEqual(len(response["agent_timeline"]), 3)
        self.assertTrue(response["agent_timeline"][0]["title"].startswith("Hi"))

    def test_rrf_merges_duplicate_hits_without_llm_rerank(self) -> None:
        dense = RetrievalHit(
            chunk_id="same",
            content="short",
            source="vector",
            sources={"vector"},
            score=0.8,
        )
        bm25 = RetrievalHit(
            chunk_id="same",
            content="longer content",
            source="bm25",
            sources={"bm25"},
            score=12.0,
        )

        fused = fuse_hits([[dense], [bm25]], top_k=5)

        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0].content, "longer content")
        self.assertEqual(fused[0].sources, {"vector", "bm25"})

    def _service(
        self,
        *,
        config=None,
        llm=None,
        vector_hits=None,
        bm25_hits=None,
        vector_retriever=None,
        graph_retriever=None,
        status_records=None,
        react_agent_factory=None,
    ) -> ChatAgentService:
        return ChatAgentService(
            config or Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_LEGACY,
            ),
            llm=llm or FakeLLM(),
            vector_retriever=vector_retriever or FakeRetriever(vector_hits),
            bm25_retriever=FakeRetriever(bm25_hits),
            graph_retriever=graph_retriever or FakeGraphRetriever(),
            status_repository=FakeStatusRepository(status_records),
            react_agent_factory=react_agent_factory,
        )


def call_all_tools_agent(*, phase, prompt, tools, state):
    query = state.get("normalized_query") or state["question"]
    for tool in tools:
        if tool.name in {"vector_search", "bm25_search"}:
            tool.func(query=query, top_k=state["top_k"])
        elif tool.name == "status_lookup":
            tool.func(query=query, limit=state["top_k"])
        elif tool.name == "graph_context":
            tool.func(focus="retrieved citations")
        elif tool.name == "get_chunk_detail" and state.get("fused_hits"):
            tool.func(chunk_id=state["fused_hits"][0].chunk_id)


def timeout_after_retrieval_agent(*, phase, prompt, tools, state):
    if phase == "retrieval":
        call_all_tools_agent(phase=phase, prompt=prompt, tools=tools, state=state)
        return
    raise AgentTimeout("test timeout")


if __name__ == "__main__":
    unittest.main()
