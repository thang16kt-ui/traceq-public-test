#!/bin/sh
# Run from project root; writes a consistent database/file pair after pausing writers.
set -eu
umask 077
backup_root="${1:-backups}"
case "$backup_root" in /*|*..*) echo 'Use a relative backup directory without ..' >&2; exit 2;; esac
mkdir -p "$backup_root"
backup_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_path="$backup_root/$backup_stamp"
mkdir "$backup_path"
# Keep db running. Pausing API/jobs prevents file/database point-in-time skew.
docker compose stop api worker scheduler importer
trap 'docker compose start api worker scheduler importer >/dev/null' EXIT INT TERM
docker compose exec -T db sh -c 'pg_dump -U traceq -d "$POSTGRES_DB" -Fc' > "$backup_path/database.dump"
docker compose run --rm --no-deps -T --user root --entrypoint tar api -C /data -czf - . > "$backup_path/exchange.tar.gz"
python3 - "$backup_path" <<'PY'
from pathlib import Path
import hashlib,json,sys
p=Path(sys.argv[1])
(p/'sha256.json').write_text(json.dumps({x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in p.iterdir() if x.is_file()},indent=2))
PY
printf 'Backup complete: %s\n' "$backup_path"
