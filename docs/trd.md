# TRD: BaoHiem Legal AI Workspace

## 1. Document Control

| Field | Value |
| --- | --- |
| Document | Technical Requirements Document |
| Product | BaoHiem Legal AI Workspace |
| Source PRD | `docs/prd.md` version 0.3 |
| Version | 0.2 |
| Date | 2026-07-02 |
| Owner | Product/Architecture Lead |
| Target Release | Local MVP trong 1 tuần |

## 2. Purpose

TRD này chuyển PRD thành thiết kế kỹ thuật đủ cụ thể để triển khai MVP. Tài liệu tập trung vào kiến trúc local, module backend/frontend, data model, pipeline dữ liệu pháp luật, schema Neo4j, metadata ChromaDB, BM25, API Flask, workflow Streamlit, rollback và kiểm thử.

## 3. Scope

### In Scope

- Streamlit frontend.
- Flask API backend.
- Multi-user nhẹ với role `admin`, `business_user`, `guest`.
- SQLite app database local.
- Admin upload trực tiếp văn bản pháp luật dạng `.docx`; không crawl theo số hiệu từ `wsvbpl.moj.gov.vn`/`vbpl.vn` trong MVP.
- Lưu raw file, metadata do admin nhập/trích xuất, normalized metadata và audit/pipeline state.
- Neo4j graph cấp 1 giữa văn bản chỉ từ quan hệ do admin nhập hoặc xác nhận.
- Neo4j graph cấp 2 theo cấu trúc văn bản.
- ChromaDB dense vector database.
- BM25 search local qua provider abstraction.
- Hybrid retrieval cho chatbot.
- Keyword search ưu tiên BM25.
- Rà soát hợp đồng cơ bản theo module thẩm quyền và hiệu lực.
- Sinh file `.docx` skeleton chưa có template thật.
- Rollback batch import/update.

### Out of Scope

- Production security.
- Cloud deployment.
- SSO/MFA/reset password.
- Import/crawl văn bản theo số hiệu từ `wsvbpl.moj.gov.vn`/`vbpl.vn`.
- Tự động lấy quan hệ sửa đổi/thay thế/bãi bỏ từ nguồn nhà nước khi chưa có quyền truy cập hợp lệ.
- PDF/HTML legal-document ingestion khi không có `.docx`.
- Version history đầy đủ theo thời gian cho từng điều/khoản.
- Template `.docx` thật.
- Rà soát hợp đồng toàn diện ngoài module thẩm quyền và hiệu lực.

## 4. Current Codebase Baseline

Codebase hiện có các module prototype:

- `main.py`: CLI cho `ingest`, `embed`, `graph-retrieve`.
- `src/ingestion/ingest.py`: đọc `.docx`, tách paragraph/table, lưu text/chunk JSON.
- `src/ingestion/llm_splitter.py`: chunk văn bản pháp luật bằng LLM.
- `src/ingestion/embed.py`: embed chunk vào ChromaDB bằng BGE-M3.
- `src/retrieval/retrieval.py`: text-to-Cypher read-only retrieval với Neo4j.
- `prompts/`: prompt chunking, text-to-Cypher, answer generation.

TRD này yêu cầu refactor theo hướng module hóa nhưng tận dụng lại các phần trên khi phù hợp.

## 5. Architecture Overview

```text
Streamlit Frontend
  |
  | HTTP JSON / file upload
  v
Flask API Backend
  |
  +-- Auth/User Service -------- SQLite
  +-- Admin Document Service --- SQLite + raw file storage
  +-- Ingestion Pipeline ------- admin DOCX upload + metadata form + docx parser + LLM splitter
  +-- Indexing Service --------- Neo4j + ChromaDB + BM25
  +-- Retrieval Service -------- Hybrid retrieval + answer generation
  +-- Contract Review Service -- docx extraction + rules + retrieval
  +-- Docx Generation Service -- python-docx skeleton export
```

### Local Runtime Components

| Component | Technology | Purpose |
| --- | --- | --- |
| Frontend | Streamlit | UI cho user/admin/guest. |
| Backend API | Flask | REST API local. |
| App DB | SQLite | Users, pipeline, document registry, audit, review jobs. |
| Graph DB | Neo4j | Knowledge graph cấp 1 và cấp 2. |
| Vector DB | ChromaDB | Dense retrieval. |
| BM25 | Provider abstraction | MVP local BM25; có thể dùng `rank-bm25`, SQLite FTS5, hoặc Elasticsearch local nếu cấu hình. |
| LLM | DeepSeek/OpenAI-compatible API | Chunking, extraction, answer generation, optional rerank/self-check. |
| Files | Local filesystem | Raw `.docx`, extracted text, generated `.docx`, snapshots. |

## 6. Proposed Repository Structure

```text
backend/
  app.py
  config.py
  api/
    auth_routes.py
    admin_document_routes.py
    retrieval_routes.py
    contract_routes.py
    docx_routes.py
  services/
    auth_service.py
    user_service.py
    document_upload_service.py
    ingestion_service.py
    indexing_service.py
    retrieval_service.py
    contract_review_service.py
    docx_generation_service.py
    rollback_service.py
  models/
    sqlite_schema.sql
    repositories.py
frontend/
  streamlit_app.py
  pages/
    chat.py
    keyword_search.py
    contract_review.py
    docx_draft.py
    admin_documents.py
    admin_pipeline.py
    admin_users.py
src/
  ingestion/
  indexing/
  retrieval/
  contract_review/
  doc_generation/
  common/
data/
  raw/
  preprocessed/
  chunked/
  generated/
  snapshots/
  chroma/
docs/
  prd.md
  trd.md
```

## 7. Configuration

Environment variables:

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `APP_ENV` | No | `local` | Runtime environment. |
| `FLASK_SECRET_KEY` | Yes | None | Session/JWT signing key. |
| `SQLITE_DB_PATH` | No | `data/app.sqlite3` | App DB path. |
| `NEO4J_URI` | Yes | `bolt://localhost:7687` | Neo4j URI. |
| `NEO4J_USER` | Yes | `neo4j` | Neo4j username. |
| `NEO4J_PASSWORD` | Yes | None | Neo4j password. |
| `CHROMA_PATH` | No | `data/chroma/legal` | ChromaDB path. |
| `CHROMA_COLLECTION` | No | `legal_chunks` | Chroma collection. |
| `BM25_PROVIDER` | No | `local` | `local`, `sqlite_fts`, or `elasticsearch`. |
| `ELASTICSEARCH_URL` | No | None | Optional local Elasticsearch endpoint. |
| `DEEPSEEK_API_KEY` | Conditional | None | Required if DeepSeek is used. |
| `OPENAI_API_KEY` | Conditional | None | Required if OpenAI is used. |
| `LLM_PROVIDER` | No | `deepseek` | `deepseek` or `openai`. |
| `LLM_MODEL_CHAT` | No | provider default | Answer generation model. |
| `LLM_MODEL_CHUNKING` | No | provider default | Chunking/extraction model. |
| `EMBEDDING_MODEL` | No | `BAAI/bge-m3` | Dense embedding model. |

## 8. Data Storage Design

### 8.1 SQLite App DB

SQLite là source of truth cho app-level state: users, pipeline, document registry, batch versioning, audit log và job state. Neo4j/Chroma/BM25 là indexes có thể rebuild từ registry + raw/chunk data.

#### `users`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `username` | TEXT UNIQUE | Login name. |
| `password_hash` | TEXT | Werkzeug password hash. |
| `role` | TEXT | `admin`, `business_user`, `guest`. |
| `is_active` | INTEGER | 0/1. |
| `created_at` | TEXT | ISO datetime. |
| `updated_at` | TEXT | ISO datetime. |

#### `document_registry`

| Column | Type | Notes |
| --- | --- | --- |
| `document_id` | TEXT PK | Stable UUID. |
| `document_number` | TEXT | Số hiệu. |
| `title` | TEXT | Tên văn bản. |
| `source_system` | TEXT | `admin_upload` by default. |
| `source_url` | TEXT | Optional canonical source URL entered by admin. |
| `sector` | TEXT | Ngành. |
| `domain` | TEXT | Lĩnh vực. |
| `issuing_body` | TEXT | Cơ quan ban hành. |
| `signer_title` | TEXT | Chức danh người ký. |
| `signer_name` | TEXT | Người ký. |
| `document_type` | TEXT | Loại văn bản. |
| `issued_date` | TEXT | ISO date. |
| `effective_date` | TEXT | ISO date. |
| `expiry_date` | TEXT | ISO date nullable. |
| `validity_status` | TEXT | `active`, `expired`, `replaced`, `abolished`, `suspended`, `unknown`. |
| `raw_metadata_json` | TEXT | Metadata entered by admin plus extraction hints from DOCX. |
| `active_version` | INTEGER | Published version. |
| `is_published` | INTEGER | 0/1. |
| `is_deleted` | INTEGER | Soft delete. |
| `created_at` | TEXT | ISO datetime. |
| `updated_at` | TEXT | ISO datetime. |

#### `document_versions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `document_id` | TEXT | FK logical. |
| `version` | INTEGER | Monotonic per document. |
| `import_batch_id` | TEXT | Batch that created version. |
| `raw_docx_path` | TEXT | Original `.docx`. |
| `preprocessed_text_path` | TEXT | Extracted text. |
| `chunk_json_path` | TEXT | Chunk JSON. |
| `metadata_json` | TEXT | Normalized metadata. |
| `status` | TEXT | `draft`, `ready_for_review`, `published`, `rolled_back`, `failed`. |
| `created_at` | TEXT | ISO datetime. |

#### `document_relations`

Stores admin-curated normalized relations for audit/rebuild. Neo4j is the graph index. DOCX upload alone is not treated as enough evidence to create document-level legal relations.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `source_document_id` | TEXT | From document. |
| `target_document_id` | TEXT | To document. |
| `relation_type` | TEXT | Canonical relation label. |
| `source_text` | TEXT | Admin note, source excerpt, or verification text if available. |
| `import_batch_id` | TEXT | Batch source. |
| `is_published` | INTEGER | 0/1. |

#### `pipeline_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | Batch/job UUID. |
| `pipeline_type` | TEXT | `import_document`, `update_effectivity`, `rebuild_indexes`. |
| `requested_by_user_id` | TEXT | User UUID. |
| `input_json` | TEXT | Upload metadata, original filename, and admin-provided fields. |
| `status` | TEXT | See pipeline states. |
| `error_message` | TEXT | Nullable. |
| `created_at` | TEXT | ISO datetime. |
| `updated_at` | TEXT | ISO datetime. |

#### `pipeline_events`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `pipeline_run_id` | TEXT | Parent. |
| `state` | TEXT | State name. |
| `message` | TEXT | Human-readable detail. |
| `payload_json` | TEXT | Structured debug payload. |
| `created_at` | TEXT | ISO datetime. |

#### `chat_interactions`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `user_id` | TEXT | User UUID. |
| `query` | TEXT | User question. |
| `mode` | TEXT | `chat` or `keyword`. |
| `answer` | TEXT | Generated answer. |
| `confidence` | REAL | 0..1. |
| `citations_json` | TEXT | Citation list. |
| `created_at` | TEXT | ISO datetime. |

#### `contract_review_jobs`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | TEXT PK | UUID. |
| `user_id` | TEXT | User UUID. |
| `file_path` | TEXT | Uploaded contract path. |
| `extracted_text_path` | TEXT | Extracted text. |
| `status` | TEXT | `pending`, `processing`, `completed`, `failed`. |
| `result_json` | TEXT | Review result. |
| `created_at` | TEXT | ISO datetime. |

## 9. Canonical Enums

### 9.1 Pipeline States

```text
pending
uploaded
parsed
chunked
graph_indexed
vector_indexed
bm25_indexed
ready_for_review
published
failed
rolled_back
```

### 9.2 Document Validity Status

Internal values:

```text
active
expired
replaced
abolished
suspended
partially_effective
unknown
```

UI labels:

- `active`: Còn hiệu lực.
- `expired`: Hết hiệu lực.
- `replaced`: Bị thay thế.
- `abolished`: Bị bãi bỏ.
- `suspended`: Bị đình chỉ/tạm ngưng hiệu lực.
- `partially_effective`: Còn hiệu lực một phần.
- `unknown`: Chưa xác định.

## 10. Neo4j Knowledge Graph Design

### 10.1 Design Decision

Store canonical directed edges only. UI and query layer can derive inverse relations by querying incoming edges. This avoids duplicate inconsistency. If a future query is too slow, inverse materialized edges can be added as an optimization.

Document-level edges are curated data. The importer may create the `Document` node from uploaded DOCX metadata, but it must create graph cấp 1 relation edges only when admin provides or confirms relation records.

### 10.2 Node Labels

```text
Document
Chapter
Section
Article
Clause
```

### 10.3 `Document` Properties

```text
document_id
source_system
source_url
title
document_number
sector
domain
issuing_body
signer_title
signer_name
document_type
issued_date
effective_date
expiry_date
validity_status
import_batch_id
published_version
is_published
```

### 10.4 Structure Node Properties

Shared:

```text
node_id
document_id
document_number
document_title
document_type
issuing_body
effective_date
expiry_date
validity_status
hierarchy_path
content
published_version
import_batch_id
is_published
```

Specific:

```text
chapter_number
chapter_title
section_number
section_title
article_number
article_title
clause_number
chunk_level
```

### 10.5 Structure Relationships

```cypher
(Document)-[:HAS_CHAPTER]->(Chapter)
(Document)-[:HAS_ARTICLE]->(Article)
(Chapter)-[:HAS_SECTION]->(Section)
(Chapter)-[:HAS_ARTICLE]->(Article)
(Section)-[:HAS_ARTICLE]->(Article)
(Article)-[:HAS_CLAUSE]->(Clause)
```

### 10.6 Document Relationship Labels

Use English canonical labels in Neo4j. UI maps them to Vietnamese labels.

| Neo4j Label | Meaning |
| --- | --- |
| `GUIDES_APPLICATION_OF` | Văn bản hướng dẫn áp dụng văn bản khác. |
| `DETAILS_OR_GUIDES_IMPLEMENTATION_OF` | Quy định chi tiết, hướng dẫn thi hành. |
| `CONSOLIDATES` | Văn bản hợp nhất văn bản khác. |
| `AMENDS_OR_SUPPLEMENTS` | Sửa đổi, bổ sung. |
| `CORRECTS` | Đính chính. |
| `REPLACES` | Thay thế. |
| `ABOLISHES` | Bãi bỏ. |
| `APPLIES` | Áp dụng. |
| `CITES_AS_LEGAL_BASIS` | Dẫn chiếu/căn cứ ban hành. |
| `EXPLAINS` | Giải thích. |
| `SUSPENDS_IMPLEMENTATION_OF` | Đình chỉ thi hành. |
| `TEMPORARILY_SUSPENDS_EFFECT_OF` | Tạm ngưng hiệu lực. |
| `ANNOUNCES` | Công bố. |
| `RELATED_TO` | Quan hệ khác/chưa phân loại. |

Incoming relation is rendered as inverse in UI. Example:

- `A -[:REPLACES]-> B`: A là văn bản thay thế, B là văn bản được/bị thay thế.
- `A -[:CITES_AS_LEGAL_BASIS]-> B`: A căn cứ/dẫn chiếu B.

### 10.7 Indexes and Constraints

Required:

```cypher
CREATE CONSTRAINT document_id_unique IF NOT EXISTS
FOR (d:Document) REQUIRE d.document_id IS UNIQUE;

CREATE INDEX document_number_index IF NOT EXISTS
FOR (d:Document) ON (d.document_number);

CREATE INDEX document_validity_index IF NOT EXISTS
FOR (d:Document) ON (d.validity_status);

CREATE CONSTRAINT structure_node_id_unique IF NOT EXISTS
FOR (n:Article) REQUIRE n.node_id IS UNIQUE;

CREATE CONSTRAINT clause_node_id_unique IF NOT EXISTS
FOR (n:Clause) REQUIRE n.node_id IS UNIQUE;
```

Optional indexes:

```cypher
CREATE INDEX article_number_index IF NOT EXISTS
FOR (a:Article) ON (a.article_number);

CREATE INDEX clause_number_index IF NOT EXISTS
FOR (c:Clause) ON (c.clause_number);
```

## 11. ChromaDB Vector Design

### 11.1 Collection

Collection name:

```text
legal_chunks
```

Embedding model:

```text
BAAI/bge-m3
```

### 11.2 Document Text

Vector document content:

- `Clause.content` if article has clauses.
- `Article.content` if article has no clauses.

Do not embed generated citations or metadata-only strings as primary content.

### 11.3 Metadata

Every vector record must include:

```json
{
  "chunk_id": "string",
  "document_id": "string",
  "document_number": "string",
  "document_title": "string",
  "document_type": "string",
  "source_system": "admin_upload",
  "source_url": "string|null",
  "sector": "string",
  "domain": "string",
  "issuing_body": "string",
  "signer_title": "string",
  "signer_name": "string",
  "issued_date": "YYYY-MM-DD",
  "effective_date": "YYYY-MM-DD",
  "expiry_date": "YYYY-MM-DD|null",
  "validity_status": "active|expired|replaced|abolished|suspended|partially_effective|unknown",
  "chapter_number": "string|null",
  "chapter_title": "string|null",
  "section_number": "string|null",
  "section_title": "string|null",
  "article_number": "string",
  "article_title": "string|null",
  "clause_number": "string|null",
  "hierarchy_path": "string",
  "chunk_level": "article|clause",
  "citation_label": "string",
  "neo4j_node_id": "string",
  "published_version": 1,
  "import_batch_id": "string"
}
```

Chroma metadata values should be scalar. If a field is logically list-like, serialize it as JSON string or store it in SQLite/Neo4j instead.

### 11.4 Filtering

Default retrieval filter:

```json
{
  "validity_status": "active",
  "is_published": true
}
```

If Chroma provider does not support boolean cleanly, store `is_published` as integer `1`.

## 12. BM25 Design

### 12.1 Provider Interface

Define a provider interface:

```python
class BM25Provider:
    def index_chunks(self, chunks: list[ChunkRecord]) -> None: ...
    def delete_by_batch(self, import_batch_id: str) -> None: ...
    def search(self, query: str, filters: dict, top_k: int) -> list[SearchHit]: ...
```

### 12.2 MVP Provider

Recommended MVP order:

1. `sqlite_fts`: SQLite FTS5 for easiest local setup and persistence.
2. `local`: `rank-bm25` in-memory index rebuilt on startup for quick prototype.
3. `elasticsearch`: optional local Elasticsearch/OpenSearch if user configures it.

The API and retrieval service must not depend directly on a specific provider.

### 12.3 Indexed Fields

BM25 index document:

```json
{
  "chunk_id": "string",
  "content": "string",
  "document_number": "string",
  "document_title": "string",
  "article_number": "string",
  "clause_number": "string",
  "citation_label": "string",
  "validity_status": "active",
  "is_published": 1,
  "published_version": 1,
  "import_batch_id": "string"
}
```

## 13. Ingestion Pipeline

### 13.1 Import by Admin DOCX Upload

Input:

`multipart/form-data` with:

| Field | Required | Notes |
| --- | --- | --- |
| `file` | Yes | `.docx` legal document uploaded by admin. |
| `document_number` | Yes | Document number entered by admin. |
| `title` | Yes | Document title entered by admin or confirmed from extraction. |
| `source_url` | No | Original source URL if admin has it. |
| `issued_date` | No | ISO date if known. |
| `effective_date` | No | ISO date if known. |
| `expiry_date` | No | ISO date if known. |
| `validity_status` | No | Defaults to `unknown` if not supplied. |
| `relations_json` | No | Admin-curated document relations, not inferred from upload alone. |

Pipeline:

1. Create `pipeline_runs` row with `pending`.
2. Validate extension and MIME signature as `.docx`; otherwise mark `failed` with `DOCX_REQUIRED`.
3. Save raw `.docx` to `data/raw/{import_batch_id}/{safe_filename}.docx`.
4. Mark state `uploaded`.
5. Parse `.docx` to text.
6. Extract best-effort metadata hints from text, but do not trust them until admin review.
7. Merge admin-provided metadata with extraction hints.
8. Chunk text into `Article`/`Clause` units.
9. Normalize metadata and inherit to chunks.
10. Write chunk JSON to `data/chunked/{import_batch_id}/{document_id}.json`.
11. Build Neo4j structure graph.
12. Build Neo4j document node and document-level relations only for admin-curated `relations_json`.
13. Add vectors to ChromaDB.
14. Add chunks to BM25.
15. Mark `ready_for_review`.
16. Admin reviews metadata, extraction warnings, and optional relations.
17. Admin publishes.

### 13.2 Admin-Curated Relation Handling

Because MVP does not access `wsvbpl.moj.gov.vn`/`vbpl.vn`, the system must not infer document-level legal relations from the uploaded DOCX alone.

Rules:

- If `relations_json` is absent, create only the `Document` node and structure graph; do not create relation edges in graph cấp 1.
- If a relation references a document that is not in `document_registry`, store it as unresolved metadata and show it as `unresolved_relation` in admin UI.
- If admin later imports the target document, the system may resolve the relation during rebuild.
- Chatbot and contract review must treat missing relation data as `insufficient_data`, not as proof that no relation exists.

### 13.3 Metadata Normalization

Normalize Vietnamese UI/source labels into internal fields:

| Source Label | Internal Field |
| --- | --- |
| Số hiệu | `document_number` |
| Ngành | `sector` |
| Lĩnh vực | `domain` |
| Cơ quan ban hành | `issuing_body` |
| Chức danh | `signer_title` |
| Người ký | `signer_name` |
| Loại văn bản | `document_type` |
| Ngày ban hành | `issued_date` |
| Ngày có hiệu lực | `effective_date` |
| Ngày hết hiệu lực | `expiry_date` |
| Tình trạng hiệu lực | `validity_status` |

### 13.4 Chunking Requirements

Chunking output schema:

```json
{
  "content": "string",
  "metadata": {
    "chapter_number": "string|null",
    "chapter_title": "string|null",
    "section_number": "string|null",
    "section_title": "string|null",
    "article_number": "string",
    "article_title": "string|null",
    "clause_number": "string|null",
    "hierarchy_path": "string",
    "chunk_level": "article|clause"
  }
}
```

Validation rules:

- `content` must not be empty.
- `article_number` is required.
- `chunk_level = clause` requires `clause_number`.
- `chunk_level = article` allows `clause_number = null`.
- `hierarchy_path` is required.
- Chunk content should not include unrelated neighboring articles.

## 14. Publishing and Rollback

### 14.1 Publishing

Publish should:

1. Mark previous version of the same document as inactive/unpublished.
2. Mark new `document_versions.status = published`.
3. Set `document_registry.active_version`.
4. Ensure Neo4j nodes for new version have `is_published = true`.
5. Ensure Chroma/BM25 chunks for new version are queryable.
6. Record audit event.

### 14.2 Rollback Strategy

MVP rollback is batch-based.

Rollback should:

1. Identify `import_batch_id`.
2. Mark affected SQLite `document_versions` as `rolled_back`.
3. Restore previous active version in `document_registry` if available.
4. In Neo4j, set nodes/relationships with `import_batch_id` to `is_published = false`.
5. In ChromaDB, delete records by `import_batch_id` if supported; otherwise rebuild collection from published SQLite/chunk data.
6. In BM25, delete records by `import_batch_id` or rebuild index.
7. Mark pipeline `rolled_back`.

If any index rollback fails, app DB remains the source of truth and system must show `partial rollback failure`.

## 15. Retrieval Design

### 15.1 Query Modes

| Mode | Trigger | Primary Retrieval |
| --- | --- | --- |
| `keyword` | User chooses keyword search | BM25 first. |
| `chat` | Natural-language question | Hybrid retrieval. |

### 15.2 Hybrid Retrieval Flow

1. Classify query as `keyword` or `chat`.
2. Apply default filter: published + active documents.
3. Run dense vector search top K.
4. Run BM25 search top K.
5. Query Neo4j document graph for relation/effectivity context if admin-curated relations exist.
6. Query Neo4j structure graph for article/clause context.
7. Merge hits by `chunk_id` / `neo4j_node_id`.
8. Rerank with weighted score.
9. Build context pack.
10. Generate answer with answer prompt.
11. Validate citation coverage.
12. Return answer, citations, confidence, warnings.

### 15.3 Scoring

MVP confidence:

```text
confidence =
  0.35 * normalized_dense_score
+ 0.25 * normalized_bm25_score
+ 0.20 * graph_support_score
+ 0.10 * citation_score
+ 0.10 * validity_score
```

Definitions:

- `graph_support_score = 1` if Neo4j confirms article/clause structure and any available curated relation for top citation, `0.7` if structure graph confirms article/clause but no document-level relation data exists, `0.5` if only document exists, else `0`.
- `citation_score = 1` if at least one citation has document + article/clause, else `0.5` if document-only, else `0`.
- `validity_score = 1` if all top citations are active, `0.5` if status is `unknown` and warning is shown, else `0`.

Warning thresholds:

- `confidence < 0.55`: show "Không đủ căn cứ chắc chắn".
- no citation: answer must refuse or ask admin to update data.
- no active result: answer must say no active legal basis found in current knowledge base.
- missing document-level relation data: answer may proceed for content lookup but must warn that amendment/replacement/abolition relationships may be incomplete.

### 15.4 Context Pack

Answer-generation context format:

```json
{
  "question": "string",
  "retrieval_mode": "chat",
  "citations": [
    {
      "citation_label": "string",
      "document_number": "string",
      "document_title": "string",
      "article_number": "string",
      "clause_number": "string|null",
      "validity_status": "active",
      "content": "string",
      "source_url": "string"
    }
  ],
  "graph_context": {
    "related_documents": [],
    "effectivity_relations": []
  }
}
```

## 16. Contract Review Design

### 16.1 Supported Input

MVP supports uploaded `.docx` contracts only.

### 16.2 Processing Flow

1. Store upload under `data/uploads/contracts/{job_id}.docx`.
2. Extract text via `python-docx`.
3. Extract fields:
   - `issuing_body`
   - `signer_title`
   - referenced legal documents
   - dates/effectivity mentions
4. Run authority review module.
5. Run effectivity review module.
6. Retrieve supporting legal basis from active knowledge base.
7. Produce structured JSON result.

### 16.3 Output Schema

```json
{
  "job_id": "string",
  "status": "completed",
  "authority_review": {
    "issuing_body": {
      "value": "string|null",
      "result": "valid|invalid|insufficient_data",
      "reason": "string",
      "citations": []
    },
    "signer_title": {
      "value": "string|null",
      "result": "valid|invalid|insufficient_data",
      "reason": "string",
      "citations": []
    }
  },
  "effectivity_review": {
    "result": "active|inactive|conflict|insufficient_data",
    "referenced_documents": [],
    "warnings": [],
    "citations": []
  }
}
```

### 16.4 MVP Rule Strategy

Rules are initially stored as JSON files under:

```text
data/rules/
  authority_rules.json
  effectivity_rules.json
```

If rule file is missing or incomplete, module returns `insufficient_data` instead of inventing a legal conclusion.

## 17. Docx Generation Skeleton

### 17.1 Input

```json
{
  "document_type": "proposal|contract|appendix|other",
  "title": "string",
  "summary": "string",
  "requested_by": "string"
}
```

### 17.2 Output

Generated `.docx` saved under:

```text
data/generated/docx/{user_id}/{document_id}.docx
```

The document must include:

- Title.
- Metadata section.
- Draft body placeholder.
- Explicit line: "Bản nháp tự động, chưa áp dụng template chính thức và cần rà soát trước khi sử dụng."

## 18. Flask API Design

Base path:

```text
/api/v1
```

### 18.1 Auth

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/auth/login` | public | Login. |
| POST | `/auth/logout` | authenticated | Logout. |
| GET | `/auth/me` | authenticated | Current user. |

### 18.2 Admin Users

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/admin/users` | admin | List users. |
| POST | `/admin/users` | admin | Create user. |
| PATCH | `/admin/users/{id}` | admin | Update user/role/status. |

### 18.3 Admin Documents

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/admin/documents` | admin | List registry documents. |
| GET | `/admin/documents/{document_id}` | admin | Document detail. |
| PATCH | `/admin/documents/{document_id}` | admin | Edit normalized metadata. |
| DELETE | `/admin/documents/{document_id}` | admin | Soft delete. |
| POST | `/admin/documents/import` | admin | Upload legal `.docx` and start import pipeline. |
| POST | `/admin/documents/{document_id}/publish` | admin | Publish reviewed version. |
| POST | `/admin/pipeline/{run_id}/rollback` | admin | Rollback batch. |
| POST | `/admin/effectivity/update` | admin | Manual metadata/effectivity update from admin input. |

### 18.4 Pipeline

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| GET | `/admin/pipeline` | admin | List pipeline runs. |
| GET | `/admin/pipeline/{run_id}` | admin | Run detail and events. |

### 18.5 Retrieval

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/chat/query` | business_user/admin | Ask natural-language question. |
| POST | `/search/keyword` | business_user/admin | Keyword search. |

Chat request:

```json
{
  "question": "string",
  "top_k": 8
}
```

Chat response:

```json
{
  "answer": "string",
  "confidence": 0.78,
  "warnings": [],
  "citations": [
    {
      "citation_label": "string",
      "document_number": "string",
      "article_number": "string",
      "clause_number": "string|null",
      "source_url": "string"
    }
  ]
}
```

### 18.6 Contract Review

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/contracts/review` | business_user/admin | Upload and review contract. |
| GET | `/contracts/review/{job_id}` | owner/admin | Get review result. |

### 18.7 Docx Draft

| Method | Path | Role | Purpose |
| --- | --- | --- | --- |
| POST | `/docx/draft` | business_user/admin | Generate skeleton docx. |
| GET | `/docx/draft/{id}/download` | owner/admin | Download generated file. |

## 19. Streamlit Frontend Design

Pages:

- Login.
- Chatbot.
- Keyword Search.
- Contract Review.
- Docx Draft.
- Admin Documents.
- Admin DOCX Import.
- Admin Pipeline.
- Admin Users.

Frontend should call Flask only. It should not import backend services directly.

Session state:

```text
access_token/session_cookie
current_user
current_role
```

Admin update-effectivity action must show confirmation text from PRD before API call.

## 20. Security Requirements

MVP local security:

- Passwords hashed with Werkzeug or Passlib.
- Role checks on every protected endpoint.
- Uploaded filenames must be sanitized.
- Uploaded files stored outside source directories.
- File downloads require owner/admin check.
- Do not log API keys.
- Do not expose `.env` content in UI.

Known limitations:

- No SSO.
- No MFA.
- No production hardening.
- No public internet deployment.

## 21. Error Handling

Common error codes:

| Code | Meaning |
| --- | --- |
| `AUTH_REQUIRED` | Not logged in. |
| `FORBIDDEN` | Role not allowed. |
| `DOCUMENT_NOT_FOUND` | Document missing. |
| `DOCX_REQUIRED` | Uploaded file is missing or not `.docx`. |
| `METADATA_INCOMPLETE` | Required admin metadata is missing. |
| `RELATIONS_UNAVAILABLE` | Document-level relations are unavailable or not yet curated. |
| `DOCX_PARSE_FAILED` | Cannot parse document. |
| `CHUNK_VALIDATION_FAILED` | Chunk schema invalid. |
| `NEO4J_INDEX_FAILED` | Graph indexing failed. |
| `VECTOR_INDEX_FAILED` | Chroma indexing failed. |
| `BM25_INDEX_FAILED` | BM25 indexing failed. |
| `LOW_CONFIDENCE` | Retrieval confidence too low. |
| `NO_CITATION` | No valid citation. |
| `ROLLBACK_PARTIAL_FAILURE` | Rollback incomplete. |

## 22. Observability

MVP logging:

- Python `logging`.
- One log file per day under `log/app-{date}.log`.
- Pipeline events in SQLite.
- For LLM calls, log prompt type/model/status/duration, not full sensitive content by default.

Metrics to record:

- Chat latency.
- Retrieval mode.
- Number of citations.
- Confidence score.
- Pipeline duration per state.
- Import success/failure count.
- Rollback success/failure count.

## 23. Testing Requirements

### 23.1 Unit Tests

- Metadata normalization.
- Relation normalization.
- Chunk schema validation.
- Pipeline state transitions.
- Role authorization.
- Confidence scoring.
- Citation validation.

### 23.2 Integration Tests

- Import sample `.docx` from local fixture.
- Build Neo4j graph for fixture.
- Add vectors to ChromaDB test path.
- Add BM25 index.
- Run keyword search.
- Run chat retrieval with mocked LLM answer.
- Rollback batch.

### 23.3 Evaluation Set

Create `tests/eval/legal_questions.jsonl`:

```json
{
  "id": "q001",
  "question": "string",
  "expected_document_number": "string",
  "expected_article": "string|null",
  "expected_answer_points": ["string"],
  "must_be_active": true
}
```

Pass criteria:

- Overall legal answer accuracy >= 80%.
- Citation coverage >= 90%.
- Active-document retrieval >= 90%.

## 24. Migration Plan From Current Prototype

1. Keep existing `src/ingestion` functions but wrap them behind `IngestionService`.
2. Fix hardcoded Chroma path/collection in embed logic.
3. Add stable `document_id`, `chunk_id`, `import_batch_id`.
4. Add SQLite app DB and repositories.
5. Add Neo4j graph writer separate from text-to-Cypher retriever.
6. Add BM25 provider.
7. Add Flask API.
8. Add Streamlit pages.
9. Add contract review and docx skeleton services.
10. Add rollback based on batch/version.

## 25. Implementation Milestones

### Milestone 1: Foundation

- SQLite schema.
- Flask app shell.
- Auth/session.
- Streamlit login.

### Milestone 2: Admin DOCX Import

- Admin `.docx` upload import.
- Required metadata validation and DOCX-only error handling.
- Metadata extraction and pipeline state.
- Admin review page.

### Milestone 3: Indexing

- Neo4j graph writer.
- Chroma writer.
- BM25 writer.
- Publish workflow.

### Milestone 4: Retrieval

- Keyword search.
- Hybrid retrieval.
- Answer generation.
- Citation/confidence validation.

### Milestone 5: Contract Review & Docx

- Contract upload.
- Authority/effectivity review skeleton.
- Docx draft generation.

### Milestone 6: QA

- Test fixtures.
- Rollback test.
- Eval set.
- UX bug pass.

## 26. Open Technical Decisions

- Whether BM25 default should be SQLite FTS5 or Elasticsearch local.
- Exact LLM model names and token/cost limits.
- Whether to use background worker thread/process for long import jobs.
- How much manual admin editing is allowed before publish.
- Which metadata fields should block publish versus only produce warnings.
- How unresolved document relations should be reviewed and resolved after later imports.
- Whether Guest can access any real retrieval endpoint.
- Whether to store chat history in MVP UI.

## 27. Acceptance Criteria

MVP is technically acceptable when:

- Admin can create users and assign roles.
- Admin can upload a legal `.docx` document with required metadata.
- Import pipeline reaches `ready_for_review`.
- Admin can publish imported document.
- Neo4j contains document and structure graph for the document.
- Neo4j contains document-level relation edges only when admin provided/confirmed them; otherwise UI and answer warnings show relation data is unavailable.
- ChromaDB contains vector chunks with required metadata.
- BM25 search returns active chunks with citations.
- Chat query returns answer, confidence and citation.
- Contract review accepts `.docx` and returns structured thẩm quyền/hiệu lực result.
- Docx skeleton can be generated and downloaded.
- Rollback can disable a published batch and remove/rebuild indexes.
- Evaluation set reaches target metrics or clearly reports failures.
