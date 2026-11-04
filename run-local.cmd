@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing Python environment: .venv
  exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,pandas,httpx" >nul 2>&1
if errorlevel 1 (
  echo Python dependencies are missing. Install requirements.txt first.
  exit /b 1
)
if not exist "web\out\index.html" (
  pushd web
  call npm.cmd run build
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
)
echo TRACE: http://127.0.0.1:8002/
echo In-situ: http://127.0.0.1:8002/in-situ
echo Ex-situ: http://127.0.0.1:8002/ex-situ
echo Research In-situ: http://127.0.0.1:8002/in-situ?research=1
echo Research Ex-situ: http://127.0.0.1:8002/ex-situ?research=1
echo Legacy tools: http://127.0.0.1:8002/legacy?research=1
".venv\Scripts\python.exe" -c "import httpx; r=httpx.get('http://127.0.0.1:8002/api/health',timeout=2,trust_env=False); r.raise_for_status(); assert r.json().get('ok')" >nul 2>&1
if not errorlevel 1 (
  echo A server is already running on port 8002.
  exit /b 0
)
echo Press Ctrl+C to stop.
echo Keep this window open while using the application.
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8002 --reload --reload-dir backend
