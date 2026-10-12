"""Production-only checks; development run.py remains unchanged."""
import os
import runpy
from pathlib import Path

password = os.environ.get('SITE_PASSWORD', '')
if not password or password == 'change-this-private-password':
    raise RuntimeError('Set SITE_PASSWORD before starting')
if os.environ.get('COOKIE_SECURE') != 'true':
    raise RuntimeError('Production requires COOKIE_SECURE=true and an HTTPS proxy')
if os.environ.get('GENERATION_MODE') == 'live' and not all(os.environ.get(key) for key in ('IMAGE25_API_KEY', 'IMAGE25_MODEL')):
    raise RuntimeError('Live generation requires IMAGE25_API_KEY and IMAGE25_MODEL')
for key in ('HF_HOME', 'HF_HUB_CACHE', 'XDG_CACHE_HOME'):
    if path := os.environ.get(key):
        Path(path).mkdir(parents=True, exist_ok=True)
runpy.run_path(str(Path(__file__).resolve().parents[2] / 'run.py'), run_name='__main__')

