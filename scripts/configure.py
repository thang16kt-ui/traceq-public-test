"""Generate development configuration without placing secrets in command history."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if target.exists():
    raise SystemExit('.env đã tồn tại; giữ nguyên cấu hình hiện tại.')
sample = (root / '.env.example').read_text()
target.write_text(sample.replace('REPLACE_WITH_RANDOM_HEX', secrets.token_hex(32)).replace('REPLACE_WITH_APP_RANDOM_HEX', secrets.token_hex(32)))
target.chmod(0o600)
print('Đã tạo .env riêng. Xem README trước khi bật HTTPS hoặc dùng trong vận hành.')
