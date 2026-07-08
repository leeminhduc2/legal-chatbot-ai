# Review top-down: `regex_chunk_text`

## 1. Hàm này nằm ở đâu trong pipeline?

`regex_chunk_text` nằm trong `backend/services/document_import_service.py` và là nhánh chunking dự phòng, có tính quyết định, cho tài liệu DOCX do admin upload.

Luồng tổng quát:

1. Admin upload DOCX.
2. Service đọc nội dung, chuẩn hóa metadata và tạo `document_id`, `import_batch_id`.
3. `_chunk_text(...)` quyết định cách chia chunk.
4. Nếu `config.llm_chunking_enabled` bật, service thử dùng `LLMVietnameseLegalSplitter`.
5. Nếu LLM chunking tắt, lỗi, hoặc trả về rỗng, service ghi warning rồi gọi `regex_chunk_text(...)`.

Nói ngắn gọn: `regex_chunk_text` là lớp fallback deterministic để hệ thống vẫn tạo được chunk khi không dùng được LLM splitter.

## 2. Input và output của `regex_chunk_text`

Input:

- `text`: toàn bộ văn bản đã trích xuất từ DOCX.
- `document_id`: định danh tài liệu trong registry.
- `import_batch_id`: định danh lô import hiện tại.
- `metadata`: metadata đã chuẩn hóa, ví dụ `document_number`, `document_title`, `validity_status`, ngày hiệu lực.

Output:

- Một list các dictionary chunk.
- Mỗi chunk đã có `chunk_id`, `content`, `article_number`, `clause_number`, `citation_label`, `hierarchy_path`, `chunk_level`, `ordinal`, metadata pháp lý và trạng thái publish.

Hàm không trả về text thô. Nó trả về record đã sẵn sàng để lưu vào file chunked JSON và đi tiếp sang các bước publish/index.

## 3. Luồng top-down bên trong hàm

Pseudo-flow:

```python
article_segments = find article segments

if no article_segments:
    return one fallback article-level chunk for whole text

chunks = []
for each article:
    clause_chunks = split article into clauses
    if no clause_chunks:
        add one article-level chunk
    else:
        add one clause-level chunk per clause

return chunks
```

Chi tiết hơn:

1. Tìm các đoạn bắt đầu bằng heading dạng `Điều <số>`.
2. Nếu không tìm được điều nào, coi toàn văn là một chunk duy nhất, gắn `article_number="1"` và `chunk_level="article"`.
3. Với mỗi Điều tìm được, thử chia tiếp thành các Khoản bằng pattern dòng dạng `1. ...`, `2. ...`.
4. Nếu một Điều có ít hơn 2 khoản được nhận diện, giữ nguyên cả Điều thành một chunk cấp article.
5. Nếu có từ 2 khoản trở lên, mỗi khoản trở thành một chunk cấp clause.
6. Mọi chunk đều đi qua `build_chunk_record(...)` để tạo ID, citation, hierarchy path và enrich metadata.

## 4. Sự thật dễ bị bỏ sót: nhánh segment-pattern hiện đang bị tắt

Đoạn đầu hàm có cấu trúc:

```python
article_segments = (
    _find_article_segments_with_segment_pattern(text)
    if False
    else _find_article_segments_with_legacy_boundaries(text)
)
```

Vì điều kiện là `if False`, code thực tế luôn dùng `_find_article_segments_with_legacy_boundaries(text)`.

Điều này quan trọng vì trong file có một regex lớn tên `EXTRACT_SEGMENTS_SEGMENT_PATTERN_1`, nhìn qua tưởng là cơ chế chính để cắt Điều. Nhưng hiện tại nó không chạy trong production path của hàm này. Cách cắt thật đang là legacy boundary splitter theo từng dòng.

Nếu đánh giá chất lượng chunking mà chỉ đọc tên biến/pattern lớn, rất dễ hiểu sai rằng hệ thống đang dùng regex segment phức tạp hơn thực tế.

## 5. Cách tìm Điều

Đường chạy thực tế:

```python
_find_article_segments_with_legacy_boundaries(text)
  -> _find_article_boundaries(text)
  -> _iter_chunk_boundary_lines(text)
  -> _ARTICLE_HEADING_RE.match(line_text)
```

`_ARTICLE_HEADING_RE` nhận heading dạng:

```regex
^\s*(?:Điều|Dieu)\s+([0-9]+[a-zA-Z]?)\.?\s*(.*)$
```

Ý nghĩa:

- Dòng có thể bắt đầu bằng whitespace.
- Sau đó là `Điều` hoặc `Dieu`.
- Tiếp theo là số điều, có thể kèm chữ cái, ví dụ `12`, `12a`.
- Dấu chấm sau số là optional.
- Phần tiêu đề sau số điều có thể có hoặc không.

Khi tìm được các boundary Điều, hàm lấy text từ vị trí bắt đầu của Điều hiện tại đến ngay trước Điều kế tiếp. Đó là một `article_segment`.

Ví dụ:

```text
Điều 1. Phạm vi điều chỉnh
...
Điều 2. Đối tượng áp dụng
...
```

Kết quả segment:

- Segment 1: từ `Điều 1...` đến trước `Điều 2...`
- Segment 2: từ `Điều 2...` đến hết hoặc trước Điều tiếp theo

## 6. Cách tìm Khoản

Sau khi có `article_text`, hàm gọi:

```python
split_article_clauses(article_text)
```

Luồng bên trong:

```python
_find_clause_boundaries(article_text)
  -> _iter_chunk_boundary_lines(article_text)
  -> _CLAUSE_HEADING_RE.match(line_text)
```

`_CLAUSE_HEADING_RE` là:

```regex
^\s*(\d+)\.\s+
```

Nó chỉ nhận các dòng bắt đầu bằng dạng:

```text
1. Nội dung khoản một
2. Nội dung khoản hai
```

Điểm rất quan trọng: `split_article_clauses` chỉ trả về clause chunks nếu tìm được ít nhất 2 clause boundary. Nếu chỉ tìm được 1 boundary, hàm trả về rỗng và toàn bộ Điều được giữ thành một article-level chunk.

Giả định ngầm ở đây là một Điều có một khoản duy nhất thì không đáng tách khoản, hoặc việc nhận diện một boundary đơn lẻ chưa đủ tin cậy. Đây là một heuristic, không phải quy tắc pháp lý chắc chắn.

## 7. Cơ chế bảo vệ vùng trích dẫn/sửa đổi

Các hàm tìm Điều và Khoản đều đi qua `_iter_chunk_boundary_lines(text)`.

Helper này duyệt từng dòng và gắn cờ `protected` nếu dòng đang nằm trong:

- dấu nháy kép thẳng `"..."`;
- dấu nháy cong mở/đóng;
- vùng amendment quote sau cụm kiểu `như sau:`;
- dòng bắt đầu bằng ký tự mở quote.

Nếu một dòng bị `protected`, `_find_article_boundaries` và `_find_clause_boundaries` bỏ qua dòng đó, kể cả khi dòng đó trông giống `Điều 5` hoặc `1. ...`.

Mục đích là tránh cắt nhầm khi văn bản luật đang trích dẫn hoặc thay thế một đoạn luật khác. Ví dụ, câu "sửa đổi Điều 3 như sau:" có thể chứa nguyên văn nhiều Điều/Khoản bên trong phần trích dẫn. Nếu không bảo vệ, splitter có thể tưởng đó là cấu trúc chính của tài liệu hiện tại.

Đây là một điểm thiết kế đúng hướng, nhưng vẫn là heuristic: nó phụ thuộc vào dấu quote và cách trình bày trong DOCX sau khi trích xuất text.

## 8. `build_chunk_record` làm gì?

`regex_chunk_text` không tự build dictionary trực tiếp. Mọi chunk đều đi qua `build_chunk_record(...)`.

Helper này tạo:

- `chunk_id`: UUID v5 từ `document_id`, `article_number`, `clause_number`, `ordinal`.
- `citation_label`: ví dụ `01/2024/TT-XYZ, Điều 3, khoản 2`.
- `hierarchy_path`: ví dụ `Document/<so_hieu>/Article/3/Clause/2`.
- `content`: text đã được chuẩn hóa thêm ngữ cảnh nếu là clause chunk.
- metadata: số hiệu, tiêu đề, loại văn bản, source, hiệu lực, ngày hiệu lực, ngày hết hiệu lực, version/publish flags.

Với chunk cấp clause, `format_clause_content(...)` cố gắng thêm prefix `Điều <article>.<clause>.` nếu nội dung chỉ bắt đầu bằng `1.`, `2.`, ...

Mục đích là để chunk clause vẫn có ngữ cảnh Điều khi đứng độc lập trong retrieval.

## 9. Ví dụ nhỏ

Input đơn giản:

```text
Điều 1. Phạm vi điều chỉnh
Văn bản này quy định ...

Điều 2. Trách nhiệm
1. Cơ quan A có trách nhiệm ...
2. Cơ quan B có trách nhiệm ...
```

Kết quả logic:

- `Điều 1` không có ít nhất 2 khoản, nên tạo 1 article chunk.
- `Điều 2` có 2 khoản, nên tạo 2 clause chunks.

Output khái niệm:

```text
chunk 1: article_number=1, clause_number=None, chunk_level=article
chunk 2: article_number=2, clause_number=1, chunk_level=clause
chunk 3: article_number=2, clause_number=2, chunk_level=clause
```

## 10. Các giả định ngầm và điểm yếu cần nhìn thẳng

1. Hàm giả định cấu trúc pháp luật nằm ở đầu dòng. Nếu DOCX extract làm `Điều 1` dính vào dòng trước, splitter có thể không nhận ra.

2. Hàm chỉ nhận `Điều` hoặc `Dieu`; các biến thể lỗi OCR/encoding hoặc viết khác có thể lọt.

3. Khoản chỉ nhận dạng `1.`, `2.`, ... ở đầu dòng. Nếu văn bản dùng `1)` hoặc `Khoản 1`, hàm hiện không tách khoản.

4. Điểm như `a)`, `b)` không được tách thành chunk riêng. Đây có thể là chủ ý để tránh chunk quá nhỏ, nhưng nếu câu hỏi truy vấn theo điểm thì retrieval có thể kém chính xác.

5. Nếu một Điều chỉ có một khoản, hàm giữ cả Điều thay vì tạo clause chunk. Điều này giúp tránh false positive nhưng làm metadata clause bị mất trong trường hợp Điều thật sự chỉ có một khoản.

6. Vùng quote/amendment quote được bảo vệ bằng heuristic dấu nháy. Nếu DOCX thiếu dấu đóng/mở quote hoặc parser làm mất ký tự, protected state có thể sai và kéo theo cắt sai.

7. Tên `regex_chunk_text` hơi rộng. Thực tế production path hiện tại là line-boundary regex splitter, không phải một parser pháp lý hoàn chỉnh.

8. Hàm không kiểm tra chất lượng chunk theo semantic completeness. Nó chỉ kiểm tra cấu trúc regex. Vì vậy "có chunk" không đồng nghĩa "chunk đúng pháp lý".

## 11. Đánh giá ngắn

`regex_chunk_text` phù hợp làm fallback deterministic: đơn giản, dễ đoán, không phụ thuộc LLM, và có bảo vệ cơ bản chống cắt nhầm trong phần trích dẫn/sửa đổi.

Nhưng nếu coi nó là bộ tách pháp lý chính xác cao thì đó là một giả định yếu. Nó chưa hiểu đầy đủ hierarchy văn bản pháp luật Việt Nam như Chương, Mục, Tiểu mục, Điều, Khoản, Điểm; cũng chưa xử lý nhiều biến thể trình bày thực tế trong DOCX. Với dữ liệu sạch, nó đủ dùng để tạo chunk cơ bản. Với văn bản phức tạp hoặc OCR/encoding xấu, cần test bằng corpus thật và đo false split/missed split thay vì chỉ tin vào regex.
