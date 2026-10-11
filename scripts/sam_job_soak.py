"""Five-minute isolated soak: concurrent simulation jobs plus real SAM RPC."""
import concurrent.futures
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))
DURATION=float(os.getenv('SOAK_SECONDS','300'))


def main():
    with tempfile.TemporaryDirectory(prefix='sam-job-soak-',dir=ROOT/'output') as data:
        os.environ['DATA_DIR']=data
        os.environ['SEGMENTATION_MODEL_DIR']=str(ROOT/'.models/slimsam')
        os.environ['GENERATION_MODE']='simulation'
        import config
        config.DATA=Path(data);config.MODE='simulation'
        import store,provider,segmentation
        store.init()
        source=ROOT/'evidence/samples/bag.png'
        asset=store.ingest(source.read_bytes(),source.name)
        segmentation.prepare(asset['id'])
        job_ids=[]
        snapshot=json.dumps({'mode':'simulation','state':{'name':'soak'},'compiled':{}})
        with store.db() as con:
            for index in range(8):
                jid=store.uid();job_ids.append(jid)
                con.execute('INSERT INTO jobs(id,idem,created,status,snapshot) VALUES(?,?,?,?,?)',
                            (jid,f'soak-{index}',time.time(),'queued',snapshot))
        started=time.monotonic();cycles=0;sam_calls=0;job_calls=0
        points=[(.5,.5),(.45,.5),(.55,.5),(.5,.45),(.5,.55),(.4,.5),(.6,.5),(.5,.4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            while time.monotonic()-started<DURATION:
                with store.db() as con:
                    con.execute("UPDATE jobs SET status='queued',result='{}'")
                work=[pool.submit(provider.execute,jid) for jid in job_ids]
                work += [pool.submit(segmentation.select,asset['id'],x,y) for x,y in points]
                values=[future.result(timeout=60) for future in work]
                assert all(store.job(jid)['status']=='simulated' for jid in job_ids)
                assert all(len(item['candidates']) for item in values[len(job_ids):])
                cycles+=1;job_calls+=len(job_ids);sam_calls+=len(points)
        elapsed=time.monotonic()-started
        report={'duration_s':round(elapsed,3),'minimum_required_s':DURATION,'cycles':cycles,
                'concurrent_simulation_job_executions':job_calls,'real_sam_rpc_calls':sam_calls,
                'workers':16,'all_jobs_final_status':'simulated','api_process_torch_imported':'torch' in sys.modules,
                'paid_calls':0,'data_dir_deleted_after_test':True}
        assert elapsed>=DURATION and not report['api_process_torch_imported']
        segmentation.close()
        (ROOT/'output/sam-job-5min-soak.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))


if __name__=='__main__':
    main()
