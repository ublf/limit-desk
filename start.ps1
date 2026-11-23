param([switch]$ConnectCli)
$ErrorActionPreference = 'Stop'
$pythonCandidates = @(
    "$env:LOCALAPPDATA/Programs/Python/Python312/python.exe",
    "$env:LOCALAPPDATA/Programs/Python/Python313/python.exe",
    "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe"
)
$pythonPath = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonPath) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $pythonPath = $pythonCommand.Source }
    else { throw 'Python 3.10 or later is required.' }
}
if ($ConnectCli) {
    & $pythonPath "$PSScriptRoot/connect_cli.py"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $pythonPath "$PSScriptRoot/server.py"
