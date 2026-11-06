param(
    [Parameter(Mandatory = $true)][string]$SshHost,
    [int]$SshPort = 22,
    [string]$SshUser = 'root',
    [int]$LocalPort = 18006
)
& ssh -N -p $SshPort -L "${LocalPort}:127.0.0.1:8006" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 "${SshUser}@${SshHost}"
exit $LASTEXITCODE
