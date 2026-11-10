# Rà soát độc lập

Rà soát này tập trung vào toàn vẹn dữ liệu và ranh giới quyền của mã nguồn MVP. Đây là kiểm tra mã nguồn, không thay nghiệm thu bảo mật hoặc thử nghiệm trên điện thoại thật. Kết quả chạy kiểm thử nằm trong [verification.md](verification.md).

Các điểm phải giữ khi mở rộng:

- Quyền xem hồ sơ phải áp dụng cho QR, tem và tệp liên quan; token QR không cấp quyền.
- `client_event_id` không được tái sử dụng giữa hồ sơ hoặc tài khoản để nhận lại dữ liệu ngoài quyền.
- Xác nhận đầu tiên, sự kiện quét và audit phải cùng giao dịch PostgreSQL. Ràng buộc duy nhất và khóa bản ghi bảo vệ khi nhiều thiết bị gửi đồng thời.
- Đổi bảng con lỗi/chi phí phải tăng phiên bản hồ sơ để importer có thể thay thế toàn bộ tập con mà không nhận nhầm snapshot cũ.
- Importer phải kiểm schema, giá trị bắt buộc, enum, phạm vi kỳ và liên kết; checksum chỉ chứng minh nội dung không đổi, không chứng minh dữ liệu hợp lệ.
- Snapshot cùng kỳ/revision cần bất biến; chạy lại không tự chốt dữ liệu mới dưới tên kết quả cũ.
- Sửa giờ hoặc múi giờ chạy không được tự xóa watermark kỳ dữ liệu đã xuất.
- Chi phí phải giữ `Decimal`, cộng mỗi khoản một lần, tách thực tế/ước tính và tiền tệ; không suy ra chi phí thiếu bằng 0.

Phạm vi chưa được kiểm chứng bằng rà soát mã: quyền camera/tem vật lý, thiết bị và trình duyệt thực tế, offline, hạ tầng TLS của nhà máy, diễn tập khôi phục và kiểm toán vận hành.

Các vấn đề đã phát hiện và sửa trong quá trình rà soát:

- Đường dẫn gói xuất tương đối được nối vào `DATA_DIR` trước khi kiểm tra quyền tải.
- Tra cứu serial trùng giữa nhiều lô báo xung đột để chọn đúng lô; không chọn sản phẩm đầu tiên.
- Kiểm tra quyền hồ sơ trước khi phát lại kết quả idempotency. Khóa ORM dùng `populate_existing=True` để lấy trạng thái mới sau khi chờ khóa PostgreSQL.
- Xác nhận đầu tiên và chốt đợt dùng cùng thứ tự khóa đợt/hồ sơ. Xác nhận muộn vào đợt đã chốt cần quản lý mở lại có lý do.
- Snapshot nguồn `REPEATABLE READ` không cập nhật dòng heartbeat trong cùng transaction, tránh xung đột tuần tự hóa khi xuất lâu.
- ZIP/XLSX có metadata cố định; retry dùng lại gói bất biến đã kiểm tra. Đã kiểm tra độc lập rằng cùng snapshot rỗng tạo lại CSV và XLSX sau hơn hai giây vẫn có cùng SHA-256.
- Importer kiểm trường bắt buộc/nullable, enum, phạm vi kỳ, các khóa duy nhất nghiệp vụ và quan hệ cha/con. Có giới hạn hàng, kích thước giải nén cả ZIP ngoài lẫn XLSX bên trong.
- Mẫu số xuất kèm loại sản phẩm/lô, kể cả đợt không có lỗi. Snapshot cha mới không được kéo phiên bản con lùi lại.

Danh sách trên ghi nhận sửa mã; chỉ các tình huống có kết quả chạy trong biên bản kiểm chứng mới được coi là đã kiểm thử tích hợp.
