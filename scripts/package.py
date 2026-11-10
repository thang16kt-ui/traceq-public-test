"""Package source and built UI, omitting credentials and runtime/business data."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
target = args.out.resolve()
if target.is_relative_to(root):
    raise SystemExit('Write the package outside the source tree to avoid including prior archives.')
target.parent.mkdir(parents=True, exist_ok=True)
skip_dirs = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.runtime', '.benchmark-runtime', 'data', 'backups'}
files = []
for path in sorted(root.rglob('*')):
    relative = path.relative_to(root)
    if not path.is_file() or path.is_symlink() or any(p in skip_dirs for p in relative.parts):
        continue
    if path.name.startswith('.env') and path.name != '.env.example':
        continue
    if path.suffix in {'.pyc', '.pyo', '.log', '.dump', '.tsbuildinfo'}:
        continue
    files.append((path, relative))
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path, relative in files:
        info = zipfile.ZipInfo('traceq/' + relative.as_posix(), (2026, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100755 if path.suffix == '.sh' else 0o100644) << 16
        archive.writestr(info, path.read_bytes())
checksum = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix(target.suffix + '.sha256').write_text(checksum + '  ' + target.name + '\n')
print(json.dumps({'package':str(target),'files':len(files),'bytes':target.stat().st_size,'sha256':checksum}))
