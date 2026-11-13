# Vận hành TraceQ

## Triển khai khuyến nghị cho dùng thật

- Máy chủ **luôn chạy** (không ngủ đông) + PostgreSQL có sao lưu của nhà cung cấp (vd. `render.yaml`: web 0.5 CPU/512 MB,
  disk 1 GB gắn `/data`, Postgres có backup). Bản `render.test-free.yaml` ngủ đông và dùng đĩa tạm: **ảnh minh chứng mất
  khi khởi động lại** – chỉ để thử. Màn **Hệ thống** cảnh báo đỏ khi `DATA_DIR` nằm trên `/tmp`.
- HTTPS bắt buộc (`APP_ORIGIN=https://…`, `COOKIE_SECURE=true`). Camera, Web Push, cài PWA đều cần HTTPS.
- Sau proxy (Render/Caddy) uvicorn đọc `X-Forwarded-For` (`FORWARDED_ALLOW_IPS`, mặc định `*` trong `scripts/run_public.py`)
  để giới hạn đăng nhập đúng theo thiết bị người dùng.

## Biến môi trường

| Biến | Ý nghĩa |
|---|---|
| `DATABASE_URL` | PostgreSQL (postgres:// tự đổi sang psycopg) |
| `APP_ORIGIN`, `COOKIE_SECURE` | Origin HTTPS thật; cookie Secure |
| `DATA_DIR` | Thư mục **bền** chứa ảnh (`attachments/`), báo cáo (`reports/`), gói xuất, sao lưu |
| `SESSION_HOURS` | Thời hạn phiên thường (mặc định 12 giờ); "Ghi nhớ thiết bị" = 30 ngày |
| `ENVIRONMENT` | `production` / `demo` (demo cho phép seed tài khoản mẫu) |
| `DEMO_PASSWORD` | Mật khẩu tài khoản mẫu (chỉ demo, ≥ 10 ký tự) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | Web Push; sinh bằng `python -m backend.app.cli generate-vapid`. Khóa riêng là bí mật |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_SECURITY` | Gửi báo cáo định kỳ (`starttls`/`ssl`/`none`). Chưa có thì báo cáo vẫn tạo và báo trong app |
| `BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `BACKUP_ENABLED` | Sao lưu đêm (mặc định `DATA_DIR/backups`, giữ 7 ngày) |

## Tiến trình

`scripts/run_public.py` chạy API + scheduler + worker + importer trong một container (chết một tiến trình thì container
dừng để nền tảng khởi động lại). Scheduler (mỗi 15 giây): xếp lịch xuất dữ liệu; mỗi phút: cảnh báo quá hạn/leo thang/
nhắc cuối ngày/nhắc chi phí/lỗi lặp lại; gửi Web Push chờ; báo cáo định kỳ; sau 02:00 giờ VN: sao lưu + diễn tập khôi phục.
Nhịp scheduler hiện ở màn Hệ thống (cảnh báo khi quá 3 phút).

## Sao lưu và khôi phục

- **Tự động hằng đêm:** bản sao logic toàn bộ bảng (ảnh chụp nhất quán) + `attachments/` + `reports/`, kèm `manifest.json`
  (SHA-256 từng tệp, số dòng + băm nội dung từng bảng). Ngay sau đó **diễn tập khôi phục** vào schema tạm, đối chiếu từng
  bảng và mã băm từng ảnh; kết quả ở màn Hệ thống.
- **Thủ công:** `python -m backend.app.cli backup --out <thư-mục>` và `python -m backend.app.cli restore-drill <thư-mục-bản-sao>`.
- **Bắt buộc chép bản sao ra nơi khác máy chủ** (kho đối tượng/ổ khác). Cùng một đĩa thì không chống được mất đĩa.
- Với Compose có thể dùng thêm `scripts/backup.sh` (pg_dump + tar) và `scripts/restore-check.py`.
- Khôi phục thật: dựng DB rỗng → `cli migrate` → nạp dữ liệu từ bản sao (theo thứ tự bảng trong `backend/app/backup.py:restore_into_schema`,
  đổi schema đích) → giải nén `files.tar.gz` vào `DATA_DIR` → chạy `restore-drill` để đối chiếu. Luôn thử trên môi trường riêng trước.

## Bảo mật

- Mật khẩu argon2id; 5 lần sai → khóa 15 phút; giới hạn 50 lần sai/5 phút/IP; Quản lý khóa tài khoản và thu hồi mọi
  phiên từ xa; người dùng tự đăng xuất từng thiết bị.
- Cookie httpOnly + Secure + SameSite=Lax, token CSRF cho mọi thao tác ghi, kiểm Origin, Idempotency-Key.
- Phân quyền kiểm ở server theo vai trò **và** đối tượng (giám sát chỉ thấy/duyệt sản phẩm mình phụ trách; nháp chỉ người tạo
  thấy; nguyên tắc 4 mắt: người tạo không tự xác nhận/đóng; lỗi ưu tiên chỉ Quản lý duyệt).
- Minh chứng bất biến: không có API sửa/xóa, trigger DB chặn UPDATE/DELETE, quyền DB runtime không có UPDATE/DELETE trên
  `attachments`, `state_history`, `audit_logs`; tệp ghi một lần, tải về có kiểm mã băm.
- Ảnh kiểm nội dung thật (JPEG/PNG/WEBP), ≤ 8 MB, ≤ 30 MP, bỏ EXIF (vị trí). Dữ liệu offline trên máy (IndexedDB, bản nháp,
  bản lưu danh mục, hồ sơ) **bị xóa khi đăng xuất**; không lưu đệm dữ liệu API trong service worker.

## Giám sát

- `/health/live`, `/health/ready` (kiểm phiên bản schema) cho health check của nền tảng.
- Lỗi máy chủ chưa xử lý, lỗi tiến trình nền và lỗi giao diện (trang trắng, lỗi JS) ghi vào `error_events` (giữ 2000 bản
  ghi) và log JSON; xem ở màn Hệ thống kèm mã yêu cầu để đối chiếu log.

## Ngủ đông (bản free)

Giao diện hiện "Máy chủ đang khởi động…", tự thử lại tới ~50 giây với **cùng** khóa idempotency (không tạo trùng); form giữ
dữ liệu (lưu nháp trên máy); mất mạng thì lưu vào hàng đợi offline và tự gửi khi có mạng.
