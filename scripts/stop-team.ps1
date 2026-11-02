$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'process-utils.ps1')
$pilotDir = Join-Path (Split-Path -Parent $PSScriptRoot) '.local/pilot'
foreach ($stateName in @('tunnel.json','server.json')) {
    $statePath = Join-Path $pilotDir $stateName
    if (!(Test-Path -LiteralPath $statePath)) { continue }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $process = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
    # Never stop an unrelated process if Windows has reused a saved process ID.
    if (Test-PilotProcess $process $state) {
        if ($stateName -eq 'server.json' -and !$state.startTicks) {
            Get-CimInstance Win32_Process -Filter "ParentProcessId=$($process.Id)" |
                Where-Object { $_.CommandLine -match 'scripts/team_server\.py' } |
                ForEach-Object { Stop-Process -Id $_.ProcessId }
        }
        if (!$process.HasExited) { Stop-Process -Id $process.Id }
        [void]$process.WaitForExit(10000)
        Write-Output "종료: $stateName"
    }
}
