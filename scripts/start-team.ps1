param([int]$Port = 8001, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'process-utils.ps1')
$pilotRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $pilotRoot
$pilotPython = Join-Path $pilotRoot '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pilotPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 가상환경 생성 실패' }
    & $pilotPython -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python 의존성 설치 실패' }
}
if (!$SkipBuild) {
    if (!(Test-Path -LiteralPath 'node_modules/vite')) {
        npm.cmd ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci 실패' }
    }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '웹 빌드 실패' }
}
& $pilotPython scripts/setup_team.py $Port
if ($LASTEXITCODE -ne 0) { throw '실행 폴더 준비 실패' }
$pilotDir = Join-Path $pilotRoot '.local/pilot'
$pilotState = Join-Path $pilotDir 'server.json'
if (Test-Path -LiteralPath $pilotState) {
    $oldState = Get-Content -LiteralPath $pilotState -Raw | ConvertFrom-Json
    $oldProcess = Get-Process -Id $oldState.pid -ErrorAction SilentlyContinue
    if (Test-PilotProcess $oldProcess $oldState) {
        Write-Output "팀 서버가 이미 실행 중입니다: http://127.0.0.1:$($oldState.port)"
        exit 0
    }
}
$bootId = [guid]::NewGuid().ToString()
$pilotLauncher = Start-Process -FilePath $pilotPython -ArgumentList @('scripts/team_server.py', "$Port", $bootId) -WorkingDirectory $pilotRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pilotDir 'server.stdout.log') -RedirectStandardError (Join-Path $pilotDir 'server.stderr.log')
$runtimePath = Join-Path $pilotDir 'server-runtime.json'
$runtimeInfo = $null
for ($attempt=0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if (Test-Path -LiteralPath $runtimePath) {
        $runtimeInfo = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json
        if ($runtimeInfo.boot_id -eq $bootId) { break }
    }
    if ($pilotLauncher.HasExited) { throw '서버가 종료되었습니다. server.stderr.log를 확인하세요.' }
}
if (!$runtimeInfo -or $runtimeInfo.boot_id -ne $bootId) { throw '서버 프로세스를 확인하지 못했습니다.' }
# Windows venv uses a launcher child; record the actual server process.
$pilotProcess = Get-Process -Id $runtimeInfo.pid
@{ pid=$pilotProcess.Id; startTicks=$pilotProcess.StartTime.ToUniversalTime().Ticks.ToString(); port=$Port } | ConvertTo-Json | Set-Content -LiteralPath $pilotState -Encoding utf8
Write-Output "팀 서버: http://127.0.0.1:$Port / 로그인 없이 접속"
Write-Output '설치 없는 URL 생성: powershell -ExecutionPolicy Bypass -File scripts/share-team.ps1'
