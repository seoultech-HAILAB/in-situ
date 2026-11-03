"""Trusted subprocess entrypoint; receives no target or API credentials."""
import json
import sys
from pathlib import Path

sys.stdin.reconfigure(encoding='utf-8')
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
if len(sys.argv)>1:
    sys.path.insert(0,sys.argv[1])
if __name__=='__main__':
    try:
        if sys.platform != 'win32':
            import resource
            from backend.worker_limits import install_posix_limits
            install_posix_limits(sys.platform, resource)
        from backend.engine import parse_table
        from backend.runtime import run
        from backend.python_runtime import run as python_run, install_audit
        body=json.loads(sys.stdin.read(3_000_001))
        if body.get('engine')=='python':
            install_audit()
            result=python_run(body['code'],parse_table(body['input_csv']),{k:parse_table(v) for k,v in body.get('sources',{}).items()},body['plan'])
        else:
            result=run(body['code'],parse_table(body['input_csv']),{k:parse_table(v) for k,v in body.get('sources',{}).items()},plan=body.get('plan'))
        payload=json.dumps({'ok':True,'records':result},ensure_ascii=False,allow_nan=False)
        if len(payload.encode())>32_000_000: raise ValueError('실행 기록 크기 제한을 초과했습니다.')
        sys.stdout.write(payload)
    except Exception as exc:
        data={'ok':False,'error':str(exc)[:2000],'type':type(exc).__name__,'records':getattr(exc,'records',[]),'failure':getattr(exc,'failure',{})}
        payload=json.dumps(data,ensure_ascii=False)
        if len(payload.encode())>32_000_000:payload=json.dumps({'ok':False,'error':'실행 기록 크기 제한 초과'})
        sys.stdout.write(payload)
