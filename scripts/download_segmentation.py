"""Download a pinned public model into the project, never execute remote model code."""
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parents[1]
target = root / '.models' / 'slimsam'
target.mkdir(parents=True, exist_ok=True)
revision = '72a5ae6'  # Model publisher revision; full commit resolved in evidence if available.
for name in ['config.json', 'preprocessor_config.json', 'model.safetensors']:
    destination = target / name
    if destination.exists():
        print(name, 'already downloaded', destination.stat().st_size)
        continue
    url = f'https://huggingface.co/nielsr/slimsam-77-uniform/resolve/{revision}/{name}'
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    destination.write_bytes(data)
    print(name, len(data))
