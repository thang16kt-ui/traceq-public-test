# Kiểm tra và xử lý trang trắng

Đã tái hiện trang trắng bằng cách tắt `Object.hasOwn` trong Chromium: sau khi dữ liệu xu hướng được tải, biểu đồ ném lỗi `Object.hasOwn is not a function`, React gỡ giao diện và chỉ còn màu nền. Đây là một nguyên nhân tương thích đã kiểm chứng; chưa có thông tin trình duyệt của người dùng để khẳng định thiết bị của họ gặp đúng nguyên nhân này.

Bản sửa dùng `Object.prototype.hasOwnProperty.call`, đồng thời dùng UUID v4 từ `crypto.getRandomValues` để các form hoạt động khi trình duyệt chưa có `crypto.randomUUID`.

Thêm lớp bắt lỗi hiển thị với nút tải lại, không để lỗi render làm trang trắng. HTML ban đầu có nội dung chờ và thông báo khi bundle bị chặn/lỗi tải; nội dung vẫn hiện nếu JavaScript bị tắt. Nút tải lại giữ nguyên đường dẫn QR và thêm tham số mới để lấy HTML hiện tại. Không tự tải lại liên tục hoặc xóa cookie, dữ liệu thiết bị hay database.

Kiểm chứng Chromium trên bản build:

- Tắt `Object.hasOwn` và `crypto.randomUUID`: Tổng quan, biểu đồ và form ghi nhận vẫn hiển thị.
- Chặn file JavaScript: có thông báo và nút Tải lại TraceQ.
- Gây lỗi render có chủ đích: có màn hình phục hồi và thông tin lỗi để gửi hỗ trợ.
- Build TypeScript/Vite thành công. Không có thay đổi schema/API/dữ liệu nghiệp vụ.

Nếu một thiết bị vẫn gặp lỗi, cần ghi nhận trình duyệt/phiên bản, URL và thông tin lỗi trên màn hình phục hồi; không coi HTTP 200 hoặc kiểm tra trên máy khác là bằng chứng thiết bị đó đã hoạt động.
