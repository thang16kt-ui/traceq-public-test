"""Verify backup checksums before an explicitly administered restore."""
from pathlib import Path
import hashlib, json, sys
if len(sys.argv) != 2:
    raise SystemExit('Usage: python scripts/restore-check.py backups/TIMESTAMP')
p=Path(sys.argv[1]).resolve()
checks=json.loads((p/'sha256.json').read_text())
if set(checks) != {'database.dump','exchange.tar.gz'}:
    raise SystemExit('Backup manifest has unexpected files')
for name, expected in checks.items():
    if hashlib.sha256((p/name).read_bytes()).hexdigest()!=expected:
        raise SystemExit('Checksum mismatch: '+name)
print('Checksums verified. Follow docs/operations.md to restore into an isolated environment first.')
