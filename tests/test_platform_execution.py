from types import SimpleNamespace
from unittest.mock import Mock
import backend.isolation as isolation
from backend.worker_limits import install_posix_limits


def test_darwin_keeps_cpu_limit_without_restricting_virtual_address_space():
    resource=SimpleNamespace(RLIMIT_CPU=0,RLIMIT_AS=5,setrlimit=Mock())
    install_posix_limits('darwin',resource)
    assert resource.setrlimit.call_args_list==[((0,(15,15)),)]
    resource.setrlimit.reset_mock()
    install_posix_limits('linux',resource)
    assert resource.setrlimit.call_count==2
    resource.setrlimit.assert_any_call(5,(768*1024*1024,768*1024*1024))


class Process:
    pid=321
    returncode=None
    def poll(self):return self.returncode
    def kill(self):self.returncode=-9


def test_resident_limit_kills_an_over_budget_worker(monkeypatch):
    monkeypatch.setattr(isolation,'resident_kb',lambda pid:769*1024)
    process=Process();monitor=isolation.ResidentLimit(process)
    monitor.thread.join(timeout=2);monitor.close()
    assert process.returncode==-9 and '768 MB' in monitor.error


def test_resident_limit_fails_closed_if_probe_is_unavailable(monkeypatch):
    def failed(pid):raise OSError('unavailable')
    monkeypatch.setattr(isolation,'resident_kb',failed)
    process=Process();monitor=isolation.ResidentLimit(process)
    monitor.thread.join(timeout=2);monitor.close()
    assert process.returncode==-9 and monitor.error
