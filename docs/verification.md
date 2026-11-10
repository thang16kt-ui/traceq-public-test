# Kiểm chứng thực tế

Kiểm thử dùng PostgreSQL **17.11 thật** trong Docker; API và worker chạy bằng Python **3.12.14** trong virtualenv. Không thay PostgreSQL bằng SQLite hoặc database giả lập. Dữ liệu kiểm thử nằm trong database riêng có hậu tố `_test`; dữ liệu đo tải nằm trong database riêng có hậu tố `_benchmark`.

Phiên bản đã dùng: FastAPI 0.115.12, SQLAlchemy 2.0.41, psycopg 3.2.9, httpx 0.28.1, pytest 8.3.5. Máy báo 3 logical CPU; giới hạn cgroup thực tế là **2 CPU và 8 GiB RAM**, filesystem 7,9 GB.

## Kiểm thử chức năng

Lệnh từ thư mục gốc dự án, sau khi cài dependencies và đặt `TEST_DATABASE_URL` chỉ đến database dùng riêng:

```sh
python -m pytest tests -q --tb=short --junitxml=docs/pytest-results.xml
```

**Kết quả cuối cùng: 51 passed trong 12,72 giây**, không có ca lỗi hoặc bỏ qua. Có một `DeprecationWarning` từ thư viện TestClient/AnyIO về tên alias `BlockingPortal`; không làm hỏng kiểm thử. Chi tiết từng ca nằm trong [pytest-results.xml](pytest-results.xml). Bộ thử bao gồm các nhóm sau:

| Luồng đã kiểm chứng | Kết quả bắt buộc |
|---|---|
| Tạo nháp, mở QR nhiều lần, tải PNG/PDF và in lại | Không xác nhận ngầm, QR giữ nguyên, chưa tăng số sản phẩm lỗi |
| Năm yêu cầu quét đồng thời từ hai tài khoản/thiết bị | Một `confirmed_now`, bốn `already_confirmed`; một hồ sơ hợp lệ |
| Timeout/gửi lại, khóa idempotency và `client_event_id` | Trả đúng kết quả đã lưu; nội dung/tài khoản/hồ sơ khác bị từ chối |
| Một serial trong cùng đợt và qua đợt mới | Chống hồ sơ gốc trùng; đợt mới dùng cùng sản phẩm và QR |
| Hai cập nhật cùng `row_version` | Chỉ một cập nhật thắng; bản cũ nhận 409 |
| Sửa chữa → kiểm tra lại → quản lý đóng → quét lại | Giữ lần xác nhận đầu, không tăng số sản phẩm lỗi |
| 100 đã kiểm tra, 8 sản phẩm lỗi, 12 lượt lỗi | 8%; nháp bị loại khỏi tử số/lượt lỗi |
| Gộp mẫu số, thiếu/0 mẫu số, tử số vượt mẫu, mẫu chồng lấn | Tính theo tổng đúng phạm vi; tỷ lệ null và cảnh báo khi chưa thể tính |
| Một hồ sơ, hai loại lỗi, một chi phí 100,25 và phân bổ 90,25 | Tiền chỉ cộng một lần; còn chưa phân bổ 10,00; vượt nguồn bị từ chối nguyên tử |
| Người ngoài quyền biết ID, QR, ảnh hoặc file xuất | Không truy cập được; ghi thiếu CSRF bị từ chối |
| Ảnh giả nội dung và ảnh PNG hợp lệ | Từ chối file giả; chuẩn hóa ảnh hợp lệ và bảo vệ tải theo quyền hồ sơ |
| API tạo hồ sơ → xác nhận → 202 tạo export → worker → tải ZIP → importer → phân tích mirror | Dữ liệu và mẫu số đối soát được từ đầu đến cuối |
| Đổi 17:00 → 18:30 → múi giờ khác; sửa lịch sau khi bỏ lỡ lần chạy đầu | Giữ mốc kỳ, không bỏ dữ liệu; `next_run_at` được tính lại |
| Hai scheduler cùng chạy; khởi động lại sau nhiều kỳ | Một chuỗi công việc, business key duy nhất và các kỳ liền nhau |
| Full snapshot CSV/XLSX, checksum, số dòng, schema và liên kết | Từ chối gói sai trước khi ghi mirror; ô giống công thức được giữ là văn bản |
| Nhập lại, bản cũ đến sau bản mới, xóa lỗi con và hủy hồ sơ | Không cộng thêm hoặc phục hồi dữ liệu cũ; đồng bộ con nhất quán theo phiên bản cha |
| Worker hết heartbeat, giới hạn thử lại, lỗi sau công bố file | Phục hồi công việc bền vững; dùng lại snapshot/file bất biến và checksum cũ |
| Dự báo chưa được kiểm chứng | Trả lý do thiếu dữ liệu/mô hình, không tạo số dự báo giả |

Đây là kiểm thử API qua ASGI `TestClient` và các connection PostgreSQL độc lập. Các tình huống “thiết bị” trong bộ thử là yêu cầu đồng thời có phiên đăng nhập riêng, chưa phải điện thoại vật lý.

## Đo tải đã chạy

Báo cáo máy đọc được: [benchmark.json](benchmark.json). Một lần đo ngày **2026-11-10**, với 100.000 sản phẩm vật lý, 100.000 hồ sơ, 100.000 dòng lỗi, 2 đợt kiểm tra; không có ảnh hoặc chi phí. Dữ liệu được bulk insert vào PostgreSQL trong 20,719 giây, không giả lập thời gian tạo hồ sơ qua API.

| Phép đo | Kết quả |
|---|---:|
| 30 yêu cầu xác nhận đồng thời trên bộ 100.000 hồ sơ | 30/30 thành công |
| P50 thời gian ASGI TestClient | 1.113,97 ms |
| P95 thời gian ASGI TestClient | **1.321,31 ms** |
| Thời gian lớn nhất | 1.326,58 ms |
| Toàn bộ nhóm 30 yêu cầu | 1,402 giây |
| Xuất kỳ chứa đúng 10.000 hồ sơ và 10.000 dòng lỗi | **2,352 giây** |
| ZIP CSV UTF-8 BOM tạo được | 966.811 byte |

Thời gian xác nhận đo từ `TestClient` trong cùng máy, gồm ASGI/Python/database và chi phí client; không có mạng điện thoại, reverse proxy hoặc TLS. Vì vậy đây **không phải** phép đo 30 điện thoại thật hoặc thời gian handler thuần. Phép đo export gồm nhận công việc, snapshot `REPEATABLE READ`, tạo file, SHA-256, tự kiểm tra gói, công bố incoming và commit hoàn tất; không gồm nhập/phân tích hoặc thời gian chờ hàng đợi.

Đây là một lần đo dữ liệu tổng hợp trên môi trường thử; không suy ra cam kết SLO vận hành. Mục tiêu phát hiện lịch trong 60 giây chưa được đo theo đồng hồ thực. Cần đo lại trên phần cứng, dữ liệu và hạ tầng triển khai đích.

Chạy lại benchmark có chủ ý xóa database thử riêng:

```sh
export BENCHMARK_DATABASE_URL='postgresql+psycopg://quality:REPLACE_TEST_PASSWORD@localhost:5432/quality_benchmark'
python -m tests.benchmark --records 100000 --concurrency 30 --export-records 10000 --output docs/benchmark.json
```

## Giới hạn cần nghiệm thu tại nơi triển khai

- Camera Safari iOS/Chrome Android, xin/từ chối quyền camera, quét tem thật, nhập mã thủ công và chất lượng máy in chưa thử trên thiết bị thật.
- Chưa chạy nghiệm thu toàn bộ Docker Compose đồng thời. Môi trường hiện tại dùng Docker storage driver `vfs` và filesystem 7,9 GB, không đủ chỗ cho toàn bộ các lớp image/build và container cùng lúc. PostgreSQL, các entrypoint API/worker/importer và luồng nghiệp vụ nêu trên đã được chạy thật.
- HTTPS, cookie trên tên miền thật, giới hạn proxy, tốc độ mạng và phiên đăng nhập trên điện thoại cần thử trước vận hành.
- Offline/IndexedDB, bridge HTTPS tới thư mục nhà máy, cảnh báo cấu hình nâng cao và mô hình dự báo thuộc giai đoạn sau; không được bộ thử này xác nhận là đã tích hợp.
- Cần diễn tập lại phục hồi trên hạ tầng vận hành, theo dõi dung lượng và đo tải có ảnh/chi phí trước khi dùng dữ liệu thật.

## Kiểm tra HTTP và khôi phục bổ sung

Ngày 2026-11-10, đã chạy Uvicorn với API thật, bản React đã build và PostgreSQL 17.11, qua HTTP loopback. Bằng chứng: [http-smoke.json](http-smoke.json).

- Trang React, health và OpenAPI trả 200; đăng nhập bằng cookie/CSRF thành công.
- Mở đường dẫn QR và tra cứu GET không đổi tử số; tải PNG/PDF thành công.
- Mẫu ban đầu 100 đã kiểm tra / 8 lỗi / 12 lượt, xác nhận một nháp thành 100 / 9 / 13. Gửi lại cùng yêu cầu trả kết quả cũ.
- API trả 202; tiến trình worker riêng tạo ZIP, file tải có SHA-256 khớp; importer riêng cập nhật mirror đúng 100 / 9 / 13.

Đã dừng API trước khi sao lưu `pg_dump -Fc` và thư mục dữ liệu file, rồi khôi phục vào database và thư mục mới. **22 bảng** có số dòng và hash nội dung khớp; **3 file** có SHA-256 khớp. Sau khôi phục, health, đăng nhập bằng tài khoản cũ, số liệu 100 / 9 / 13 và tải báo cáo cũ đều đạt. Bằng chứng: [restore-drill.json](restore-drill.json).

Diễn tập dùng dữ liệu mẫu nhỏ, kết nối chủ sở hữu và `pg_restore --no-owner --no-privileges`; chưa chứng minh toàn bộ cấp quyền runtime, HTTPS hoặc tốc độ phục hồi bộ 100.000 hồ sơ. Vai trò PostgreSQL `traceq_app` đã được kiểm tra riêng: được INSERT audit, không được UPDATE audit. Image backend đã build thành công; chạy đồng thời toàn bộ Compose bị giới hạn dung lượng `vfs` như đã nêu. Frontend đã qua TypeScript và Vite build; chưa có kiểm tra trực quan bằng trình duyệt.
