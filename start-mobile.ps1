param([switch]$Stop)
$ErrorActionPreference = 'Stop'
$pythonCandidates = @(
    "$env:LOCALAPPDATA/Programs/Python/Python312/python.exe",
    "$env:LOCALAPPDATA/Programs/Python/Python313/python.exe",
    "$env:LOCALAPPDATA/Programs/Python/Python314/python.exe"
)
$pythonPath = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonPath) { throw 'Python was not found.' }
if ($Stop) { & $pythonPath "$PSScriptRoot/setup_mobile.py" --stop }
else { & $pythonPath "$PSScriptRoot/setup_mobile.py" }
exit $LASTEXITCODE
