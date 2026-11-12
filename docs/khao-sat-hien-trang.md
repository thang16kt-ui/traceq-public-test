# Khảo sát hiện trạng TraceQ (Bước 0 / Hạng mục 1)

Ngày khảo sát: 2026-11-12. Commit gốc: `800bff3`. Chưa sửa code ứng dụng.

Kiểm chứng tại chỗ: `pytest` trên PostgreSQL 16 thật → **87 passed** (26,6 giây); `npm run build` frontend → thành công. Bản test Render không mở được từ môi trường khảo sát (proxy chặn), nên hiện trạng được đọc từ mã nguồn, không từ bản đang chạy.

## 1. Stack

| Lớp | Công nghệ | Nhận xét |
|---|---|---|
| Frontend | React 19 + TypeScript + Vite 6, `lucide-react`, `@zxing/browser` (quét QR) | SPA một file `main.tsx` ~80 KB, dòng rất dài, không có router, không test frontend |
| Backend | FastAPI 0.115 + SQLAlchemy 2 + psycopg 3, Pydantic 2 | Mã gọn nhưng nhiều dòng dồn (`a;b;c`) — khó review |
| DB | PostgreSQL 17 (test chạy được trên 16) | Migration SQL có version (`001`, `002`) + bảng `schema_migrations`, health `/health/ready` kiểm version |
| Tiến trình nền | `worker/` scheduler + worker + importer, hàng việc bằng PostgreSQL (`SKIP LOCKED`, heartbeat, retry) | Tận dụng được cho cron cảnh báo/quá hạn và gửi báo cáo định kỳ |
| PDF/Ảnh/QR | reportlab + font DejaVu (có tiếng Việt), Pillow, qrcode, openpyxl | Đủ cho PDF A4/Excel phía server |
| Bảo mật | argon2id, cookie phiên httpOnly + `SameSite=Lax` + CSRF token + kiểm Origin, `Idempotency-Key` cho mọi thao tác ghi | Nền tảng tốt |
| Triển khai | Docker Compose (Nginx, Caddy HTTPS), Render (`render.yaml` trả phí, `render.test-free.yaml` free) | Bản test public chạy cấu hình **free** |

**Đề xuất: GIỮ stack.** Không có lý do kỹ thuật để đổi. Chỉ đề xuất *tái cấu trúc trong cùng stack*: tách `main.tsx` thành module theo màn hình + thêm router nhẹ khi viết lại từng màn (xem mục 7, câu hỏi Q9).

## 2. Schema DB hiện có (22 bảng)

- Danh mục: `product_types` (sku, name, đơn vị, `is_active`, `has_been_used`), `batches` (lot_code thuộc product_type), `defect_types` (code, name, **`severity_default`**, `is_active`, `has_been_used`). Có khóa chuẩn hóa Unicode chống trùng tên.
- Kiểm tra: `inspection_sessions` (batch, line, shift, stage, `inspected_count`, `population_key`, status `open|closed`) ≈ "Đợt kiểm tra".
- Sản phẩm vật lý: `units` (batch, serial, `qr_token` ngẫu nhiên) — QR gắn **sản phẩm**, không gắn hồ sơ.
- Hồ sơ: `defect_cases` (unit, session, status `draft|confirmed|in_progress|recheck|closed|cancelled`, `created_by`, `assigned_to`, `result`, `first_confirmed_at`), duy nhất theo (session, unit).
- Mục lỗi: `case_defects` (defect_type, `occurrence_count`, **severity cố định `low|medium|high|critical`**, nguyên nhân nghi ngờ/xác minh). Duy nhất theo (case, defect_type). **Không có snapshot tên.**
- Sự kiện: `case_events` (lịch sử hành động), `scan_events` (idempotent theo `client_event_id`).
- Minh chứng: `attachments` (case_id, storage_key, content_type, size) — gắn **hồ sơ**, không gắn mục lỗi; **không lưu sha256**.
- Chi phí: `cost_entries` (category, amount Decimal, `actual|estimated`) + `cost_allocations` (phân bổ theo mục lỗi).
- Hệ thống: `users` (**một** `role` ∈ inspector/manager/admin), `auth_sessions`, `login_attempts`, `audit_logs` (DB role runtime không được UPDATE), `idempotency_records`.
- Xuất/nhập: `export_schedules`, `export_runs`, `import_runs`, `analysis_records` (mirror phân tích).

## 3. API hiện có (`/api/v1`)

Phiên: `auth/login`, `auth/catalog-login` (bản test), `auth/me`, `auth/logout`. Danh mục: CRUD + `DELETE` (xóa hẳn nếu chưa dùng, ngược lại ngừng dùng) + `restore` + `history` cho product-types / batches / defect-types. Đợt: `GET/POST inspection-sessions`, `PATCH` (quản lý chốt đợt, đối soát mẫu số). Hồ sơ: `GET/POST defect-cases`, `GET/PATCH defect-cases/{id}` (đổi trạng thái nằm trong PATCH), `POST …/confirm` (quét xác nhận idempotent), `POST …/costs`, `POST …/attachments`, `GET attachments/{id}`, `GET qr/{token}`, `GET units/{id}/label` (PNG/PDF tem). Phân tích: `analytics/summary|pareto|trends|groups|forecast|imported-summary`. Xuất: `export-schedules`, `export-runs` (+download, retry), `import-runs`. Quản trị: `users` (chỉ liệt kê), `audit-logs`. Không có API tạo/sửa/khóa người dùng (chỉ CLI).

## 4. Màn hình hiện có

Tổng quan · Hồ sơ lỗi (bảng + chi tiết) · Tạo hồ sơ · Quét QR · Phân tích (Pareto, xu hướng ngày, nhóm, chi phí, dự báo "chưa đủ dữ liệu") · Lịch sử xuất/nhập · Cài đặt (lịch xuất + danh mục). Đăng nhập (ẩn khi bật public demo). Có chế độ "minh họa chỉ đọc" khi không có API.

## 5. Đối chiếu với đặc tả

| Đặc tả | Hiện trạng | Đánh giá |
|---|---|---|
| `site` mặc định | Không có | Thiếu |
| Nhiều vai trò/tài khoản; Giám sát theo sản phẩm; Cấp trên | 1 vai trò/tài khoản; không có giám sát/cấp trên | **Thiếu, phải migrate** |
| Đăng nhập mã NV, ghi nhớ 30 ngày, khóa tài khoản, danh sách thiết bị, thu hồi | Phiên cố định 12h, không có danh sách thiết bị, không khóa theo tài khoản | Thiếu |
| Màn "Tôi", đổi mật khẩu, quản lý đặt lại mật khẩu | Không có | Thiếu |
| Điều hướng theo vai trò (thanh dưới / thanh bên) | Một bộ tab chung | Thiếu |
| Danh mục soft delete + khôi phục + hộp xác nhận | **Đã có** (xóa hẳn khi chưa dùng) | Giữ; thêm snapshot tên |
| Mức độ do quản lý cài (≤3, bật/tắt, tiêu chí, giá, hạn, phương án gợi ý) | 4 mức cố định trong code; `severity_default` trên loại lỗi | **Sai so với đặc tả** (vi phạm "không mặc định mức") |
| Cờ ưu tiên cascade | Không có | Thiếu |
| Lịch sử giá thị trường | Không có | Thiếu |
| Máy trạng thái 8 bước + nhánh từ chối, MỘT hàm chuyển trạng thái, `state_history` | 6 trạng thái khác nghĩa; chuyển trạng thái viết thẳng trong `PATCH`; `case_events` gần giống state_history | **Sai, phải thiết kế lại** |
| Mã DX-xxxx | Chỉ UUID | Thiếu |
| Tạo đề xuất từ QR/serial, tự điền đợt, "Lưu nháp"/"Xem tờ tổng quan", tờ A4, QR lớn | Có tạo hồ sơ nháp + tem QR PNG/PDF; không có tờ tổng quan | Một phần |
| Minh chứng theo **từng mục lỗi**, lý do khi thiếu ảnh, sha256, bất biến | API ảnh theo hồ sơ (JPEG/PNG ≤5 MB, kiểm nội dung thật, không có API xóa); **không có UI tải ảnh**; không lưu hash | Một phần, thiếu quan trọng |
| Giám sát "Xác nhận lỗi"/"Từ chối" | "Xác nhận" hiện là người quét tự xác nhận (`/confirm`) | **Khác nghĩa** (xem Q3) |
| Phương án, chi phí ước tính 2 nguồn (median, N mẫu), định tuyến cấp trên | Không có | Thiếu |
| Hoàn tất xử lý (vật tư/giờ/khác, nguyên nhân gốc, ảnh sau) | Có `cost_entries` tổng quát, không có UI nhập | Một phần |
| Cron cảnh báo/quá hạn, thông báo, Web Push | Chỉ có scheduler cho xuất dữ liệu | Thiếu (hạ tầng tái dùng được) |
| Tra cứu nhiều tiêu chí + lịch sử sản phẩm | Tìm theo serial, `GET qr/{token}` trả mọi hồ sơ của sản phẩm | Một phần |
| PWA + offline + hàng đợi đồng bộ | Không có manifest/service worker/IndexedDB; có màn khởi động + thử lại | Thiếu |
| Dashboard KPI, dự báo có điều kiện kèm sai số | Có summary/Pareto/xu hướng ngày/dự báo trả "chưa đủ dữ liệu" (đúng tinh thần) | Một phần |
| Báo cáo PDF/Excel BC-xxxx, mã băm ảnh, chỗ ký, gửi email định kỳ | Có gói ZIP CSV/XLSX có checksum theo lịch; không có PDF báo cáo, không có email | Một phần |
| Tự động duyệt (a→h) | Không có | Thiếu (làm sau cùng theo lộ trình) |
| Audit log | Có, append-only ở mức quyền DB | Tốt; bổ sung hành động mới |
| Sao lưu/khôi phục | Script `backup.sh` + `restore-check.py`, đã diễn tập; chưa tự động hằng ngày | Một phần |
| Test | 87 test tích hợp PostgreSQL thật (đồng thời, idempotency, quyền, import/export) | Tốt; thiếu test frontend/E2E trình duyệt |

## 6. Rủi ro (ưu tiên giảm dần)

1. **Ảnh minh chứng sẽ mất trên bản test.** `render.test-free.yaml` đặt `DATA_DIR=/tmp/traceq-test` — đĩa tạm, mất mỗi lần khởi động lại/deploy, trong khi DB vẫn giữ bản ghi → bản ghi trỏ tới file không còn. Không đạt yêu cầu "minh chứng không thể sửa". Dùng thật cần đĩa bền (gói trả phí `render.yaml` có disk 1 GB) hoặc object storage kiểu S3. CSDL free của Render cũng có giới hạn thời hạn — cần kiểm tra lại điều khoản hiện tại của Render.
2. **Bản test public không cần đăng nhập và khách có vai trò `admin`.** Bất kỳ ai có link đều được đóng/hủy hồ sơ, xem audit log, tạo lịch xuất; đăng nhập danh mục chấp nhận *mật khẩu bất kỳ*. Chấp nhận được với dữ liệu mẫu, **không được đưa dữ liệu thật vào** trước khi tắt `PUBLIC_DEMO_ACCESS`/`PUBLIC_DEMO_CATALOG_LOGIN`.
3. **Hash minh chứng không được lưu.** Server tính sha256 của file gốc chỉ để làm khóa idempotency, rồi lưu file JPEG đã nén lại (khác byte với file gốc). Không có cách chứng minh ảnh chưa bị thay trên đĩa.
4. **Giới hạn đăng nhập theo IP có thể khóa nhầm mọi người.** Đếm theo `request.client.host`; sau proxy của Render, uvicorn chưa cấu hình `--forwarded-allow-ips` nên khả năng cao mọi người dùng chung một IP → 20 lần sai bất kỳ trong 5 phút sẽ chặn cả nhà máy. Không có khóa theo tài khoản. (Chưa xác minh được trên bản chạy thật.)
5. **Phân quyền thô.** Một vai trò/tài khoản; inspector thấy hồ sơ mình tạo/được gán; manager/admin thấy và làm được mọi thứ. Không có phạm vi "giám sát chỉ duyệt sản phẩm mình phụ trách".
6. **Mức độ cố định + mặc định** trái đặc tả; dữ liệu cũ có `critical` cần ánh xạ khi migrate.
7. **Không có snapshot tên** loại lỗi/mức: sửa tên danh mục làm đổi nội dung hồ sơ cũ khi hiển thị (hiện code còn chủ động tăng `row_version` hồ sơ khi đổi tên để mirror nhận bản mới).
8. **Đổi trạng thái phân tán** (`PATCH defect-cases`, `/confirm`, `PATCH inspection-sessions`) — khó bảo đảm "mọi đổi trạng thái qua một hàm".
9. **Frontend khó bảo trì**: `main.tsx` ~80 KB trong ~150 dòng, chưa có test giao diện.
10. Phân hệ xuất/nhập mirror (worker/importer/`analysis_records`) khá lớn, không nằm trong đặc tả mới; mỗi thay đổi schema hồ sơ phải sửa cả hợp đồng file → chi phí bảo trì.

## 7. Điểm mâu thuẫn / chưa rõ — đề xuất phương án (cần anh/chị chốt)

| # | Vấn đề | Đề xuất |
|---|---|---|
| Q1 | Lưu ảnh khi dùng thật: Render free mất file | Dùng S3-compatible (vd. Cloudflare R2/Backblaze B2) qua một lớp `FileStore` (đĩa cho dev/test, S3 cho thật) + nâng gói Render "luôn chạy" + Postgres có backup. Trong lúc chưa chốt: làm `FileStore` chạy đĩa. |
| Q2 | Mức độ: dữ liệu cũ 4 mức `low/medium/high/critical` | Ánh xạ `low→Nhẹ`, `medium→Trung bình`, `high`+`critical→Nặng`; lưu giá trị gốc trong snapshot; bỏ `severity_default`. |
| Q3 | "Xác nhận" hiện tại = người quét tự xác nhận sản phẩm lỗi (tăng tử số thống kê). Đặc tả: Giám sát "Xác nhận lỗi". | Bỏ `/confirm` kiểu cũ; sản phẩm chỉ tính là "lỗi" trong thống kê khi giám sát **Xác nhận lỗi** (hoặc tự duyệt sau này). Giữ cơ chế `client_event_id` chống trùng cho "Gửi đề xuất"/"Gửi minh chứng". |
| Q4 | QR: hiện gắn sản phẩm (`units.qr_token`, dùng lại qua nhiều đợt). Đặc tả: "Gửi đề xuất → sinh QR" và quét QR để chụp minh chứng. | Giữ QR theo **sản phẩm** (in một lần, dán lâu dài); quét QR mở đề xuất đang mở của sản phẩm đó; màn "Sau khi gửi" hiện/tải QR này kèm mã DX. Tránh nhiều tem trên một sản phẩm. |
| Q5 | Trùng đề xuất: hiện cấm 2 hồ sơ cùng sản phẩm trong cùng đợt. Đặc tả chỉ cảnh báo "trùng đề xuất đang mở cùng serial + loại lỗi". | Cấm 2 đề xuất **đang mở** cho cùng serial (thêm mục lỗi vào đề xuất đang mở); đề xuất đã đóng thì cho tạo mới. Cảnh báo trùng loại lỗi trong thẻ "Hệ thống đã kiểm tra trước". |
| Q6 | "Cấp trên" gắn theo sản phẩm hay chung toàn nhà máy? Ngưỡng chi phí chung hay theo sản phẩm? | Một danh sách cấp trên chung; ngưỡng chung (VND) cấu hình trong Thiết lập. Mở rộng sau nếu cần. |
| Q7 | "Giá vốn" (Hủy) và "giá trị thu hồi" (Tái chế), "đơn giá giờ công" không có trong mô hình dữ liệu | Thêm `product.unit_cost`, `product.salvage_value` (tùy chọn), `site_setting.hourly_rate` (mặc định, cho phép sửa khi nhập). |
| Q8 | Bản test public (không đăng nhập, khách = admin) | Sau hạng mục 2: tắt truy cập khách; tạo sẵn tài khoản demo cho từng vai trò (mật khẩu đặt qua biến môi trường), ghi rõ trên trang đăng nhập "BẢN TEST". |
| Q9 | Frontend một file lớn | Viết màn mới thành module riêng (`screens/…`), thêm router nhẹ; thêm Vitest (unit) và Playwright (E2E, Chromium đã có sẵn). Không đổi React/Vite. |
| Q10 | PIN/vân tay | Hạng mục 2 làm mật khẩu + ghi nhớ 30 ngày + thiết bị; WebAuthn (vân tay/Face ID) làm ở hạng mục 17 nếu còn thời gian — có thư viện `webauthn` cho Python. PIN đơn thuần không làm (yếu hơn WebAuthn, dễ lộ trên thiết bị cá nhân). |
| Q11 | Email báo cáo định kỳ cần SMTP/dịch vụ gửi mail | Cần anh/chị cung cấp nhà cung cấp SMTP (tài khoản/khóa đưa qua biến môi trường). Chưa có thì làm nút tải về + thông báo trong app. |
| Q12 | Phân hệ xuất/nhập mirror CSV/XLSX hiện có | Giữ nguyên (đã có test), không mở rộng; ẩn khỏi điều hướng chính, chuyển vào "Hệ thống" của Admin. Báo cáo PDF/Excel mới (BC-xxxx) làm riêng. Nếu không cần, có thể gỡ ở hạng mục 17 để giảm bảo trì. |
| Q13 | Giờ "nhắc cuối ngày", số ngày X nhắc nhập chi phí thực tế | Mặc định 16:30 giờ Việt Nam và X = 2 ngày, cấu hình được. |

## 8. Kế hoạch tiếp theo

Thực hiện theo mục 12 của đặc tả, mỗi hạng mục 1 commit có test, sau khi anh/chị chốt các điểm Q1–Q13 (ít nhất Q2, Q3, Q4, Q5, Q8 vì ảnh hưởng ngay hạng mục 2–6). Migration mới đánh số tiếp `003_…`, không sửa migration cũ, giữ dữ liệu demo hiện có.
