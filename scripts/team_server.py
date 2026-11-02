"""A separate team server; its power request ends when this process stops."""
import ctypes
import os
import sys
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.setup_team import setup

port=int(sys.argv[1]) if len(sys.argv)>1 else 8001
folder=setup(port)
os.environ.pop('TRACE_ACCESS_FILE',None)
os.environ.pop('TRACE_LEGACY_AUTH',None)
os.environ['TRACE_DATA_DIR']=str(folder/'sessions')
os.environ['TRACE_STUDY_MODE']='team-pilot'
power_request_active=False
if os.name=='nt':
    # Process-scoped: keep network/server available for the planned team session.
    # Does not keep the display on or alter Windows power settings.
    power_api=ctypes.windll.kernel32.SetThreadExecutionState
    power_api.argtypes=[ctypes.c_uint32]
    power_api.restype=ctypes.c_uint32
    power_request_active=bool(power_api(0x80000001))
    if not power_request_active:
        print('Warning: Windows keep-awake request failed; keep the PC awake manually.',file=sys.stderr)
import uvicorn
if len(sys.argv)>2:
    (folder/'server-runtime.json').write_text(json.dumps({'pid':os.getpid(),'boot_id':sys.argv[2],
        'power_request_active':power_request_active}),encoding='utf-8')
uvicorn.run('backend.app:app',host='127.0.0.1',port=port,workers=1,proxy_headers=True,forwarded_allow_ips='127.0.0.1')
