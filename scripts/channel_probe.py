"""Read-only channel evidence. No credential values are printed or persisted in evidence."""
import sys
import json
import time
from pathlib import Path
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '后端代码'))
import config

out = ROOT / 'evidence'
out.mkdir(exist_ok=True)
with httpx.Client(timeout=30) as client:
    for route in ('models', 'pricing'):
        begin = time.monotonic()
        response = client.get(config.BASE + '/v1/' + route, headers={'Authorization': 'Bearer ' + config.KEY})
        data = response.json()
        records = data.get('data', data) if isinstance(data, dict) else data
        if isinstance(records, dict):
            records = records.get('models', [])
        selected = [r for r in records if 'image-2.5' in str(r)] if isinstance(records, list) else records
        evidence = dict(endpoint=route, status=response.status_code, duration_s=round(time.monotonic() - begin, 3), records=selected)
        (out / f'channel-{route}.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
        print(route, response.status_code, json.dumps(selected, ensure_ascii=True)[:14000])
