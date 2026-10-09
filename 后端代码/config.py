import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data'))).resolve()
PASSWORD = os.getenv('SITE_PASSWORD', '')
MODEL_DIR = Path(os.getenv('SEGMENTATION_MODEL_DIR', str(ROOT / '.models/slimsam'))).resolve()
SEGMENTATION_DEVICE = os.getenv('SEGMENTATION_DEVICE', 'cpu').lower()
MODE = os.getenv('GENERATION_MODE', 'simulation')
BASE = os.getenv('IMAGE25_BASE_URL', 'https://task-api-1-cn.65535.space').rstrip('/')
KEY = os.getenv('IMAGE25_API_KEY', '')
MODEL = os.getenv('IMAGE25_MODEL', '')
EXPERIMENTAL = os.getenv('IMAGE25_EXPERIMENTAL', 'false').lower() == 'true'
SOURCE_STRATEGY = os.getenv('SOURCE_STRATEGY', 'full')
