# Hạng mục 9 — Sửa, xóa và khôi phục danh mục

Phạm vi: loại sản phẩm (`product-types`), lô sản xuất (`batches`), loại lỗi (`defect-types`). Dây chuyền, ca và công đoạn vẫn là trường nhập chữ, chưa chuyển thành danh mục mới.

## Cách dùng

1. Mở **Cài đặt → Danh mục vận hành**. Chọn một trong ba danh mục.
2. Khách public xem được danh sách; bấm **Đăng nhập quản lý** bằng tài khoản manager/admin hiện có để thay đổi. Không có mật khẩu mặc định mới trong bản sửa này.
3. **Sửa** mở form có lý do thay đổi. **Xóa** luôn mở hộp xác nhận có lý do.
4. Máy chủ kiểm tra lại dữ liệu liên quan trong giao dịch: chưa từng dùng thì xóa hẳn; đã dùng thì ngừng sử dụng. Cả trường hợp loại lỗi từng được ghi rồi bỏ khỏi phiếu cũng được giữ lại.
5. Chọn trạng thái **Ngừng sử dụng** để khôi phục. Nếu loại sản phẩm ngừng sử dụng, các lô con tạm ẩn khỏi lựa chọn mới; phải khôi phục sản phẩm trước khi khôi phục một lô đã ngừng sử dụng riêng.
6. **Lịch sử** ghi ai, làm gì, lúc nào, lý do và giá trị trước/sau. Việc xóa hẳn vẫn để lại audit trong server.

Danh mục ngừng sử dụng không xuất hiện trong form mới. API cũng chặn tạo đợt/phiếu mới bằng ID đã ngừng sử dụng, kể cả gọi trực tiếp. Hồ sơ cũ, QR cũ, chi phí và báo cáo vẫn truy xuất được. Loại lỗi ngừng sử dụng đang có trên phiếu cũ vẫn được giữ khi sửa phiếu; không được thêm vào phiếu mới.

Sửa tên cập nhật nhãn trong các truy vấn mới và tăng phiên bản các bản ghi xuất có nhãn liên quan. Không tái tạo hoặc sửa file xuất/snapshot đã hoàn tất. Điều này giữ hợp đồng nhập dữ liệu: nội dung thay đổi phải có phiên bản mới.

## Quyền và tên trùng

Mọi API thêm/sửa/xóa/khôi phục và xem audit danh mục kiểm tra manager/admin tại server. Danh tính dùng chung `public.guest` bị chặn dù phiên cũ của nó có role admin. Ghi nhận thông thường vẫn không cần đăng nhập trong chế độ public demo. Phân quyền toàn bộ app thuộc hạng mục 6, chưa nằm trong thay đổi này.

Tên/mã được chuẩn hóa Unicode NFC, bỏ khoảng trắng đầu/cuối, gộp khoảng trắng liên tiếp và `casefold`. Giữ dấu tiếng Việt. Tên sản phẩm và tên lỗi duy nhất trong từng danh mục; mã lô duy nhất trong một loại sản phẩm. SKU/mã lỗi cũng được kiểm tra tương tự. Mục ngừng sử dụng vẫn giữ tên; khôi phục thay vì tạo bản trùng.

Các thao tác ghi có CSRF, Idempotency-Key và row_version; lỗi xung đột yêu cầu tải lại. Khóa giao dịch dùng chung giữa thay đổi danh mục và ghi nhận mới tránh xóa trong lúc phát sinh tham chiếu. Chuyển lô đã dùng sang sản phẩm khác bị chặn.

## API

- `GET /api/v1/{catalog}?state=active|inactive|all&page=1&page_size=20`: mặc định chỉ mục đang dùng; phân trang tối đa 100.
- `POST /api/v1/{catalog}`: thêm.
- `PATCH /api/v1/{catalog}/{id}`: đầy đủ trường sửa + `row_version`, `reason`.
- `DELETE /api/v1/{catalog}/{id}`: JSON `row_version`, `reason`; trả `operation=delete|deactivate`.
- `POST /api/v1/{catalog}/{id}/restore`: JSON `row_version`, `reason`.
- `GET /api/v1/{catalog}/{id}/history`: audit phân trang, truy vấn được cả sau xóa hẳn.
- `POST /api/v1/auth/catalog-login`: xác thực manager/admin hiện có, thay phiên cookie hiện tại. Tài khoản inspector không được nâng quyền.

`catalog` là một trong ba tên ở đầu tài liệu. Xem `backend/openapi.json` để biết request đầy đủ.

## Migration và giữ dữ liệu

Chạy `python -m backend.app.cli migrate`. Migration 002 thêm `is_active` cho sản phẩm/lô, khóa tên/mã chuẩn hóa, cờ đã từng sử dụng và ràng buộc duy nhất. Tái dùng `is_active` hiện có của loại lỗi. Giữ UUID, tên gốc, FK, số lượng và chi phí. Backfill nhận biết các tham chiếu hiện có và lịch sử lỗi đã bị bỏ khỏi phiếu.

Migration khóa bảng danh mục, kiểm tra tên/mã trùng và chạy trong một giao dịch. **Nếu dữ liệu cũ trùng hoặc tên rỗng: dừng, rollback và báo ID cần đối soát; không tự đổi tên, gộp hoặc xóa.** Việc sửa tên cũ cần được người phụ trách xác nhận trước. Chạy lại sau thành công không áp dụng lần hai. Health readiness yêu cầu schema 002.

Render test Free chạy migration lúc khởi động như trước. Không đổi gói, ổ đĩa hoặc cấu hình database. Cần sao lưu database theo quy trình vận hành trước khi nâng cấp môi trường quan trọng. Bản ứng dụng trước 002 không tương thích hoàn toàn với ràng buộc ghi mới; không rollback code cũ đơn lẻ. Nếu cần phục hồi, dùng phương án database + ứng dụng tương thích hoặc bản sửa tiến tiếp; không tự xóa cột/downgrade.

## Kiểm chứng

Kết quả: **81 kiểm thử đạt** trên PostgreSQL thật; frontend build TypeScript/Vite thành công. Chạy toàn bộ pytest trên PostgreSQL riêng có hậu tố `_test` theo `tests/README.md`. Các kiểm thử mới bao gồm ba danh mục, hard delete, ngừng sử dụng, khôi phục, trùng tên khi thêm/sửa, Unicode/khoảng trắng, quyền manager/inspector/guest, phiên bản, audit, idempotency, ghi đồng thời, dữ liệu lịch sử, xuất/nhập sau đổi tên và migration từ schema cũ/cài mới/chạy lại/dừng vì trùng.

Kiểm tra trình duyệt Chromium đã chạy trên database test riêng ở 375×812 và 1280×900: đăng nhập quản lý, thêm, sửa, hủy xóa, xóa chưa dùng, ngừng sử dụng đã dùng, xem audit, khôi phục. Không tràn ngang ở 375px; nút vùng danh mục cao ít nhất 48px; không có lỗi JavaScript trong các luồng này. Chưa kiểm tra găng tay trên thiết bị vật lý hoặc mạng di động.

Giới hạn hạ tầng đã biết chưa thuộc mục 9: ảnh/file xuất của Render Free còn nằm ở thư mục tạm; khách public vẫn dùng chung danh tính cho các chức năng ngoài danh mục. Chưa thực hiện các hạng mục 1–8.

Khi chủ dữ liệu đã xác nhận bỏ một loại lỗi trùng, quản trị triển khai có thể đặt `CATALOG_RETIREMENTS_JSON` thành danh sách kế hoạch có `id`, `expected_code`, `expected_name`, `row_version`, `reason`. Migration 002 đối chiếu chính xác bản ghi, chuyển ngừng sử dụng, thêm mã vào nhãn lưu trữ để phân biệt, giữ ID/FK và ghi audit trước/sau dưới danh tính hệ thống. Phiên bản phiếu/chi tiết liên quan được tăng để xuất/nhập nhất quán. Chỉ chạy trước 002, cùng giao dịch; kế hoạch sai hoặc trùng chưa giải quyết vẫn làm migration dừng. Không có kế hoạch thì không tự đối soát. Sau triển khai, xóa kế hoạch hoặc đặt `[]`; không đưa thông tin môi trường cụ thể vào mã nguồn.

## Cách vào quản lý trên bản test public

Theo yêu cầu dùng thử, bật riêng `PUBLIC_DEMO_CATALOG_LOGIN=true` cùng `ENVIRONMENT=demo` và `PUBLIC_DEMO_ACCESS=true` để hộp quản lý danh mục nhận mật khẩu bất kỳ. Không cần nhập tên tài khoản. Máy chủ cấp phiên cho danh tính dùng chung `public.catalog` có vai trò manager; không đăng nhập thay tài khoản admin thật. Lịch sử ghi rõ quản lý bản test dùng chung. CSRF, Origin, Idempotency-Key và kiểm tra phiên bản vẫn áp dụng. Tắt cờ sẽ vô hiệu phiên quản lý thử hiện có. Ngoài chế độ này, đăng nhập quản lý vẫn kiểm tra mật khẩu; `/auth/login` thông thường luôn kiểm tra mật khẩu. Không cần migration, không đổi mật khẩu hay dữ liệu tài khoản hiện có.
