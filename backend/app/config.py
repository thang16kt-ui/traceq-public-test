import os
from pathlib import Path

DATABASE_URL = os.environ['DATABASE_URL']
APP_ORIGIN = os.getenv('APP_ORIGIN', 'http://localhost:8080').rstrip('/')
COOKIE_SECURE = os.getenv('COOKIE_SECURE', 'true').lower() == 'true'
DATA_DIR = Path(os.getenv('DATA_DIR', '/data')).resolve()
SESSION_HOURS = int(os.getenv('SESSION_HOURS', '12'))
ENVIRONMENT = os.getenv('ENVIRONMENT', 'production')
VAPID_PUBLIC_KEY = os.getenv('VAPID_PUBLIC_KEY', '')
VAPID_PRIVATE_KEY = os.getenv('VAPID_PRIVATE_KEY', '')
VAPID_SUBJECT = os.getenv('VAPID_SUBJECT', 'mailto:admin@example.invalid')
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USER = os.getenv('SMTP_USER', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM = os.getenv('SMTP_FROM', SMTP_USER)
SMTP_SECURITY = os.getenv('SMTP_SECURITY', 'starttls')  # starttls | ssl | none
