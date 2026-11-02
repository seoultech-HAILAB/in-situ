"""Wall-clock + Windows Job memory/process limits around capability execution."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile
import threading

from .legacy_engine import Unsupported

ROOT=Path(__file__).resolve().parent.parent
EXECUTIONS = threading.BoundedSemaphore(2)


def resident_kb(pid):
    """Trusted parent-only probe; /bin/ps reports RSS in KiB on macOS."""
    result=subprocess.run(['/bin/ps','-o','rss=','-p',str(pid)],capture_output=True,text=True,timeout=2)
    if result.returncode or not result.stdout.strip():raise OSError('RSS probe failed')
    return int(result.stdout.strip())


class ResidentLimit:
    def __init__(self,process,memory_mb=768):
        self.process=process;self.memory_mb=memory_mb
        self.stopped=threading.Event();self.error=None
        self.thread=threading.Thread(target=self.watch,daemon=True)
        self.thread.start()

    def watch(self):
        while not self.stopped.is_set() and self.process.poll() is None:
            try:
                if resident_kb(self.process.pid)>self.memory_mb*1024:
                    self.error=f'실행 메모리 제한({self.memory_mb} MB)을 초과했습니다.'
            except (OSError,ValueError,subprocess.TimeoutExpired):
                if self.stopped.is_set() or self.process.poll() is not None:return
                self.error='실행 메모리 감시를 시작하지 못했습니다. 제한 없이 실행하지 않았습니다.'
            if self.error:
                try:self.process.kill()
                except ProcessLookupError:pass
                return
            self.stopped.wait(0.2)

    def close(self):
        self.stopped.set();self.thread.join(timeout=3)


def windows_job(process,memory_mb=512):
    from ctypes import wintypes as w
    class IO(ctypes.Structure):
        _fields_=[(x,ctypes.c_ulonglong) for x in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class BASIC(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class EXT(ctypes.Structure):
        _fields_=[('basic',BASIC),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateJobObjectW.restype=w.HANDLE;k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
    k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.CreateJobObjectW(None,None);info=EXT();info.basic.flags=0x2000|0x100|0x8;info.basic.active=1;info.process_memory=memory_mb*1024*1024
    if not handle or not k.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not k.AssignProcessToJobObject(handle,w.HANDLE(int(process._handle))):
        err=ctypes.get_last_error()
        if handle:k.CloseHandle(handle)
        raise Unsupported(f'실행 메모리 격리 설정 실패 ({err}). 제한 없이 실행하지 않았습니다.')
    return lambda:k.CloseHandle(handle)


def isolated_run(code,input_csv,sources=None,timeout=20,engine='capability',plan=None):
    if not EXECUTIONS.acquire(timeout=45):
        raise Unsupported('다른 실행을 처리 중입니다. 잠시 후 다시 요청해 주세요.')
    try:
        return _isolated_run(code,input_csv,sources,timeout,engine,plan)
    finally:
        EXECUTIONS.release()


def _isolated_run(code,input_csv,sources=None,timeout=20,engine='capability',plan=None):
    env={k:v for k,v in os.environ.items() if k.upper() in ('SYSTEMROOT','WINDIR','PATH','TEMP','TMP','LOCALAPPDATA','USERPROFILE')}
    env.update(PYTHONIOENCODING='utf-8',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    scratch=tempfile.TemporaryDirectory(prefix='trace-worker-')
    proc=subprocess.Popen([getattr(sys, '_base_executable', sys.executable),'-I',str(ROOT/'backend'/'worker.py'),sysconfig.get_path('purelib')],cwd=scratch.name,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                          text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    close=lambda:None
    monitor=None
    try:
        if os.name=='nt': close=windows_job(proc)
        elif sys.platform=='darwin':
            monitor=ResidentLimit(proc)
        payload=json.dumps({'code':code,'input_csv':input_csv,'sources':sources or {},'engine':engine,'plan':plan},ensure_ascii=False)
        if len(payload.encode())>3_000_000: raise Unsupported('입력 합계 크기 제한을 초과했습니다.')
        out,err=proc.communicate(payload,timeout=timeout)
        if monitor:
            monitor.close()
            if monitor.error:raise Unsupported(monitor.error)
        if proc.returncode!=0 or not out: raise Unsupported(f'격리 실행 종료 ({proc.returncode}). '+err[-1200:])
        result=json.loads(out)
        if not result['ok']:
            from .python_runtime import PythonFailure
            raise PythonFailure(result['error'],result.get('records'),result.get('failure'))
        return result['records']
    except subprocess.TimeoutExpired as exc:
        proc.kill();proc.communicate()
        raise Unsupported('격리 실행 시간 제한(20초)을 초과했습니다.') from exc
    finally:
        if proc.poll() is None:proc.kill();proc.communicate()
        if monitor:monitor.close()
        close()
        scratch.cleanup()
