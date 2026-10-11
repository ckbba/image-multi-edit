import concurrent.futures
import importlib
import sys
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'后端代码'))
sys.path.insert(0,str(ROOT/'tests'))


def fresh_segmentation():
    sys.modules.pop('segmentation',None)
    return importlib.import_module('segmentation')


def test_api_process_does_not_import_torch_or_transformers():
    before=set(sys.modules)
    fresh_segmentation()
    assert 'torch' not in set(sys.modules)-before
    assert 'transformers' not in set(sys.modules)-before


def test_native_worker_crash_is_controlled_and_next_call_restarts():
    segmentation=fresh_segmentation()
    client=segmentation.SamProcessClient(worker='fake_sam_worker:serve',timeout=2)
    try:
        with pytest.raises(HTTPException) as error:
            client.request('crash')
        assert error.value.status_code==503
        recovered=client.request('prepare',image_id='asset')
        assert recovered['method']=='prepare'
        assert recovered['pid']!=client.last_failed_pid
    finally:
        client.close()


def test_worker_timeout_is_bounded_and_does_not_block_other_api_work():
    segmentation=fresh_segmentation()
    client=segmentation.SamProcessClient(worker='fake_sam_worker:serve',timeout=.2)
    started=time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor() as pool:
            future=pool.submit(client.request,'hang')
            # Represents health/draft/generation work in the API process.
            assert pool.submit(lambda:'api-alive').result(timeout=.1)=='api-alive'
            with pytest.raises(HTTPException) as error:
                future.result(timeout=2)
        assert error.value.status_code==503
        assert time.monotonic()-started<2
        assert client.request('select',image_id='asset',x=.5,y=.5)['method']=='select'
    finally:
        client.close()