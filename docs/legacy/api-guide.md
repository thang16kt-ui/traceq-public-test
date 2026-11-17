# API và ví dụ tích hợp

API REST có tiền tố `/api/v1`. OpenAPI từ mã đang chạy là hợp đồng có thẩm quyền: `/openapi.json`, giao diện `/docs`. Xem schema sinh kèm trong bản bàn giao nếu có; khi nâng cấp phải sinh lại thay vì sửa tay lệch khỏi API.

## Phiên, quyền và lỗi

Đăng nhập nhận JSON `username`, `password`. Cookie phiên `session` là `HttpOnly`; client gửi `credentials: include`. Token CSRF từ phiên được gửi trong header `X-CSRF-Token` cho hành động ghi. `Origin`, nếu có, phải khớp `APP_ORIGIN`. Không đưa cookie, token hay mật khẩu vào QR hoặc URL.

Các vai trò: `inspector` (nhân viên), `manager` (quản lý chất lượng), `admin` (quản trị viên). Nhân viên chỉ thấy hồ sơ mình tạo hoặc được giao; quản lý/quản trị thấy hồ sơ trong phạm vi tổ chức MVP. Tài khoản không hoạt động/phiên hết hạn bị từ chối. Không có cơ chế tenant/nhà máy độc lập trong MVP.

Lỗi JSON chuẩn:

```json
{
  "code": "VERSION_CONFLICT",
  "message": "Hồ sơ đã được cập nhật. Vui lòng tải lại.",
  "field_errors": {},
  "request_id": "mã-truy-vết-yêu-cầu"
}
```

Ví dụ chỉ minh họa hình dạng lỗi; mã/thông báo cụ thể xem OpenAPI và kiểm chứng. Trạng thái HTTP chính: `401` cần đăng nhập, `403` thiếu quyền/CSRF/origin, `404` không thấy tài nguyên trong quyền, `409` trùng/xung đột phiên bản hoặc khóa idempotency, `422` dữ liệu không hợp lệ, `429` vượt giới hạn. API có thể trả `404` cho hồ sơ ngoài quyền để tránh tiết lộ tài nguyên.

GET chỉ đọc. Mở liên kết QR, preload, crawler hay xem trước không xác nhận. Phải POST rõ ràng sau đăng nhập.

| Endpoint | Quyền MVP |
|---|---|
| `POST /auth/login`, health | Chưa cần phiên; login kiểm origin và giới hạn thử sai |
| `GET /auth/me`, `POST /auth/logout` | Đã đăng nhập |
| `GET /product-types`, `/batches`, `/defect-types`, `/inspection-sessions` | Đã đăng nhập |
| `POST /product-types`, `/batches`, `/defect-types` | `admin` |
| `POST /inspection-sessions`, `/defect-cases` | Đã đăng nhập; kiểm tra quan hệ và trạng thái đợt |
| `PATCH /inspection-sessions/{id}` | `manager`, `admin`; cần lý do và phiên bản |
| `GET /defect-cases`, `/{id}`, `/qr/{token}`, `/units/{id}/label` | Quản lý/quản trị hoặc hồ sơ được tạo/được giao |
| `POST /defect-cases/{id}/confirm` | Có quyền hồ sơ |
| `PATCH /defect-cases/{id}` | Có quyền hồ sơ; đóng/hủy/giao việc cần `manager`/`admin` |
| `POST /defect-cases/{id}/costs` | `manager`, `admin` |
| `POST /defect-cases/{id}/attachments`, `GET /attachments/{id}` | Có quyền hồ sơ |
| `GET /export-schedules`, `/export-runs`, `/import-runs`, `/audit-logs` | `manager`, `admin` |
| `POST/PATCH /export-schedules` | `admin` |
| `POST /export-runs`, `GET /export-runs/{id}`, `/{id}/download` | `manager`, `admin` |
| `GET /users` | `manager`, `admin`; chỉ trả thông tin tài khoản an toàn |
| `GET /analytics/*` | `manager`, `admin` |

Danh sách trả `items`, `total`, `page`, `page_size` nếu có phân trang. `page >= 1`, cỡ trang tối đa 100; thứ tự hiện cố định theo thời điểm tạo giảm dần. Tìm kiếm hồ sơ phía API hiện theo serial, không phải bộ máy tìm kiếm mọi trường.

## Idempotency và đồng thời

Gửi `Idempotency-Key` ngẫu nhiên ổn định cho một thao tác ghi. Nếu timeout, gửi lại cùng tài khoản, thao tác, khóa **và đúng payload cũ**. Kết quả thành công đã lưu được trả lại, không tạo thêm. Cùng khóa nhưng payload khác trả xung đột; thao tác mới phải dùng khóa mới.

Xác nhận còn có `client_event_id` UUID trong JSON. Giữ nguyên ID và `observed_at` khi thử lại; không tạo UUID mới mỗi lần retry. `actor_id` luôn lấy từ phiên, không được nhận từ client. Hai điện thoại dùng hai event khác nhau vẫn chỉ có một lần xác nhận đầu tiên nhờ khóa/cập nhật điều kiện và transaction database.

PATCH gửi `row_version` hiện thấy cùng lý do. Khi trả `409`, tải lại và cho người dùng xem thay đổi; không lặp ghi đè bằng phiên bản mới mà không kiểm tra nội dung.

## Danh mục và đợt kiểm tra

Danh mục đọc: `GET /product-types`, `GET /defect-types`, `GET /batches`. Quản trị viên tạo danh mục qua POST tương ứng. UUID liên kết phải là ID đang tồn tại.

Ví dụ tạo đợt kiểm tra:

```http
POST /api/v1/inspection-sessions
Content-Type: application/json
X-CSRF-Token: <token-phien>
Idempotency-Key: <uuid-thao-tac>
```

```json
{
  "batch_id": "11111111-1111-4111-8111-111111111111",
  "line": "Dây chuyền 1",
  "shift": "Ca sáng",
  "stage": "Kiểm tra cuối",
  "inspected_count": 100,
  "sample_method": "Kiểm tra toàn bộ",
  "population_key": "LO-2026-001-KT-CUOI",
  "started_at": "2026-11-10T08:00:00+07:00"
}
```

`population_key` là mã phạm vi mẫu dùng đối soát; không tự chứng minh hai mẫu không trùng. `inspected_count` có thể `null`, khác 0. PATCH đợt yêu cầu `row_version` và `reason`.

## Tạo tem và xác nhận

```json
{
  "inspection_session_id": "22222222-2222-4222-8222-222222222222",
  "serial_number": "SP-000001",
  "detected_at": "2026-11-10T09:20:00+07:00",
  "note": "Phát hiện tại bàn kiểm tra cuối",
  "defects": [
    {
      "defect_type_id": "33333333-3333-4333-8333-333333333333",
      "occurrence_count": 2,
      "severity": "medium",
      "suspected_cause": "Cần xác minh"
    }
  ]
}
```

Gửi body trên tới `POST /defect-cases`. Đây là nháp. Serial được liên kết/cấp sản phẩm trong lô của đợt, QR bền vững nằm ở sản phẩm; không dùng QR chung cho SKU hay loại lỗi. Phạm vi serial hiện duy nhất theo `(batch_id, serial_number)`; nếu muốn serial toàn nhà máy cần thay quy tắc/ràng buộc trước khi vận hành.

`GET /qr/{token}` trả sản phẩm và các hồ sơ người dùng được xem. Nếu sản phẩm có nhiều đợt, chọn đúng hồ sơ trước khi xác nhận. Nhập tay có thể dùng serial; nếu trùng serial giữa các lô, API yêu cầu dùng QR chính xác thay vì tự chọn một sản phẩm. `GET /units/{id}/label?format=pdf&width_mm=60&height_mm=40` tải tem theo quyền; `format` là `png`/`pdf`, mặc định 60×40 mm, chiều rộng 35–150 mm và cao 30–150 mm. In lại không thay token. Tem liên kết tới `${APP_ORIGIN}/q/{token}`; PNG có bố cục chữ và QR, PDF dùng kích thước trang tương ứng. Kích thước thực phải được thử trên máy in và thiết bị đích.

```http
POST /api/v1/defect-cases/<case-id>/confirm
Content-Type: application/json
X-CSRF-Token: <token-phien>
Idempotency-Key: <uuid-on-dinh>
```

```json
{
  "client_event_id": "44444444-4444-4444-8444-444444444444",
  "observed_at": "2026-11-10T09:21:00+07:00",
  "device_id": "dien-thoai-ban-kiem-tra-1"
}
```

Response có `case_id`, `first_confirmed_at`, `outcome`, `request_id`. `confirmed_now` nghĩa request đó tạo xác nhận đầu; `already_confirmed` nghĩa hồ sơ đã có xác nhận. Gửi lại cùng request trả response đã lưu của request đó, nên có thể vẫn nhận `confirmed_now` dù lần gọi HTTP sau là retry. Không dùng `outcome` để tự cộng số trên client; lấy tổng từ backend.

## Xử lý và chi phí

Trạng thái: `draft` → `confirmed` → `in_progress` → `recheck` → `closed`; `cancelled` cần lý do. Sửa/chuyển trạng thái qua `PATCH /defect-cases/{id}` có `row_version`, `reason`, có thể có `action_taken`, `assigned_to`, `note`, `defects`. Đóng có `result` trong `passed_after_repair`, `scrapped`, `other`; quy tắc chuyển/duyệt được kiểm tra ở backend.

Ví dụ khoản chi:

```json
{
  "category": "repair_labor",
  "amount": "100000.00",
  "currency": "VND",
  "cost_status": "actual",
  "source_reference": "PHIEU-SUA-0001",
  "allocations": [
    {
      "case_defect_id": "55555555-5555-4555-8555-555555555555",
      "allocated_amount": "60000.00"
    }
  ]
}
```

Gửi tới `POST /defect-cases/{id}/costs`. `amount` và `allocated_amount` **phải là chuỗi**, không là số JSON float. Phân bổ phải cùng hồ sơ, tổng không vượt khoản nguồn; phần còn lại là chưa phân bổ.

API ảnh nhận multipart field `file` qua `POST /defect-cases/{id}/attachments`, giới hạn 5 MiB và 20 triệu pixel. Nội dung phải là JPEG/PNG hợp lệ; backend giải mã và lưu lại JPEG với tên nội bộ, không tin đuôi file client. Tải bằng `GET /attachments/{id}` kiểm quyền hồ sơ. UI upload ảnh và quy trình quản lý minh chứng đầy đủ có thể thuộc phần mở rộng; kiểm trạng thái bàn giao trong README.

## Lịch và công việc xuất

```json
{
  "name": "Chốt dữ liệu ngày trước",
  "enabled": true,
  "local_time": "17:00",
  "days_of_week": [0, 1, 2, 3, 4, 5, 6],
  "timezone": "Asia/Ho_Chi_Minh",
  "period_rule": "previous_day",
  "format": "csv",
  "destination_id": "local",
  "filters": {}
}
```

`POST /export-schedules`; thứ Hai=0, Chủ nhật=6. MVP chỉ hỗ trợ kỳ `previous_day`, đích `local`, format `csv` hoặc `xlsx`; không nhập đường dẫn tùy ý. PATCH gửi đầy đủ cấu hình lịch và `row_version`; sửa giờ/múi giờ tính lại `next_run_at` và giữ watermark kỳ để đối soát.

Xuất ngay:

```json
{
  "period_start": "2026-11-09T00:00:00+07:00",
  "period_end": "2026-11-10T00:00:00+07:00",
  "scope": {},
  "format": "csv",
  "revision": 1
}
```

`POST /export-runs` trả `202` và `run_id`; polling `GET /export-runs/{id}` thay vì giữ request chờ. Chỉ tải `GET /export-runs/{id}/download` sau `succeeded`, có kiểm tra quyền. Lần chạy lại cùng business key nhận công việc/kết quả cũ; revision mới dùng khi sửa sau chốt. Hợp đồng ZIP xem [file-contract.md](file-contract.md).

## Phân tích

`GET /analytics/summary`, `/analytics/pareto`, `/analytics/trends`, `/analytics/forecast` lấy số liệu backend theo quyền và phạm vi. `/analytics/groups?group_by=batch|shift|line|product_type` so sánh nhóm bằng đúng mẫu số; `/analytics/imported-summary` đọc số liệu mirror sau importer. Không tính tỷ lệ/tiền lại bằng các dòng bảng hiện tại trên frontend. Thiếu mẫu số trả tỷ lệ `null`; thiếu lịch sử/mô hình kiểm chứng thì forecast giải thích chưa đủ dữ liệu.

Các bộ lọc MVP hỗ trợ theo từng endpoint được liệt kê trong OpenAPI. Không gửi tên cột SQL hoặc `order_by` tùy ý; danh sách cần phân trang và giới hạn cỡ trang. Scope export chấp nhận `inspection_session_id`, `batch_id`, `product_type_id`, `line`, `shift`, `stage`.

`summary`/`pareto`/`trends` dùng database ghi nhận trực tiếp. `imported-summary` có `source=validated_import_mirror`, gồm toàn bộ dữ liệu đã nhập và hợp nhất theo ID/phiên bản; `data_as_of` lấy lần nhập thành công gần nhất. Đây là endpoint đối soát mô-đun nhận, không mặc định có cùng phạm vi với một truy vấn dashboard đang lọc. Dữ liệu mirror không thay thế database ghi nhận. Bản cũ không được ghi đè bản mới, và báo cáo phải giải thích đang dùng dữ liệu trực tiếp hay snapshot đã nhập.
