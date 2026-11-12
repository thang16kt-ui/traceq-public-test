# TraceQ — Ghi nhận và xử lý sản phẩm lỗi bằng QR

QC ghi nhận sản phẩm lỗi bằng QR, lưu minh chứng không sửa được (SHA-256), duyệt nhiều cấp, tính chi phí xử lý,
báo cáo/dự báo và tự động duyệt có kiểm soát. Web app dạng PWA, giao diện 100% tiếng Việt, dùng trên điện thoại
cá nhân (thanh điều hướng dưới) và máy tính (thanh bên cho Quản lý/Admin).

**Stack:** React 19 + TypeScript + Vite (PWA) · FastAPI + SQLAlchemy 2 · PostgreSQL 16/17 · tiến trình nền
(scheduler/worker/importer) dùng hàng việc PostgreSQL · reportlab (PDF), openpyxl (Excel), pywebpush (Web Push).

Báo cáo khảo sát và kết quả thực hiện: [docs/khao-sat-hien-trang.md](docs/khao-sat-hien-trang.md).
Vận hành, biến môi trường, sao lưu: [docs/van-hanh.md](docs/van-hanh.md).

## Vai trò và luồng

| Vai trò | Việc chính |
|---|---|
| Người tạo | Quét QR/nhập serial → tạo đề xuất (1 đề xuất = 1 sản phẩm, nhiều mục lỗi, mức BẮT BUỘC chọn) → tờ tổng quan → **Gửi đề xuất** → dán QR → chụp minh chứng từng mục → **Gửi minh chứng** |
| Giám sát (theo sản phẩm) | **Xác nhận lỗi** / **Từ chối** (lý do) → **Chốt phương án** → **Hoàn tất xử lý** (chi phí thực tế, nguyên nhân gốc, ảnh sau) → **Đóng đề xuất** / **Yêu cầu làm lại** |
| Cấp trên | **Phê duyệt** / **Từ chối** khi chi phí > ngưỡng, phương án Hủy, hoặc có lỗi ưu tiên |
| Quản lý | Thiết lập danh mục/mức/giá/ngưỡng, Tổng quan, Báo cáo PDF/Excel, Tự động duyệt, khóa tài khoản/đặt lại mật khẩu |
| Admin | Người dùng + vai trò, danh mục, nhật ký, hệ thống (sức khỏe, sao lưu, lỗi) |

Trạng thái: Nháp → Chờ minh chứng → Chờ xác nhận → Chờ chọn phương án → [Chờ cấp trên] → Đang xử lý → Chờ kiểm tra
đóng → Đã đóng (nhánh từ chối/làm lại; "Quá hạn" là cờ). Mọi đổi trạng thái đi qua **một** hàm
(`backend/app/workflow.py: transition`) kiểm quyền + kiểm chuyển hợp lệ + ghi `state_history` + `audit_log`.

## Chạy cục bộ

Cần Python 3.12+, Node 22, PostgreSQL 16/17.

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.lock
cd frontend && npm ci && npm run build && cd ..
export DATABASE_URL='postgresql+psycopg://<user>@localhost/traceq_demo' DATA_DIR=./data APP_ORIGIN=http://localhost:8080 COOKIE_SECURE=false ENVIRONMENT=demo DEMO_PASSWORD='<ít nhất 10 ký tự>'
python -m backend.app.cli migrate
python -m backend.app.cli seed-demo          # chỉ với ENVIRONMENT=demo và DB có hậu tố _demo/_test
uvicorn scripts.serve_local:app --port 8080 &
python -m worker.main scheduler &            # cảnh báo/quá hạn, Web Push, báo cáo định kỳ, sao lưu đêm
python -m worker.main worker &               # gói xuất dữ liệu
```

Tài khoản mẫu: `demo.nguoitao`, `demo.giamsat`, `demo.giamsat2` (thay thế), `demo.captren`, `demo.quanly`, `demo.admin`
(mật khẩu = `DEMO_PASSWORD`). Bản cài thật: tạo tài khoản bằng
`python -m backend.app.cli create-user --username ... --display-name ... --roles admin,quan_ly` (bắt buộc đổi mật khẩu lần đầu).

Docker Compose (`compose.yaml`) và Render (`render.yaml` trả phí – khuyến nghị cho dùng thật; `render.test-free.yaml` chỉ để
thử, **đĩa tạm sẽ mất ảnh**) vẫn dùng được như trước; xem [docs/van-hanh.md](docs/van-hanh.md).

## Kiểm thử

```sh
export TEST_DATABASE_URL='postgresql+psycopg://<user>@localhost/traceq_test'   # DB dùng một lần, tên kết thúc _test
python -m pytest tests -q                       # 159 test: unit + API trên PostgreSQL thật
cd frontend && npm test                          # Vitest: hàng đợi offline
node e2e/full-flow.mjs http://localhost:8080 "$DEMO_PASSWORD" ảnh.jpg   # E2E giao diện nhiều vai trò (cần Playwright)
```

Bao gồm: máy trạng thái (mọi tổ hợp), chi phí (nguồn, median, ngoại lai, N mẫu, cửa sổ), định tuyến cấp trên, tự duyệt
(ca loại trừ, cổng bật, đảo ngược, kiểm tra mẫu, tự tạm dừng), cascade cờ ưu tiên, phân quyền (gọi API trái quyền bị chặn),
đồng thời/idempotency, offline gửi trùng, minh chứng bất biến, sao lưu + diễn tập khôi phục, so schema migration với models.

## Cấu trúc

```text
backend/app/   workflow (máy trạng thái), proposals, evidence, review, treatment, completion, costing/actuals,
               notify (thông báo + cron), dashboard, reports, auto (tự duyệt), accounts, backup, system
frontend/src/  lib/ (api, offline, router, push), ui/ (components, charts), screens/ (20 màn hình)
migrations/    001–013, áp dụng bằng `python -m backend.app.cli migrate`
worker/        scheduler/worker/importer + jobs (cảnh báo, push, báo cáo định kỳ, sao lưu)
tests/         pytest (PostgreSQL thật); frontend/e2e: Playwright
docs/          khảo sát + kết quả, vận hành, hợp đồng file; legacy/ = tài liệu MVP cũ
```
