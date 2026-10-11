"""Real local SlimSAM integration and serialized concurrent-call evidence."""
import concurrent.futures
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))


def main():
    with tempfile.TemporaryDirectory(prefix='sam-isolation-',dir=ROOT/'output') as data:
        os.environ['DATA_DIR']=data
        os.environ['SEGMENTATION_MODEL_DIR']=str(ROOT/'.models/slimsam')
        import config
        config.DATA=Path(data)
        import store
        import segmentation
        store.init()
        source=ROOT/'evidence/samples/bag.png'
        meta=store.ingest(source.read_bytes(),source.name)
        started=time.monotonic()
        prepared=segmentation.prepare(meta['id'])
        points=[(.5,.5),(.45,.5),(.55,.5),(.5,.45),(.5,.55),(.4,.5),(.6,.5),(.5,.4)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures=[pool.submit(segmentation.select,meta['id'],x,y) for x,y in points]
            results=[future.result(timeout=240) for future in futures]
        report={
            'fixture':'evidence/samples/bag.png',
            'model':str(config.MODEL_DIR),
            'api_process_torch_imported':'torch' in sys.modules,
            'prepare':prepared,
            'concurrent_requests':len(results),
            'candidate_counts':[len(item['candidates']) for item in results],
            'mask_methods':sorted({candidate['origin']['method'] for item in results for candidate in item['candidates']}),
            'elapsed_s':round(time.monotonic()-started,3),
            'serialized_single_worker':True,
        }
        assert not report['api_process_torch_imported']
        assert all(count>0 for count in report['candidate_counts'])
        assert report['mask_methods']==['slimsam-77-uniform']
        segmentation.close()
        output=ROOT/'output/sam-isolation-real.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    main()
