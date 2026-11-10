# Từ điển dữ liệu và chỉ số

## Đơn vị đếm và thời gian

- **Loại sản phẩm**: SKU/tên/đơn vị tính có thể cấu hình; không là sản phẩm vật lý.
- **Sản phẩm vật lý (`unit`)**: serial hoặc mã nội bộ cùng QR ổn định. In lại không tạo sản phẩm.
- **Đợt kiểm tra**: một lô, dây chuyền, ca và công đoạn. `inspected_count = NULL` nghĩa chưa nhập; `0` nghĩa đã ghi nhận không kiểm tra sản phẩm nào.
- **Hồ sơ**: duy nhất theo sản phẩm và đợt. Nháp không tham gia tử số. Kiểm tra lại sau sửa thuộc lịch sử hồ sơ.
- **Lượt lỗi**: số lần xuất hiện của một loại lỗi được người kiểm tra xác định. `occurrence_count` là số nguyên dương. Không lấy số dòng lỗi thay tổng lượt.
- **Thời điểm phát hiện**: thời gian nghiệp vụ phát hiện lỗi; **observed_at**: thiết bị quan sát sự kiện; **received_at**: máy chủ nhận. Đồng hồ điện thoại không được dùng làm bằng chứng duy nhất cho thời điểm nhận.
- **first_confirmed_at**: lần đầu máy chủ xác nhận hợp lệ; không thay đổi khi quét lại.
- **created_at/updated_at/row_version**: dùng đối soát và truyền thay đổi; không thay thời gian nghiệp vụ.

Mọi thời điểm trao đổi ISO 8601 có offset. Database dùng `TIMESTAMPTZ`. Múi giờ là tên IANA, ví dụ `Asia/Ho_Chi_Minh`; không chỉ lưu `UTC+7`.

## Phạm vi và công thức

| Chỉ số | Cách tính | Dữ liệu thiếu/giới hạn |
|---|---|---|
| Tổng đã kiểm tra | Tổng `inspected_count` trong đúng tập đợt được lọc | Nếu bất kỳ đợt nào thiếu mẫu số, đánh dấu thiếu; không tự dùng sản lượng |
| Sản phẩm lỗi | Đếm hồ sơ đã xác nhận, không hủy trong phạm vi đợt | Mỗi cặp sản phẩm–đợt đếm một; cùng sản phẩm ở đợt độc lập khác là lượt kiểm tra khác |
| Tỷ lệ lỗi | `numerator / denominator × 100` | Thiếu mẫu số hoặc mẫu số bằng 0: `null`, UI “Chưa đủ dữ liệu” |
| Tổng lượt lỗi | Tổng `occurrence_count` của các hồ sơ hợp lệ | Có thể lớn hơn số sản phẩm lỗi |
| Sản phẩm bị ảnh hưởng bởi loại lỗi | Đếm hồ sơ riêng biệt có loại lỗi đó | Một sản phẩm có nhiều loại có thể thuộc nhiều nhóm; không cộng thành tổng sản phẩm |
| Tỷ trọng lượt lỗi | Lượt của loại / tổng lượt | Ghi rõ cơ sở là lượt, không phải sản phẩm |
| Pareto tích lũy | Sắp theo lượt giảm dần, tổng dồn / tổng lượt | Không giả định quy luật 80/20 luôn đúng |
| Tỷ lệ sau gộp | Tổng tử số / tổng mẫu số các phạm vi không chồng lấn | Không trung bình cộng các tỷ lệ |
| Tỷ lệ đạt sau sửa | Hồ sơ đóng đạt sau sửa / hồ sơ có kết quả kiểm tra lại hợp lệ | Không suy từ mọi hồ sơ đóng nếu gồm loại bỏ/kết quả khác |
| Thời gian xử lý | Thời điểm đóng − lần xác nhận đầu | Hồ sơ chưa đóng không được coi có thời gian 0 |
| Bao phủ chi phí thực tế | Hồ sơ có ít nhất một khoản `actual` / hồ sơ lỗi | Khoản ước tính chưa là chi phí thực tế; không có khoản chi là chưa biết, không phải miễn phí |

Ví dụ: một đợt kiểm tra 100 sản phẩm có 8 hồ sơ đã xác nhận và tổng 12 lượt lỗi cho kết quả **8%**, **8 sản phẩm lỗi**, **12 lượt lỗi**. Hai lỗi trên cùng sản phẩm không làm tử số thành 9.

MVP chọn đợt theo thời điểm bắt đầu đợt trong `[period_start, period_end)`, rồi lấy mẫu số và toàn bộ hồ sơ thuộc đợt đó tại mốc chốt. Đây là báo cáo theo phạm vi đợt, không phải số lần quét xảy ra trong ngày. Đợt kéo dài qua ngày vẫn ở kỳ bắt đầu; cần chốt quy tắc này với nghiệp vụ trước dùng thật. Giao diện, export và ứng dụng nhận phải giữ cùng quy tắc.

Nếu số sản phẩm lỗi vượt số đã kiểm tra, giữ nguyên hồ sơ, gắn cảnh báo đối soát và trả tỷ lệ `null` cho đến khi đối soát. Nhiều đợt cùng `population_key` cũng làm tỷ lệ `null` vì có nguy cơ mẫu chồng lấn. Mã population khác nhau không chứng minh mẫu không trùng; chất lượng khai báo vẫn cần người quản lý xác minh. Khi các đợt tái kiểm tra/mẫu chồng lấn, chỉ có số tổng thì không đủ loại trùng mẫu số; tách báo cáo hoặc ghi rõ đơn vị lượt kiểm tra.

Mọi kết quả cần đi kèm bộ lọc/phạm vi, tử số, mẫu số, thời điểm dữ liệu `data_as_of` và cảnh báo. Các báo cáo từ mẫu không tự đại diện toàn bộ sản xuất.

## Tiền và phân bổ

`amount`, `allocated_amount` dùng `NUMERIC(18,2)`. API/JSON dùng chuỗi thập phân, ví dụ `"125000.00"`, kèm `currency`. Không cộng hai tiền tệ khác nhau khi chưa có quy tắc quy đổi có nguồn.

| Khái niệm | Quy tắc |
|---|---|
| Khoản chi nguồn | Một `cost_entry` cộng một lần theo hồ sơ, không theo số lỗi |
| Thực tế / ước tính | Tính riêng theo `cost_status`; không gộp thành “thiệt hại thực tế” |
| Phân bổ | Gắn khoản nguồn vào lỗi con; kiểm tra cùng hồ sơ và tổng phân bổ không vượt khoản nguồn trong giao dịch |
| Chưa phân bổ | `amount − tổng allocated_amount`; hiển thị riêng, không làm mất tiền |
| Tổng tiền theo loại lỗi | Tổng phần được phân bổ tới loại; không nhân toàn bộ chi phí với từng loại |
| Chi phí trung bình | Tổng phần chi phí có dữ liệu / số trường hợp có dữ liệu theo định nghĩa đã chọn |
| Loại bỏ/phế phẩm | Dùng giá trị tổn thất được duyệt trừ thu hồi có căn cứ; không mặc định giá bán là thiệt hại |

Ví dụ: hồ sơ có 2 loại lỗi và khoản sửa `100000.00 VND`, phân bổ `60000.00` và `25000.00` thì tổng vẫn `100000.00`, phần chưa phân bổ `15000.00`. Không ghi `100000.00` vào cả hai nhóm rồi báo `200000.00`.

Không nối trực tiếp `case_defects × cost_entries` rồi tổng hợp tiền: phải tổng hợp mỗi bảng về cấp hồ sơ trước, hoặc dùng truy vấn riêng. Các nhóm “phổ biến nhất”, “tổng tiền cao nhất” và “tiền bình quân cao nhất” phải có thứ hạng riêng.

## Nguyên nhân, minh chứng và dữ liệu thiếu

Nguyên nhân nghi ngờ và nguyên nhân đã xác minh là hai trường khác nhau. Tương quan ca/lô không đủ kết luận nguyên nhân. Ghi chú/ảnh/chứng từ là minh chứng, được kiểm tra quyền theo hồ sơ.

Dữ liệu không có giữ `null`/trạng thái chưa có, không điền giả 0. Danh mục vô hiệu hóa vẫn giữ liên kết lịch sử. Hủy là thay đổi nghiệp vụ có lý do, audit và phiên bản; importer phải nhận được trạng thái này.

## Dự báo

MVP chỉ trả điều kiện chưa đủ dữ liệu; không tạo dự báo bằng số ngẫu nhiên hoặc đường xu hướng rồi gọi là mô hình. Để bật dự báo cần xác định mục tiêu, kỳ dự báo, kế hoạch số lượng kiểm tra, độ ổn định cách lấy mẫu, dữ liệu đầu vào, khoảng huấn luyện, `model_version`, backtest theo thứ tự thời gian, baseline và khoảng bất định. Số ngày tối thiểu đơn lẻ không chứng minh dữ liệu đủ.
