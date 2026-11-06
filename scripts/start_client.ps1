param(
    [string]$GatewayUrl = 'https://localhost:18006',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Python) {
    $localPython = Join-Path $projectRoot '.venv-client\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python' }
}
$clientLog = Join-Path $projectRoot ('runtime_results\live-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.jsonl')
$env:PYTHONIOENCODING = 'utf-8'
& $Python (Join-Path $projectRoot 'realtime_av_test.py') --url $GatewayUrl --insecure --sprite-dir (Join-Path $projectRoot 'tachie\sanae') --log-file $clientLog
exit $LASTEXITCODE
