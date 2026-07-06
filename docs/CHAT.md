# Chat Agent Service

Tài liệu này giải thích `backend/services/chat_agent_service.py` theo hướng top-down: bắt đầu từ vai trò của module trong backend, đi qua luồng xử lý chính, sau đó mới xuống từng class/function.

## 1. Vai trò của module

`chat_agent_service.py` là lõi RAG cho route `POST /api/v1/chat`.

Nó không tự import DOCX, không tự publish văn bản, và không tự sửa index. Nó chỉ đọc các nguồn đã được publish bởi admin/publish pipeline:

- SQLite: metadata văn bản, trạng thái hiệu lực, quan hệ nhập bởi admin.
- Chroma: vector index cho semantic retrieval.
- Elasticsearch: BM25/full-text retrieval nếu được cấu hình.
- Neo4j: graph context cho cấu trúc văn bản và quan hệ pháp lý đã publish.
- DeepSeek/OpenAI-compatible chat API: phân loại intent, kiểm tra evidence, sinh câu trả lời.

Luồng lớn:

```text
client/chat route
  -> ChatAgentService.answer()
  -> route_intent
  -> resolve_exact_status
  -> vector_retrieve
  -> bm25_retrieve
  -> graph_enrich
  -> fuse_and_rerank
  -> evidence_check
  -> generate_output
  -> response payload
```

Điểm quan trọng: service này được thiết kế để fail mềm. Nếu LLM, Chroma, Elasticsearch hoặc Neo4j không sẵn sàng, request không nhất thiết crash. Thay vào đó service thêm `warnings`, giảm confidence, hoặc trả `insufficient_evidence`.

## 2. Các mode và warning chính

### Retrieval mode

- `legal_lookup`: tra cứu nội dung pháp luật thông thường.
- `status_basic`: kiểm tra hiệu lực/trạng thái cơ bản của văn bản.
- `out_of_scope`: câu hỏi nằm ngoài phạm vi V1, ví dụ soạn thảo hoặc rà soát hợp đồng.
- `insufficient_evidence`: hệ thống không tìm được citation/evidence đủ để trả lời.

### Warning code

- `NO_CITATION`: không có citation hợp lệ.
- `LOW_RELEVANCE`: evidence tìm được có thể không trả lời sát câu hỏi.
- `UNKNOWN_VALIDITY`: một hoặc nhiều văn bản có trạng thái hiệu lực chưa rõ.
- `RETRIEVER_UNAVAILABLE`: một retriever không khả dụng.
- `STATUS_INCOMPLETE`: metadata hiệu lực chưa đủ để kết luận chắc chắn.
- `LLM_UNAVAILABLE`: LLM không khả dụng ở bước kiểm tra evidence.

## 3. State xuyên suốt pipeline

### `ChatAgentState`

`ChatAgentState` là `TypedDict` đóng vai trò như một object state chung. Mỗi node trong pipeline đọc một phần state và trả thêm field mới.

Các field quan trọng:

- `trace_id`: id để trace log cho từng request.
- `question`: câu hỏi gốc.
- `normalized_query`: query đã được LLM hoặc fallback chuẩn hóa.
- `user_role`: role hiện tại, ảnh hưởng đến giới hạn `top_k`.
- `top_k`: số kết quả tối đa được lấy và trả về.
- `mode`: mode xử lý hiện tại.
- `explicit_expired`: người dùng có hỏi rõ về văn bản hết hiệu lực/thay thế/bãi bỏ không.
- `filters`: filter extract được từ query, như `document_number`, `article_number`.
- `warnings`: danh sách cảnh báo tích lũy qua các bước.
- `status_records`: metadata hiệu lực lấy trực tiếp từ SQLite.
- `vector_hits`: kết quả từ Chroma.
- `bm25_hits`: kết quả từ Elasticsearch/BM25.
- `fused_hits`: kết quả sau khi hợp nhất/rerank.
- `graph_context`: context lấy từ Neo4j.
- `citations`: citation chuẩn hóa cho response.
- `confidence`: điểm tin cậy cuối cùng.
- `answer`: câu trả lời cuối cùng.
- `llm_check`: kết quả LLM kiểm tra evidence.

## 4. Contract cho LLM

### `ChatLLM`

`ChatLLM` là `Protocol`, tức interface mềm cho LLM client. `ChatAgentService` không phụ thuộc cứng vào `DeepSeekChatClient`; test hoặc implementation khác có thể inject một object khác miễn là có đủ 3 hàm:

### `classify(question)`

Nhận câu hỏi và trả metadata định tuyến:

- `mode`
- `normalized_query`
- `explicit_expired`

### `check_evidence(question, mode, hits, status_records)`

Kiểm tra evidence đã retrieve có liên quan với câu hỏi không. Hàm này không được thêm fact mới, chỉ đánh giá evidence hiện có.

### `generate_answer(question, mode, hits, status_records, graph_context, warnings)`

Sinh câu trả lời cuối cùng dựa trên evidence đã cung cấp. Prompt yêu cầu không bịa căn cứ pháp lý, số điều, quan hệ hoặc trạng thái hiệu lực.

## 5. Model dữ liệu retrieval

### `RetrievalHit`

`RetrievalHit` là dataclass chuẩn hóa một kết quả retrieval từ Chroma hoặc Elasticsearch.

Các field chính:

- `chunk_id`: id chunk trong index.
- `document_id`: id văn bản trong registry.
- `document_number`: số/ký hiệu văn bản.
- `document_title`: tiêu đề văn bản.
- `content`: nội dung chunk.
- `article_number`: số điều.
- `clause_number`: số khoản.
- `citation_label`: nhãn citation hiển thị.
- `validity_status`: trạng thái hiệu lực.
- `is_published`: chunk/văn bản có publish không.
- `score`: điểm retrieval/rerank.
- `source`: nguồn chính, ví dụ `vector`, `bm25`, hoặc `bm25+vector`.
- `sources`: set nguồn đã đóng góp vào hit.

### `RetrievalHit.key`

Tạo khóa ổn định để dedup kết quả.

Thứ tự ưu tiên:

1. Nếu có `chunk_id`, dùng `chunk_id`.
2. Nếu không, ghép `document_id` hoặc `document_number`, `article_number`, `clause_number`, `citation_label`.
3. Nếu vẫn rỗng, tạo UUID mới.

Điều này giúp `fuse_hits()` nhận ra cùng một chunk xuất hiện ở cả vector và BM25.

### `RetrievalHit.from_payload(payload, source, score=None, content=None)`

Chuyển metadata thô thành `RetrievalHit`.

Cách xử lý:

- Lấy `chunk_id`, `document_id`, `document_number`, `document_title`.
- Hỗ trợ nhiều tên field cho title: `document_title`, `title`, `document_name`.
- Lấy `content` từ tham số truyền vào hoặc từ payload.
- Normalize `validity_status`.
- Ép `is_published` về bool.
- Gắn `source` và khởi tạo `sources={source}`.
- Nếu thiếu `citation_label`, tự dựng nhãn từ `document_number`, `article_number`, `clause_number`.

### `RetrievalHit.citation()`

Trả citation dict dùng cho API response và LLM prompt.

Citation gồm:

- `citation_label`
- `document_id`
- `document_title`
- `document_name`
- `document_number`
- `article_number`
- `clause_number`
- `article`
- `validity_status`
- `is_active`
- `chunk_id`

## 6. LLM client: `DeepSeekChatClient`

### `__init__(config)`

Lưu config và tạo `_client=None`. Client thật chỉ được tạo khi gọi API lần đầu.

### `classify(question)`

Mục tiêu: xác định câu hỏi nên đi theo mode nào.

Cách xử lý:

1. Tạo fallback bằng `classify_question_heuristically(question)`.
2. Gọi `_chat_json()` với system prompt yêu cầu trả JSON.
3. Nếu LLM không trả dict hợp lệ, dùng fallback.
4. Nếu `mode` không thuộc 3 mode hợp lệ, dùng mode từ fallback.
5. Trả `mode`, `normalized_query`, `explicit_expired`.

Điểm đáng chú ý: classification không trả lời câu hỏi, chỉ định tuyến.

### `check_evidence(question, mode, hits, status_records)`

Mục tiêu: dùng LLM như một lớp kiểm tra relevance.

Cách xử lý:

1. Tạo payload gồm câu hỏi, mode, tối đa 8 citation, status records đã compact.
2. Gọi `_chat_json()` với prompt yêu cầu JSON.
3. Nếu LLM không trả dict, fallback về:

```python
{"relevant": bool(hits or status_records), "confidence_delta": 0.0}
```

4. Ép `confidence_delta` về float và giới hạn trong `-0.1..0.1`.
5. Trả `relevant`, `confidence_delta`, `warnings`.

### `generate_answer(question, mode, hits, status_records, graph_context, warnings)`

Mục tiêu: sinh câu trả lời tiếng Việt dựa trên evidence.

Cách xử lý:

1. Tạo payload gồm:
   - câu hỏi
   - mode
   - tối đa 8 citations, mỗi citation có thêm `content` đã cắt còn 180 từ
   - status records đã compact
   - graph context
   - warnings
2. Gọi `_chat_text()` với prompt yêu cầu:
   - trả lời tiếng Việt
   - chỉ dùng evidence đã cung cấp
   - nếu evidence yếu thì phải nói rõ caveat
   - không bịa căn cứ pháp lý, số điều, trạng thái hoặc quan hệ
3. Nếu có nội dung, strip và trả về.
4. Nếu không có, trả chuỗi rỗng để pipeline fallback sang extractive answer.

### `_chat_json(messages)`

Gọi `_chat_text()` với `response_format={"type": "json_object"}` rồi parse JSON.

Nếu không có text, JSON lỗi, hoặc JSON không phải dict thì trả `None`.

### `_chat_text(messages, response_format=None)`

Mục tiêu: gọi DeepSeek qua OpenAI-compatible SDK.

Cách xử lý:

1. Đọc `DEEPSEEK_API_KEY` từ environment.
2. Nếu thiếu key, trả `""`.
3. Import `OpenAI` từ package `openai`.
4. Nếu thiếu package, trả `""`.
5. Lazy-init client:

```python
OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
```

6. Gọi `chat.completions.create()` với:
   - model từ `config.llm_model_chat` hoặc `deepseek-chat`
   - `temperature=0`
   - `response_format` nếu có
7. Nếu lỗi provider/network, log warning và trả `""`.

## 7. Vector retriever: `ChromaVectorRetriever`

### `__init__(config, embedding_provider=None)`

Lưu config và khởi tạo embedding provider.

Nếu không inject provider, dùng:

```python
LocalEmbeddingProvider(config.embedding_model)
```

### `search(query, top_k, filters, include_expired)`

Mục tiêu: semantic retrieval từ Chroma.

Cách xử lý:

1. Import `chromadb`; nếu thiếu package thì raise `RetrieverUnavailable`.
2. Mở persistent client tại `config.chroma_path`.
3. Lấy collection `config.chroma_collection`.
4. Embed query bằng `embedding_provider.embed_documents([query])[0]`.
5. Query collection với:

```python
where={"is_published": 1}
include=["documents", "metadatas", "distances"]
n_results=max(top_k * 2, top_k)
```

6. Lấy `ids`, `documents`, `metadatas`, `distances` bằng `first_list()`.
7. Với từng kết quả:
   - lấy metadata
   - đổi distance thành score: `1.0 / (1.0 + distance)`
   - tạo `RetrievalHit.from_payload(..., source="vector")`
   - lọc bằng `hit_allowed()`
8. Dừng khi đủ `top_k`.

## 8. BM25 retriever: `ElasticsearchBM25Retriever`

### `__init__(config)`

Lưu config và đặt `_client=None` để lazy-init.

### `search(query, top_k, filters, include_expired)`

Mục tiêu: full-text retrieval/BM25 qua Elasticsearch.

Cách xử lý:

1. Nếu `config.bm25_provider != "elasticsearch"`, raise `RetrieverUnavailable`.
2. Lấy Elasticsearch client bằng `_get_client()`.
3. Tạo filter bắt buộc:

```python
{"term": {"is_published": True}}
```

4. Nếu có `document_number`, thêm filter document.
5. Nếu có `article_number`, thêm filter article.
6. Gọi `client.search()` với `multi_match` trên:
   - `content^3`
   - `document_title^2`
   - `citation_label`
   - `document_number`
7. Lấy tối đa `max(top_k * 2, top_k)`.
8. Với từng hit:
   - đọc `_source`
   - tạo `RetrievalHit.from_payload(..., source="bm25")`
   - lọc bằng `hit_allowed()`
9. Dừng khi đủ `top_k`.

### `_get_client()`

Lazy-init Elasticsearch client.

Cách xử lý:

1. Nếu `_client` đã có, trả lại.
2. Nếu thiếu `config.elasticsearch_url`, raise `RetrieverUnavailable`.
3. Import `Elasticsearch`; thiếu package thì raise `RetrieverUnavailable`.
4. Tạo kwargs gồm:
   - `hosts`
   - `verify_certs`
   - `api_key` nếu có
   - nếu không có API key nhưng có username/password, dùng `basic_auth`
5. Cache client vào `_client`.

## 9. Graph retriever: `FixedNeo4jContextRetriever`

### `__init__(config)`

Lưu config và đặt `_driver=None` để lazy-init.

### `enrich(hits, top_k)`

Mục tiêu: bổ sung graph context từ Neo4j cho các hit đã retrieve.

Cách xử lý:

1. Nếu không có hits hoặc thiếu `neo4j_password`, trả context rỗng:

```python
{
  "related_documents": [],
  "effectivity_relations": [],
  "support_score": 0.0
}
```

2. Lấy driver bằng `_get_driver()`.
3. Với từng hit trong `hits[:top_k]`:
   - Nếu có `document_id` và `article_number`, kiểm tra graph có node `Document -> Article -> Clause` tương ứng không.
   - Nếu tìm thấy structure, tăng biến `structures`.
   - Nếu có `document_id`, query quan hệ `ADMIN_RELATION` đã publish từ document sang target.
4. Tính `support_score`:
   - `1.0` nếu có cả structure và related relations.
   - `0.7` nếu có structure nhưng không có related relations.
   - `0.5` nếu có hits nhưng không chứng minh được structure.
   - `0.0` nếu lỗi hoặc rỗng.
5. Trả:
   - `related_documents`
   - `effectivity_relations`
   - `support_score`

Nếu query Neo4j lỗi, service log warning và trả graph context rỗng.

### `_get_driver()`

Lazy-init Neo4j driver.

Cách xử lý:

1. Nếu `_driver` đã có, trả lại.
2. Import `GraphDatabase`; thiếu package thì raise `RetrieverUnavailable`.
3. Tạo driver từ `neo4j_uri`, `neo4j_user`, `neo4j_password`.
4. Gọi `verify_connectivity()`.
5. Cache driver.

### `_session_kwargs()`

Nếu config có `neo4j_database`, trả:

```python
{"database": config.neo4j_database}
```

Nếu không, trả `{}`.

## 10. Status repository: `DocumentStatusRepository`

### `__init__(db_path)`

Lưu đường dẫn SQLite database.

### `find_status_records(query, filters, limit)`

Mục tiêu: tìm metadata hiệu lực trực tiếp trong SQLite cho mode `status_basic`.

Cách xử lý:

1. Tạo danh sách terms gồm:
   - `filters.get("document_number")`
   - `query`
2. Mở SQLite connection.
3. Với từng term:
   - bỏ qua nếu rỗng
   - query `document_registry`
   - chỉ lấy `is_published = 1`
   - match `document_number LIKE ? OR title LIKE ?`
   - order theo `updated_at DESC`
   - limit theo tham số
4. Với mỗi record:
   - convert row thành dict
   - attach `relations` bằng `_relations_for()`
   - dedup theo `document_id`
5. Dừng khi đủ limit.

### `_relations_for(connection, document_id)`

Đọc các quan hệ đã publish từ bảng `document_relations`.

Trả tối đa 10 quan hệ mới nhất gồm:

- `relation_type`
- `target_document_id`
- `target_document_number`
- `source_text`

## 11. Exception marker

### `RetrieverUnavailable`

Exception dùng để báo retriever không khả dụng theo cách có kiểm soát.

Các retriever raise exception này khi thiếu package, thiếu config hoặc query provider lỗi. `ChatAgentService` bắt exception này và biến thành warning thay vì để request crash.

## 12. Orchestrator chính: `ChatAgentService`

### `__init__(config, llm=None, vector_retriever=None, bm25_retriever=None, graph_retriever=None, status_repository=None)`

Mục tiêu: khởi tạo toàn bộ dependency của chat agent.

Cách xử lý:

1. Lưu config.
2. Nếu không inject `llm`, dùng `DeepSeekChatClient(config)`.
3. Nếu không inject vector retriever, dùng `ChromaVectorRetriever(config)`.
4. Nếu không inject BM25 retriever, dùng `ElasticsearchBM25Retriever(config)`.
5. Nếu không inject graph retriever, dùng `FixedNeo4jContextRetriever(config)`.
6. Nếu không inject status repository, dùng `DocumentStatusRepository(config.sqlite_db_path)`.
7. Gọi `_build_graph()` để compile LangGraph nếu package có sẵn.

Việc cho phép inject dependency giúp test service mà không cần gọi thật Chroma, Elasticsearch, Neo4j hoặc LLM.

### `answer(message, user=None, requested_top_k=None)`

Đây là entrypoint chính.

Cách xử lý:

1. Tạo `trace_id`.
2. Xác định role:
   - nếu có `user`, dùng `user["role"]`
   - nếu không, dùng `ROLE_GUEST`
3. Tạo state ban đầu:
   - `question=message`
   - `normalized_query=message`
   - `top_k=resolve_top_k(requested_top_k, user_role)`
   - `mode=legal_lookup`
   - `explicit_expired=False`
   - `filters={}`
   - `warnings=[]`
4. Đo thời gian bằng `time.perf_counter()`.
5. Nếu `_graph` có sẵn, chạy `self._graph.invoke(state)`.
6. Nếu không có LangGraph, chạy `_run_without_langgraph(state)`.
7. Nếu toàn bộ pipeline lỗi, log exception và trả `insufficient_evidence_response()` kèm warning `CHAT_SERVICE_ERROR`.
8. Log kết quả gồm trace id, mode, duration, số hit, warning code, model.
9. Trả response payload:

```python
{
  "answer": answer,
  "response": answer,
  "query": message,
  "retrieval_mode": state.get("mode", MODE_INSUFFICIENT_EVIDENCE),
  "confidence": round(..., 3),
  "warnings": state.get("warnings", []),
  "citations": state.get("citations", []),
  "trace_id": trace_id,
}
```

### `_build_graph()`

Mục tiêu: dựng LangGraph nếu package `langgraph` có sẵn.

Cách xử lý:

1. Import `END`, `START`, `StateGraph`.
2. Nếu import lỗi, trả `None`.
3. Tạo `StateGraph(ChatAgentState)`.
4. Add các node:
   - `route_intent`
   - `resolve_exact_status`
   - `vector_retrieve`
   - `bm25_retrieve`
   - `graph_enrich`
   - `fuse_and_rerank`
   - `evidence_check`
   - `generate_output`
5. Add edge tuyến tính từ `START` tới `END`.
6. `compile()` graph và trả về.

### `_run_without_langgraph(state)`

Fallback khi không có LangGraph.

Cách xử lý:

1. Lặp qua cùng danh sách node như graph.
2. Gọi từng node với state hiện tại.
3. `state.update(node(state))`.
4. Trả state cuối.

## 13. Các node xử lý trong `ChatAgentService`

### `_route_intent(state)`

Mục tiêu: phân loại câu hỏi và extract filter.

Cách xử lý:

1. Lấy `question` từ state.
2. Gọi `self.llm.classify(question)`.
3. Nếu mode trả về không hợp lệ, fallback sang `classify_question_heuristically(question)`.
4. Gọi `extract_filters()` trên `normalized_query` hoặc question gốc.
5. Trả:
   - `mode`
   - `normalized_query`
   - `explicit_expired`
   - `filters`

### `_resolve_exact_status(state)`

Mục tiêu: tìm metadata hiệu lực chính xác trong SQLite nếu query là status query.

Cách xử lý:

1. Nếu mode là `out_of_scope`, trả `status_records=[]`.
2. Nếu mode là `status_basic`, gọi:

```python
self.status_repository.find_status_records(
    normalized_query_or_question,
    filters,
    top_k,
)
```

3. Nếu mode khác, trả list rỗng.

### `_vector_retrieve(state)`

Mục tiêu: retrieve semantic bằng Chroma.

Cách xử lý:

1. Nếu mode là `out_of_scope`, trả `vector_hits=[]`.
2. Tính `include_expired = should_include_expired(state)`.
3. Gọi `self.vector_retriever.search(...)`.
4. Nếu thành công, trả `vector_hits`.
5. Nếu `RetrieverUnavailable`, trả `vector_hits=[]` và append warning `RETRIEVER_UNAVAILABLE`.

### `_bm25_retrieve(state)`

Mục tiêu: retrieve lexical/full-text bằng Elasticsearch.

Cách xử lý tương tự `_vector_retrieve()`:

1. Skip nếu `out_of_scope`.
2. Tính `include_expired`.
3. Gọi `self.bm25_retriever.search(...)`.
4. Bắt `RetrieverUnavailable` và append warning.

### `_graph_enrich(state)`

Mục tiêu: bổ sung graph context từ Neo4j.

Cách xử lý:

1. Gộp `vector_hits` và `bm25_hits`.
2. Gọi `self.graph_retriever.enrich(hits, top_k)`.
3. Trả `graph_context`.

### `_fuse_and_rerank(state)`

Mục tiêu: hợp nhất kết quả từ vector và BM25.

Cách xử lý:

1. Gọi `fuse_hits([vector_hits, bm25_hits], top_k)`.
2. Nếu có hit có `validity_status` unknown, append warning `UNKNOWN_VALIDITY`.
3. Tạo citations từ `hit.citation()`.
4. Với mỗi `status_record`, append thêm citation bằng `citation_from_status_record()`.
5. Dedup citation bằng `unique_citations()`.
6. Trả:
   - `fused_hits`
   - `citations`
   - `warnings`

### `_evidence_check(state)`

Mục tiêu: quyết định evidence hiện tại có đủ để trả lời không và tính confidence.

Cách xử lý:

1. Lấy `hits`, `status_records`, `warnings`, `citations`.
2. Nếu không có citation:
   - append warning `NO_CITATION`
   - đổi mode thành `insufficient_evidence`
   - set confidence `0.0`
   - không gọi LLM check
3. Nếu có citation:
   - gọi `self.llm.check_evidence(...)`
   - nếu LLM check không khả dụng, append `LLM_UNAVAILABLE`
   - nếu LLM báo không relevant, append `LOW_RELEVANCE`
4. Tính confidence bằng `compute_confidence()`.
5. Nếu citation có validity unknown, append `UNKNOWN_VALIDITY`.
6. Nếu mode là `status_basic` và status record unknown, append `STATUS_INCOMPLETE`.
7. Trả:
   - `confidence`
   - `warnings`
   - `llm_check`

### `_generate_output(state)`

Mục tiêu: tạo câu trả lời cuối.

Cách xử lý:

1. Nếu mode là `out_of_scope`, trả câu canned response nói V1 chỉ hỗ trợ tra cứu pháp luật và kiểm tra hiệu lực cơ bản.
2. Nếu mode là `insufficient_evidence`, trả câu canned response nói không đủ căn cứ trong kho dữ liệu.
3. Ngược lại, gọi `self.llm.generate_answer(...)`.
4. Nếu LLM trả answer, dùng answer đó.
5. Nếu LLM không trả answer, fallback sang `build_extractive_answer(state)`.

## 14. Helper functions

### `resolve_top_k(raw_top_k, user_role)`

Giới hạn số kết quả theo role.

Logic:

- Guest mặc định `3`, tối đa `3`.
- Admin mặc định `8`, tối đa `20`.
- Role khác mặc định `8`, tối đa `12`.
- Nếu `raw_top_k` không parse được thành int, dùng default.
- Kết quả luôn nằm trong `1..maximum`.

### `classify_question_heuristically(question)`

Fallback phân loại bằng keyword.

Cách xử lý:

1. Normalize query bằng `normalize_query_text()`.
2. Nếu chứa term ngoài phạm vi như `soan thao`, `draft`, `review hop dong`, trả `out_of_scope`.
3. Nếu chứa term trạng thái như `hieu luc`, `het hieu luc`, `validity`, trả `status_basic`.
4. Ngược lại trả `legal_lookup`.
5. `explicit_expired=True` nếu query có term như `het hieu luc`, `expired`, `thay the`, `bai bo`.

### `extract_filters(query)`

Extract filter từ câu hỏi.

Hiện hỗ trợ:

- `article_number`: regex bắt `dieu 5` hoặc `article 5`.
- `document_number`: regex bắt format gần giống `123/2024/ABC-XYZ`.

Trả dict có thể gồm `article_number`, `document_number`.

### `should_include_expired(state)`

Trả `True` nếu:

- mode là `status_basic`, hoặc
- người dùng hỏi rõ về văn bản hết hiệu lực/thay thế/bãi bỏ qua `explicit_expired`.

Nếu `False`, retrieval sẽ lọc bớt văn bản inactive.

### `hit_allowed(hit, filters, include_expired)`

Lọc từng retrieval hit.

Cách xử lý:

1. Nếu filter có `document_number` mà hit không khớp, loại.
2. Nếu filter có `article_number` mà hit không khớp, loại.
3. Normalize `validity_status`.
4. Nếu `include_expired=True`, cho qua.
5. Nếu không include expired, chỉ cho qua khi:
   - status rỗng/None,
   - status active,
   - status unknown.

Điểm cần chú ý: status unknown vẫn được cho qua để tránh che mất văn bản mới publish nhưng chưa đủ metadata hiệu lực.

### `fuse_hits(hit_lists, top_k, rrf_k=60)`

Hợp nhất nhiều danh sách hit bằng Reciprocal Rank Fusion.

Cách xử lý:

1. Duyệt từng list hit.
2. Với mỗi hit, lấy `hit.key`.
3. Cộng điểm:

```python
1.0 / (rrf_k + rank)
```

4. Nếu key chưa có, thêm hit vào `merged`.
5. Nếu key đã có:
   - merge `sources`
   - giữ content dài hơn
   - giữ score retrieval lớn hơn trước khi overwrite bằng RRF score
6. Sau khi duyệt xong, set `hit.score` bằng RRF score.
7. Set `hit.source` bằng danh sách source đã sort, ví dụ `bm25+vector`.
8. Sort giảm dần theo score và lấy `top_k`.

### `compute_confidence(hits, citations, graph_context, llm_delta)`

Tính confidence cuối cùng.

Nếu không có citation, trả `0.0`.

Nếu có citation, confidence là tổng có trọng số:

- `0.35 * dense_score`
- `0.25 * bm25_score`
- `0.20 * graph_score`
- `0.10 * citation_score`
- `0.10 * validity_score`
- `llm_delta`

Ý nghĩa các score:

- `dense_score=1.0` nếu có hit từ vector, `0.3` nếu có hit nhưng không có vector, `0.0` nếu không có hit.
- `bm25_score=1.0` nếu có hit từ BM25, `0.3` nếu có hit nhưng không có BM25, `0.0` nếu không có hit.
- `graph_score` lấy từ `graph_context.support_score`.
- `citation_score=1.0` nếu có citation gắn article, nếu không là `0.5`.
- `validity_score=1.0` nếu tất cả status active, `0.5` nếu có unknown, `0.2` nếu còn lại.

Kết quả cuối bị clamp trong `0.0..1.0`.

### `build_extractive_answer(state)`

Fallback khi LLM không sinh được answer.

Cách xử lý:

1. Nếu có warnings, nối tối đa 2 warning đầu vào cuối câu trả lời.
2. Nếu mode là `status_basic` và có `status_records`:
   - trả dòng `Theo metadata hien co trong kho du lieu:`
   - liệt kê tối đa 3 văn bản
   - ghi `validity_status`
   - nếu có relations, ghi quan hệ đã nhập
   - nếu status unknown và không có relation, ghi caveat chưa đủ dữ liệu
3. Nếu không phải status query:
   - nếu không có hits, trả không đủ căn cứ
   - nếu có hits, liệt kê tối đa 3 hit, mỗi hit cắt còn 70 từ

### `insufficient_evidence_response(query, trace_id, warnings)`

Tạo response chuẩn khi agent không có đủ evidence hoặc crash trước khi sinh evidence.

Trả:

- `answer`
- `response`
- `query`
- `retrieval_mode=insufficient_evidence`
- `confidence=0.0`
- `warnings`
- `citations=[]`
- `trace_id`

### `citation_from_status_record(record)`

Chuyển record từ SQLite `document_registry` thành citation.

Khác với citation từ chunk, citation này không có `article_number`, `clause_number`, `chunk_id`.

### `unique_citations(citations)`

Dedup citations theo tổ hợp:

- `chunk_id`
- `document_id`
- `document_number`
- `article_number`
- `clause_number`

Giữ citation đầu tiên gặp được.

### `compact_status_records(records)`

Rút gọn status records trước khi đưa vào LLM prompt.

Chỉ giữ tối đa 8 record và các field:

- `document_id`
- `document_number`
- `title`
- `validity_status`
- `effective_date`
- `expiry_date`
- `relations`

### `append_warning(warnings, code, message)`

Thêm warning mới nếu chưa có warning cùng `code`.

Nếu code đã tồn tại, trả nguyên list cũ. Điều này tránh response bị lặp nhiều warning cùng loại.

### `warning(code, message)`

Tạo warning dict:

```python
{"code": code, "message": message}
```

### `normalize_validity_status(value)`

Ép value thành text bằng `optional_text()`. Nếu rỗng, trả `None`; nếu có, lower-case.

### `is_active_status(status)`

Normalize status rồi kiểm tra có thuộc:

- `active`
- `partially_effective`
- `partially_expired`

### `is_unknown_status(status)`

Normalize status rồi kiểm tra có thuộc:

- `None`
- `""`
- `VALIDITY_UNKNOWN`

### `normalize_query_text(value)`

Lower-case query và thay một số chuỗi bị lỗi encoding/mojibake sang ký tự không dấu.

Mục tiêu là giúp heuristic keyword match được các cụm như `hieu luc`, `bai bo`, `thay the`.

### `optional_text(value)`

Nếu value là `None`, trả `None`.

Nếu không, convert sang string, strip whitespace, rồi:

- nếu còn text, trả text
- nếu rỗng, trả `None`

### `coerce_bool(value, default=False)`

Ép value về bool.

Logic:

- `None`: trả default.
- bool: trả nguyên.
- int/float: dùng `bool(value)`.
- string: true nếu nằm trong `{"1", "true", "yes", "on"}`.

### `safe_float(value, default=0.0)`

Ép value về float an toàn.

Nếu parse lỗi, NaN hoặc infinity, trả default.

### `first_list(value)`

Chuẩn hóa response dạng list lồng nhau từ Chroma.

Logic:

- Nếu value là list và phần tử đầu cũng là list, trả phần tử đầu.
- Nếu value là list thường, trả value.
- Nếu không, trả `[]`.

### `trim_words(text, max_words)`

Cắt text theo số từ.

Nếu text có ít hơn hoặc bằng `max_words`, trả nguyên.

Nếu dài hơn, trả `max_words` đầu và thêm `...`.

## 15. Các điểm cần cảnh giác

### 15.1. `out_of_scope` có thể bị chuyển thành `insufficient_evidence`

Theo pipeline hiện tại, `_vector_retrieve()` và `_bm25_retrieve()` skip retrieval nếu mode là `out_of_scope`, nên sẽ không có citation. Sau đó `_evidence_check()` thấy không có citation và đổi mode thành `insufficient_evidence`.

Hệ quả có thể xảy ra: `_generate_output()` không còn thấy `MODE_OUT_OF_SCOPE`, nên trả câu "không đủ căn cứ" thay vì câu "V1 chưa hỗ trợ soạn thảo/rà soát hợp đồng".

Nếu muốn giữ đúng semantics, cần test riêng câu hỏi ngoài phạm vi và cân nhắc cho `_evidence_check()` preserve `out_of_scope`.

### 15.2. `normalize_query_text()` có vẻ xử lý mojibake, chưa chắc xử lý Unicode tiếng Việt chuẩn

Heuristic đang check các term như `hieu luc`, nhưng người dùng thường gõ `hiệu lực`.

Nếu LLM unavailable, fallback classification có thể miss query tiếng Việt có dấu nếu normalize không chuyển Unicode chuẩn sang không dấu.

### 15.3. Warning từ LLM evidence check chưa chắc được dùng

`DeepSeekChatClient.check_evidence()` có thể trả field `warnings`, nhưng `_evidence_check()` hiện chỉ dùng `relevant` và `confidence_delta`. Nếu muốn tận dụng warning chi tiết từ LLM, cần merge chúng vào `state["warnings"]` một cách có kiểm soát.

### 15.4. `DocumentStatusRepository.find_status_records()` dùng LIKE trên cả câu hỏi

Nếu không extract được `document_number`, service dùng toàn bộ query tự nhiên để LIKE vào `document_number` hoặc `title`. Với câu hỏi dài, khả năng match chính xác có thể thấp.

Điểm này quan trọng với mode `status_basic`: câu hỏi "văn bản X còn hiệu lực không" sẽ tốt hơn nếu extract được số văn bản hoặc title rõ ràng.

### 15.5. `INACTIVE_STATUSES` đang được khai báo nhưng không dùng trực tiếp

Logic loại văn bản inactive hiện nằm gián tiếp trong `hit_allowed()`: chỉ allow active/unknown khi không include expired.

Việc `INACTIVE_STATUSES` không được dùng không nhất thiết là bug, nhưng là tín hiệu cần kiểm tra khi mở rộng rule hiệu lực.

### 15.6. Confidence là heuristic, không phải xác suất pháp lý

`confidence` được tính từ tín hiệu retrieval/graph/citation/status và một delta nhỏ từ LLM. Nó không chứng minh câu trả lời đúng về mặt pháp lý.

Với legal domain, confidence cao vẫn cần citation đủ tốt và trạng thái hiệu lực đáng tin cậy.

## 16. Cách đọc file khi debug

Nếu debug một câu trả lời sai, nên đi theo thứ tự:

1. Kiểm tra `trace_id` trong response/log.
2. Xác định `retrieval_mode`.
3. Xem `warnings`.
4. Xem `citations` có rỗng không.
5. Nếu citation rỗng, kiểm tra Chroma/BM25 có index published chưa.
6. Nếu citation có nhưng sai, kiểm tra `extract_filters()`, `hit_allowed()`, và metadata chunk.
7. Nếu status sai, kiểm tra SQLite `document_registry` và `document_relations`.
8. Nếu graph context sai/rỗng, kiểm tra Neo4j publish writer và `FixedNeo4jContextRetriever.enrich()`.
9. Nếu answer bịa hoặc quá tự tin, kiểm tra prompt `generate_answer()` và fallback `build_extractive_answer()`.

Nguyên tắc quan trọng: đừng vội kết luận "LLM sai" khi chưa kiểm tra citations, validity metadata và index state. Chat agent chỉ tốt bằng evidence mà nó nhận được.
