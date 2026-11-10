# Vận hành, bảo mật và phục hồi

## Trước khi đưa vào sử dụng

MVP là phần mềm có thể kiểm chứng trong môi trường thử, chưa thay thế nghiệm thu tại nhà máy. Chạy các kiểm thử PostgreSQL, thử nhãn trên máy in/điện thoại thật, kiểm tra quyền camera và diễn tập khôi phục trước khi nhập dữ liệu vận hành. Kết quả đã đo nằm trong [verification.md](verification.md); các mục tiêu tải trong yêu cầu không phải cam kết đã đạt.

Giữ dữ liệu minh họa trong database riêng. Không chạy seed minh họa vào database sản xuất. `.env.example` chỉ chứa cấu hình mẫu; tạo mật khẩu riêng và không đưa `.env`, backup hay ảnh sản phẩm vào Git.

## HTTPS và cookie

- Frontend và `/api/v1` đi cùng hostname qua reverse proxy. URL QR sử dụng `APP_ORIGIN` đúng hostname HTTPS người dùng sẽ truy cập.
- Sản xuất đặt `COOKIE_SECURE=true`. Cookie phiên `HttpOnly`, `SameSite` phù hợp; thao tác ghi gửi token CSRF và kiểm tra origin ở API.
- Chỉ thử HTTP trên localhost với `COOKIE_SECURE=false`. Camera từ điện thoại thường cần HTTPS; `http://địa-chỉ-LAN` không tương đương localhost.
- Có thể dùng Caddy trước Nginx: hostname thật và DNS trỏ đúng máy chủ sẽ cấp chứng thư công khai; chế độ localhost dùng CA nội bộ cần tin cậy trên thiết bị thử. Không tắt xác minh TLS để giải quyết lỗi chứng thư.
- Không công bố cổng PostgreSQL ra Internet. Chỉ reverse proxy/API được nhận lưu lượng ngoài; volume database và báo cáo phải bền vững.

## Dữ liệu và quyền

Backend xác định người thao tác từ phiên đăng nhập, không tin `actor_id` từ client. Nhân viên chỉ thao tác hồ sơ theo quyền được giao/được tạo; quản lý xác minh và duyệt; quản trị viên quản lý người dùng, danh mục và lịch. Kiểm tra quyền phải xảy ra ở API cho cả QR, ảnh, tem và file xuất; ẩn nút trên frontend không đủ bảo vệ.

QR chỉ là định danh ngẫu nhiên. Biết token hoặc UUID không cấp quyền. Mở `/q/{token}` hay `GET /api/v1/qr/{token}` không xác nhận lỗi. Không ghi QR token, mật khẩu, cookie hoặc nội dung nhạy cảm vào access log. Đặt policy redact đường dẫn `/q/` và `/api/v1/qr/` ở proxy/log collector nếu lưu access log.

API dùng truy vấn tham số hóa, mật khẩu băm bằng thư viện chuyên dụng, lỗi chuẩn có `request_id`, phân trang giới hạn. Quy trình vận hành vẫn cần TLS, giới hạn tần suất tại reverse proxy, cập nhật bản vá, giám sát truy cập và chính sách mật khẩu theo tổ chức. Không coi thử nghiệm cục bộ là kiểm toán bảo mật hoàn chỉnh.

## Tiến trình nền và đối soát

`scheduler`, `worker` và `importer` là các tiến trình độc lập. Scheduler chỉ tạo công việc PostgreSQL khi đến hạn. Worker claim việc bằng khóa database, tạo snapshot/file rồi mới đánh dấu thành công. Importer chỉ nhận gói hoàn chỉnh và đã kiểm tra. Redis không được dùng làm nguồn dữ liệu.

Theo dõi riêng:

| Tín hiệu | Ý nghĩa cần xử lý |
|---|---|
| `/health/live` lỗi | Tiến trình API không sống |
| `/health/ready` lỗi | Database hoặc điều kiện phục vụ chưa sẵn sàng |
| Công việc `queued` quá lâu | Worker không chạy hoặc thiếu tài nguyên |
| `running` nhưng heartbeat cũ | Worker mắc kẹt; kiểm tra retry/reclaim và lỗi file |
| `failed` và hết lượt thử | Cần sửa nguyên nhân, chạy lại có quyền; không sửa DB tùy tiện |
| Lịch `next_run_at` quá khứ lâu | Scheduler dừng, transaction lỗi hoặc lịch bất thường |
| Gói trong `incoming` không chuyển | Importer dừng, gói thiếu dấu hoàn tất hoặc lỗi schema |
| Gói trong `failed` | Xem `error_details`, checksum, schema, liên kết ID; đối soát nguồn |
| Số lỗi vượt mẫu số | Sửa dữ liệu mẫu số/phạm vi có lý do; không xóa hồ sơ |
| Dung lượng volume sắp hết | Tạm dừng phát sinh file nếu cần; tăng dung lượng hoặc áp dụng retention đã duyệt |

Lưu giờ đến hạn, giờ bắt đầu, chờ hàng đợi và giờ hoàn tất riêng. “Đã xếp hàng” chưa phải “Đã xuất”. Mục tiêu phát hiện lịch trong 60 giây chỉ có ý nghĩa khi scheduler/database khỏe; phải đo cả queue và thời gian tạo file.

Khi khởi động lại, sổ công việc database còn tồn tại. Theo dõi công việc dở dang, heartbeat và gói file; không xóa hàng `running`/`failed` để ép xuất lại. Dùng cùng business key để nhận kết quả cũ, hoặc tạo revision mới khi dữ liệu đến muộn/sửa sau chốt.

## Sao lưu

Sao lưu database **và** volume chứa snapshot/gói xuất/minh chứng. PostgreSQL dump không chứa file ngoài database; sao lưu file không thay database.

Một chính sách đề xuất để tổ chức phê duyệt: backup database hàng ngày, backup file tăng dần hàng ngày, giữ bản ngày 30 ngày và bản tháng 12 tháng; lưu bản mã hóa ngoài máy chủ. Có thể bắt đầu xem xét thời hạn snapshot/file 90 ngày và audit 365 ngày, nhưng phải giữ đủ dữ liệu tái lập báo cáo và điều chỉnh theo nghiệp vụ/pháp lý. Đây là khuyến nghị, chưa có scheduler backup/retention tự động của sản phẩm. Xác định RPO/RTO và thời hạn lưu được duyệt trước khi xóa.

Để có bản nhất quán khi thử nghiệm, dừng các tiến trình ghi và đợi công việc đang chạy kết thúc trước khi dump/copy volume. Với hệ thống lớn, dùng backup PostgreSQL chuẩn, WAL/PITR và cơ chế snapshot file được thiết kế theo cutoff. Không nén volume database đang chạy rồi mặc định có thể phục hồi.

Không xóa bản snapshot cũ chỉ vì đã có CSV mới. `export_runs` tham chiếu file nào thì retention phải giữ hoặc đánh dấu đã hết hạn rõ ràng. Muốn xóa dữ liệu cần chính sách có phê duyệt, audit và kiểm tra liên kết; MVP chưa có tự động xóa lịch sử.

## Diễn tập khôi phục

1. Tạo môi trường/volume mới, không phục hồi đè môi trường đang dùng.
2. Chọn database dump và bộ file cùng mốc đối soát; kiểm tra checksum và quyền đọc.
3. Khôi phục dump vào PostgreSQL cùng major version tương thích; chạy migrations còn thiếu bằng công cụ đi kèm.
4. Khôi phục file vào đúng `DATA_DIR`, đặt quyền chỉ cho tài khoản dịch vụ, không public thư mục bằng static server.
5. Khởi động API, kiểm tra health và đăng nhập. So sánh số phiên/đợt/hồ sơ/chi phí, lấy một QR và xem lịch sử, tải một báo cáo cũ và kiểm checksum.
6. Khởi động worker/importer/scheduler; kiểm tra công việc dở dang được phục hồi an toàn, import lại không nhân dữ liệu, lịch quá hạn được đối soát.
7. Ghi thời gian phục hồi, số liệu đối soát, lỗi và người thực hiện. Chỉ chuyển người dùng khi kết quả đạt yêu cầu đã duyệt.

Tạo backup từ thư mục dự án sau khi thông báo cửa sổ tạm dừng ghi:

```sh
sh scripts/backup.sh backups
python scripts/restore-check.py backups/<moc-UTC-vua-tao>
```

Script dừng API/worker/scheduler/importer, dump PostgreSQL và nén volume `exchange`, ghi checksum rồi khởi động lại các tiến trình. Cần dung lượng đủ và kiểm tra tiến trình thực sự lên lại sau script. Không sao lưu file `.env` vào kho không mã hóa.

Ví dụ khôi phục vào **Compose project mới**, chưa nối người dùng vào môi trường phục hồi:

```sh
cp .env .env.restore
chmod 600 .env.restore
```

Sửa `.env.restore`: `HTTP_PORT=18080`, `APP_ORIGIN=http://localhost:18080`, `COOKIE_SECURE=false`, `ENVIRONMENT=restore`. Giữ mật khẩu database phù hợp; project mới tạo volume riêng dù tên database giống bản gốc. Không bật profile HTTPS trong diễn tập này.

```sh
docker compose -p traceq-restore --env-file .env.restore up -d db
docker compose -p traceq-restore --env-file .env.restore exec -T db sh -c 'pg_restore -U traceq -d "$POSTGRES_DB" --clean --if-exists' < backups/<moc-UTC>/database.dump
docker compose -p traceq-restore --env-file .env.restore run --rm --no-deps -T --user root --entrypoint tar api -C /data -xzf - < backups/<moc-UTC>/exchange.tar.gz
docker compose -p traceq-restore --env-file .env.restore up -d
```

Đợi health PostgreSQL trước `pg_restore`; kiểm tra exit code mỗi lệnh. Tar ở ví dụ chỉ nhận backup do chính quy trình được tin cậy tạo ra và đã kiểm checksum, không dùng với tệp tùy ý. Sau restore mở `http://localhost:18080`, kiểm số liệu/QR/file cũ và ghi log diễn tập. Không tuyên bố phục hồi đã đạt cho đến khi có bằng chứng chạy thực tế.

## Camera, offline và bridge

Kiểm tra trên ít nhất các thiết bị/trình duyệt người dùng thật: cấp/từ chối quyền camera, camera khác nhau, xoay màn hình, QR bị mờ, kích thước tem và khoảng trắng, in lại, nhập mã thủ công, quét liên tiếp, hai điện thoại cùng xác nhận. Kiểm thử API không chứng minh camera/tem vật lý hoạt động.

MVP cần mạng cho thao tác ghi; không có bảo đảm lần mở đầu offline hay hàng chờ IndexedDB. Không hiển thị “Đã lưu lên hệ thống” khi chưa có phản hồi máy chủ. Giai đoạn offline cần hàng chờ theo tài khoản, `client_event_id` bất biến, nút thử lại, xử lý phiên hết hạn, giới hạn lưu trữ và kiểm thử đổi tài khoản. IndexedDB không thay backup.

Importer thư mục chạy cùng máy chủ/volume không phải bridge của nhà máy qua mạng. Bridge HTTPS với tài khoản dịch vụ là phần mở rộng: chỉ ghi trong thư mục được cấu hình, chặn path traversal, tải file có quyền và xác minh checksum. Trình duyệt không có quyền tự ghi ổ đĩa bất kỳ. Khi chưa có bridge, dùng tải gói có kiểm tra quyền hoặc importer cục bộ.

## Nâng cấp

Trước nâng cấp: backup, kiểm checksum, đọc thay đổi schema/hợp đồng file và thử trên bản sao dữ liệu. Migrations phải chạy trước API/worker phiên bản mới. Không sửa trực tiếp migration đã áp dụng; tạo phiên bản mới. Không dùng `create_all()` như quy trình nâng cấp production. Nâng cấp không tương thích cần kế hoạch chuyển đổi và cửa sổ bảo trì.

Rollback ứng dụng không tự rollback schema. Khi migration thay đổi phá vỡ tương thích, dùng phục hồi đã thử hoặc migration ngược được thiết kế/kiểm chứng. Khóa phiên bản Python/Node và dependency từ lockfile; giữ bản image/source và manifest để tái lập.
