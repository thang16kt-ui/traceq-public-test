# TraceQ — Quản lý sản phẩm lỗi bằng QR

MVP có mã nguồn frontend React/TypeScript, API FastAPI, PostgreSQL thật, worker/scheduler/importer độc lập và hợp đồng file kiểm tra được. Luồng chính: tạo đợt và mẫu số → tạo hồ sơ nháp/tem QR → quét, đăng nhập và bấm xác nhận → xem số liệu → xuất snapshot theo lịch → nhập vào mirror phân tích.

Mã nguồn triển khai và kết quả đã kiểm chứng được phân biệt trong [docs/verification.md](docs/verification.md). Giao diện có chế độ **minh họa chỉ đọc** khi chưa nối API; chế độ này không lưu nghiệp vụ và không phải database vận hành. Không có tuyên bố đã triển khai trên tên miền công khai.

## Chạy thử đầy đủ bằng Docker Compose

Cần Docker Engine + Compose v2, Python 3 để tạo cấu hình, các cổng localhost 8080 còn trống. Chạy từ thư mục chứa README:

```sh
python3 scripts/configure.py
docker compose up --build -d
docker compose exec api python -m backend.app.cli create-user --username admin --display-name 'Quản trị viên' --role admin
```

Lệnh tạo tài khoản hỏi mật khẩu hai lần, tối thiểu 12 ký tự; không có mật khẩu quản trị mặc định. Script cấu hình sinh mật khẩu database ngẫu nhiên trong `.env` quyền 600 và không ghi đè `.env` đã tồn tại. Mẫu `.env.example` không là bí mật thật và phải được thay trước khi chạy.

Mở **http://localhost:8080**, đăng nhập `admin`. API docs: **http://localhost:8080/docs**, OpenAPI: **http://localhost:8080/openapi.json**. Kiểm tra:

```sh
docker compose ps
curl -fsS http://localhost:8080/health/live
curl -fsS http://localhost:8080/health/ready
docker compose logs --tail=100 api worker scheduler importer
```

Compose chạy `db`, migration một lần, `api`, `worker`, `scheduler`, `importer`, `frontend` Nginx. Scheduler/worker dùng hàng công việc PostgreSQL bền vững; không cần Redis/Celery ở MVP. Volume `database` và `exchange` giữ dữ liệu qua khởi động lại. Dừng bằng `docker compose down` giữ volume; tùy chọn `-v` xóa dữ liệu nên chỉ dùng với môi trường thử có thể bỏ.

Frontend chỉ bind `127.0.0.1:8080` ở cấu hình HTTP mặc định. Không dùng URL LAN HTTP để thử camera trên điện thoại; cấu hình HTTPS theo phần dưới.

## Thiết lập dữ liệu ban đầu và luồng kiểm chứng

Database vận hành khởi tạo rỗng, không tự chèn dữ liệu minh họa. Quản trị viên tạo loại sản phẩm, lô và loại lỗi trong Cài đặt hoặc bằng API được phân quyền; xem [api-guide.md](docs/api-guide.md) và OpenAPI. Các danh mục cần giá trị thật do đơn vị sử dụng xác nhận. Tài khoản mới tạo bằng CLI `create-user` với vai trò `manager` hoặc `inspector`; chưa có màn hình quản trị tài khoản đầy đủ.

1. Tạo danh mục SKU/lô/lỗi, sau đó tạo đợt với đúng số đã kiểm tra và `population_key`.
2. Tạo một hồ sơ có serial và một hoặc nhiều loại lỗi. Hồ sơ ở trạng thái **Nháp**, chưa tăng số sản phẩm lỗi.
3. Mở chi tiết, tải PNG/PDF và in tem. Tem dùng QR của sản phẩm, mã nhập tay, tên và lô. In lại giữ nguyên QR.
4. Mở mục Quét, quét camera hoặc nhập mã trên tem; chọn đúng hồ sơ/đợt. Chỉ bấm **Xác nhận sản phẩm lỗi** mới lưu chính thức. GET QR chỉ đọc.
5. Quét lại hoặc gửi lại cùng request: không tăng sản phẩm lỗi. Xem lịch sử và thống kê backend. Một đợt 100 đã kiểm tra / 8 sản phẩm lỗi / 12 lượt lỗi phải hiển thị 8%, 8 và 12.
6. Quản lý cập nhật xử lý → chờ kiểm tra lại → đóng có kết quả/lý do. Sửa có `row_version`; xung đột cần tải lại, không ghi đè.
7. Quản trị tạo lịch giờ/ngày/múi giờ hoặc quản lý xuất ngay một kỳ. API trả 202; theo dõi `queued/running/succeeded/failed`, tải ZIP khi hoàn tất.
8. Importer nhận ZIP hoàn chỉnh từ `incoming`, kiểm tra manifest/checksum/schema/liên kết rồi cập nhật mirror. Đối soát qua `GET /api/v1/analytics/imported-summary` và lịch sử nhập; nhập lại không cộng thêm dữ liệu.

Phạm vi thời gian hiện theo **ngày bắt đầu đợt**; lấy cả mẫu số và hồ sơ của các đợt trong `[period_start, period_end)`. Với các đợt chồng lấn, không tuyên bố đã loại trùng sản phẩm vật lý toàn hệ thống. Thiếu mẫu số/0/mẫu chồng lấn hoặc tử số vượt mẫu số trả tỷ lệ chưa đủ dữ liệu. Xem [từ điển dữ liệu](docs/data-dictionary.md).

## Dữ liệu minh họa riêng

Chế độ giao diện minh họa chỉ đọc không cần seed database. Để thử **API/database thật** bằng bộ mẫu, tạo một Compose project và database riêng:

```sh
cp .env .env.demo
chmod 600 .env.demo
```

Sửa `.env.demo`: `POSTGRES_DB=traceq_demo`, `ENVIRONMENT=demo`, `HTTP_PORT=18081`, `APP_ORIGIN=http://localhost:18081`, `COOKIE_SECURE=false`. Giữ file ngoài Git; dùng project name riêng để volume tách khỏi vận hành.

```sh
docker compose -p traceq-demo --env-file .env.demo up --build -d
```

Seed chỉ cho phép `ENVIRONMENT=demo` và database có hậu tố `_demo`/`_test`, danh mục còn rỗng. Mật khẩu demo truyền qua biến môi trường được chỉ định, không truyền giá trị mật khẩu trong tham số CLI. Có thể dùng lời nhắc bảo mật trong container:

```sh
docker compose -p traceq-demo --env-file .env.demo exec api python -c "import getpass,os; os.environ['DEMO_PASSWORD']=getpass.getpass('Mật khẩu demo (ít nhất 12 ký tự): '); from backend.app.cli import seed_demo; seed_demo('DEMO_PASSWORD')"
```

Mở `http://localhost:18081`, tài khoản `demo.admin` hoặc `demo.inspector`, mật khẩu vừa nhập. Bộ mẫu có nhãn `DỮ LIỆU MẪU`: 100 đã kiểm tra, 8 hồ sơ đã xác nhận, 12 lượt lỗi, 2 nháp và 4 khoản thực tế tổng `500000.00 VND`. Không dùng bộ mẫu để đánh giá chất lượng sản xuất thật.

## HTTPS, dữ liệu bền vững và vận hành

Với hostname thật, cấu hình DNS/cổng, đặt `APP_DOMAIN=ten-mien-cua-ban`, `APP_ORIGIN=https://ten-mien-cua-ban`, `COOKIE_SECURE=true`, `ENVIRONMENT=production`, rồi:

```sh
docker compose --profile https up --build -d
```

Caddy kết thúc TLS và proxy tới frontend/API cùng hostname. Cấu hình localhost dùng CA nội bộ nên thiết bị thử cần tin cậy chứng thư tương ứng. Không bật `COOKIE_SECURE=false` cho vận hành HTTPS. Không public cổng PostgreSQL; giới hạn quyền tài khoản runtime và bảo vệ volume.

Backup và diễn tập khôi phục:

```sh
sh scripts/backup.sh backups
python3 scripts/restore-check.py backups/<moc-UTC-vua-tao>
```

Đọc [operations.md](docs/operations.md) trước khi thực hiện: script tạm dừng tiến trình ghi, cần backup database **và** file, và phải thử khôi phục vào môi trường riêng. Retention/backup định kỳ chưa được scheduler tự động hóa; cần chính sách vận hành riêng. Không xóa snapshot còn tham chiếu trong lịch sử.

## Kiểm thử và đo tải

Backend cần PostgreSQL thật; SQLite không là bằng chứng chống trùng/đồng thời. Test chỉ cho database tạm có tên kết thúc `_test` và sẽ xóa dữ liệu trong database đó.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
export TEST_DATABASE_URL='postgresql+psycopg://<tai-khoan-test>:<mat-khau-test>@localhost:5432/traceq_test'
python -m pytest tests -q
cd frontend
npm ci
npm run build
```

PostgreSQL Compose không mở cổng ra host theo mặc định; URL ví dụ dành cho database kiểm thử được chuẩn bị riêng. Không sửa cấu hình production để chạy tests. Mật khẩu mẫu trong URL phải được thay và giữ ngoài lịch sử/log nếu là bí mật thật.

Kết quả đã đo, tài nguyên và giới hạn xem [verification.md](docs/verification.md), hướng dẫn test/benchmark xem [tests/README.md](tests/README.md). Mục tiêu 30 thiết bị/100.000 hồ sơ, P95 xác nhận dưới 2 giây và xuất 10.000 hồ sơ dưới 60 giây là mục tiêu thử nghiệm theo hạ tầng; không mặc định coi là đã đạt.

## Phạm vi bàn giao

| Nhóm | Mã nguồn có trong MVP | Giới hạn còn lại |
|---|---|---|
| Ghi nhận | Tạo danh mục trong Settings/API, đợt/mẫu số, hồ sơ nhiều lỗi, tem PNG/PDF, tra cứu/xác nhận, idempotency, audit | Tài khoản quản trị qua CLI; serial hiện duy nhất trong lô; giao diện hiển thị tối đa 100 hồ sơ gần nhất |
| Xử lý | Trạng thái, phân công, lý do, kết quả, kiểm phiên bản | Cần xác nhận quy trình duyệt và danh mục kết quả thực tế |
| Phân tích | Tổng hợp SQL, Pareto, xu hướng ngày, so nhóm đúng mẫu số, chi phí/phân bổ và mirror nhập | UI lọc ngày; bộ lọc sản phẩm/lô/ca/công đoạn đầy đủ qua API. Chưa có đầy đủ biểu đồ tuần/tháng/so kỳ và cấu hình cảnh báo nghiệp vụ |
| Xuất/nhập | PostgreSQL queue, lịch IANA, retry/heartbeat, snapshot bất biến CSV/XLSX ZIP, checksum/schema/import idempotent | Bridge HTTPS qua mạng nhà máy chưa triển khai; chỉ volume tích hợp cục bộ/tải thủ công |
| Minh chứng/chi phí | API ảnh JPEG/PNG có giới hạn/quyền và API chi phí Decimal/phân bổ | UI nhập minh chứng/chi phí và workflow mở rộng chưa đầy đủ |
| Camera | Quét trình duyệt và nhập tay, xử lý HTTPS/quyền camera | Cần nghiệm thu trên điện thoại/máy in/tem thật |
| Offline | Thử lại xác nhận giữ event ID trong phiên; không báo lưu khi chưa có phản hồi | Chưa có Service Worker + IndexedDB/hàng chờ offline bền vững theo tài khoản |
| Dự báo/AI | Endpoint nêu rõ chưa đủ dữ liệu và điều kiện bổ sung | Chưa huấn luyện/kiểm chứng mô hình; chưa nhận diện lỗi bằng ảnh |
| Vận hành | Compose, migrations, lockfile, health, backup/checksum/restore hướng dẫn | Cần TLS thật, giám sát tập trung, retention được duyệt và diễn tập phục hồi |

Danh mục mức độ hiện cố định `low/medium/high/critical`, kết quả đóng `passed_after_repair/scrapped/other`; yêu cầu cấu hình tùy ngành cần mở rộng có migration/API/UI tương ứng. Ứng dụng MVP dùng một tổ chức, chưa có tenant/multi-site độc lập.

## Tài liệu và cấu trúc

- [Thiết kế, flow, kiến trúc, ERD và màn hình](docs/design.md)
- [Từ điển dữ liệu, mẫu số và chi phí](docs/data-dictionary.md)
- [API, quyền, lỗi, idempotency và request mẫu](docs/api-guide.md)
- [Hợp đồng file và quy trình đối soát](docs/file-contract.md)
- [Vận hành, bảo mật, backup/restore](docs/operations.md)
- [Kiểm chứng thực tế và giới hạn](docs/verification.md)
- [Rà soát độc lập](docs/review-notes.md)
- [Gói manifest minh họa có checksum thật](worker/examples/README.md)
- [Yêu cầu gốc](SPECIFICATION.vi.md)

```text
frontend/       React, TypeScript, giao diện tiếng Việt
backend/app/    API, auth, nghiệp vụ và SQL phân tích
worker/         Scheduler, hàng việc, snapshot, import/export
bridge/         Ranh giới và hướng mở rộng bridge qua HTTPS
migrations/     Schema PostgreSQL có phiên bản
tests/          PostgreSQL integration, đồng thời, hợp đồng file
deploy/         Dockerfile, Nginx, Caddy và khởi tạo quyền DB
scripts/        Cấu hình, backup và kiểm checksum phục hồi
docs/           Thiết kế, API, dữ liệu, vận hành và kiểm chứng
```

## Chạy local khi không dùng toàn bộ container ứng dụng

Có thể dùng PostgreSQL riêng, cài Python từ `requirements.lock`, rồi đặt các biến môi trường `DATABASE_URL`, `DATA_DIR`, `APP_ORIGIN=http://localhost:8080`, `COOKIE_SECURE=false` cho môi trường phát triển. Không đưa URL có mật khẩu vào Git hoặc lịch sử lệnh dùng chung. Chạy migration bằng tài khoản sở hữu schema; API dùng tài khoản runtime được cấp quyền phù hợp.

Sau khi tạo tài khoản bằng CLI và build frontend (`cd frontend && npm ci && npm run build`), từ thư mục gốc chạy:

```sh
uvicorn scripts.serve_local:app --host 127.0.0.1 --port 8080 --no-access-log
```

Runner này phục vụ cùng API thật và React đã build; mở QR chỉ hiển thị ứng dụng. Chạy mỗi tiến trình sau trong terminal/dịch vụ riêng với cùng cấu hình database và `DATA_DIR`:

```sh
python -m worker.main scheduler
python -m worker.main worker
python -m worker.main importer
```

Đây là phương án local đã kiểm tra qua HTTP, không thay reverse proxy/HTTPS trong vận hành. Lịch vẫn thuộc tiến trình máy chủ, không thuộc tab trình duyệt. Cách này hữu ích khi môi trường thử không đủ dung lượng chạy toàn bộ Compose bằng storage driver `vfs`.
