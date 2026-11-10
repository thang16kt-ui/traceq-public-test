Bạn là chuyên gia phân tích nghiệp vụ, quản lý chất lượng sản xuất, kiến trúc phần mềm, lập trình full-stack và phân tích dữ liệu. Hãy thiết kế và xây dựng một hệ thống web/app quản lý sản phẩm lỗi bằng QR, tự động xuất dữ liệu theo lịch do người dùng cài đặt và tích hợp ứng dụng phân tích.

Mục tiêu là tạo một hệ thống dùng được trong thực tế: thao tác nhanh trên điện thoại, dữ liệu kiểm chứng được, không đếm trùng và giúp quản lý ưu tiên xử lý đúng vấn đề.

Trước khi viết mã, trình bày ngắn gọn giả định và thiết kế; sau đó triển khai theo từng giai đoạn, kèm cách chạy và kiểm chứng.

**1. Mục tiêu, phạm vi và flow tổng thể**

Hệ thống cần trả lời:

- Đã kiểm tra bao nhiêu sản phẩm? Có bao nhiêu sản phẩm lỗi và tỷ lệ là bao nhiêu?
- Loại sản phẩm, lô, ca hoặc công đoạn nào có tỷ lệ lỗi cao?
- Lỗi nào phổ biến nhất, nghiêm trọng nhất và gây thiệt hại lớn nhất?
- Hồ sơ lỗi đang được xử lý đến đâu? Tình hình đang tăng hay giảm?
- Có đủ dữ liệu để dự báo chưa, và cần thu thập thêm gì?

Flow chính:

Phát hiện sản phẩm lỗi → mở web → chọn sản phẩm, lô và loại lỗi → tạo hồ sơ nháp và QR riêng → in/dán tem lên sản phẩm → quét bằng điện thoại và xác nhận → lưu chính thức → tổng hợp theo kỳ → tự xuất file theo Settings → chuyển vào thư mục tích hợp → ứng dụng phân tích kiểm tra và nhập dữ liệu → hiển thị báo cáo, cảnh báo và dự báo khi đủ điều kiện.

Có hai mô-đun:

- **Ghi nhận:** danh mục, hồ sơ lỗi, QR, quét xác nhận, xử lý và lịch xuất.
- **Phân tích:** tiếp nhận dữ liệu, kiểm tra, thống kê, chi phí, xu hướng và dự báo.

Có thể triển khai trong một hệ thống nhưng phải hỗ trợ trao đổi file với phần mềm khác. Cơ sở dữ liệu là nguồn chính; file phục vụ trao đổi và chốt báo cáo.

Chưa mặc định ngành sản xuất; danh mục sản phẩm, lỗi, mức độ và đơn vị tính có thể cấu hình.

Ở MVP, con người chọn lỗi, QR dùng để định danh. Nhận diện lỗi bằng ảnh là phần mở rộng nếu có dữ liệu gán nhãn phù hợp.

**2. Người dùng, màn hình và giao diện**

Phân quyền:

- **Nhân viên kiểm tra:** tạo hồ sơ/tem, quét xác nhận, bổ sung thông tin và cập nhật bước xử lý được giao.
- **Quản lý chất lượng:** xác minh, sửa có lý do, duyệt kết quả xử lý và xem phân tích.
- **Quản trị viên:** quản lý tài khoản, danh mục, lịch xuất và tích hợp.

Các màn hình:

- Đăng nhập.
- Tổng quan.
- Tạo hồ sơ và QR.
- Quét QR.
- Danh sách hồ sơ.
- Chi tiết và lịch sử xử lý.
- Phân tích.
- Lịch sử xuất/nhập.
- Settings.

Giao diện tiếng Việt, responsive cho điện thoại và máy tính; nút đủ lớn, có tìm kiếm và giá trị mặc định.

Tự điền người thao tác, thời gian, ca/dây chuyền khi có thông tin; không bắt nhập lại dữ liệu đã biết.

Hiển thị rõ trạng thái nháp, chờ đồng bộ, đã lưu, đang xử lý và lỗi thao tác.

**3. Định danh sản phẩm, tạo tem và quét xác nhận**

- Một sản phẩm vật lý có một ID và QR ổn định.
- Liên kết serial sẵn có hoặc cấp mã nội bộ; không dùng chung QR cho cả loại sản phẩm hoặc loại lỗi.
- Tạo QR chỉ tạo hồ sơ nháp. Lần quét xác nhận đầu tiên mới đưa hồ sơ vào thống kê sản phẩm lỗi.
- In lại giữ nguyên QR.
- Chống tạo nhiều hồ sơ gốc cho cùng sản phẩm trong cùng đợt kiểm tra.
- Một sản phẩm có thể có nhiều loại/lượt lỗi nhưng chỉ là một sản phẩm lỗi trong cùng phạm vi kiểm tra.
- Kiểm tra lại sau sửa chữa lưu thành sự kiện thuộc hồ sơ cũ; không tăng số sản phẩm lỗi ban đầu.
- Đợt kiểm tra độc lập mới liên kết lại cùng sản phẩm và QR.
- Quét lại mở hồ sơ/lịch sử, không cộng thêm sản phẩm.
- Hai điện thoại cùng xác nhận vẫn chỉ tạo một lần ghi nhận hợp lệ.
- Xem hồ sơ không tự đổi trạng thái.
- GET chỉ đọc; mở hoặc xem trước đường dẫn QR không tự xác nhận.
- Nếu có nhiều hồ sơ qua các đợt kiểm tra, người dùng phải chọn đúng hồ sơ.

QR chứa đường dẫn `/q/{token}` trên tên miền ứng dụng. Token ngẫu nhiên khó đoán, không chứa thông tin đăng nhập, chi phí hoặc quyền truy cập. Quét vẫn phải đăng nhập và được phân quyền.

Cho tải PNG và in PDF theo kích thước tem cấu hình. Tem gồm QR, mã nhập tay, tên sản phẩm và lô; giữ tương phản và khoảng trắng để dễ quét, kiểm tra trên tem/thiết bị thật.

Luồng trạng thái:

Nháp/chờ xác nhận → đã ghi nhận lỗi → đang xử lý → chờ kiểm tra lại → đã đóng.

Kết quả đóng gồm đạt sau sửa chữa, loại bỏ hoặc kết quả cấu hình khác.

Có hủy hồ sơ/tem và lý do; lưu người phụ trách, biện pháp, thời gian, kết quả và lịch sử sửa/chuyển trạng thái. Theo dõi tem đã tạo nhưng chưa quét.

**4. Camera và mất kết nối**

Dùng HTTPS, xin quyền camera; xử lý từ chối quyền, camera không khả dụng và nhập mã thủ công. Chọn thư viện QR tương thích các trình duyệt mục tiêu; kiểm tra trên điện thoại thật.

Khi triển khai offline:

- Service Worker cache phần ứng dụng; IndexedDB lưu danh mục/hồ sơ cần thiết và yêu cầu chờ đồng bộ.
- Giữ nguyên `client_event_id` khi gửi lại.
- Chỉ báo “Đã lưu lên hệ thống” và xóa yêu cầu chờ sau khi máy chủ xác nhận.
- Thử đồng bộ khi mở app, có mạng trở lại và có nút thử lại; không phụ thuộc hoàn toàn Background Sync.
- Nếu app/hồ sơ chưa được cache, báo rõ chưa thể xác nhận offline; không hứa lần mở đầu khi mất mạng vẫn hoạt động.
- Phiên hết hạn phải đăng nhập lại.
- Tách hàng chờ theo tài khoản, không gửi nhầm dữ liệu khi đổi người dùng.
- Giới hạn ảnh/dữ liệu lưu tạm, nêu giới hạn lưu trữ trình duyệt; IndexedDB không thay thế backup.
- Chống camera gửi liên tục tại giao diện và vẫn kiểm tra chống trùng tại backend.

**5. Mô hình dữ liệu**

Tách loại sản phẩm, sản phẩm vật lý, đợt kiểm tra, hồ sơ, chi tiết lỗi, sự kiện xử lý và chi phí.

| Bảng | Trường chính |
|---|---|
| `users` | id, display_name, role, password_hash, is_active |
| `product_types` | id, sku, name, unit_of_measure |
| `batches` | id, product_type_id, lot_code |
| `units` | id, batch_id, serial_number, qr_token |
| `inspection_sessions` | id, batch_id, line, shift, stage, inspected_count, sample_method, started_at, ended_at, status |
| `defect_cases` | id, unit_id, inspection_session_id, status, detected_at, first_confirmed_at, created_by, assigned_to, row_version |
| `defect_types` | id, code, name, severity_default, is_active |
| `case_defects` | id, case_id, defect_type_id, occurrence_count, severity, suspected_cause, verified_cause |
| `case_events` | id, case_id, event_type, actor_id, occurred_at, action_taken, result, reason |
| `cost_entries` | id, case_id, category, amount, currency, cost_status, source_reference |
| `cost_allocations` | id, cost_entry_id, case_defect_id, allocated_amount |
| `attachments` | id, case_id, storage_key, content_type, size_bytes, uploaded_by |
| `scan_events` | id, client_event_id, case_id, actor_id, observed_at, received_at, outcome |
| `export_schedules` | id, enabled, local_time, days_of_week, timezone, period_rule, format, destination_id, next_run_at, version |
| `export_runs` | id, schedule_id, business_key, period_start, period_end, cutoff_at, revision, status, attempts, next_retry_at, snapshot_reference |
| `import_runs` | id, export_id, revision, checksum, status, processed_at, error_details |
| `audit_logs` | id, actor_id, action, entity_type, entity_id, changed_fields, reason, request_id, created_at |

Quy ước:

- ID dùng UUID, quan hệ có khóa ngoại.
- Token QR duy nhất và không rỗng; serial không rỗng duy nhất trong phạm vi sản phẩm đã quy định.
- Thời điểm dùng `TIMESTAMPTZ`; trao đổi ISO 8601, hiển thị theo múi giờ IANA.
- Lưu riêng thời điểm nghiệp vụ, thời điểm thiết bị quan sát và thời điểm máy chủ nhận.
- Tiền dùng `NUMERIC(18,2)`; JSON truyền chuỗi thập phân kèm `currency`, không dùng `float`.
- Số lượng nguyên không âm; `occurrence_count` nguyên dương.
- `inspected_count` có thể `NULL` khi chưa nhập, khác `0`.
- Định nghĩa rõ một lượt lỗi.
- Các bảng nghiệp vụ xuất ra có `created_at`, `updated_at` và `row_version`.
- Thay đổi hồ sơ, lỗi con, chi phí hoặc trạng thái hủy phải được truyền sang ứng dụng phân tích.
- Danh mục chuẩn hóa; nguyên nhân nghi ngờ khác nguyên nhân đã xác minh. Ảnh và ghi chú là minh chứng.
- MVP: một đợt kiểm tra gắn với một lô/ca/công đoạn.
- Tổng số đã kiểm tra lấy từ nhập liệu hoặc nguồn kiểm tra cùng phạm vi; không tự thay bằng tổng sản lượng.

**6. Kiến trúc và công nghệ tham khảo**

Ưu tiên backend chia mô-đun, dùng chung PostgreSQL; tách worker để xuất/phân tích không chặn quét.

| Thành phần | Công nghệ đề xuất | Vai trò |
|---|---|---|
| Frontend | React + TypeScript, PWA | Giao diện, QR, Settings, dashboard |
| Backend | Python + FastAPI | API, kiểm tra dữ liệu, phân quyền và nghiệp vụ |
| Database | PostgreSQL | Dữ liệu chính, giao dịch, ràng buộc chống trùng |
| Scheduler/worker | Một Celery Beat, Celery worker, Redis | Kiểm tra lịch và xử lý nền |
| Phân tích | SQL, pandas; thư viện thống kê khi cần | Tổng hợp, xử lý theo lô và dự báo |
| Lưu file | Volume bền vững ở MVP; lưu trữ đối tượng khi mở rộng | Ảnh, tem, snapshot và báo cáo |
| Triển khai thử | Docker Compose + HTTPS | Chạy các thành phần |

Chốt phiên bản tương thích, lockfile và migrations.

Có thể thay công nghệ/scheduler đơn giản hơn nếu giải thích tradeoff và vẫn bảo đảm dữ liệu bền vững, retry, chống trùng và phục hồi lỗi.

Redis không thay PostgreSQL làm nguồn dữ liệu chính.

**7. API và hợp đồng giao tiếp**

Dùng REST API `/api/v1`, có OpenAPI, request/response mẫu và quyền từng endpoint.

| API | Chức năng |
|---|---|
| `POST /auth/login`; `POST /auth/logout` | Đăng nhập/đăng xuất |
| `GET /product-types`; `GET /defect-types` | Lấy danh mục |
| `POST /inspection-sessions`; `PATCH /inspection-sessions/{id}` | Tạo đợt/cập nhật số đã kiểm tra |
| `POST /defect-cases` | Tạo nháp, tạo/liên kết sản phẩm |
| `GET /qr/{token}` | Tra cứu đúng sản phẩm và hồ sơ được phép xem |
| `GET /units/{id}/label` | Tem PNG/PDF, hỗ trợ in lại |
| `POST /defect-cases/{id}/confirm` | Xác nhận lần đầu |
| `PATCH /defect-cases/{id}` | Sửa/chuyển trạng thái có kiểm tra phiên bản |
| `POST /defect-cases/{id}/attachments` | Tải minh chứng |
| `POST /defect-cases/{id}/costs` | Ghi chi phí |
| `GET, POST /export-schedules`; `PATCH /export-schedules/{id}` | Xem/tạo/sửa lịch |
| `POST /export-runs`; `GET /export-runs/{id}` | Xuất ngay và theo dõi công việc |
| `GET /export-runs/{id}/download` | Tải kết quả có kiểm tra quyền |
| `GET /analytics/summary`; `GET /analytics/pareto`; `GET /analytics/trends` | Tổng hợp và xu hướng |
| `GET /analytics/forecast` | Dự báo hoặc lý do chưa đủ dữ liệu |

Request xác nhận có `client_event_id`, `observed_at` và `device_id` nếu có; `actor_id` lấy từ phiên đăng nhập.

Response có `case_id`, `first_confirmed_at`, `outcome` và `request_id`. Phân biệt `confirmed_now` và `already_confirmed`; gửi lại cùng request trả kết quả đã lưu của request đó.

API danh sách có phân trang, lọc/sắp xếp hợp lệ và giới hạn kích thước.

Lỗi chuẩn gồm `code`, `message`, `field_errors`, `request_id`; quy định HTTP `401/403/404/409/422/429`.

Tạo công việc xuất trả HTTP `202` và `run_id`; frontend theo dõi trạng thái thay vì giữ request chờ xuất xong.

**8. Toàn vẹn dữ liệu và đồng thời**

- `UNIQUE` cho cặp `inspection_session_id + unit_id`; `client_event_id` duy nhất.
- Xác nhận, ghi sự kiện và audit cùng một database transaction.
- Dùng cập nhật có điều kiện/khóa bản ghi để chỉ có một lần xác nhận đầu.
- API ghi hỗ trợ `Idempotency-Key`: cùng tài khoản, thao tác, khóa và nội dung trả kết quả cũ; cùng khóa nhưng nội dung khác báo xung đột.
- Kiểm tra `row_version` khi sửa để tránh ghi đè thay đổi mới hơn.
- Cập nhật hồ sơ và bảng con nhất quán; hủy/xóa logic giữ lịch sử và trạng thái truyền sang importer.
- Số sản phẩm lỗi vượt số đã kiểm tra phải được đánh dấu và đối soát trước khi chốt báo cáo chính thức; không xóa/mất hồ sơ để làm đẹp số.
- Tỷ lệ, tổng chi phí và quy tắc dữ liệu tính tại backend; frontend hiển thị.
- Khi nối bảng lỗi với chi phí phải tổng hợp đúng cấp hồ sơ để không nhân số dòng.
- Kiểm tra phân bổ tiền trong giao dịch, không dùng `CHECK` liên bảng.

**9. Settings, lịch xuất và xử lý nền**

Settings cho phép:

- Bật/tắt xuất tự động.
- Chọn giờ/ngày hoặc cuối ca; hỗ trợ nhiều lịch.
- Chọn múi giờ, mặc định `Asia/Ho_Chi_Minh`.
- Chọn kỳ dữ liệu, bộ lọc, CSV UTF-8/XLSX và nơi nhận.
- Xuất ngay hoặc chạy lại.
- Xem lần chạy gần nhất, lần chạy tiếp theo, trạng thái và lỗi.

Lịch lưu vào `export_schedules`.

Phương án tham khảo: một Celery Beat kiểm tra các lịch đến hạn mỗi phút và tạo `export_run`; khi sửa giờ/múi giờ tính lại `next_run_at`.

Máy chủ chạy độc lập với điện thoại. Phân biệt giờ khởi chạy, thời gian chờ hàng đợi và giờ file hoàn tất.

Yêu cầu:

- Kỳ có mốc đầu bao gồm, mốc cuối không bao gồm; không chồng lấn/bỏ khoảng khi đổi lịch.
- Báo cáo có phạm vi, múi giờ, `cutoff_at` và `revision`.
- Dùng thời điểm nghiệp vụ để xếp kỳ, giữ thời điểm đồng bộ để đối soát.
- Chốt dữ liệu nhất quán, giữ snapshot/kết quả để tái lập báo cáo cũ.
- Dữ liệu đến muộn hoặc sửa sau chốt tạo phiên bản bổ sung, không ghi đè âm thầm.
- Một scheduler chủ động cho cùng lịch; có khóa/ràng buộc database chống tạo công việc trùng.
- `business_key` xác định lịch, phạm vi, kỳ và phiên bản; chạy lại nhận ra kết quả cũ.
- Theo dõi `queued/running/succeeded/failed`, số lần thử, lỗi, thời gian và heartbeat.
- Retry tăng thời gian chờ, hữu hạn số lần; có chạy lại theo quyền.
- Phát hiện worker mắc kẹt, kỳ bị bỏ lỡ và công việc chưa hoàn thành sau khởi động lại.
- Database giữ công việc bền vững để đối soát khi Redis/worker dừng; đẩy vào hàng đợi chưa có nghĩa là xuất thành công.
- Không dùng timer frontend hoặc chỉ `BackgroundTasks` của một request làm cơ chế xuất định kỳ bền vững.

**10. File xuất và ứng dụng nhận dữ liệu**

Gói trao đổi gồm:

- `manifest.json`: `schema_version`, `export_id`, `revision`, `snapshot_mode`, `scope`, `period_start`, `period_end`, `timezone`, `cutoff_at`, danh sách file, số dòng và SHA-256.
- `inspection_sessions.csv`: mẫu số và phạm vi.
- `defect_cases.csv`: sản phẩm, hồ sơ, trạng thái, thời điểm và phiên bản.
- `case_defects.csv`: chi tiết lỗi.
- `cost_entries.csv` và `cost_allocations.csv`: chi phí và phân bổ.

CSV dùng UTF-8, quy định BOM khi phục vụ Excel; ID là văn bản, thời gian ISO 8601, số thập phân chuẩn hóa.

XLSX giữ đúng kiểu dữ liệu và tránh ô văn bản bị diễn giải thành công thức.

MVP dùng full snapshot theo phạm vi/kỳ, ghi rõ trong manifest.

Import theo ID và phiên bản mới hơn; thay đổi hồ sơ phải đồng bộ lỗi con, phân bổ và trạng thái hủy, không chỉ thêm dòng. Giữ các bảng con nhất quán với snapshot hồ sơ.

Ghi file tạm rồi công bố manifest/dấu hoàn tất cuối cùng; đổi tên nguyên tử chỉ khi lưu trữ hỗ trợ.

Importer chỉ đọc gói hoàn chỉnh, kiểm tra schema/checksum/số dòng/khóa liên kết, đưa vào staging rồi cập nhật bằng giao dịch.

Có `incoming/processed/failed`, lỗi dễ đối soát và rà soát lại sau khởi động. Nhập lại `export_id + revision` không cộng thêm dữ liệu; không để bản cũ ghi đè bản mới.

Nếu thư mục ở máy nhà máy/mạng nội bộ, dùng bridge agent Python chạy nền, nhận file qua HTTPS bằng tài khoản dịch vụ đủ quyền cần thiết.

Giới hạn thư mục được ghi, chặn đường dẫn vượt thư mục; không giả định web ghi được vào ổ đĩa bất kỳ. Chưa cấu hình bridge vẫn cho tải file thủ công.

**11. Chỉ số, dashboard và công thức**

Bộ lọc gồm thời gian, loại sản phẩm, lô, dây chuyền, ca, công đoạn, lỗi và mức độ. Từ chỉ số xem được hồ sơ nguồn.

Hiển thị:

- Tổng đã kiểm tra, số sản phẩm lỗi duy nhất, tỷ lệ lỗi và tổng lượt lỗi.
- Xếp hạng lỗi theo lượt và số sản phẩm bị ảnh hưởng.
- So sánh tỷ lệ giữa các loại sản phẩm/lô/ca trên mẫu số tương ứng, không chỉ so số tuyệt đối.
- Lỗi phổ biến, nghiêm trọng, gây tổng chi phí cao và chi phí trung bình cao.
- Hồ sơ chờ xác nhận/đang xử lý/đã đóng, thời gian xử lý và tỷ lệ đạt sau sửa.
- Xu hướng ngày/tuần/tháng và so kỳ trước tương đương.

Công thức:

**Tỷ lệ sản phẩm lỗi (%) = Số sản phẩm lỗi duy nhất / Tổng sản phẩm đã kiểm tra cùng phạm vi × 100.**

Thiếu mẫu số hoặc mẫu số bằng 0 hiển thị “Chưa đủ dữ liệu”, không giả định 0%.

Gộp các lô không chồng lấn dùng tổng tử số chia tổng mẫu số, không trung bình cộng tỷ lệ.

Với đợt kiểm tra lại/mẫu chồng lấn, phải có dữ liệu để loại trùng cả hai phía hoặc tách báo cáo và ghi rõ đang tính theo lượt kiểm tra. Không suy ra đã loại trùng mẫu số nếu chỉ có số tổng.

Kết quả từ mẫu không tự đại diện toàn bộ sản xuất nếu cách lấy mẫu chưa phù hợp.

Một sản phẩm nhiều loại lỗi có thể xuất hiện trong nhiều nhóm; giải thích tỷ trọng đang tính theo lượt lỗi hay sản phẩm.

Dùng biểu đồ xu hướng, cột và Pareto có tỷ trọng tích lũy; không mặc định 80/20 luôn đúng.

Mỗi kết quả có phạm vi, bộ lọc, `numerator`, `denominator`, `data_as_of` và cảnh báo dữ liệu.

SQL/backend xác định tập dữ liệu hợp lệ; pandas dùng khi cần xử lý theo lô, đọc từng phần khi dữ liệu lớn.

**12. Phân tích chi phí**

Phân biệt:

- Lỗi xảy ra nhiều nhất.
- Lỗi gây tổng thiệt hại lớn nhất.
- Lỗi có chi phí trung bình mỗi trường hợp cao nhất.

Khoản chi gồm vật tư/công sửa, kiểm tra lại, vận chuyển, xử lý phế phẩm và chi phí tăng thêm khác có căn cứ.

Với sản phẩm loại bỏ, quy định giá trị ghi nhận và phần thu hồi; không mặc định giá bán là thiệt hại.

Mỗi khoản chi cộng một lần.

Sản phẩm nhiều lỗi có quy tắc phân bổ hoặc phần chưa phân bổ; không gán toàn bộ tiền cho từng lỗi rồi cộng lặp. Tổng phân bổ không vượt khoản nguồn.

Tách tổng thực tế khỏi ước tính. Hồ sơ thiếu chi phí không xem là 0; hiển thị mức độ bao phủ dữ liệu chi phí và nguồn tính.

**13. Cảnh báo, đánh giá và dự báo**

Cho cấu hình ngưỡng tỷ lệ lỗi, lỗi nghiêm trọng và chi phí; cảnh báo trên dashboard.

Mỗi nhận định gắn kỳ, số liệu và hồ sơ liên quan. Gợi ý vấn đề cần kiểm tra và biện pháp, không tự kết luận nguyên nhân từ tương quan.

Giai đoạn đầu ưu tiên thống kê mô tả.

Chỉ dự báo khi dữ liệu đủ và phù hợp với mô hình; giải thích điều kiện, không tùy ý đặt số ngày tối thiểu rồi coi là đảm bảo.

Dự báo phải có:

- Mục tiêu và kỳ dự báo.
- Dữ liệu đầu vào và giả định.
- `model_version`.
- Thời điểm và khoảng huấn luyện.
- Sai số kiểm chứng theo thứ tự thời gian.
- So sánh với phương pháp đơn giản.
- Độ bất định.

Dự báo số lượng lỗi phải xét số lượng dự kiến kiểm tra/sản xuất phù hợp.

Nếu chưa đủ, hiển thị “Chưa đủ dữ liệu để dự báo” và nêu cần bổ sung gì.

Nếu dùng AI viết nhận xét, chỉ diễn giải số liệu đã tính; không bịa dữ liệu, sửa nguồn hoặc đưa ra nguyên nhân chắc chắn chưa được xác minh.

**14. Bảo mật, quyền truy cập và nhật ký**

- Đăng nhập chuẩn; ưu tiên cookie `HttpOnly`, `Secure`, `SameSite` phù hợp và chống CSRF cho hành động ghi.
- Mật khẩu tự quản phải băm bằng thư viện chuyên dụng.
- Kiểm tra vai trò và quyền từng hồ sơ, ảnh, file tải tại backend; biết ID/QR không tự có quyền.
- Kiểm tra đầu vào, truy vấn tham số hóa, giới hạn tần suất/phân trang và origin hợp lệ.
- Ảnh tải lên kiểm tra nội dung, loại/kích thước, đổi tên lưu trữ và bảo vệ quyền tải.
- Bí mật nằm trong biến môi trường/secret manager, không đưa vào frontend, QR, git hoặc log.
- Log có `request_id`, `run_id`, mức lỗi và thời gian; che token/cookie/thông tin nhạy cảm.
- Audit có kiểm soát quyền sửa/xóa, lưu người thao tác, thay đổi và lý do.
- Nêu thời gian lưu và cách phục hồi.

**15. Triển khai và vận hành**

Bàn giao Docker Compose cho môi trường thử, gồm frontend, API, PostgreSQL, Redis, worker và scheduler; bridge nếu được triển khai.

Nêu cách cấu hình HTTPS, volume bền vững, migrations, backup database/file và quy trình khôi phục.

Có `/health/live` và `/health/ready`.

Theo dõi lỗi API, hàng đợi, công việc mắc kẹt, xuất/nhập, dung lượng và lần backup gần nhất.

Dùng chung Python package giữa API/worker khi phù hợp để tránh lặp công thức.

Mục tiêu kiểm thử đề xuất, chưa phải kết quả đã đo:

- 30 thiết bị đồng thời với bộ dữ liệu 100.000 hồ sơ.
- P95 API xác nhận dưới 2 giây phía máy chủ, không tính mạng điện thoại và tải ảnh.
- Phát hiện lịch đến hạn trong 60 giây khi dịch vụ khỏe; đo riêng hàng đợi và tạo file.
- Gói 10.000 hồ sơ: mục tiêu xuất dưới 60 giây trên cấu hình thử nghiệm được ghi rõ.

Đo thực tế, ghi tài nguyên và dữ liệu thử, điều chỉnh mục tiêu theo hạ tầng. Không mô tả các chỉ tiêu này như cam kết đã đạt.

**16. Lộ trình triển khai**

- **Giai đoạn 1 — MVP:** danh mục, số đã kiểm tra, tạo/in QR, quét xác nhận, database thật, chống trùng, dashboard cơ bản, Settings, xuất theo lịch và nhật ký.
- **Giai đoạn 2:** tự tiếp nhận thư mục/bridge, ảnh, quản lý xử lý/kiểm tra lại, chi phí, offline và cảnh báo nâng cao.
- **Giai đoạn 3:** dự báo, biểu đồ kiểm soát thống kê khi phù hợp, tích hợp hệ thống sản xuất và hỗ trợ nhận diện ảnh khi có dữ liệu phù hợp.

Thiết kế dữ liệu để hỗ trợ toàn bộ phạm vi; triển khai luồng hoàn chỉnh theo giai đoạn.

Dữ liệu minh họa có nhãn riêng và không lẫn vào vận hành.

**17. Tiêu chí nghiệm thu và kiểm thử**

| Tình huống | Kết quả bắt buộc |
|---|---|
| Tạo QR chưa xác nhận | Không tăng số sản phẩm lỗi |
| Quét cùng QR 5 lần/hai thiết bị đồng thời | Chỉ một sản phẩm lỗi trong cùng đợt |
| 100 đã kiểm tra, 8 sản phẩm lỗi, 12 lượt lỗi | Tỷ lệ 8%, tổng lượt lỗi 12 |
| Một sản phẩm nhiều lỗi và khoản chi | Không cộng trùng sản phẩm/tiền; phân bổ đối soát được |
| Timeout rồi gửi lại | Trả kết quả cũ, không ghi thêm |
| Đổi lịch 17:00 sang 18:30 hoặc đổi múi giờ | `next_run_at` đúng, kỳ dữ liệu có thể đối soát |
| Đóng web điện thoại | Máy chủ vẫn thực hiện lịch khi dịch vụ hoạt động |
| Chạy lại kỳ xuất/nhập lại file | Không tăng sai số lượng/chi phí |
| Bản cũ nhập sau bản mới | Không ghi đè dữ liệu mới |
| Đồng bộ muộn/sửa sau chốt | Truy được kỳ, hồ sơ và revision bổ sung |
| Thiếu mẫu số, chi phí hoặc lịch sử | Không tạo chỉ số/dự báo gây hiểu nhầm |
| File chưa hoàn chỉnh/checksum/schema sai | Không nhập vào dữ liệu chính, có lỗi đối soát |
| Worker/Redis dừng rồi khởi động lại | Phát hiện công việc dở dang, khôi phục an toàn |
| Người dùng ngoài quyền truy cập ID/QR/file | Bị từ chối, không lộ dữ liệu |
| Tải lại app khi còn yêu cầu offline | Giữ yêu cầu trong giới hạn lưu trữ, đồng bộ không trùng |

Test giao dịch/đồng thời trên PostgreSQL thật; không chỉ dùng database giả lập.

Kiểm tra camera và tem trên thiết bị thật, quyền camera, hàng chờ offline và đổi tài khoản.

Thử khôi phục backup trước vận hành. Kiểm thử và đo tải phù hợp các giai đoạn đã triển khai.

**18. Đầu ra phải bàn giao**

1. **Bản thiết kế:** giả định, phạm vi từng giai đoạn, flow chạy, sơ đồ kiến trúc và ERD. Dùng Mermaid cho flow/sơ đồ quan hệ khi phù hợp.
2. **Từ điển dữ liệu:** định nghĩa chỉ số, mẫu số/phạm vi, công thức chi phí và quy tắc xử lý dữ liệu thiếu.
3. **Thiết kế màn hình:** luồng sử dụng ngắn gọn, thuận tiện tại hiện trường.
4. **Database:** migrations PostgreSQL, dữ liệu mẫu có nhãn và quy trình nâng cấp.
5. **API:** OpenAPI với request/response mẫu, mã lỗi, phân quyền, idempotency và ví dụ truy xuất hồ sơ.
6. **Mã nguồn:** frontend, backend, worker, scheduler và bridge thuộc giai đoạn đã triển khai; cấu trúc source có `frontend`, `backend`, `worker`, `bridge`, `migrations`, `tests`, `docs` khi cần.
7. **Tích hợp dữ liệu:** hợp đồng file, manifest mẫu, quy trình nhập/đối soát/chạy lại.
8. **Cấu hình chạy:** Docker Compose, lockfile, `.env.example` chỉ có giá trị mẫu và README.
9. **Kiểm chứng:** kết quả kiểm thử luồng chính, đồng thời, quyền, phục hồi lỗi và benchmark thực tế.
10. **Trạng thái bàn giao:** chức năng đã hoạt động, phần chưa tích hợp và giả định còn cần xác nhận.

Ưu tiên một luồng chạy thật từ tạo tem đến báo cáo, số liệu truy xuất được và cách vận hành rõ ràng.

Nếu môi trường không chạy được thành phần nào, phải nói rõ; không trình bày mô phỏng như chức năng đã hoạt động.