@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -c "import httpx; r=httpx.get('http://127.0.0.1:8002/api/health',timeout=3,trust_env=False); r.raise_for_status(); assert r.json().get('api_configured')" >nul 2>&1
if errorlevel 1 (
  echo Run run-local.cmd first and configure OPENAI_API_KEY in the server .env.
  pause
  exit /b 1
)
if not exist ".local\cloudflared.exe" (
  curl.exe -L --fail -o ".local\cloudflared.exe" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -c "import httpx; r=httpx.get('http://127.0.0.1:8003/api/health',timeout=2,trust_env=False); r.raise_for_status()" >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "$studyRoot=(Get-Location).Path; Start-Process -FilePath ($studyRoot+'\.venv\Scripts\python.exe') -ArgumentList '-m','uvicorn','backend.share:app','--host','0.0.0.0','--port','8003' -WorkingDirectory $studyRoot -WindowStyle Hidden -RedirectStandardOutput ($studyRoot+'\.local\study-gateway.stdout.log') -RedirectStandardError ($studyRoot+'\.local\study-gateway.stderr.log')"
)
echo A temporary HTTPS address will appear below.
echo Append /in-situ or /ex-situ to that address and share it with participants.
echo Keep this window and the backend running throughout the experiment.
echo Restarting the tunnel changes the URL and browser origin. Do not restart during a participant session.
".local\cloudflared.exe" tunnel --url http://127.0.0.1:8003 --no-autoupdate --protocol http2
