# Backend Overview

Tài liệu này mô tả các function/class chính trong phần backend theo hướng top-down: bắt đầu từ lúc app khởi động, đi qua API route, rồi xuống service/database/indexing. Các function được nhóm theo file để dễ đối chiếu với code.

## 1. Luồng tổng quan

### 1.1. Khởi động ứng dụng

Luồng khởi động đi từ `backend/app.py`:

```text
create_app()
  -> Config.from_env()
  -> init_db()
  -> seed_admin_user()
  -> register admin/auth/chat blueprints
  -> /api/v1/health
```

Ý nghĩa:

- `Config.from_env()` đọc cấu hình từ `.env`/environment.
- `init_db()` tạo SQLite schema và chạy migration nhỏ để giữ database cũ tương thích.
- `seed_admin_user()` tạo admin đầu tiên nếu có `ADMIN_USERNAME` và `ADMIN_PASSWORD`.
- Các route được chia thành 3 blueprint:
  - `/api/v1/auth`: đăng ký, đăng nhập, đăng xuất, xem user hiện tại.
  - `/api/v1/admin`: quản lý user, upload/review/publish/rollback/delete văn bản.
  - `/api/v1/chat`: nhận câu hỏi và lưu lịch sử chat.

### 1.2. Luồng auth

```text
POST /api/v1/auth/login
  -> AuthService.login()
    -> get_user_by_username()
    -> check_password_hash()
    -> tạo auth_sessions với token_hash

Các route cần đăng nhập
  -> require_auth()
    -> extract_bearer_token()
    -> AuthService.get_user_for_token()
    -> g.current_user

Các route admin
  -> require_role("admin")
    -> require_auth()
    -> kiểm tra role trong g.current_user
```

Token thật chỉ trả về cho client một lần. Backend lưu `sha256(token)` trong `auth_sessions`, nhờ vậy database không giữ raw access token.

### 1.3. Luồng import DOCX

```text
POST /api/v1/admin/documents/import
  -> DocumentImportService.import_document()
    -> _create_pipeline_run()
    -> _validate_docx()
    -> _save_raw_docx()
    -> extract_docx()
    -> extract_metadata_hints()
    -> _parse_metadata()
       -> infer_metadata_with_deepseek()
       -> parse_relations_json()
    -> _upsert_document_registry()
    -> _write_preprocessed_text()
    -> build_normalized_metadata()
    -> _chunk_text()
       -> LLMVietnameseLegalSplitter nếu bật LLM chunking
       -> regex_chunk_text() fallback
    -> validate_chunks()
    -> _write_chunks()
    -> _store_version_and_relations()
    -> _mark_pipeline(... ready_for_review ...)
    -> trả về is_publishable/publish_blockers
  -> nếu is_publishable: DocumentIndexingService.enqueue_publish_document()
```

SQLite là source of truth ở tầng app: `document_registry`, `document_versions`, `document_relations`, `pipeline_runs`, `pipeline_events`. Chroma, Neo4j và Elasticsearch/BM25 là index rebuild được từ dữ liệu/version đã lưu.

### 1.4. Luồng sửa review rồi publish

```text
PATCH /documents/<id>/metadata
PATCH /documents/<id>/chunks
PUT   /documents/<id>/relationships
  -> DocumentImportService.update_...()
    -> _ensure_editable_latest_version()
       -> nếu latest đang là active/published thì _clone_active_version_for_edit()
    -> ghi metadata/chunks/relations vào latest editable version
    -> status = ready_for_review
  -> nếu query ?auto_publish=1 và is_publishable:
       DocumentIndexingService.enqueue_publish_document()
```

Điểm quan trọng: backend không sửa trực tiếp version active đã publish. Nếu văn bản đã publish, service clone bản active thành version mới `ready_for_review`, rồi mọi chỉnh sửa đi vào version mới đó.

### 1.5. Luồng publish/indexing

```text
POST /api/v1/admin/documents/<id>/publish
  -> DocumentIndexingService.enqueue_publish_document()
    -> _validate_publish_candidate()
    -> _get_active_publish_run()
    -> _create_pipeline_run(status=queued)
    -> submit_publish_job()
      -> _run_publish_job()
        -> run_publish_pipeline()
          -> load_chunk_json()
          -> validate_chunks()
          -> normalize_chunk_records()
          -> collect_publish_warnings()
          -> _get_relations()
          -> build_default_indexing_providers()
          -> Neo4jGraphWriter.index_chunks()
          -> ChromaVectorProvider.index_chunks()
          -> ElasticsearchBM25Provider.index_chunks()
          -> _unpublish_old_batches()
          -> _mark_sqlite_published()
          -> _mark_pipeline(status=published)
```

Publish chạy qua `ThreadPoolExecutor(max_workers=1)`, nên API trả về `202` với trạng thái `queued`; chi tiết tiến trình nằm trong `pipeline_runs` và `pipeline_events`.

### 1.6. Luồng rollback/delete

```text
POST /api/v1/admin/pipeline/<run_id>/rollback
  -> DocumentIndexingService.rollback_pipeline()
    -> cleanup_indexed_batch()
    -> _get_previous_restorable_version()
    -> index lại version trước nếu có
    -> _mark_sqlite_rolled_back()

DELETE /api/v1/admin/documents/<id>
  -> DocumentIndexingService.delete_document()
    -> cleanup indexes theo import_batch_id
    -> xóa document_relations/document_versions/document_registry
    -> delete_artifacts_safely()
```

Delete có guard `delete_artifacts_safely()` để chỉ xóa file trong các thư mục quản lý: `data/raw`, `data/preprocessed`, `data/chunked`.

### 1.7. Luồng chat hiện tại

```text
POST /api/v1/chat
  -> _build_fallback_answer()
  -> nếu có token hợp lệ:
       ChatHistoryService.ensure_conversation()
       ChatHistoryService.add_message(user)
       ChatHistoryService.add_message(assistant)
```

Frontend guest mode is temporary and anonymous: it has no access token, is not a
persisted backend session, cannot open profile pages, and should be routed
toward login/register when the user wants saved history or account settings.

Route chat hiện chưa gọi retrieval/index thật. Nó trả fallback answer cố định và chỉ lưu lịch sử khi request có Bearer token hợp lệ.

## 2. `backend/app.py`

### `create_app(config: Config | None = None) -> Flask`

Entry point tạo Flask app.

Cách implement:

- Bật logging mức `INFO`.
- Lấy config truyền vào hoặc gọi `Config.from_env()`.
- Tạo `Flask(__name__)`, lưu `SECRET_KEY` và `APP_CONFIG` vào `app.config`.
- Gọi `init_db(app_config.sqlite_db_path)` để đảm bảo SQLite sẵn sàng.
- Gọi `seed_admin_user(app_config)` để seed admin nếu env hợp lệ.
- Register `admin_bp`, `auth_bp`, `chat_bp`.
- Định nghĩa route health check `GET /api/v1/health`.

### `health_check()`

Nested route bên trong `create_app()`.

Cách implement:

- Trả JSON gồm `status`, `app_env`, `sqlite_db_path`.
- Dùng để kiểm tra backend đã khởi động và đang trỏ tới DB nào.

## 3. `backend/config.py`

### `Config`

Dataclass immutable chứa toàn bộ cấu hình backend: Flask secret, SQLite path, admin seed, token TTL, Neo4j, Chroma, Elasticsearch/BM25, LLM, embedding model.

### `Config.from_env() -> Config`

Cách implement:

- Gọi `os.getenv()` cho từng biến môi trường.
- Dùng helper `_int_from_env`, `_bool_from_env`, `_sqlite_db_path_from_env` để parse kiểu dữ liệu.
- Có fallback tương thích cho một số tên env cũ như `NEO4J_USERNAME`, `DEEPSEEK_MODEL_METADATA`.

### `_int_from_env(name, default) -> int`

Đọc env và ép sang `int`; nếu không có hoặc parse lỗi thì trả `default`.

### `_bool_from_env(name, default) -> bool`

Đọc env dạng `"1"`, `"true"`, `"yes"`, `"on"` là `True`; không có env thì trả `default`.

### `_sqlite_db_path_from_env(name, default) -> str`

Chuẩn hóa SQLite path:

- Rỗng thì dùng default.
- `:memory:` được giữ nguyên.
- Nếu env là thư mục hoặc kết thúc bằng `/`/`\`, tự nối thêm `app.sqlite3`.
- Nếu có suffix file thì dùng trực tiếp.
- Nếu không có suffix thì xem như thư mục và nối `app.sqlite3`.

## 4. `backend/api/decorators.py`

### `require_auth(route)`

Decorator bắt buộc có Bearer token hợp lệ.

Cách implement:

- Gọi `extract_bearer_token()`.
- Nếu thiếu token, trả `AUTH_REQUIRED`.
- Tạo `AuthService` từ app config.
- Gọi `get_user_for_token(token)`.
- Nếu token không hợp lệ/hết hạn/user inactive, trả `AUTH_REQUIRED`.
- Gán `g.current_user` và `g.current_token`, rồi gọi route gốc.

### `require_role(*roles)`

Decorator phân quyền theo role.

Cách implement:

- Bọc route bằng `require_auth`.
- Kiểm tra `g.current_user["role"]` có nằm trong danh sách role cho phép không.
- Nếu không, trả `FORBIDDEN`.

### `extract_bearer_token() -> str | None`

Parse header `Authorization`.

Cách implement:

- Lấy header.
- Tách theo khoảng trắng đầu tiên.
- Chỉ nhận scheme `Bearer`.
- Trả token đã strip hoặc `None`.

### `error_response(code, message, status_code, details=None)`

Chuẩn hóa lỗi API.

Cách implement:

- Tạo payload `{"error": {"code": ..., "message": ...}}`.
- Thêm `details` nếu có.
- Trả tuple `(payload, status_code)` để Flask convert thành response.

### `_get_auth_service() -> AuthService`

Factory nội bộ để tạo `AuthService` từ `current_app.config["APP_CONFIG"]`.

## 5. `backend/api/auth_routes.py`

### `login()`

Route `POST /api/v1/auth/login`.

Cách implement:

- Đọc JSON body, lấy `username`, `password`.
- Nếu thiếu, trả `INVALID_CREDENTIALS`.
- Gọi `AuthService.login()`.
- Nếu service raise `AuthError`, trả lỗi chuẩn.
- Thành công trả access token, token type, expires_at và user đã sanitize.

### `register()`

Route `POST /api/v1/auth/register`.

Cách implement:

- Đọc `username`, `password`.
- Gọi `AuthService.register_user()`.
- User mới mặc định là `free_user`, sau đó login ngay.
- Trả `201`.

### `logout()`

Route `POST /api/v1/auth/logout`, cần auth.

Cách implement:

- Lấy token từ header.
- Nếu có token, gọi `AuthService.logout(token)` để set `revoked_at`.
- Trả `{"status": "ok"}`.

### `me()`

Route `GET /api/v1/auth/me`, cần auth.

Profile UI note: frontend guest mode does not call this route because it has no
Bearer token. `/profile` is reserved for authenticated non-guest users, while
`/admin/profile` remains under the admin route guard.

Cách implement:

- `require_auth` đã gán `g.current_user`.
- Route chỉ trả user hiện tại.

### `_get_auth_service()`

Factory giống decorators: tạo `AuthService` từ app config.

## 6. `backend/api/admin_routes.py`

### `list_users()`

Route `GET /api/v1/admin/users`, cần role admin.

Cách implement: gọi `AuthService.list_users()` và trả danh sách user đã sanitize.

### `create_user()`

Route `POST /api/v1/admin/users`, cần role admin.

Cách implement:

- Đọc `username`, `password`, `role` từ JSON.
- Gọi `AuthService.create_user()`.
- Bắt `AuthError`.
- Thành công trả `201`.

### `update_user(user_id)`

Route `PATCH /api/v1/admin/users/<user_id>`, cần role admin.

Cách implement:

- Chỉ nhận các field `role`, `password`, `is_active`.
- Gọi `AuthService.update_user()` với `current_user_id` để chặn admin tự khóa/tự hạ quyền.

### `import_document()`

Route `POST /api/v1/admin/documents/import`, cần role admin.

Cách implement:

- Gọi `DocumentImportService.import_document()` với file upload, form data và user id.
- Nếu kết quả `is_publishable`, tự enqueue publish.
- Nếu auto publish lỗi, gọi `mark_latest_version_needs_republish()` và trả document ở trạng thái `ready_for_review` kèm `auto_publish_error`.
- Bắt `DocumentImportError`.

### `list_documents()`

Route `GET /api/v1/admin/documents`, cần role admin.

Cách implement: đọc query `status`, gọi `DocumentImportService.list_documents(status_filter)`.

### `get_document(document_id)`

Route `GET /api/v1/admin/documents/<document_id>`, cần role admin.

Cách implement:

- Gọi `DocumentImportService.get_document_detail(document_id, scope=...)`.
- `scope` mặc định là `latest`, có thể dùng `active`.
- Không tìm thấy thì trả `DOCUMENT_NOT_FOUND`.

### `download_document(document_id)`

Route `GET /api/v1/admin/documents/<document_id>/download`, cần role admin.

Cách implement:

- Gọi `get_raw_docx_path()`.
- Nếu path tồn tại, trả `send_file(..., as_attachment=True)`.

### `update_document_metadata(document_id)`

Route `PATCH /api/v1/admin/documents/<document_id>/metadata`, cần role admin.

Cách implement:

- Gọi `DocumentImportService.update_document_metadata()`.
- Gọi `_auto_publish_after_save()` nếu request có `?auto_publish=1`.

### `update_document_chunks(document_id)`

Route `PATCH /api/v1/admin/documents/<document_id>/chunks`, cần role admin.

Cách implement:

- Body có thể là `{"chunks": [...]}` hoặc trực tiếp là array.
- Nếu không phải list, trả `CHUNK_VALIDATION_FAILED`.
- Gọi `DocumentImportService.update_document_chunks()`.
- Có thể auto publish giống metadata.

### `replace_document_relationships(document_id)`

Route `PUT /api/v1/admin/documents/<document_id>/relationships`, cần role admin.

Cách implement:

- Body có thể là `{"relations": [...]}` hoặc trực tiếp là array.
- Gọi `DocumentImportService.replace_document_relations()`.
- Có thể auto publish.

### `delete_document(document_id)`

Route `DELETE /api/v1/admin/documents/<document_id>`, cần role admin.

Cách implement: gọi `DocumentIndexingService.delete_document()` để cleanup indexes, DB rows và artifact files.

### `publish_document(document_id)`

Route `POST /api/v1/admin/documents/<document_id>/publish`, cần role admin.

Cách implement:

- Gọi `DocumentIndexingService.enqueue_publish_document()`.
- Trả `202` vì publish chạy background.

### `list_pipeline_runs()`

Route `GET /api/v1/admin/pipeline`, cần role admin.

Cách implement: gọi `DocumentImportService.list_pipeline_runs()`.

### `get_pipeline_run(run_id)`

Route `GET /api/v1/admin/pipeline/<run_id>`, cần role admin.

Cách implement: gọi `DocumentImportService.get_pipeline_detail(run_id)`, gồm pipeline run và events.

### `rollback_pipeline_run(run_id)`

Route `POST /api/v1/admin/pipeline/<run_id>/rollback`, cần role admin.

Cách implement: gọi `DocumentIndexingService.rollback_pipeline()`.

### `_get_import_service()`, `_get_indexing_service()`, `_get_auth_service()`

Các factory nhỏ lấy `APP_CONFIG` từ Flask context và tạo service tương ứng.

### `_auto_publish_after_save(document_id, detail)`

Cách implement:

- Nếu query không có `auto_publish=1` hoặc document chưa publishable, trả detail cũ.
- Nếu có, gọi `enqueue_publish_document()`.
- Sau khi enqueue, reload document detail mới nhất rồi gắn `publish_result`.
- Nếu publish enqueue lỗi, mark latest version `needs_republish`, reload detail và gắn `publish_error`.

## 7. `backend/api/chat_routes.py`

### `chat()`

Route `POST /api/v1/chat`.

Anonymous/guest behavior: if the request has no valid Bearer token, the route
returns only the answer payload and does not create a `conversation_id`. Nothing
is inserted into `chat_conversations` or `chat_messages`; guest messages stay in
frontend component state and disappear on close/reload/navigation.

Cách implement:

- Đọc `message`; nếu rỗng trả `MESSAGE_REQUIRED`.
- Gọi `_get_optional_user()` để nhận user nếu Bearer token hợp lệ.
- Tạo answer bằng `_build_fallback_answer(message)`.
- Nếu không có user, trả answer ngay và không lưu DB.
- Nếu có user, đảm bảo conversation tồn tại, lưu message user và assistant vào SQLite, rồi trả answer kèm conversation info.

### `list_conversations()`

Route `GET /api/v1/chat/conversations`, cần auth.

Only requests with a valid Bearer token can load persisted chat history.

Cách implement: gọi `ChatHistoryService.list_conversations(user_id)`.

### `get_conversation(conversation_id)`

Route `GET /api/v1/chat/conversations/<conversation_id>`, cần auth.

Cách implement: gọi `ChatHistoryService.get_conversation()`, trả `CONVERSATION_NOT_FOUND` nếu không thuộc user hiện tại.

### `ChatHistoryService.__init__(db_path)`

Lưu DB path để các method mở SQLite connection khi cần.

### `ChatHistoryService.ensure_conversation(user_id, conversation_id, first_message)`

Cách implement:

- Nếu có `conversation_id`, gọi `get_conversation()` để kiểm tra quyền sở hữu; không có thì raise `ValueError`.
- Nếu không có, tạo conversation mới với UUID, title từ `make_title(first_message)`, timestamp UTC.

### `ChatHistoryService.add_message(...)`

Cách implement:

- Tạo message UUID.
- Serialize `citations` bằng JSON.
- Insert vào `chat_messages`.
- Update `chat_conversations.updated_at`.

### `ChatHistoryService.list_conversations(user_id)`

Query các conversation của user, sort theo `updated_at DESC`.

### `ChatHistoryService.get_conversation(user_id, conversation_id)`

Query conversation theo `id` và `user_id`, sau đó query messages theo `created_at ASC`; message được format bằng `format_message()`.

### `_build_fallback_answer(message)`

Trả payload cố định gồm `answer`, `response`, `citations=[]`, `confidence=None`, `query=message`. Đây là placeholder, chưa gọi retrieval.

### `_get_optional_user()`

Nếu request có Bearer token hợp lệ thì trả user từ `AuthService.get_user_for_token()`, không hợp lệ thì trả `None` thay vì lỗi.

### `_get_auth_service()`, `_get_chat_history_service()`

Factory service từ app config.

### `format_message(message)`

Parse `citations_json`; nếu JSON lỗi thì trả `citations=[]`. Trả object message sạch cho API.

### `make_title(message)`

Chuẩn hóa whitespace, cắt title tối đa 60 ký tự, fallback `"Conversation"`.

### `utc_now_iso()`

Trả timestamp UTC ISO.

## 8. `backend/services/auth_service.py`

### `AuthError`

Exception chuẩn cho auth/user service, giữ `code`, `message`, `status_code`.

### `AuthService.__init__(db_path, token_ttl_hours=24)`

Lưu DB path và TTL token dạng `timedelta`.

### `create_user(username, password, role)`

Cách implement:

- Normalize username.
- Validate username/password.
- Validate role thuộc `VALID_ROLES`.
- Hash password bằng `generate_password_hash`.
- Insert vào `users`.
- Bắt `sqlite3.IntegrityError` unique username và đổi thành `USERNAME_EXISTS`.
- Load lại user theo id và trả `sanitize_user()`.

### `register_user(username, password)`

Tạo user role `free_user`, rồi gọi `login()` để trả token ngay.

### `list_users()`

Query toàn bộ `users`, sort mới nhất trước, sanitize từng user để bỏ `password_hash`.

### `get_user_by_username(username)`

Normalize username rồi query `users`.

### `update_user(user_id, updates, current_user_id)`

Cách implement:

- Load user; không có thì `USER_NOT_FOUND`.
- Validate role mới.
- Tính `next_is_active`.
- Chặn admin tự demote hoặc tự deactivate.
- Chặn hệ thống mất active admin cuối cùng.
- Nếu đổi password hoặc deactivate, revoke session đang active.
- Update `users`, commit, load lại và sanitize.

### `get_user_by_id(user_id)`

Query user theo id.

### `login(username, password)`

Cách implement:

- Load user theo username.
- Check password bằng `check_password_hash`.
- Chặn inactive user.
- Sinh token bằng `secrets.token_urlsafe(48)`.
- Hash token bằng `hash_token()`.
- Insert `auth_sessions` với `expires_at`.
- Trả raw token cho client và user đã sanitize.

### `get_user_for_token(token)`

Cách implement:

- Hash token.
- Join `auth_sessions` với `users`.
- Chỉ nhận session chưa revoked, chưa hết hạn, user active.
- Trả `sanitize_user()` hoặc `None`.

### `logout(token)`

Hash token và set `revoked_at` cho session tương ứng.

### `_active_admin_count()`

Đếm user role admin đang active, dùng để bảo vệ không mất admin cuối cùng.

### Helper functions

- `hash_token(token)`: SHA-256 raw token.
- `sanitize_user(user)`: bỏ `password_hash`, ép `is_active` về bool.
- `utc_now_iso()`: UTC timestamp.
- `normalize_username(username)`: strip username.
- `validate_username(username)`: bắt buộc 3-50 ký tự.
- `validate_password(password)`: bắt buộc tối thiểu 6 ký tự.

## 9. `backend/services/document_import_service.py`

### `DocumentImportError`

Exception chuẩn cho import/review service, giữ `code`, `message`, `status_code`, `details`.

### `ImportMetadata`

Dataclass chứa metadata đã resolve: số hiệu, title, cơ quan ban hành, ngày ban hành/hiệu lực, người ký, document type, relations, review flags và evidence extraction.

### `DocumentImportService.__init__(config)`

Lưu `Config` và `sqlite_db_path`.

### `import_document(file_storage, form_data, requested_by_user_id)`

Function trung tâm của pipeline upload DOCX.

Cách implement:

- Sinh `pipeline_run_id`, `import_batch_id`.
- Tạo pipeline run trạng thái `pending`.
- Validate file là DOCX thật bằng extension và zip structure.
- Lưu raw DOCX vào `data/raw/<import_batch_id>/`.
- Parse DOCX bằng `python-docx` qua `extract_docx()`.
- Ghép paragraphs thành text, reject nếu rỗng.
- Extract metadata hints bằng regex/table/signature helper.
- Parse/merge metadata từ form, hints, DeepSeek.
- Upsert `document_registry`, tạo version mới.
- Ghi text vào `data/preprocessed/<import_batch_id>/`.
- Build metadata chuẩn.
- Chunk text bằng LLM nếu bật; fallback regex deterministic.
- Validate chunks, ghi JSON vào `data/chunked/<import_batch_id>/`.
- Lưu `document_versions` và `document_relations`.
- Ghi pipeline events: uploaded, parsed, chunked, ready_for_review.
- Tính `publish_blockers` từ metadata bắt buộc.
- Nếu lỗi có kiểm soát, mark pipeline failed rồi raise `DocumentImportError`.

### `list_documents(status_filter=None)`

Cách implement:

- Query `document_registry` join latest version và active version.
- Bỏ document đã deleted.
- Filter `published` hoặc `ready_for_review` nếu có.
- Overlay metadata latest khi đang xem review queue.
- Đếm chunks từ `chunk_json_path`.
- Tính `needs_review`, `needs_republish`, `last_publish_error`, `publish_blockers`, `is_publishable`.

### `get_document_detail(document_id, chunk_preview_limit=5, scope="latest")`

Cách implement:

- Load registry; bỏ deleted.
- Chọn version latest hoặc active tùy `scope`.
- Load relations theo `source_document_id`.
- Load pipeline events theo `import_batch_id` của version.
- Load toàn bộ chunks và preview từ chunk JSON.
- Overlay metadata nếu không phải scope active.
- Trả document, version, relations, events, chunks, flags review/publish.

### `list_pipeline_runs()`

Query `pipeline_runs` sort theo `created_at DESC`.

### `get_pipeline_detail(run_id)`

Load pipeline run và toàn bộ events theo thời gian tăng dần.

### `get_raw_docx_path(document_id)`

Load raw DOCX path từ latest version; chỉ trả path nếu file còn tồn tại.

### `mark_latest_version_needs_republish(document_id, message, details=None)`

Cách implement:

- Load latest version.
- Update `metadata_json.needs_republish = True`.
- Gắn `last_publish_error`.
- Set version status về `ready_for_review`.

### `_ensure_editable_latest_version(connection, document_id)`

Cách implement:

- Load registry và latest version.
- Nếu document đã published và latest chính là active version status `published`, gọi `_clone_active_version_for_edit()`.
- Trả registry và latest editable version.

### `_get_latest_version(connection, document_id)`

Query latest `document_versions` theo version DESC.

### `_clone_active_version_for_edit(connection, registry, active_version)`

Cách implement:

- Tạo `version = max(version) + 1`.
- Sinh `import_batch_id` mới.
- Copy metadata từ active nhưng set `is_published=False`, `needs_republish=True`.
- Load chunks active, normalize lại metadata/version/import_batch_id, ghi chunk JSON mới.
- Insert version mới status `ready_for_review`.
- Copy relations active sang batch mới với `is_published=0`.

### `_rewrite_version_chunks_metadata(version, metadata_json)`

Load chunk JSON, gọi `normalize_chunks_for_version()`, ghi lại file JSON với metadata mới.

### `update_document_metadata(document_id, payload)`

Cách implement:

- Chỉ nhận field trong `METADATA_UPDATE_FIELDS` trừ `source_url`.
- Đảm bảo có editable latest version.
- Update `metadata_json`, tính `needs_republish`, `needs_review_fields`.
- Rewrite chunk metadata.
- Nếu document chưa published, update luôn registry.
- Trả detail mới.

### `update_document_chunks(document_id, chunks)`

Cách implement:

- Validate chunks.
- Đảm bảo editable latest version.
- Normalize chunks theo metadata/version hiện tại.
- Ghi lại chunk JSON.
- Set status `ready_for_review`, mark `needs_republish` nếu registry đang published.

### `replace_document_relations(document_id, relations)`

Cách implement:

- Validate mỗi relation có `relation_type` và target.
- Đảm bảo editable latest version.
- Xóa relations cũ của import batch.
- Insert relations mới với `is_published=0`.
- Update `relations_unavailable` và `needs_republish`.

### `_parse_metadata(form_data, metadata_hints, text, paragraphs, import_batch_id)`

Cách implement:

- Gọi `infer_metadata_with_deepseek()`.
- Merge hints regex và LLM, trong đó LLM value không rỗng có thể bổ sung/override.
- Form data có ưu tiên cao nhất qua `first_present()`.
- Nếu thiếu `document_number`, tạo `UNIDENTIFIED-<batch>`.
- Nếu thiếu title, dùng `make_fallback_title()`.
- Thu thập `needs_review_fields` cho field thiếu hoặc confidence thấp.
- Parse relations từ form `relations_json`, nếu không có thì dùng relations do LLM infer.
- Trả `ImportMetadata`.

### `_validate_docx(file_storage)`

Validate có file, filename `.docx`, và zip archive có `[Content_Types].xml` + `word/document.xml`.

### `_save_raw_docx(file_storage, import_batch_id)`

Lưu file vào `data/raw/<import_batch_id>/<secure_filename>`.

### `_write_preprocessed_text(document_id, import_batch_id, text)`

Ghi text đã extract vào `data/preprocessed/<import_batch_id>/<document_id>.txt`.

### `_write_chunks(document_id, import_batch_id, chunks)`

Ghi chunks JSON vào `data/chunked/<import_batch_id>/<document_id>.json`.

### `_chunk_text(text, document_id, import_batch_id, metadata, warnings)`

Cách implement:

- Nếu `config.llm_chunking_enabled`, thử dùng `src.ingestion.llm_splitter.LLMVietnameseLegalSplitter`.
- Normalize LLM chunks bằng `normalize_llm_chunks()`.
- Nếu LLM lỗi hoặc trả rỗng, append warning.
- Fallback luôn là `regex_chunk_text()`.

### `_upsert_document_registry(metadata, now)`

Cách implement:

- Tìm document chưa deleted theo `document_number`.
- Nếu chưa có, insert `document_registry` mới với version 1.
- Nếu có, update registry metadata và version tiếp theo là `max(version)+1`.
- Trả `(document_id, version)`.

### `_store_version_and_relations(...)`

Insert `document_versions` với paths/metadata/status `ready_for_review`, rồi insert từng relation vào `document_relations`.

### `_create_pipeline_run(...)`, `_mark_pipeline(...)`, `_fail_pipeline(...)`

Bộ helper ghi `pipeline_runs` và `pipeline_events`.

- `_create_pipeline_run`: insert run mới và event đầu.
- `_mark_pipeline`: update status run và append event.
- `_fail_pipeline`: set status `failed`, set `error_message`, append event lỗi.

### Helper metadata/chunk functions

- `optional_str(value)`: strip và trả `None` nếu rỗng.
- `bool_from_form(value, default)`: parse boolean từ form.
- `first_present(*values)`: trả value đầu tiên không rỗng.
- `parse_json(raw_value)`: parse JSON object an toàn, lỗi thì `{}`.
- `overlay_metadata(document, metadata)`: copy field metadata vào document.
- `get_publish_blockers(metadata)`: trả các field bắt buộc còn thiếu; `validity_status=unknown` cũng bị xem là blocker.
- `normalize_chunks_for_version(chunks, metadata, version)`: cập nhật import batch, publish flag, version và metadata trên từng chunk.
- `make_fallback_title(paragraphs, import_batch_id)`: lấy paragraph đầu làm title fallback hoặc `Untitled document ...`.
- `normalize_inferred_relations(raw_relations)`: chuẩn hóa relation do LLM infer.
- `low_confidence_fields(metadata, threshold=0.7)`: lấy field có confidence thấp.
- `parse_relations_json(raw_value)`: parse relations từ JSON string, validate schema tối thiểu.
- `infer_metadata_with_deepseek(config, text, paragraphs)`: nếu có `DEEPSEEK_API_KEY` và package `openai`, gọi DeepSeek để extract metadata JSON; lỗi thì trả `{}`.
- `make_first_context()`, `make_closing_context()`, `extract_effective_clause_text()`: cắt ngữ cảnh gửi LLM/regex.
- `extract_effective_date(text)`: tìm ngày dạng `dd/mm/yyyy` hoặc `ngày ... tháng ... năm ...`, trả `YYYY-MM-DD`.
- `extract_signature()`, `extract_signature_lines_from_last_table()`, `flatten_table_text()`, `dedupe_preserving_order()`, `looks_like_signer_title()`, `looks_like_signer_name()`: tìm chức danh/người ký từ cuối văn bản và bảng cuối.
- `extract_document_type_from_title(title)`: map title prefix sang loại văn bản.
- `extract_docx(docx_path)`: dùng `python-docx` lấy paragraphs và tables.
- `extract_metadata_hints(text, tables, paragraphs)`: gom hints từ table đầu, head text, title, hiệu lực, chữ ký.
- `extract_issuing_body_from_first_table()`, `split_cell_lines()`, `cleanup_issuing_body()`, `is_issuing_body_candidate()`: nhận diện cơ quan ban hành.
- `extract_document_number_from_first_table()`, `extract_document_number_from_text()`, `cleanup_document_number()`: nhận diện số hiệu văn bản.
- `extract_title_from_paragraphs()`, `is_standalone_document_type()`, `is_title_boundary()`: nhận diện title từ paragraphs đầu.
- `build_normalized_metadata(...)`: tạo metadata chuẩn cho version/chunks.
- `normalize_llm_chunks(...)`: chuyển output LLM splitter sang chunk record chuẩn.
- `regex_chunk_text(...)`: tách text theo dòng bắt đầu `Điều/Dieu`; nếu không tìm thấy điều thì tạo 1 chunk toàn văn.
- `split_article_clauses(article_text)`: tách khoản dạng dòng bắt đầu `1.`, `2.`, ...
- `build_chunk_record(...)`: tạo chunk dict có `chunk_id`, citation label, hierarchy path và metadata publish.
- `make_chunk_id(...)`: UUIDv5 deterministic từ document/article/clause/ordinal.
- `make_citation_label(...)`: tạo nhãn citation dạng số hiệu + điều + khoản.
- `validate_chunks(chunks)`: bắt buộc có content, article_number, hierarchy_path và clause_number nếu chunk level là clause.
- `load_chunk_preview(path, limit)`: đọc chunks và trả preview content tối đa 1000 ký tự.
- `load_chunks(path)`: đọc chunk JSON an toàn; file thiếu/JSON lỗi thì trả `[]`.
- `count_chunks(path)`: đếm chunks.
- `utc_now_iso()`: UTC timestamp.

## 10. `backend/services/indexing_service.py`

### `IndexingError`

Exception chuẩn cho publish/index/delete/rollback, giữ `code`, `message`, `status_code`, `details`.

### `ChunkRecord`

Dataclass đại diện chunk đã sẵn sàng index.

### `ChunkRecord.from_raw(raw_chunk, version, force_published)`

Cách implement:

- Lấy field từ raw chunk và strip/normalize.
- Set `is_published=force_published`, `published_version=version`.
- Tạo `neo4j_node_id` bằng `make_neo4j_node_id()`.

### `ChunkRecord.to_index_document()`

Convert dataclass sang dict để Elasticsearch/BM25 index.

### `ChunkRecord.to_scalar_metadata()`

Tạo metadata chỉ gồm scalar value cho Chroma.

### `IndexWriter`

Protocol chung cho provider index: cần `name`, `index_chunks()`, `delete_by_batch()`.

### `ElasticsearchBM25Provider`

Provider BM25 qua Elasticsearch.

- `__init__(config)`: lưu config/index name.
- `index_chunks(chunks, relations=None)`: ensure index, build bulk actions, index `_source` là `chunk.to_index_document()`.
- `ensure_index()`: tạo index nếu chưa tồn tại với `elasticsearch_index_mapping()`.
- `delete_by_batch(import_batch_id)`: xóa docs theo batch bằng `delete_by_query`.
- `search(query, filters=None, top_k=10)`: multi-match trên `content`, `document_title`, `citation_label`, kèm filter term.
- `_get_client()`: lazy init Elasticsearch client, validate config/dependency/auth.

### `ChromaVectorProvider`

Provider vector index qua Chroma.

- `__init__(config, embedding_provider=None)`: dùng `LocalEmbeddingProvider(config.embedding_model)` nếu không inject provider.
- `index_chunks(chunks, relations=None)`: mở persistent Chroma client, upsert ids/documents/metadatas/embeddings.
- `delete_by_batch(import_batch_id)`: xóa records trong collection theo metadata `import_batch_id`.

### `LocalEmbeddingProvider`

Embedding provider local.

- `__init__(model_name)`: lưu model name và cache model.
- `embed_documents(documents)`: nếu load được `FlagEmbedding.BGEM3FlagModel`, encode dense vectors; nếu không, fallback `hash_embedding()` và set `quality_warning`.
- `_load_bge_model()`: lazy import/load BGE-M3.

### `Neo4jGraphWriter`

Provider graph index qua Neo4j.

- `__init__(config)`: lưu config và lazy driver.
- `index_chunks(chunks, relations=None)`: merge `Document`, `Article`, `Clause`, tạo `HAS_ARTICLE`, `HAS_CLAUSE`, và `ADMIN_RELATION` tới `DocumentReference`.
- `delete_by_batch(import_batch_id)`: xóa relations và nodes theo batch.
- `unpublish_by_batch(import_batch_id)`: set `is_published=false` theo batch.
- `_get_driver()`: validate password/dependency, tạo Neo4j driver và `verify_connectivity()`.
- `_session_kwargs()`: trả `{"database": ...}` nếu config có Neo4j database.

### `DocumentIndexingService.__init__(config, providers=None)`

Lưu config, DB path, và optional provider list để test/inject.

### `publish_document(document_id, requested_by_user_id)`

Publish synchronous.

Cách implement:

- Validate candidate.
- Tạo pipeline run `pending`.
- Gọi trực tiếp `run_publish_pipeline()`.

Route hiện dùng `enqueue_publish_document()` để chạy background, nhưng function này vẫn hữu ích cho test hoặc batch job synchronous.

### `enqueue_publish_document(document_id, requested_by_user_id)`

Cách implement:

- Validate latest version publishable.
- Nếu đã có active publish run cùng document/version/batch, trả `already_running=True`.
- Tạo pipeline run status `queued`.
- Gọi `submit_publish_job()`.
- Trả thông tin pipeline run ngay.

### `run_publish_pipeline(pipeline_run_id)`

Function trung tâm của publish.

Cách implement:

- Load pipeline run và parse input.
- Validate có `document_id` và `import_batch_id`.
- Load version theo batch, bắt buộc status `ready_for_review`.
- Load chunk JSON và validate.
- Normalize raw chunks thành `ChunkRecord` với `force_published=True`.
- Thu warnings publish.
- Load relations của batch.
- Tìm old published batches của cùng document.
- Với từng provider theo thứ tự Neo4j, Chroma, Elasticsearch:
  - mark pipeline state indexing started.
  - gọi `provider.index_chunks(chunks, relations)`.
  - mark completed.
- Cleanup old batches.
- Update SQLite sang published qua `_mark_sqlite_published()`.
- Nếu lỗi sau khi đã index một phần, best-effort cleanup các provider đã index, mark pipeline failed, mark version `needs_republish`.

### `rollback_pipeline(run_id, requested_by_user_id)`

Cách implement:

- Load source pipeline run và `import_batch_id`.
- Load version tương ứng.
- Tạo rollback pipeline run mới.
- Cleanup indexes của batch bị rollback.
- Tìm previous restorable version.
- Nếu có version trước, index lại chunks/relations của version đó.
- Update SQLite bằng `_mark_sqlite_rolled_back()`.
- Mark rollback completed.

### `delete_document(document_id, requested_by_user_id)`

Cách implement:

- Load registry và tất cả versions.
- Tính các import batch cần cleanup index.
- Cleanup indexes.
- Thu artifact paths.
- Xóa relations, versions, registry khỏi SQLite.
- Gọi `delete_artifacts_safely()` để xóa raw/preprocessed/chunked files trong allowed roots.

### Private DB/query helpers

- `_get_registry(document_id)`: load registry chưa deleted.
- `_get_versions_for_document(document_id)`: load versions theo version ASC.
- `_get_latest_version(document_id)`: load latest version.
- `_validate_publish_candidate(document_id)`: latest phải `ready_for_review` và không còn publish blockers.
- `_get_version_by_batch(import_batch_id)`: load version theo batch.
- `_get_pipeline_run(run_id)`: load pipeline run.
- `_get_active_publish_run(document_id, version, import_batch_id)`: tìm publish run còn active cho cùng target.
- `_get_relations(import_batch_id)`: load relations của batch.
- `_get_published_batches_for_document(document_id, exclude_import_batch_id)`: tìm batch published cũ cần supersede/cleanup.
- `_get_previous_restorable_version(document_id, before_version)`: tìm version cũ có chunk JSON và chưa rolled_back.

### Private mutation helpers

- `_mark_sqlite_published(...)`: set version mới `published`, supersede batches cũ, update registry active_version/is_published/raw metadata, mark relations published.
- `_mark_publish_failure(...)`: gắn `needs_republish` và `last_publish_error` vào metadata version.
- `_mark_sqlite_rolled_back(...)`: set version rollback `rolled_back`, restore previous version nếu có, update registry/relations.
- `_create_pipeline_run(...)`: insert pipeline run và event đầu.
- `_mark_pipeline(...)`: update pipeline status và append event.
- `_fail_pipeline(...)`: set failed và append error event.
- `_unpublish_old_batches(providers, old_batches)`: cleanup old batches khỏi providers.

### Module helper functions

- `build_default_indexing_providers(config)`: trả `[Neo4jGraphWriter, ChromaVectorProvider, ElasticsearchBM25Provider]`.
- `publish_pipeline_input(document_id, version)`: tạo input JSON chuẩn cho publish pipeline.
- `submit_publish_job(config, pipeline_run_id)`: submit background job vào executor.
- `_run_publish_job(config, pipeline_run_id)`: tạo service mới và chạy pipeline, log exception nếu lỗi.
- `load_chunk_json(path)`: đọc chunk JSON, lỗi thiếu file/JSON sai/list sai thì raise `IndexingError`.
- `normalize_chunk_records(raw_chunks, version, force_published)`: convert raw dict thành `ChunkRecord`, validate required fields.
- `collect_publish_warnings(version, chunks)`: cảnh báo validity unknown, thiếu effective_date, thiếu relations.
- `cleanup_indexed_batch(providers, import_batch_id)`: gọi `delete_by_batch()` từng provider, gom lỗi thay vì dừng ngay.
- `collect_version_artifact_paths(versions)`: lấy raw/preprocessed/chunk paths từ versions.
- `delete_artifacts_safely(paths)`: chỉ xóa file dưới allowed storage roots, rồi cleanup thư mục rỗng.
- `cleanup_empty_storage_dir(path, allowed_roots)`: xóa thư mục rỗng nếu nằm trong allowed roots và không phải root.
- `is_relative_to_any(path, roots)`, `is_relative_to(path, root)`: guard path safety.
- `exception_details(exc)`: chuẩn hóa exception thành details dict.
- `parse_json(raw_value)`: parse JSON object an toàn.
- `sanitize_scalar_metadata(metadata)`: lọc metadata thành scalar cho Chroma.
- `hash_embedding(document, dimensions=384)`: tạo vector deterministic fallback bằng hashing token.
- `make_neo4j_node_id(document_id, node_kind, local_id)`: tạo id node Neo4j.
- `elasticsearch_index_mapping()`: mapping/analyzer tiếng Việt cho Elasticsearch index.
- `utc_now_iso()`: UTC timestamp.

## 11. `backend/models/database.py`

### `ClosingConnection`

Subclass `sqlite3.Connection` để context manager tự close connection sau khi commit/rollback logic của sqlite chạy xong.

### `get_connection(db_path)`

Cách implement:

- Mở SQLite connection bằng `ClosingConnection`.
- Set `row_factory = sqlite3.Row`.
- Bật `PRAGMA foreign_keys = ON`.

### `init_db(db_path)`

Cách implement:

- Tạo parent directory nếu không phải `:memory:`.
- Đọc `sqlite_schema.sql`.
- Mở connection.
- Chạy một số migration guard trước schema (`_ensure_user_roles`, `_ensure_import_batch_id`).
- Executescript schema.
- Gọi `apply_migrations()`.
- Commit.

### `row_to_dict(row)`

Convert `sqlite3.Row` sang dict; `None` giữ nguyên.

### `apply_migrations(connection)`

Gọi các migration tương thích:

- `_ensure_user_roles()`
- `_ensure_import_batch_id()`
- `_ensure_document_relations()`
- `_ensure_chat_history()`

### `_ensure_user_roles(connection)`

Nếu bảng `users` cũ chưa có role `free_user`, tạo bảng mới với CHECK constraint mới, copy data, drop bảng cũ, rename.

### `_ensure_import_batch_id(connection)`

Nếu `document_versions` chưa có `import_batch_id`, thêm column. Nếu còn `crawl_batch_id`, copy sang `import_batch_id`. Tạo index.

### `_ensure_document_relations(connection)`

Tạo bảng/index `document_relations` nếu chưa có.

### `_ensure_chat_history(connection)`

Tạo bảng/index `chat_conversations` và `chat_messages` nếu chưa có.

### `_get_columns(connection, table_name)`

Đọc `PRAGMA table_info(table_name)` và trả set tên column.

## 12. `backend/models/sqlite_schema.sql`

Schema chính gồm:

- `users`: tài khoản, role, trạng thái active.
- `auth_sessions`: session token hash, expiry, revoke.
- `chat_conversations`, `chat_messages`: lịch sử chat theo user.
- `document_registry`: bản ghi tài liệu cấp document, active version, publish flags.
- `document_versions`: từng version/import batch, artifact paths, metadata JSON, status.
- `document_relations`: quan hệ văn bản do admin/LLM cung cấp, publish flag theo batch.
- `pipeline_runs`: trạng thái tổng của import/publish/rollback.
- `pipeline_events`: timeline chi tiết của từng pipeline.

## 13. `backend/services/seed_service.py`

### `seed_admin_user(config)`

Cách implement:

- Nếu thiếu `ADMIN_USERNAME` hoặc `ADMIN_PASSWORD`, log warning và bỏ qua.
- Tạo `AuthService`.
- Nếu username admin đã tồn tại, bỏ qua.
- Nếu chưa có, gọi `AuthService.create_user(..., role=admin)`.
- Nếu env admin không hợp lệ, catch `AuthError` và log lỗi.

## 14. Các module `src` được backend gọi gián tiếp

Các file này không nằm trong `backend/`, nhưng có liên quan:

- `src/ingestion/llm_splitter.py`: được `DocumentImportService._chunk_text()` import khi `LLM_CHUNKING_ENABLED=true`.
- `src/retrieval/retrieval.py`: hiện chưa được `backend/api/chat_routes.py` gọi, nhưng là module retrieval Neo4j/LLM độc lập cho CLI.
- `src/ingestion/ingest.py` và `src/ingestion/embed.py`: phục vụ CLI legacy trong `main.py`, không phải luồng admin upload chính.

Vì vậy khi đọc backend hiện tại, nên xem admin upload/publish pipeline là luồng chính; các module `src` là hỗ trợ/legacy hoặc optional.
