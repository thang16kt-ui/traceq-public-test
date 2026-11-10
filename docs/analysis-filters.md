# Lọc phân tích theo loại sản phẩm và lô

Thanh lọc mới nằm dưới bộ chọn thời gian trong Phân tích, và có cùng lựa chọn trên Tổng quan.

1. Chọn **Loại sản phẩm** để xem tổng số liệu của các lô thuộc loại đó.
2. Chọn **Lô sản phẩm** để thu hẹp xuống một lô. Danh sách chỉ chứa lô của loại sản phẩm đang chọn.
3. Đổi loại sản phẩm sẽ bỏ lựa chọn lô cũ. **Bỏ lọc sản phẩm / lô** trở về tất cả sản phẩm, giữ nguyên kỳ thời gian.

Summary, Pareto, xu hướng, so sánh nhóm, chi phí và thông tin dự báo cùng nhận `product_type_id`, `batch_id`, `period_start`, `period_end`. Các mốc thời gian dùng chung một query, theo thời điểm bắt đầu đợt kiểm tra như hợp đồng API hiện có. Tử số và mẫu số đều tính ở server trong cùng phạm vi; không lọc riêng biểu đồ trên dữ liệu tổng.

Danh mục ngừng sử dụng vẫn có trong lựa chọn phân tích và được ghi chú rõ để xem lịch sử. Form ghi nhận mới tiếp tục chỉ dùng danh mục đang hoạt động. Không đổi schema, không di chuyển hoặc sửa dữ liệu.

Đổi bộ lọc sẽ hủy request cũ; kết quả được gắn khóa phạm vi để phản hồi chậm không ghi đè lựa chọn mới. Các phần summary/Pareto/trends/forecast cập nhật cùng một lần, không hiển thị kết quả lẫn phạm vi nếu một request lỗi. Có trạng thái đang tải, trống và thử lại; so sánh nhóm có xử lý tương tự. Bản minh họa offline khóa bộ lọc, không giả lập kết quả lọc từ số liệu cố định.

Kiểm chứng:

- Build TypeScript/Vite và kiểm thử PostgreSQL thật.
- Ba lô thuộc hai loại sản phẩm: kiểm tra giao của loại sản phẩm, lô và thời gian; tỷ lệ, lượt lỗi, chi phí và nhóm đều đúng; loại sản phẩm ngừng dùng vẫn phân tích được.
- Chromium 375px/1280px: chọn loại/lô, reset lô khi đổi loại, kết hợp thời gian, chi phí, so sánh, dữ liệu rỗng, lỗi/thử lại và phản hồi cũ đến muộn. Không tràn ngang; ô chọn mới cao ít nhất 48px.

Giới hạn hiện có: dự báo chưa có mô hình được kiểm chứng nên vẫn hiển thị chưa đủ dữ liệu. Nút Hồ sơ nguồn mở danh sách hồ sơ chung; chức năng xuất dữ liệu có phạm vi riêng, không tự nhận bộ lọc mới. Danh sách hồ sơ gần đây trên Tổng quan chỉ xét tối đa 100 hồ sơ đã tải; số liệu phân tích dùng toàn bộ dữ liệu phù hợp ở server.
