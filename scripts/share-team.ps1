param([int]$Port = 8001)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'process-utils.ps1')
$pilotRoot = Split-Path -Parent $PSScriptRoot
$pilotDir = Join-Path $pilotRoot '.local/pilot'
# The development prototype intentionally has no account login.
$health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health"
if (!$health.ok) { throw '먼저 scripts/start-team.ps1을 실행하세요.' }
$meta = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'cloudflared.json') -Raw | ConvertFrom-Json
$toolDir = Join-Path $pilotRoot '.local/tools'
New-Item -ItemType Directory -Path $toolDir -Force | Out-Null
$tunnelExe = Join-Path $toolDir 'cloudflared.exe'
if (!(Test-Path -LiteralPath $tunnelExe)) {
    Invoke-WebRequest -Uri $meta.url -OutFile $tunnelExe -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $tunnelExe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $meta.sha256) {
    throw 'Cloudflare 공식 배포본 체크섬과 다릅니다. 실행하지 않습니다.'
}
$statePath = Join-Path $pilotDir 'tunnel.json'
if (Test-Path -LiteralPath $statePath) {
    $oldState = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $oldProcess = Get-Process -Id $oldState.pid -ErrorAction SilentlyContinue
    if (Test-PilotProcess $oldProcess $oldState) {
        Get-Content -LiteralPath (Join-Path $pilotDir '공유주소.txt')
        exit 0
    }
}
$logPath = Join-Path $pilotDir 'tunnel.stderr.log'
$tunnelProcess = Start-Process -FilePath $tunnelExe -ArgumentList @('tunnel','--url',"http://127.0.0.1:$Port",'--no-autoupdate','--protocol','http2') -WorkingDirectory $pilotRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $pilotDir 'tunnel.stdout.log') -RedirectStandardError $logPath
@{pid=$tunnelProcess.Id;startTicks=$tunnelProcess.StartTime.ToUniversalTime().Ticks.ToString()} | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding utf8
for ($attempt=0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 1000
    if ($tunnelProcess.HasExited) { throw '터널이 종료되었습니다. .local/pilot/tunnel.stderr.log를 확인하세요.' }
    $tunnelLog = Get-Content -LiteralPath $logPath -Raw -ErrorAction SilentlyContinue
    if ($tunnelLog -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
        $url = $Matches[0]
        Set-Content -LiteralPath (Join-Path $pilotDir '공유주소.txt') -Value $url -Encoding utf8
        Write-Output $url
        Write-Output '로그인 없이 접속합니다. URL을 아는 사람은 개발자 기능도 사용할 수 있습니다. PC와 서버가 실행 중이어야 합니다.'
        exit 0
    }
}
throw '공유 URL을 확인하지 못했습니다. 로그를 확인한 뒤 stop-team.ps1로 종료하고 재시도하세요.'
