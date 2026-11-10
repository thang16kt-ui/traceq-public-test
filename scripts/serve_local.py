"""Optional local runner serving the built React app beside the real API.

Set DATABASE_URL, DATA_DIR, APP_ORIGIN, COOKIE_SECURE first. This does not
replace worker/scheduler/importer processes or production HTTPS.
"""
from pathlib import Path
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.app.main import app

dist = Path(__file__).resolve().parents[1] / 'frontend' / 'dist'
if not (dist / 'index.html').is_file():
    raise RuntimeError('Build frontend first: cd frontend && npm ci && npm run build')

@app.get('/q/{token}', include_in_schema=False)
def qr_landing(token: str):
    # Opening a URL only renders the app; it never confirms a defect.
    return FileResponse(dist / 'index.html', headers={'Cache-Control':'no-store'})

app.mount('/', StaticFiles(directory=dist, html=True), name='frontend')
