param(
    [string]$Python = 'python',
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GatewayArgs
)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $ProjectRoot
try {
    & $Python -m api_mode @GatewayArgs
    $GatewayExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $GatewayExitCode
