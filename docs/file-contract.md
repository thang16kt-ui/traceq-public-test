# Hợp đồng trao đổi dữ liệu 1.0

## Gói và phạm vi

Mỗi lần xuất tạo một ZIP hoàn chỉnh với sáu thành viên ở thư mục gốc:

```text
manifest.json
inspection_sessions.csv
defect_cases.csv
case_defects.csv
cost_entries.csv
cost_allocations.csv
```

Khi chọn XLSX, năm file dữ liệu mang đuôi `.xlsx`, mỗi file có một sheet `data`. Không có đường dẫn con, tên tùy ý, tệp bổ sung hoặc thành viên ZIP trùng tên. Importer không extract đường dẫn do gói cung cấp.

`snapshot_mode = full`: toàn bộ đợt có `inspection_sessions.started_at >= period_start AND < period_end` và thỏa `scope`; toàn bộ hồ sơ/chi tiết/chi phí/phân bổ thuộc các đợt đó tại cutoff. Gói có thể chứa hồ sơ nháp/hủy để truyền đầy đủ trạng thái. Khi tính số lỗi, ứng dụng nhận phải lọc đã xác nhận và chưa hủy; không đếm mọi dòng `defect_cases`.

Kỳ là nửa mở `[period_start, period_end)`, không chọn theo giờ file hoàn tất. `cutoff_at` là thời điểm chốt đọc dữ liệu, khác thời điểm lịch đến hạn/bắt đầu/hoàn tất. Đồng bộ muộn hoặc sửa sau chốt phải tạo revision mới, không ghi đè báo cáo cũ. Giữ snapshot và file cũ để tái lập.

## Manifest

| Trường | Ý nghĩa |
|---|---|
| `schema_version` | Chuỗi phiên bản hợp đồng; hiện `"1.0"` |
| `export_id`, `revision` | Định danh lần xuất và phiên bản; revision nguyên dương |
| `snapshot_mode` | `"full"` |
| `scope` | Bộ lọc sản phẩm/lô/đợt/dây chuyền/ca/công đoạn, không là đường dẫn ghi |
| `period_start`, `period_end` | ISO 8601 có múi giờ, đầu < cuối |
| `timezone` | Tên IANA của quy tắc kỳ |
| `cutoff_at` | Mốc chốt dữ liệu có múi giờ |
| `cohort_rule` | Giải thích chọn đợt và toàn bộ bảng con |
| `csv_encoding` | `"UTF-8-BOM"` |
| `csv_text_escape` | `"apostrophe-prefix-v1"` |
| `null_encoding` | `"empty-cell"` |
| `files` | Mỗi phần tử gồm `name`, `table`, `rows`, `sha256`, `columns` |

SHA-256 tính trên **byte file dữ liệu thực tế trong ZIP**, gồm cả BOM, dấu xuống dòng và escape; không tính trên dữ liệu đã parse. `rows` không gồm dòng header. Manifest được thêm cuối; ZIP chỉ công bố sau khi ghi xong, flush/fsync và rename trên cùng filesystem.

Xem mẫu máy sinh trong `worker/examples/` nếu có trong bản bàn giao. Không dùng manifest minh họa để ghép với dữ liệu vận hành: checksum/số dòng phải được sinh lại từ đúng file.

## Kiểu dữ liệu

- UUID/serial/mã/tên/thời gian là văn bản. Thời gian ISO 8601 phải có offset.
- Số đếm là số nguyên không âm; `occurrence_count` và `row_version` nguyên dương. `inspected_count` có thể để trống nghĩa `null`.
- Tiền là chuỗi thập phân chuẩn hai chữ số, ví dụ `"125000.00"`, cùng mã tiền tệ ba chữ cái; không chuyển qua float.
- CSV UTF-8 có BOM, xuống dòng CRLF, quoting theo thư viện CSV. Ô trống là `null`; ở hợp đồng này chuỗi rỗng và `null` không phân biệt.
- CSV dùng escape chống công thức: nếu văn bản bắt đầu bằng `=`, `+`, `-`, `@`, tab, CR hoặc dấu nháy đơn, thêm một dấu nháy đơn ở đầu. Importer gỡ đúng một dấu theo `apostrophe-prefix-v1`, không trim tùy ý.
- XLSX ghi chuỗi dưới kiểu text, kể cả chuỗi trông như công thức. Importer từ chối ô formula. Số đếm giữ kiểu số; UUID/thời gian/tiền giữ kiểu exact text để tránh mất chính xác.

Các bảng xuất chứa `created_at`, `updated_at`, `row_version`. Hồ sơ có thông tin serial/sản phẩm/lô, chi tiết lỗi có mã/tên chuẩn hóa để ứng dụng ngoài giải thích dữ liệu mà không cần truy database ghi nhận.

## Kiểm tra trước khi nhập

Importer kiểm tra toàn bộ gói vào staging/bộ nhớ giới hạn trước khi thay dữ liệu phân tích:

1. ZIP hợp lệ, có đúng 5 file dữ liệu và manifest, không trùng/đường dẫn vượt thư mục.
2. Giới hạn kích thước nén và tổng byte thành viên ZIP giải nén 128 MiB; tối đa 250.000 dòng mỗi bảng. XLSX là ZIP lồng nên được kiểm thêm số thành viên tối đa 1.000 và tổng byte giải nén nội bộ 128 MiB. Đây là giới hạn gói, không phải cam kết RAM tiến trình tối đa 128 MiB: đối tượng Python, snapshot và parse vẫn tốn thêm bộ nhớ. Gói lớn hơn cần chia phạm vi/kỳ hoặc thiết kế streaming riêng.
3. Đúng `schema_version`, `snapshot_mode`, UUID/revision/kỳ/cutoff và danh sách file.
4. SHA-256 khớp, số dòng và header khớp manifest; cột lõi bắt buộc có mặt.
5. UUID/phiên bản/thời gian/số lượng/tiền hợp lệ, ID trong từng bảng không trùng.
6. Hồ sơ tham chiếu đợt có trong gói; lỗi và chi phí tham chiếu hồ sơ; phân bổ tham chiếu khoản chi và lỗi cùng hồ sơ.
7. Tổng phân bổ không vượt khoản nguồn.

Sau khi kiểm tra mới cập nhật mirror phân tích bằng một giao dịch. Gói lỗi không cập nhật một phần bảng chính. Phần giới hạn là khả năng đã chọn của MVP, không phải công cụ nhập dữ liệu tùy ý/không giới hạn.

## Chống nhập trùng và bản cũ

`export_id + revision` là khóa nhận dạng gói. Nhập lại cùng định danh và checksum không cộng thêm sản phẩm/tiền. Cùng định danh nhưng nội dung khác là xung đột, cần đối soát thay vì âm thầm thay thế.

Ứng dụng nhận cập nhật theo ID và phiên bản; bản cũ không được ghi đè bản mới. Khi một hồ sơ phiên bản mới được nhập, các bảng con thuộc snapshot phải được đồng bộ nhất quán, gồm lỗi bị gỡ, phân bổ và trạng thái hủy. Không chỉ append các dòng mới.

Không xóa toàn bộ mirror chỉ vì một gói full không chứa ID ngoài phạm vi của nó. Full chỉ đầy đủ trong scope/kỳ đã khai báo, không là bản sao toàn doanh nghiệp. Trường hợp scope giao nhau cần quy tắc phiên bản cấp hồ sơ/đợt và đối soát dữ liệu cùng phiên bản nhưng khác nội dung.

## Thư mục, chạy lại và sửa sau chốt

Volume tích hợp dùng các vùng `incoming/`, `processed/`, `failed/` dưới `DATA_DIR`. Chỉ đưa ZIP hoàn chỉnh vào `incoming`; không đặt `.tmp` rồi đổi tên ở filesystem khác và cho rằng thao tác nguyên tử. Trường hợp object storage cần dấu hoàn tất tương đương.

Lịch sử nhập lưu định danh, checksum, trạng thái, thời điểm và lỗi. Sau sửa nguyên nhân, đưa lại gói hợp lệ/phiên bản mới qua luồng nhập; không chỉnh trực tiếp bảng phân tích. Khởi động lại phải tiếp tục rà `incoming` và không nhân dữ liệu đã nhập.

Ví dụ sau chốt: revision 1 đã ghi nhận 8 sản phẩm lỗi; một hồ sơ thuộc đúng đợt gửi đến muộn. Tạo revision 2 cùng kỳ/phạm vi ở cutoff mới, kiểm tra snapshot mới, nhập cập nhật theo ID. Báo cáo cũ còn để đối soát, revision 2 là bản bổ sung được nhận rõ; không sửa âm thầm file revision 1.

Importer nội bộ dùng chung volume không là bridge qua mạng. Tích hợp máy nhà máy cần bridge HTTPS với tài khoản dịch vụ và danh sách thư mục được phép; khi chưa triển khai, tải ZIP thủ công có kiểm tra quyền ở API.

## Thay đổi giá trị từ bản cải tiến (schema ứng dụng 006+)

Cấu trúc gói không đổi (vẫn `schema_version = "1.0"`), nhưng giá trị một số cột đổi nghĩa; hệ thống nhận cần cập nhật:

- `defect_cases.status` ∈ `nhap, cho_minh_chung, cho_xac_nhan, cho_phuong_an, cho_cap_tren, dang_xu_ly, cho_dong, da_dong, da_huy`.
  Sản phẩm được tính là lỗi khi `first_confirmed_at` có giá trị (Giám sát "Xác nhận lỗi") và trạng thái khác `da_huy`.
- `case_defects.level` (thay cột `severity`) ∈ `nhe, trung_binh, nang`, do Quản lý cài theo từng loại lỗi; `code`, `name` là snapshot tên/mã loại lỗi lúc ghi nhận.
- `defect_cases.result` = phương án cuối khi đóng (`sua, tai_che, huy, khac`).
- Chi phí thực tế khi đóng ghi một dòng `cost_entries` (`category = xu_ly_thuc_te`, `cost_status = actual`).
