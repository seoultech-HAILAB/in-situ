@echo off
setlocal
cd /d "%~dp0"
echo Keep the existing run-local.cmd backend running on port 8002.
echo Participant In-situ: http://YOUR-LAN-IP:8003/in-situ
echo Participant Ex-situ: http://YOUR-LAN-IP:8003/ex-situ
echo The API key stays on this server. Do not share port 8002.
".venv\Scripts\python.exe" -c "import httpx; r=httpx.get('http://127.0.0.1:8002/api/health',timeout=3,trust_env=False); r.raise_for_status(); assert r.json().get('api_configured')" >nul 2>&1
if errorlevel 1 (
  echo Run run-local.cmd first and configure the server .env API key.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import httpx; r=httpx.get('http://127.0.0.1:8003/api/health',timeout=2,trust_env=False); r.raise_for_status()" >nul 2>&1
if not errorlevel 1 (
  echo The participant gateway is already running on port 8003.
  pause
  exit /b 0
)
".venv\Scripts\python.exe" -m uvicorn backend.share:app --host 0.0.0.0 --port 8003
