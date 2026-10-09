import sys,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))
import config
headers={'Authorization':'Bearer '+config.KEY}
records=[]
with httpx.Client(timeout=30) as client:
    # Only retrieve this task's specific request; don't copy other account history.
    first=json.loads((ROOT/'evidence/real/01-single-bag.json').read_text(encoding='utf-8'))
    tid=first['result']['request_id']
    for path in ['/v1/tasks/'+tid, '/v1/usage']:
        r=client.get(config.BASE+path,headers=headers)
        record={'path':path,'http_status':r.status_code}
        try:
            data=r.json()
            record['fields']=list(data) if isinstance(data,dict) else []
            record['cost_usd']=data.get('cost_usd') if isinstance(data,dict) else None
            # No balance, unrelated prompts, or account history in the delivery.
            record['image25_model_stats']=[v for v in data.get('model_stats',[]) if v.get('model')==config.MODEL] if isinstance(data,dict) else []
        except Exception:record['body_type']='non-JSON'
        records.append(record)
(ROOT/'evidence/billing-verification.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
print(json.dumps(records,indent=2))
