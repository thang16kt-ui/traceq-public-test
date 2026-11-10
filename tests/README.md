# Kiểm chứng trên PostgreSQL thật

Không chạy bộ này vào cơ sở dữ liệu vận hành. `TEST_DATABASE_URL` bắt buộc chỉ đến database có tên kết thúc bằng `_test`; bộ kiểm thử từ chối database khác và xóa dữ liệu kiểm thử giữa các ca.

```sh
export TEST_DATABASE_URL='postgresql+psycopg://quality:quality-test-password@localhost:5432/quality_test'
python -m pytest tests -q
```

Môi trường kiểm thử dùng API FastAPI qua `TestClient`, với các connection PostgreSQL độc lập cho các thao tác đồng thời. Đây là kiểm thử nghiệp vụ/database; không thay thế kiểm tra camera/tem trên điện thoại hoặc đo mạng/HTTPS.

Bộ benchmark là phép đo bổ sung, không chạy tự động khi chạy pytest; xem `docs/verification.md` để biết số liệu thực đo và giới hạn.

Đo tải riêng trên database có hậu tố `_benchmark` (lệnh này xóa database đó):

```sh
export BENCHMARK_DATABASE_URL='postgresql+psycopg://quality:REPLACE_TEST_PASSWORD@localhost:5432/quality_benchmark'
python -m tests.benchmark --records 100000 --concurrency 30 --export-records 10000 --output docs/benchmark.json
```

Benchmark tạo dữ liệu bằng bulk insert, xác nhận qua ASGI TestClient và chạy entrypoint worker thật. Không chứa phép đo camera, mạng điện thoại, TLS hoặc 30 thiết bị vật lý. Loại `tests/.runtime/`, `tests/.benchmark-runtime/`, `.pytest_cache/` và `__pycache__/` khỏi gói bàn giao.
