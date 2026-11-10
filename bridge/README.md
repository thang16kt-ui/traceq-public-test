# Bridge tới thư mục nhà máy — chưa triển khai ở MVP

MVP chuyển gói ZIP hoàn chỉnh qua volume bền vững `/data/incoming` và cho quản lý
tải qua API có xác thực. Tiến trình `python -m worker.main importer` kiểm tra rồi
chuyển sang `/data/processed` hoặc `/data/failed`. Không nhập `.tmp`.

Để dùng thư mục ở máy nhà máy: cần bridge agent riêng được cài tại máy đó,
chỉ kéo HTTPS bằng tài khoản dịch vụ có quyền đọc bản xuất, ghim tên miền và
thư mục đích cho phép, kiểm checksum, ghi tệp tạm rồi đổi tên. Không đưa thông
tin đăng nhập vào QR hoặc cho trình duyệt ghi đường dẫn tùy ý. Endpoint service
account và agent Windows/Linux chưa có trong MVP; không cấu hình giả là đã chạy.
