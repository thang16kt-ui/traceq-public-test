"""Lưu file (ảnh minh chứng, báo cáo). DB chỉ giữ khóa đường dẫn + SHA-256.

Mặc định: thư mục DATA_DIR trên đĩa bền (Render disk / volume Docker).
Có thể thay bằng kho S3-compatible (Q1) bằng cách cài lớp cùng giao diện.
Chỉ ghi mới, không ghi đè: put() từ chối nếu khóa đã tồn tại.
"""
import hashlib
import os
from pathlib import Path

from .config import DATA_DIR


class LocalFileStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Khóa file không hợp lệ')
        return path

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + '.tmp')
        with open(temporary, 'xb') as handle:  # 'x': không ghi đè file đang có
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            temporary.unlink()
            raise FileExistsError(key)
        os.replace(temporary, path)
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def path(self, key: str) -> Path:
        return self._path(key)

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()


store = LocalFileStore(DATA_DIR)
