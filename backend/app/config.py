import os
from pathlib import Path

DATABASE_URL = os.environ['DATABASE_URL']
APP_ORIGIN = os.getenv('APP_ORIGIN', 'http://localhost:8080').rstrip('/')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'
DATA_DIR = Path(os.getenv('DATA_DIR', '/data')).resolve()
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '12'))
ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')
