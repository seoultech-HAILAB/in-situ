@echo off
setlocal
cd /d "%~dp0"
git branch --show-current | findstr /x "in-situ" >nul
if errorlevel 1 (
  echo This script only pushes the in-situ branch. Switch to in-situ first.
  pause
  exit /b 1
)
git push origin HEAD:in-situ
if errorlevel 1 (
  echo Push failed. Check GitHub access and network connectivity in this terminal.
  pause
  exit /b 1
)
echo Published: https://github.com/seoultech-HAILAB/in-situ/tree/in-situ
pause
