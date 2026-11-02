from concurrent.futures import ThreadPoolExecutor
import threading
import time

import backend.isolation as isolation


def test_shared_worker_capacity_and_release_after_failure(monkeypatch):
    active=0
    peak=0
    mutex=threading.Lock()
    def run(code,*args):
        nonlocal active,peak
        with mutex:
            active+=1
            peak=max(peak,active)
        try:
            time.sleep(.03)
            if code=='fail':
                raise ValueError('expected worker failure')
            return code
        finally:
            with mutex:
                active-=1
    monkeypatch.setattr(isolation,'_isolated_run',run)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(isolation.isolated_run,code,'') for code in ['one','fail','two','three','four','five']]
        results=[]
        for f in futures:
            try: results.append(f.result())
            except ValueError: results.append('failed')
    assert peak==2 and active==0
    assert results==['one','failed','two','three','four','five']
    assert isolation.isolated_run('after failure','')=='after failure'
