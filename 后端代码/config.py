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


def normalize_model_setting(model):
    return {
        'gpt-image-2.5-flare-eco': 'gpt-image-2.5-flare',
        'gpt-image-2.5-sunburst-eco': 'gpt-image-2.5-sunburst',
    }.get(model, model)


DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'data'))).resolve()
PASSWORD = os.getenv('SITE_PASSWORD', '')
MODEL_DIR = Path(os.getenv('SEGMENTATION_MODEL_DIR', str(ROOT / '.models/slimsam'))).resolve()
SEGMENTATION_DEVICE = os.getenv('SEGMENTATION_DEVICE', 'cpu').lower()
MODE = os.getenv('GENERATION_MODE', 'simulation')
BASE = os.getenv('IMAGE25_BASE_URL', 'https://task-api-1-cn.65535.space').rstrip('/')
KEY = os.getenv('IMAGE25_API_KEY', '')
MODEL = normalize_model_setting(os.getenv('IMAGE25_MODEL', ''))
EXPERIMENTAL = os.getenv('IMAGE25_EXPERIMENTAL', 'false').lower() == 'true'
SOURCE_STRATEGY = os.getenv('SOURCE_STRATEGY', 'full')
GEMINI_BASE = os.getenv('GEMINI_BASE_URL', 'https://cccodex.cn/v1/chat/completions')
GEMINI_KEY = os.getenv('GEMINI_API_KEY', '')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')
GEMINI_TIMEOUT = float(os.getenv('GEMINI_TIMEOUT_SECONDS', '45'))

PUBLIC_BASE_URL = os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8787').rstrip('/')
EMAIL_VERIFICATION_REQUIRED = os.getenv('EMAIL_VERIFICATION_REQUIRED', 'false').lower() == 'true'
SMTP_HOST = os.getenv('SMTP_HOST', '')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
SMTP_USERNAME = os.getenv('SMTP_USERNAME', '')
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', '')
SMTP_FROM_NAME = os.getenv('SMTP_FROM_NAME', '拾影')
SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'true').lower() == 'true'


def mail_ready():
    return all((SMTP_HOST, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM_EMAIL, PUBLIC_BASE_URL))
