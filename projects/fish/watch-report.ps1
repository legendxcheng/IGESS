param(
    [string]$Scenario = "week_1_growth",
    [int]$Port = 0,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$localIgess = Join-Path $repositoryRoot ".tmp\py311-venv\Scripts\igess.exe"
if (-not (Test-Path -LiteralPath $localIgess -PathType Leaf)) {
    $localIgess = (Get-Command igess -ErrorAction Stop).Source
}

$arguments = @(
    "model",
    "watch",
    "--project", $PSScriptRoot,
    "--scenario", $Scenario,
    "--port", $Port
)
if ($NoBrowser) {
    $arguments += "--no-browser"
}

& $localIgess @arguments
exit $LASTEXITCODE
