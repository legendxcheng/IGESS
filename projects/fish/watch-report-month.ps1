param(
    [int]$Port = 0,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$watchReportParameters = @{
    Scenario = "month_1_growth"
    Port = $Port
}
if ($NoBrowser) {
    $watchReportParameters["NoBrowser"] = $true
}

& (Join-Path $PSScriptRoot "watch-report.ps1") @watchReportParameters
exit $LASTEXITCODE
