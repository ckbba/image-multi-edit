"""Public, attributed segmentation sample photographs; not private user assets."""
import sys
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config
import store
import segmentation

store.init()
out = ROOT / 'evidence' / 'samples'; out.mkdir(parents=True, exist_ok=True)
sources = {'car': 'https://huggingface.co/ybelkada/segment-anything/resolve/main/assets/car.png',
           'truck': 'https://raw.githubusercontent.com/facebookresearch/segment-anything/main/notebooks/images/truck.jpg'}
manifest = {}
for name, url in sources.items():
    dest = out / (name + '.png')
    if not dest.exists():
        r = httpx.get(url, follow_redirects=True, timeout=120); r.raise_for_status(); content = r.content
        im = store.ingest(content, name + '.png')
        dest.write_bytes((config.DATA / im['path']).read_bytes())
    else:
        im = store.ingest(dest.read_bytes(), name + '.png')
    manifest[name] = {'asset': im, 'source_url': url}
(out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('samples downloaded', flush=True)
timings = []
for name, data in manifest.items():
    aid = data['asset']['id']
    prep = segmentation.prepare(aid)
    for i, (x, y) in enumerate([(0.4, .5), (.3, .6), (.5, .6), (.6, .5), (.7, .6)]):
        start = time.monotonic()
        result = segmentation.select(aid, x, y)
        for j, mask in enumerate(result['candidates']):
            (out / f'{name}-point{i}-mask{j}.png').write_bytes((config.DATA / mask['path']).read_bytes())
        timings.append({'sample': name, 'prepare': prep, 'point': [x, y], 'elapsed_ms': result['elapsed_ms'], 'candidate_count': len(result['candidates'])})
        print(name, i, result['elapsed_ms'], len(result['candidates']), flush=True)
(ROOT / 'evidence' / 'segmentation-timings.json').write_text(json.dumps(timings, indent=2), encoding='utf-8')
