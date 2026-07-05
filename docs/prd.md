# PRD: BaoHiem Legal AI Workspace

## Title

**BaoHiem Legal AI Workspace**

Một ứng dụng AI nội bộ chạy local, hỗ trợ tra cứu pháp luật bảo hiểm, quản trị kho văn bản pháp luật, rà soát hợp đồng cơ bản, cảnh báo rủi ro và tạo khung xuất file `.docx` cho tài liệu nghiệp vụ.

## Change History

| Version | Date | Owner | Change |
| --- | --- | --- | --- |
| 0.1 | 2026-07-01 | Product/Architecture Lead | Tạo PRD bản đầu từ yêu cầu trong `requirements.md`, hiện trạng codebase CLI, và các quyết định phạm vi MVP đã chốt. |
| 0.2 | 2026-07-02 | Product/Architecture Lead | Cập nhật cấu trúc knowledge graph 2 cấp và metadata vector database theo mô hình metadata/quan hệ văn bản từ giao diện tham chiếu. |
| 0.3 | 2026-07-02 | Product/Architecture Lead | Tạm bỏ import bằng crawl theo số hiệu từ `wsvbpl.moj.gov.vn`/`vbpl.vn`; chuyển MVP sang upload trực tiếp file `.docx` bởi admin và ghi rõ giới hạn quan hệ văn bản/knowledge graph. |

## Overview

BaoHiem Legal AI Workspace chuyển prototype CLI hiện tại thành một ứng dụng hoàn chỉnh hơn cho người dùng cơ bản trong lĩnh vực bảo hiểm. Sản phẩm tập trung vào việc giúp người dùng hỏi đáp trên kho văn bản pháp luật do admin quản lý, kiểm tra hiệu lực văn bản, rà soát hợp đồng sơ bộ và hỗ trợ tạo khung tài liệu `.docx`.

Lý do xây dựng sản phẩm:

- Khối lượng văn bản pháp luật bảo hiểm lớn, thường có quan hệ sửa đổi, thay thế, bãi bỏ, hợp nhất phức tạp.
- Người dùng nghiệp vụ cần câu trả lời có căn cứ pháp lý, tình trạng hiệu lực và nguồn trích dẫn rõ ràng.
- Admin cần một workflow có kiểm soát để nhập văn bản, cập nhật dữ liệu, rollback và publish dữ liệu vào kho tri thức.
- Rà soát hợp đồng cơ bản cần kết hợp rule, hiệu lực văn bản và retrieval để phát hiện rủi ro sơ bộ.

MVP vẫn là local prototype, nhưng được thiết kế theo hướng có frontend Streamlit, backend Flask API, multi-user nhẹ, và các module dữ liệu riêng để có thể nâng cấp thành hệ thống dùng thật.

## Success Metrics

Do sản phẩm hướng tới dùng thật trong khoảng 1 tuần, success metrics của MVP cần thực dụng và đo được bằng test set nhỏ.

### Primary Metrics

- **Legal answer accuracy >= 80%** trên bộ câu hỏi kiểm thử nội bộ về lĩnh vực bảo hiểm.
- **Citation coverage >= 90%**: câu trả lời pháp lý phải có ít nhất một citation hợp lệ tới văn bản/điều/khoản liên quan.
- **Effective-document retrieval rate >= 90%**: kết quả truy xuất mặc định chỉ dùng văn bản còn hiệu lực, trừ khi người dùng/admin yêu cầu kiểm tra văn bản hết hiệu lực.
- **Admin DOCX ingest success rate >= 80%** với danh sách file `.docx` pháp luật do admin tải lên trực tiếp.

### Secondary Metrics

- Thời gian phản hồi chatbot cho câu hỏi thông thường <= 20 giây trong môi trường local.
- Pipeline import một văn bản có trạng thái rõ ràng: pending, uploaded, parsed, indexed, published hoặc failed.
- Rà soát hợp đồng trả được báo cáo có cấu trúc với trạng thái thẩm quyền và hiệu lực cho các trường hợp có đủ dữ liệu đầu vào.
- Có thể rollback một lần import/update đã publish mà không làm hỏng dữ liệu đang dùng.

## Messaging

### External/User-Facing Messaging

BaoHiem Legal AI Workspace là trợ lý pháp lý nội bộ cho lĩnh vực bảo hiểm, giúp người dùng tra cứu quy định, kiểm tra hiệu lực căn cứ pháp lý, rà soát hợp đồng sơ bộ và nhận câu trả lời có trích dẫn rõ ràng từ kho văn bản đã được admin kiểm soát.

### Admin Messaging

Admin có thể upload trực tiếp file `.docx` văn bản pháp luật đã tải sẵn, nhập/chỉnh metadata cần thiết, kiểm tra trạng thái xử lý, quản lý dữ liệu đã publish và rollback khi phát hiện lỗi. MVP không gọi `wsvbpl.moj.gov.vn`/`vbpl.vn` để crawl theo số hiệu vì nguồn này yêu cầu quyền truy cập.

### Trust/Safety Messaging

Sản phẩm không thay thế chuyên gia pháp lý. Các kết quả trả lời, rà soát và cảnh báo rủi ro là hỗ trợ sơ bộ, cần được người có chuyên môn kiểm tra trước khi sử dụng chính thức.

## Timeline/Release Planning

### MVP 1 Tuần

| Phase | Timebox | Scope |
| --- | --- | --- |
| Day 1 | Product/Architecture | Chốt PRD, TRD, data model MVP, pipeline states, API boundary. |
| Day 2 | Backend Foundation | Flask API, auth nhẹ, role Admin/User/Guest, SQLite app DB, cấu trúc service layer. |
| Day 3 | Admin Data Pipeline | Upload trực tiếp file `.docx`, lưu raw/audit, nhập metadata tối thiểu, parse/chunk. |
| Day 4 | Indexing | ChromaDB dense embedding, BM25 index, Neo4j graph cấp 2 cấu trúc; graph cấp 1 chỉ tạo từ metadata/quan hệ admin đã nhập. |
| Day 5 | Retrieval & Chat | Hybrid retrieval, lọc văn bản còn hiệu lực trước retrieve, trả lời có citation và confidence. |
| Day 6 | Contract Review & Docx Skeleton | Upload hợp đồng, module rà soát thẩm quyền/hiệu lực, báo cáo sơ bộ, khung sinh `.docx` chưa có template thật. |
| Day 7 | Streamlit UX & QA | UI cho User/Admin/Guest, test set, rollback demo, sửa lỗi release. |

### Post-MVP

- Chuẩn hóa bộ rule rà soát hợp đồng.
- Bổ sung template thật cho tờ trình/hợp đồng.
- Tăng cường bảo mật, audit log, backup/restore.
- Bổ sung workflow metadata/quan hệ văn bản thủ công tốt hơn, deduplication, confidence scoring và evaluation.
- Chỉ xem xét tích hợp lại nguồn `wsvbpl.moj.gov.vn`/`vbpl.vn` khi có quyền truy cập hợp lệ hoặc API/nguồn dữ liệu ổn định.

## Personas

### Key Persona: Business User

Người dùng nghiệp vụ cần hỏi đáp pháp luật bảo hiểm, kiểm tra căn cứ pháp lý và upload hợp đồng để nhận rà soát sơ bộ. Họ không quản lý kho dữ liệu và không được tự thêm văn bản pháp luật.

Nhu cầu chính:

- Hỏi bằng ngôn ngữ tự nhiên.
- Nhận câu trả lời dễ hiểu, có căn cứ pháp lý và trạng thái hiệu lực.
- Upload hợp đồng để kiểm tra thẩm quyền và hiệu lực sơ bộ.

### Admin

Người vận hành kỹ thuật chịu trách nhiệm quản lý kho văn bản, import/cập nhật dữ liệu, xử lý lỗi pipeline, rollback và quản lý người dùng.

Nhu cầu chính:

- Upload file `.docx` văn bản pháp luật.
- Nhập hoặc chỉnh metadata tối thiểu như số hiệu, tên văn bản, cơ quan ban hành, ngày hiệu lực, trạng thái hiệu lực.
- Nhập thủ công quan hệ văn bản nếu có căn cứ.
- Theo dõi trạng thái pipeline.
- Quản lý dữ liệu đã publish.
- Cập nhật metadata/hiệu lực thủ công khi có căn cứ.
- Rollback nếu import/update sai.

### Guest

Người dùng chưa đăng nhập hoặc quyền hạn thấp. Guest chỉ được xem/try một phần rất hạn chế tùy cấu hình MVP.

Nhu cầu chính:

- Trải nghiệm giới hạn hoặc xem thông tin cơ bản.
- Không được upload hợp đồng hoặc truy cập tính năng admin.

## User Scenarios

### Scenario 1: Business User Hỏi Về Quy Định Bảo Hiểm

Một nhân sự nghiệp vụ cần biết quy định hiện hành về một vấn đề bảo hiểm. Người dùng đăng nhập, nhập câu hỏi tự nhiên. Hệ thống nhận diện đây là câu hỏi nội dung, lọc trước các văn bản còn hiệu lực nếu metadata đã có, truy xuất kết hợp dense embedding, BM25, Neo4j graph cấp 2 và Neo4j graph cấp 1 nếu có quan hệ được admin nhập thủ công, sau đó sinh câu trả lời có format cố định. Câu trả lời phải nêu căn cứ theo văn bản số nào, điều/khoản nào, trạng thái hiệu lực và confidence; nếu thiếu metadata hiệu lực hoặc quan hệ, hệ thống phải cảnh báo.

### Scenario 2: Business User Tìm Theo Từ Khóa

Người dùng muốn tìm nhanh các đoạn có chứa một thuật ngữ cụ thể. Hệ thống ưu tiên BM25, vẫn áp dụng lọc văn bản còn hiệu lực, hiển thị danh sách kết quả có văn bản/điều/khoản/citation. Nếu confidence thấp hoặc thiếu citation, hệ thống cảnh báo.

### Scenario 3: Admin Upload Văn Bản DOCX

Admin upload file `.docx` văn bản pháp luật đã tải sẵn. Hệ thống lưu file gốc, audit record, parse nội dung, đề xuất metadata có thể trích xuất từ nội dung file, chunk theo điều/khoản, cập nhật graph cấp 2, ChromaDB và BM25. Admin nhập/chỉnh metadata tối thiểu và có thể nhập quan hệ văn bản thủ công trước khi publish. Nếu không có quan hệ được nhập, graph cấp 1 không được tạo quan hệ suy đoán.

### Scenario 4: Admin Cập Nhật Metadata/Hiệu Lực Thủ Công

Admin mở màn hình quản lý văn bản để chỉnh trạng thái hiệu lực, ngày hiệu lực/ngày hết hiệu lực và quan hệ sửa đổi, thay thế, bãi bỏ nếu có căn cứ. UI phải hiển thị cảnh báo rằng dữ liệu này không được tự động xác minh từ `wsvbpl.moj.gov.vn`/`vbpl.vn` trong MVP. Sau khi admin xác nhận, hệ thống ghi phiên bản metadata mới, cập nhật index/graph tương ứng và cho phép rollback nếu kết quả sai.

### Scenario 5: Business User Rà Soát Hợp Đồng

Người dùng upload hợp đồng. Hệ thống trích xuất các thông tin đầu vào cần thiết cho module rà soát thẩm quyền và hiệu lực, gồm tên cơ quan ban hành, chức danh người ký, ngày hết hiệu lực và dữ liệu quan hệ thay thế/bãi bỏ nếu đã có trong metadata do admin quản lý. Hệ thống trả báo cáo sơ bộ theo module:

- Rà soát thẩm quyền: tên cơ quan ban hành đúng/không đúng thẩm quyền; chức danh người ký đúng/không đúng thẩm quyền.
- Rà soát hiệu lực: văn bản, điều luật, căn cứ viện dẫn còn hiệu lực hay không nếu metadata đủ; có bị sửa đổi, bổ sung, thay thế, bãi bỏ hoặc xung đột hiệu lực hay không nếu quan hệ đã được admin nhập. Nếu thiếu metadata/quan hệ, báo `không đủ dữ liệu` thay vì suy luận.

### Scenario 6: User Tạo Khung File Docx

Người dùng vào module tạo tài liệu. MVP chưa có template thật, nhưng vẫn cung cấp khung workflow: chọn loại tài liệu, nhập thông tin cơ bản, sinh file `.docx` skeleton để tải về. Nội dung sinh ra phải được đánh dấu là bản nháp và chưa áp dụng template chính thức.

## User Stories/Features/Requirements

### P0 - Authentication & Role Management

- Là Admin/Business User/Guest, tôi có thể đăng nhập để hệ thống áp dụng đúng quyền.
- Là Admin, tôi có thể quản lý user cơ bản: thêm, sửa, khóa/mở khóa, gán role.
- Là hệ thống, tôi cần multi-user nhẹ: user table, password hash, session riêng, role-based access control.

Lý do: sản phẩm có phân quyền admin/người dùng rõ ràng và cần tránh người dùng thường tác động vào kho dữ liệu.

### P0 - Admin Legal Document Ingestion

- Là Admin, tôi có thể upload trực tiếp file `.docx` văn bản pháp luật để hệ thống import.
- Hệ thống không crawl theo số hiệu từ `wsvbpl.moj.gov.vn`/`vbpl.vn` trong MVP.
- Hệ thống lưu file gốc, metadata do admin nhập hoặc metadata trích xuất được từ DOCX, dữ liệu chuẩn hóa, trạng thái pipeline và audit record.
- Admin có thể nhập thủ công quan hệ văn bản như sửa đổi, thay thế, bãi bỏ nếu có nguồn kiểm chứng.
- Hệ thống auto-publish sau upload khi metadata bắt buộc đầy đủ và `validity_status != unknown`; nếu thiếu thì đưa vào hàng `ready_for_review`.

Lý do: chất lượng dữ liệu pháp luật quyết định chất lượng retrieval và câu trả lời.

### P0 - Pipeline State Management

Pipeline import/update cần có trạng thái tối thiểu:

- `pending`
- `uploaded`
- `parsed`
- `chunked`
- `graph_indexed`
- `vector_indexed`
- `bm25_indexed`
- `ready_for_review`
- `published`
- `failed`
- `rolled_back`

Lý do: admin cần biết lỗi xảy ra ở đâu và có thể khôi phục an toàn.

### P0 - Rollback

- Là Admin, tôi có thể rollback một lần import hoặc update đã publish.
- Rollback phải khôi phục trạng thái published trước đó của metadata, Neo4j graph, ChromaDB và BM25 ở mức MVP.
- Nếu rollback không thể hoàn tất toàn bộ, hệ thống phải báo trạng thái partial failure và giữ audit log.

Lý do: dữ liệu pháp luật sai có thể làm sai toàn bộ câu trả lời.

### P0 - Knowledge Graph Level 1: Document Graph

Hệ thống dùng Neo4j để lưu graph cấp 1 giữa các văn bản pháp luật khi admin cung cấp quan hệ đã kiểm chứng. Đây là lớp tương ứng với màn hình "Văn bản đang xem" và hai cột quan hệ văn bản trong giao diện tham chiếu. Vì MVP import từ file `.docx` upload trực tiếp, hệ thống không có quyền truy cập nguồn `wsvbpl.moj.gov.vn`/`vbpl.vn` để tự động lấy đầy đủ quan hệ giữa các văn bản.

Node trung tâm là `Document`. Metadata tối thiểu của `Document` gồm:

- `document_id`: định danh nội bộ ổn định.
- `source_system`: nguồn dữ liệu, mặc định là `admin_upload`.
- `title`: tên đầy đủ của văn bản.
- `document_number`: số hiệu văn bản.
- `sector`: ngành.
- `domain`: lĩnh vực.
- `issuing_body`: cơ quan ban hành.
- `signer_title`: chức danh người ký.
- `signer_name`: người ký.
- `document_type`: loại văn bản.
- `issued_date`: ngày ban hành.
- `effective_date`: ngày có hiệu lực.
- `expiry_date`: ngày hết hiệu lực, có thể null.
- `validity_status`: tình trạng hiệu lực, ví dụ còn hiệu lực, hết hiệu lực, bị thay thế, bị bãi bỏ.
- `raw_metadata`: metadata gốc do admin nhập hoặc trích xuất từ DOCX để phục vụ audit.
- `import_batch_id`: batch import/update đã tạo ra bản ghi.
- `published_version`: phiên bản dữ liệu đang publish.

Nếu admin nhập dữ liệu quan hệ, quan hệ cấp văn bản cần bao phủ các nhóm trong giao diện tham chiếu:

- Văn bản hướng dẫn áp dụng / văn bản được hướng dẫn áp dụng.
- Văn bản quy định chi tiết, hướng dẫn thi hành / văn bản được quy định chi tiết, hướng dẫn thi hành.
- Văn bản hợp nhất / văn bản được hợp nhất.
- Văn bản sửa đổi bổ sung / văn bản được sửa đổi bổ sung.
- Văn bản đính chính / văn bản được đính chính.
- Văn bản thay thế / văn bản được thay thế.
- Văn bản bãi bỏ / văn bản bị bãi bỏ.
- Văn bản áp dụng.
- Văn bản dẫn chiếu hoặc căn cứ ban hành.
- Văn bản giải thích / văn bản được giải thích.
- Văn bản đình chỉ thi hành / văn bản bị đình chỉ thi hành.
- Văn bản tạm ngưng hiệu lực / văn bản bị tạm ngưng hiệu lực.
- Văn bản công bố / văn bản được công bố.

Ở mức sản phẩm, các quan hệ đã được nhập phải hiển thị được theo hai chiều giống giao diện tham chiếu: văn bản hiện tại tác động tới văn bản nào, và văn bản hiện tại bị/được văn bản nào tác động. Nếu chưa có dữ liệu quan hệ, UI phải hiển thị trạng thái chưa đủ dữ liệu thay vì để trống như thể không có quan hệ.

Lý do: hiệu lực và quan hệ văn bản là nền tảng cho câu trả lời đáng tin, nhưng với nguồn DOCX upload trực tiếp, hệ thống chỉ được phép dùng quan hệ do admin nhập hoặc xác nhận.

### P0 - Knowledge Graph Level 2: Legal Structure Graph

Hệ thống dùng Neo4j để lưu graph cấp 2 theo cấu trúc bên trong từng văn bản. MVP tập trung biểu diễn cấu trúc pháp lý, chưa cố gắng suy luận toàn bộ quan hệ nội dung giữa các khoản/điều.

Cấu trúc tối thiểu:

```text
(Document)-[:HAS_CHAPTER]->(Chapter)
(Chapter)-[:HAS_SECTION]->(Section)
(Section)-[:HAS_ARTICLE]->(Article)
(Article)-[:HAS_CLAUSE]->(Clause)
```

Các biến thể cần hỗ trợ:

- Nếu văn bản không có chương, `Document` có thể nối trực tiếp tới `Article`.
- Nếu chương không có mục, `Chapter` có thể nối trực tiếp tới `Article`.
- Nếu điều không có khoản, `Article` chứa trực tiếp nội dung dùng cho retrieval.
- Nếu có khoản, `Clause` là đơn vị retrieval chính.

Metadata tối thiểu của node cấu trúc:

- `node_id`: định danh nội bộ ổn định.
- `document_id`: khóa liên kết về `Document`.
- `document_number`: số hiệu văn bản được thừa kế.
- `document_title`: tên văn bản được thừa kế.
- `document_type`: loại văn bản được thừa kế.
- `issuing_body`: cơ quan ban hành được thừa kế.
- `effective_date`, `expiry_date`, `validity_status`: metadata hiệu lực được thừa kế từ văn bản.
- `chapter_number`, `chapter_title`: nếu có.
- `section_number`, `section_title`: nếu có.
- `article_number`, `article_title`.
- `clause_number`: nếu node là khoản.
- `hierarchy_path`: đường dẫn cấu trúc, ví dụ `Chương I > Mục 1 > Điều 3 > Khoản 2`.
- `content`: nội dung đầy đủ của điều hoặc khoản.
- `chunk_level`: `article` hoặc `clause`.

MVP chỉ lưu trạng thái mới nhất, chưa lưu version history theo thời gian.

Lý do: citation theo điều/khoản là yêu cầu bắt buộc của trải nghiệm pháp lý.

### P0 - Dense Embedding & Vector Database Metadata

Hệ thống chunk theo điều hoặc khoản nếu điều có nhiều khoản. Mỗi chunk được lưu vào ChromaDB local cùng metadata đủ để lọc hiệu lực, truy ngược văn bản, dựng citation và liên kết lại Neo4j.

Metadata tối thiểu của mỗi vector record:

- `chunk_id`: định danh chunk ổn định.
- `document_id`: định danh văn bản trong hệ thống.
- `document_number`: số hiệu văn bản.
- `document_title`: tên văn bản.
- `document_type`: loại văn bản.
- `source_system`: nguồn dữ liệu, mặc định là `admin_upload`.
- `sector`: ngành.
- `domain`: lĩnh vực.
- `issuing_body`: cơ quan ban hành.
- `signer_title`: chức danh người ký.
- `signer_name`: người ký.
- `issued_date`: ngày ban hành.
- `effective_date`: ngày có hiệu lực.
- `expiry_date`: ngày hết hiệu lực, có thể null.
- `validity_status`: tình trạng hiệu lực.
- `chapter_number`, `chapter_title`: nếu có.
- `section_number`, `section_title`: nếu có.
- `article_number`, `article_title`.
- `clause_number`: nếu chunk là khoản.
- `hierarchy_path`: đường dẫn cấu trúc.
- `chunk_level`: `article` hoặc `clause`.
- `citation_label`: nhãn citation hiển thị, ví dụ `Nghị định số ... Điều 3 Khoản 2`.
- `neo4j_node_id`: ID node `Article` hoặc `Clause` tương ứng trong Neo4j.
- `published_version`: phiên bản dữ liệu đang publish.
- `import_batch_id`: batch import/update đã tạo ra vector.

Metadata phải hỗ trợ lọc trước theo `validity_status = còn hiệu lực` trước khi retrieve. Nội dung embed là text của điều/khoản, nhưng citation và filtering không được phụ thuộc vào LLM sinh lại metadata.

Lý do: dense retrieval giúp trả lời câu hỏi tự nhiên tốt hơn keyword search, nhưng trong sản phẩm pháp lý vector phải luôn truy ngược được về văn bản, hiệu lực và vị trí điều/khoản.

### P0 - BM25 Search

- Hệ thống có chỉ mục BM25 local cho tìm kiếm từ khóa.
- Khi người dùng dùng tính năng tìm theo từ khóa, BM25 là nguồn truy xuất ưu tiên.
- Kết quả BM25 vẫn phải có citation và trạng thái hiệu lực.

Lý do: truy vấn keyword cần độ chính xác lexical cao.

### P0 - Hybrid Retrieval

- Với câu hỏi nội dung thông thường, hệ thống kết hợp dense embedding, BM25, Neo4j graph cấp 2 và Neo4j graph cấp 1 nếu đã có quan hệ được admin nhập.
- Hệ thống lọc văn bản còn hiệu lực trước khi retrieve khi `validity_status` đã xác định; văn bản có trạng thái `unknown` phải được cảnh báo rõ.
- Nếu thiếu citation hoặc confidence thấp, hệ thống phải cảnh báo không đủ căn cứ.

Lý do: câu hỏi pháp lý cần kết hợp ngữ nghĩa, từ khóa, hiệu lực và cấu trúc pháp luật.

### P0 - Chatbot Answering

- Người dùng hỏi bằng tiếng Việt.
- Câu trả lời dùng format cố định, sẽ chốt chi tiết sau.
- Định hướng format: "Theo văn bản số ..., tại Điều/Khoản ..., quy định ...".
- Mỗi câu trả lời phải có căn cứ pháp lý và trạng thái hiệu lực.
- Nếu ngoài phạm vi bảo hiểm hoặc thiếu dữ liệu, hệ thống từ chối/cảnh báo.

Lý do: người dùng cần câu trả lời kiểm chứng được, không chỉ văn bản sinh bởi LLM.

### P0 - Contract Review

Module rà soát hợp đồng MVP gồm hai nhóm.

**Module Rà Soát Thẩm Quyền**

Mục đích:

- Kiểm tra văn bản có được ban hành bởi đúng chủ thể có thẩm quyền hay không.
- Kiểm tra chủ thể ban hành có được phép ban hành loại văn bản đó không.
- Kiểm tra người ký văn bản có đúng thẩm quyền ký hay không.
- Cảnh báo dấu hiệu vượt quá hoặc thiếu thẩm quyền theo quy định pháp luật.

Dữ liệu đầu vào:

- Tên cơ quan ban hành.
- Chức danh người ký.

Dữ liệu đầu ra:

- Tên cơ quan ban hành: đúng thẩm quyền hoặc không đúng thẩm quyền.
- Chức danh người ký: đúng thẩm quyền hoặc không đúng thẩm quyền.

**Module Rà Soát Hiệu Lực**

Mục đích:

- Kiểm tra văn bản còn hiệu lực hay không.
- Kiểm tra điều luật còn hiệu lực hay không.
- Kiểm tra văn bản đã bị sửa đổi, bổ sung hoặc thay thế chưa.
- Kiểm tra căn cứ pháp lý được viện dẫn còn hiệu lực không.
- Cảnh báo xung đột hiệu lực giữa các văn bản nếu phát hiện được.

Dữ liệu đầu vào:

- Ngày hết hiệu lực nếu có trong metadata.
- Dữ liệu quan hệ kiểu thay thế/bãi bỏ nếu admin đã nhập.

Dữ liệu đầu ra:

- Trạng thái còn hiệu lực hoặc không còn hiệu lực.
- Danh sách cảnh báo nếu thiếu dữ liệu, thiếu quan hệ văn bản, thiếu citation hoặc confidence thấp.

Lý do: rà soát hợp đồng là module giá trị cao nhưng MVP cần giữ scope rule-based/prototype.

### P1 - Docx Generation Skeleton

- MVP vẫn có khung sinh file `.docx`.
- Chưa có template thật.
- Người dùng có thể nhập thông tin cơ bản và tải file `.docx` skeleton.
- File phải thể hiện rõ đây là bản nháp/chưa áp dụng template chính thức.

Lý do: giữ đường kiến trúc cho module soạn tờ trình/hợp đồng mà không chặn MVP vì thiếu template.

### P1 - Admin Data Management

- Admin có thể xem danh sách văn bản trong kho.
- Admin có thể thêm, sửa, xóa mềm văn bản.
- Admin có thể xem trạng thái hiệu lực và quan hệ văn bản.
- Admin có thể cập nhật hiệu lực thủ công với cảnh báo rằng metadata/quan hệ cần được người có chuyên môn xác nhận.

Lý do: hệ thống dữ liệu pháp luật cần vận hành và sửa lỗi được qua UI.

### P2 - Guest Mode

- Guest có quyền rất hạn chế.
- Guest không được upload hợp đồng.
- Guest không được truy cập admin.
- Phạm vi Guest cụ thể sẽ tùy cấu hình MVP.

Lý do: Guest hữu ích cho demo nhưng không nên làm tăng rủi ro dữ liệu.

## Features Out

Các phần sau không nằm trong MVP 1 tuần:

- Hỗ trợ nhiều lĩnh vực ngoài bảo hiểm.
- Upload văn bản pháp luật bởi Business User.
- Import văn bản bằng crawl/tra cứu số hiệu từ `wsvbpl.moj.gov.vn`/`vbpl.vn`.
- Tự động lấy quan hệ sửa đổi/thay thế/bãi bỏ từ nguồn nhà nước khi chưa có quyền truy cập hợp lệ.
- Hỗ trợ văn bản pháp luật dạng PDF/HTML nếu không có `.docx`.
- Bảo mật production-grade như reset password, SSO, MFA, rate limit nâng cao.
- Version history đầy đủ theo thời gian cho từng điều/khoản.
- Template `.docx` thật cho tờ trình/hợp đồng.
- Deployment cloud hoặc server production.
- Tự động cập nhật hiệu lực theo lịch nền hoặc crawl lại nguồn bên ngoài; MVP dùng chỉnh sửa thủ công bởi admin.
- Rà soát hợp đồng pháp lý toàn diện ngoài hai module thẩm quyền và hiệu lực.

## Designs

### Information Architecture

Ứng dụng Streamlit MVP gồm các khu vực chính:

- Login
- Chatbot tra cứu pháp luật
- Tìm kiếm từ khóa
- Upload và rà soát hợp đồng
- Tạo file `.docx` skeleton
- Admin: quản lý văn bản
- Admin: upload/import DOCX
- Admin: trạng thái pipeline
- Admin: cập nhật metadata/hiệu lực thủ công
- Admin: quản lý user

### Early Screen Sketches

#### User Chat

```text
+------------------------------------------------------------+
| BaoHiem Legal AI Workspace                 User: business  |
+------------------------------------------------------------+
| Sidebar                                                    |
| - Chatbot                                                  |
| - Tim kiem tu khoa                                         |
| - Ra soat hop dong                                         |
| - Tao docx draft                                           |
+----------------------+-------------------------------------+
| Question             | Answer                              |
| [input...]           | Theo van ban so ...                 |
| [Ask]                | Can cu: Dieu ..., Khoan ...         |
|                      | Hieu luc: Con hieu luc              |
|                      | Confidence: ...                     |
|                      | Citations                           |
+----------------------+-------------------------------------+
```

#### Admin DOCX Import

```text
+------------------------------------------------------------+
| Admin Console                              User: admin     |
+------------------------------------------------------------+
| Upload van ban .docx: [Choose file] [Import]                |
| Metadata: so hieu, ten van ban, loai, co quan, ngay hieu luc |
| Relations: optional, admin-curated                           |
+------------------------------------------------------------+
| Pipeline                                                   |
| pending -> uploaded -> parsed -> chunked                    |
| published or ready_for_review                               |
+------------------------------------------------------------+
| Published documents | Ready for review                      |
| [Edit + Reindex]    | [Publish when complete]               |
+------------------------------------------------------------+
```

#### Contract Review

```text
+------------------------------------------------------------+
| Ra soat hop dong                                           |
+------------------------------------------------------------+
| Upload .docx: [Choose file] [Review]                       |
+------------------------------------------------------------+
| Module tham quyen                                          |
| - Ten co quan ban hanh: Dung/Khong dung/Khong du du lieu   |
| - Chuc danh nguoi ky: Dung/Khong dung/Khong du du lieu     |
+------------------------------------------------------------+
| Module hieu luc                                            |
| - Trang thai: Con hieu luc/Khong con hieu luc              |
| - Canh bao: ...                                            |
| - Citations: ...                                           |
+------------------------------------------------------------+
```

## Open Issues

- Bộ metadata tối thiểu admin bắt buộc nhập trước khi publish cần được chốt.
- Cách hiển thị trạng thái thiếu quan hệ văn bản trong UI cần được thiết kế rõ để tránh hiểu nhầm là văn bản không có quan hệ.
- Bộ nhãn quan hệ Neo4j cần chốt tên tiếng Anh/tiếng Việt nhất quán.
- Công thức confidence score cần chốt: retrieval score, rerank score, citation presence, graph support, LLM self-check.
- Format câu trả lời cuối cùng cần chốt sau.
- Bộ test accuracy 80% cần được xây dựng: số lượng câu hỏi, loại câu hỏi, ground truth, cách chấm.
- Rule rà soát thẩm quyền/hiệu lực cần được cụ thể hóa thành bảng rule hoặc cấu hình.
- Guest mode có được hỏi thử trên dữ liệu thật hay chỉ xem màn hình demo.
- Cơ chế rollback ChromaDB/BM25/Neo4j ở MVP sẽ snapshot theo batch hay soft-delete theo version.
- Có cần giữ lịch sử câu hỏi/câu trả lời theo user trong MVP hay không.

## Q&A

**Q: MVP có bao gồm tất cả module không?**  
A: Có. MVP gồm chatbot, admin quản lý kho dữ liệu, import DOCX trực tiếp từ admin, graph cấp 2 theo cấu trúc văn bản, graph cấp 1 từ quan hệ admin nhập nếu có, dense embedding, BM25, hybrid retrieval, rà soát hợp đồng cơ bản và khung sinh `.docx`.

**Q: Sản phẩm hỗ trợ lĩnh vực nào?**  
A: Chỉ lĩnh vực bảo hiểm trong MVP.

**Q: Người dùng thường có được thêm văn bản pháp luật không?**  
A: Không. Người dùng chỉ hỏi trên kho do admin quản lý và chỉ upload hợp đồng để rà soát.

**Q: MVP có crawl từ `wsvbpl.moj.gov.vn`/`vbpl.vn` không?**
A: Không. Tính năng crawl/import theo số hiệu được tạm bỏ vì nguồn `https://wsvbpl.moj.gov.vn/` không cho phép dùng nếu không có quyền truy cập. MVP xử lý trực tiếp file `.docx` do admin upload.

**Q: Nếu admin chưa có thông tin quan hệ giữa các văn bản thì sao?**
A: Hệ thống vẫn xử lý nội dung DOCX, tạo chunk, ChromaDB, BM25 và graph cấp 2 theo cấu trúc văn bản. Graph cấp 1 giữa các văn bản và các kết luận liên quan tới sửa đổi/thay thế/bãi bỏ sẽ bị thiếu hoặc được đánh dấu `không đủ dữ liệu`.

**Q: Graph dùng công nghệ gì?**  
A: Neo4j cho graph cấp 2 theo cấu trúc `Document -> Chapter -> Article -> Clause`. Graph cấp 1 giữa văn bản chỉ có dữ liệu khi admin nhập hoặc xác nhận quan hệ.

**Q: Có lưu version history theo thời gian không?**  
A: MVP chỉ lưu trạng thái mới nhất.

**Q: Retrieval xử lý keyword và câu hỏi tự nhiên khác nhau thế nào?**  
A: Tìm từ khóa ưu tiên BM25. Câu hỏi tự nhiên dùng hybrid retrieval kết hợp dense embedding, BM25, graph cấp 2 và graph cấp 1 nếu có quan hệ được nhập.

**Q: Có lọc văn bản còn hiệu lực trước retrieval không?**  
A: Có.

**Q: Sản phẩm chạy ở đâu?**  
A: Local cá nhân.

**Q: Frontend/backend là gì?**  
A: Streamlit frontend và Flask API backend.

**Q: Multi-user nhẹ nghĩa là gì?**  
A: Có user table, password hash, login/logout, session riêng và role Admin/Business User/Guest, nhưng chưa đạt chuẩn bảo mật production.

**Q: Có được gọi DeepSeek/OpenAI API không?**  
A: Có.

**Q: Release target là gì?**  
A: Dùng thật ở mức MVP trong khoảng 1 tuần, với độ chính xác chung khoảng 80%.

## Other Considerations

### Current Codebase Fit

Codebase hiện có các mảnh prototype quan trọng:

- CLI entrypoint cho ingest/embed/graph retrieval.
- Ingestion `.docx` local.
- LLM-based legal chunking.
- ChromaDB embedding bằng BGE-M3.
- Text-to-Cypher retrieval với Neo4j.
- Prompt trả lời có yêu cầu citation.

PRD này giả định TRD sẽ refactor prototype thành kiến trúc module:

- `backend/api`
- `backend/services`
- `backend/models`
- `frontend/streamlit`
- `src/ingestion`
- `src/indexing`
- `src/retrieval`
- `src/contract_review`
- `src/doc_generation`

### Risk Notes

- MVP 1 tuần vẫn có rủi ro nếu phải hoàn thiện graph writer, BM25, UI, auth, rollback và contract review cùng lúc.
- Độ chính xác 80% cần được định nghĩa bằng test set có ground truth, nếu không sẽ dễ trở thành cảm tính.
- Vì bỏ crawl từ `wsvbpl.moj.gov.vn`/`vbpl.vn`, MVP giảm rủi ro truy cập nguồn nhưng tăng rủi ro thiếu metadata quan hệ, hiệu lực, thay thế/bãi bỏ.
- LLM chunking có thể sai cấu trúc văn bản, cần review và rollback.
- Local prototype có thể chậm nếu embed nhiều văn bản bằng model lớn.

### Product Principle

Ưu tiên độ tin cậy hơn độ "thông minh". Với pháp lý, hệ thống nên trả lời ít nhưng có căn cứ, hơn là trả lời nhiều nhưng thiếu citation hoặc dùng nhầm văn bản hết hiệu lực.
