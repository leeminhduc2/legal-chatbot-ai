from __future__ import annotations

import unittest

from backend.config import Config
from backend.services.chat_agent_service import (
    AGENT_MODE_LEGACY,
    AGENT_MODE_REACT,
    AgentTimeout,
    ChatAgentService,
    MODE_INSUFFICIENT_EVIDENCE,
    MODE_LEGAL_LOOKUP,
    MODE_STATUS_BASIC,
    RetrievalHit,
    WARNING_AGENT_TIMEOUT_PARTIAL,
    WARNING_STATUS_INCOMPLETE,
    WARNING_UNKNOWN_VALIDITY,
    fuse_hits,
)


class FakeLLM:
    def __init__(self, mode: str = MODE_LEGAL_LOOKUP):
        self.mode = mode

    def classify(self, question: str) -> dict:
        return {
            "mode": self.mode,
            "normalized_query": question,
            "explicit_expired": False,
        }

    def check_evidence(self, question, mode, hits, status_records):
        return {"relevant": True, "confidence_delta": 0.0, "warnings": []}

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
        return "Generated answer from supplied evidence."


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

        response = service.answer("Dieu 1 quy dinh gi?", user={"role": "free_user"})

        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)
        self.assertEqual(len(response["citations"]), 1)
        self.assertIn(
            WARNING_UNKNOWN_VALIDITY,
            [item["code"] for item in response["warnings"]],
        )
        self.assertGreater(response["confidence"], 0)

    def test_no_citation_returns_insufficient_evidence(self) -> None:
        service = self._service()

        response = service.answer("Khong co trong kho?", user={"role": "free_user"})

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

        response = service.answer("01/2026/QH con hieu luc khong?", user={"role": "free_user"})

        self.assertEqual(response["retrieval_mode"], MODE_STATUS_BASIC)
        self.assertEqual(response["citations"][0]["document_number"], "01/2026/QH")
        self.assertIn(
            WARNING_STATUS_INCOMPLETE,
            [item["code"] for item in response["warnings"]],
        )

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
            user={"role": "free_user"},
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

    def test_react_path_without_citation_is_insufficient_evidence(self) -> None:
        service = self._service(
            config=Config(
                app_env="test",
                sqlite_db_path=":memory:",
                chat_agent_mode=AGENT_MODE_REACT,
            ),
            react_agent_factory=call_all_tools_agent,
        )

        response = service.answer("Khong co citation?", user={"role": "free_user"})

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

        response = service.answer("Dieu 1 quy dinh gi?", user={"role": "free_user"})

        self.assertEqual(response["retrieval_mode"], MODE_LEGAL_LOOKUP)
        self.assertEqual(len(response["citations"]), 1)
        self.assertIn(
            WARNING_AGENT_TIMEOUT_PARTIAL,
            [item["code"] for item in response["warnings"]],
        )

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
            graph_retriever=FakeGraphRetriever(),
            status_repository=FakeStatusRepository(status_records),
            react_agent_factory=react_agent_factory,
        )


def call_all_tools_agent(*, phase, prompt, tools, state):
    for tool in tools:
        if tool.name in {"vector_search", "bm25_search"}:
            tool.func(query=state["question"], top_k=state["top_k"])
        elif tool.name == "status_lookup":
            tool.func(query=state["question"], limit=state["top_k"])
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
