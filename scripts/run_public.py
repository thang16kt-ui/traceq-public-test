"""Single-host public test deployment; PostgreSQL and file storage remain durable.

Required: DATABASE_URL, APP_ORIGIN (or provider public origin), and DATA_DIR.
Optional explicit demo seed: ENVIRONMENT=demo, SEED_DEMO=true, DEMO_PASSWORD;
database name must end in _demo, as enforced by the existing seed CLI.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def configure():
    database = os.environ['DATABASE_URL']
    for scheme in ('postgres://', 'postgresql://'):
        if database.startswith(scheme):
            database = 'postgresql+psycopg://' + database[len(scheme):]
            break
    os.environ['DATABASE_URL'] = database
    origin = os.getenv('APP_ORIGIN') or os.getenv('RENDER_EXTERNAL_URL')
    if not origin and os.getenv('RAILWAY_PUBLIC_DOMAIN'):
        origin = 'https://' + os.environ['RAILWAY_PUBLIC_DOMAIN']
    parsed = urlsplit(origin or '')
    if parsed.scheme != 'https' or not parsed.netloc or parsed.path not in ('', '/'):
        raise RuntimeError('Configure the actual HTTPS APP_ORIGIN before public deployment')
    os.environ['APP_ORIGIN'] = origin.rstrip('/')
    os.environ['COOKIE_SECURE'] = 'true'
    os.environ.setdefault('DATA_DIR', '/data')
    os.environ.setdefault('ENVIRONMENT', 'demo')
    os.environ.setdefault('PUBLIC_DEMO_ACCESS', 'true' if os.environ['ENVIRONMENT']=='demo' else 'false')
    Path(os.environ['DATA_DIR']).mkdir(parents=True, exist_ok=True)
    return int(os.getenv('PORT', '8000'))

def main():
    port = configure()
    from backend.app.cli import migrate, seed_demo
    migrate()
    if os.getenv('SEED_DEMO', '').lower() == 'true':
        from backend.app.db import SessionLocal
        from backend.app.models import ProductType
        from sqlalchemy import select
        with SessionLocal() as db:
            empty = db.scalar(select(ProductType.id).limit(1)) is None
        if empty:
            seed_demo('DEMO_PASSWORD')
    commands = [
        [sys.executable, '-m', 'uvicorn', 'scripts.serve_local:app', '--host', '0.0.0.0', '--port', str(port), '--no-access-log'],
        *[[sys.executable, '-m', 'worker.main', mode] for mode in ('scheduler', 'worker', 'importer')],
    ]
    children = []
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
        for child in children:
            if child.poll() is None:
                child.terminate()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT))
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('A required service exited; restart the test deployment')
            time.sleep(1)
    finally:
        stop()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

if __name__ == '__main__':
    main()
