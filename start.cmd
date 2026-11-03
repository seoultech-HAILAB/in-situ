@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi,uvicorn,pandas,httpx" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 exit /b 1
)
if not exist "node_modules\vite" (
  call npm.cmd ci
  if errorlevel 1 exit /b 1
)
call npm.cmd run build
if errorlevel 1 exit /b 1
if not exist "web\out\index.html" (
  pushd web
  call npm.cmd ci
  if errorlevel 1 exit /b 1
  call npm.cmd run build
  if errorlevel 1 exit /b 1
  popd
)
echo.
echo Trace: http://127.0.0.1:8000
echo Research settings: http://127.0.0.1:8000/?research=1
echo Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
