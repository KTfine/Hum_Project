param(
    [ValidateSet('minicpm', 'api')]
    [string]$Backend = 'minicpm',
    [string]$GatewayUrl = '',
    [string]$Python = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (-not $Python) {
    $localPython = Join-Path $projectRoot '.venv-client\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python' }
}
$clientLog = Join-Path $projectRoot ('experiments\runtime\live-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.jsonl')
$env:PYTHONIOENCODING = 'utf-8'
if (-not $GatewayUrl) {
    $GatewayUrl = if ($Backend -eq 'api') { 'http://127.0.0.1:8006' } else { 'https://localhost:18006' }
}
$clientArguments = @('--backend', $Backend, '--sprite-dir', (Join-Path $projectRoot 'tachie\sanae'), '--log-file', $clientLog)
if ($GatewayUrl) { $clientArguments += @('--url', $GatewayUrl) }
if ($Backend -eq 'minicpm') { $clientArguments += '--insecure' }
& $Python (Join-Path $projectRoot 'realtime_av_test.py') @clientArguments
exit $LASTEXITCODE
