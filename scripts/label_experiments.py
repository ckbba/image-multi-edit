import copy
import json
import sys
import time
from pathlib import Path
import httpx
from real_experiments import fixture,run_one,OUT
import config,store

def usage():
    r=httpx.get(config.BASE+'/v1/usage',headers={'Authorization':'Bearer '+config.KEY},timeout=30)
    r.raise_for_status();d=r.json()
    return {'unit':d.get('unit'), 'stat':next((x for x in d.get('model_stats',[]) if x.get('model')==config.MODEL),{})}

store.init();base=fixture()['01-single-bag']
for name,label in [('label-empty',''),('label-wrong','红色鞋子')]:
    st=copy.deepcopy(base);st['mappings'][0]['source']['label']=label
    before=usage();result=run_one(name,st,'context-crop');after=usage()
    delta={'before':before,'after':after,'requests_delta':after['stat'].get('requests',0)-before['stat'].get('requests',0),
           'cost_delta':round(after['stat'].get('actual_cost',0)-before['stat'].get('actual_cost',0),8),
           'attribution':'Account model aggregate delta around one test, not a per-request invoice. External concurrent usage cannot be ruled out.'}
    (OUT/(name+'-billing.json')).write_text(json.dumps(delta,indent=2),encoding='utf-8')
    print(name,delta['requests_delta'],delta['cost_delta'],flush=True)
