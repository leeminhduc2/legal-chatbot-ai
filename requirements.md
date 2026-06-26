# Tên chủ đề : Hệ thống RAG chatbot tra cứu pháp luật, rà soát hợp đồng cơ bản, cảnh báo rủi ro và hỗ trợ soạn thảo hợp đồng/tờ trình trong lĩnh vực

## Mô tả :

Bộ phận pháp chế doanh nghiệp thường phải xử lý đồng thời nhiều nghiệp vụ như tra cứu văn bản pháp luật, kiểm tra hiệu lực văn bản, rà soát điều khoản hợp đồng, phát hiện rủi ro pháp lý và hỗ trợ soạn thảo hồ sơ nội bộ. Ví dụ: Trong lĩnh vực bảo hiểm, khối lượng văn bản quy phạm pháp luật lớn, có nhiều văn bản hướng dẫn, sửa đổi, hợp nhất và thay thế nên việc tra cứu thủ công dễ mất thời gian và dễ sử dụng nhầm văn bản đã hết hiệu lực hoặc chưa cập nhật đủ bản sửa đổi.


## Các bước thực hiện :

"Bước 1: Khảo sát phạm vi và thu thập dữ liệu
- Chốt phạm vi lĩnh vực bảo hiểm.
- Xác định danh mục văn bản lõi, văn bản hướng dẫn, văn bản sửa đổi, văn bản hợp nhất và nguồn tra cứu ưu tiên.
- Tải, chuẩn hóa và phân loại dữ liệu theo loại văn bản, số hiệu, ngày ban hành, ngày hiệu lực, ngày hết hiệu lực, quan hệ sửa đổi/bổ sung/thay thế.
- Chuẩn bị thêm bộ hợp đồng mẫu, tờ trình mẫu và checklist rà soát hợp đồng cơ bản theo nghiệp vụ.

Bước 2: Xây dựng kho tri thức pháp lý
- Chuyển đổi văn bản sang định dạng có cấu trúc: chương, mục, điều, khoản, điểm.
- Chunk theo đơn vị pháp lý thay vì cắt theo số ký tự thuần túy để tăng độ chính xác truy xuất.
- Gắn metadata cho từng chunk, ví dụ: số hiệu, tên văn bản, điều khoản, ngày hiệu lực, trạng thái hiệu lực, văn bản thay thế, lĩnh vực con.
- Xây dựng chỉ mục tìm kiếm kết hợp toàn văn và vector để phục vụ RAG.

Bước 3: Xây dựng tính năng cập nhật hiệu lực
- Thiết kế bảng quản lý hiệu lực văn bản với các trạng thái như còn hiệu lực, hết hiệu lực, bị sửa đổi một phần, được hợp nhất, bị thay thế.
- Xây dựng pipeline cập nhật định kỳ từ các nguồn chính thống hoặc nguồn tổng hợp có cấu trúc, sau đó kiểm tra lại thủ công với các văn bản quan trọng.
- Khi người dùng hỏi, hệ thống phải lọc bỏ chunk thuộc văn bản hết hiệu lực toàn bộ, đồng thời ưu tiên trích dẫn văn bản hợp nhất hoặc văn bản mới nhất đang còn hiệu lực.
- Nếu gặp trường hợp quy định đã bị sửa đổi một phần, hệ thống cần thông báo rõ rằng nội dung trả lời dựa trên phiên bản đã được cập nhật.

Bước 4. Xây dựng chatbot tra cứu pháp luật
- Xây dựng giao diện hỏi đáp cho người dùng nhập câu hỏi tự nhiên.
- Thực hiện truy xuất tài liệu liên quan theo lĩnh vực đã lựa chọn, sau đó sinh câu trả lời có cấu trúc gồm: kết luận ngắn, căn cứ pháp lý, tình trạng hiệu lực, khuyến nghị rà soát thêm.
- Bắt buộc hiển thị nguồn trích dẫn theo điều/khoản/văn bản để người dùng kiểm tra lại.
- Bổ sung guardrail để từ chối hoặc cảnh báo khi câu hỏi vượt khỏi phạm vi lĩnh vực đã lựa chọn hoặc vượt quá độ tin cậy của dữ liệu hiện có.

Bước 5. Xây dựng chức năng rà soát hợp đồng và cảnh báo rủi ro
- Xác định phạm vi hợp đồng cần hỗ trợ, ví dụ hợp đồng đại lý bảo hiểm, hợp đồng dịch vụ liên quan đến bảo hiểm hoặc hợp đồng hợp tác kinh doanh có yếu tố bảo hiểm.
- Xây dựng checklist rà soát cơ bản, gồm các nhóm mục như thông tin chủ thể, căn cứ pháp lý, đối tượng, quyền và nghĩa vụ, điều kiện thanh toán, trách nhiệm vi phạm, chấm dứt, giải quyết tranh chấp, điều khoản hiệu lực.
- Kết hợp rule-based và LLM để phát hiện các trường hợp như thiếu điều khoản bắt buộc, thuật ngữ mơ hồ, mâu thuẫn điều khoản, phân bổ rủi ro bất lợi cho doanh nghiệp, hoặc dẫn chiếu văn bản đã cũ.
- Trả ra báo cáo rà soát ngắn gồm: mục đã đạt, mục cần bổ sung, mức độ rủi ro, và gợi ý chỉnh sửa.

Bước 6. Hỗ trợ viết hợp đồng và tờ trình
- Xây dựng form nhập liệu cho từng loại biểu mẫu cần hỗ trợ.
- Thiết kế prompt template để sinh nháp hợp đồng/tờ trình theo cấu trúc chuẩn.
- Chèn căn cứ pháp lý phù hợp từ kho tri thức khi tạo nội dung, nhưng vẫn yêu cầu người dùng rà soát pháp lý cuối cùng trước khi sử dụng thực tế.
- Cho phép người dùng chọn mẫu văn bản, ví dụ: tờ trình xin ý kiến, tờ trình phê duyệt ký kết, hợp đồng nguyên tắc, phụ lục hợp đồng.

Bước 7. Kiểm thử và đánh giá
- Kiểm thử bộ câu hỏi pháp lý theo tình huống thực tế trong lĩnh vực bảo hiểm.
- Kiểm thử riêng trường hợp văn bản bị sửa đổi, bị thay thế hoặc có văn bản hợp nhất để đánh giá tính đúng đắn của cơ chế hiệu lực.
- Kiểm thử chức năng rà soát trên các hợp đồng mẫu có cài sẵn lỗi hoặc điều khoản rủi ro.
- Đánh giá đầu ra theo các tiêu chí: đúng căn cứ, đúng hiệu lực, rõ cảnh báo, dễ đọc, có thể chỉnh sửa tiếp."

## Yêu cầu đầu ra 

"Hệ thống đầu ra tối thiểu cần đáp ứng các chức năng sau:
- Cho phép người dùng hỏi đáp các vấn đề pháp lý trong một lĩnh vực cụ thể là bảo hiểm.
- Mỗi câu trả lời phải hiển thị căn cứ pháp lý tương ứng và trạng thái hiệu lực của văn bản được sử dụng.
- Hệ thống phải có cơ chế cập nhật dữ liệu văn bản và ưu tiên văn bản mới nhất còn hiệu lực khi trả lời.
- Cho phép tải lên hợp đồng để rà soát theo checklist cơ bản.
- Trả ra danh sách cảnh báo rủi ro pháp lý sơ bộ cho hợp đồng đã nhập.
- Hỗ trợ sinh nháp hợp đồng và tờ trình từ mẫu đầu vào."