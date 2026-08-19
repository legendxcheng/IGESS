[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,

    [string]$SourceRoot = 'E:\IGESS',
    [string]$DistributionRoot = 'E:\GameBalancer',
    [string]$JsonRoot = 'E:\fish-oasis\igess_export\json',
    [string]$Scenario = 'smoke',
    [string]$PythonPath = '',
    [string]$ExpectedRemote = 'https://codeup.aliyun.com/691876b8876b90de1aac524d/GameBalancer.git',
    [switch]$AllowDirtyDistribution
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Action
    )

    Write-Host "[GameBalancer] $Label"
    & $Action
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

function Get-InputFingerprint {
    param([Parameter(Mandatory = $true)][string]$Root)

    Get-ChildItem -LiteralPath $Root -Recurse -File -Filter '*.json' |
        Sort-Object FullName |
        ForEach-Object {
            $relative = [System.IO.Path]::GetRelativePath($Root, $_.FullName)
            $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
            "$relative|$($_.Length)|$($_.LastWriteTimeUtc.Ticks)|$hash"
        }
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)

    $descendants = @()
    $frontier = @($Process.Id)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($parentId in $frontier) {
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$parentId" -ErrorAction SilentlyContinue
            foreach ($child in $children) {
                $descendants += [int]$child.ProcessId
                $next += [int]$child.ProcessId
            }
        }
        $frontier = $next
    }
    foreach ($processId in ($descendants | Sort-Object -Descending -Unique)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
    Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
}

$SourceRoot = [System.IO.Path]::GetFullPath($SourceRoot)
$DistributionRoot = [System.IO.Path]::GetFullPath($DistributionRoot)
$JsonRoot = [System.IO.Path]::GetFullPath($JsonRoot)
if (-not $PythonPath) {
    $PythonPath = Join-Path $SourceRoot '.tmp\py311-venv\Scripts\python.exe'
}
$PythonPath = [System.IO.Path]::GetFullPath($PythonPath)

foreach ($requiredDirectory in @($SourceRoot, $DistributionRoot, $JsonRoot)) {
    if (-not (Test-Path -LiteralPath $requiredDirectory -PathType Container)) {
        throw "Required directory is unavailable: $requiredDirectory"
    }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable is unavailable: $PythonPath"
}

Invoke-Checked 'checking Python 3.11 x64' {
    & $PythonPath -c "import struct,sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8 else 1)"
}
Invoke-Checked 'checking source repository' {
    git -C $SourceRoot rev-parse --is-inside-work-tree | Out-Null
}
Invoke-Checked 'checking distribution repository' {
    git -C $DistributionRoot rev-parse --is-inside-work-tree | Out-Null
}

if ($ExpectedRemote) {
    $actualRemote = (git -C $DistributionRoot remote get-url origin).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualRemote -ne $ExpectedRemote) {
        throw "Unexpected GameBalancer origin: $actualRemote"
    }
}

$distributionStatus = @(git -C $DistributionRoot status --short)
if ($distributionStatus.Count -gt 0 -and -not $AllowDirtyDistribution) {
    throw "GameBalancer must be clean before export. Review its existing changes first."
}
$sourceStatus = @(git -C $SourceRoot status --short)
if ($sourceStatus.Count -gt 0) {
    Write-Warning 'IGESS has uncommitted changes; the candidate will contain working-tree code.'
    $sourceStatus | ForEach-Object { Write-Host "  $_" }
}

$manifestPath = Join-Path $DistributionRoot 'operator-manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw "Current operator manifest is unavailable: $manifestPath"
}
$currentManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$currentVersion = [version]$currentManifest.tool_version
$requestedVersion = [version]$Version
if ($requestedVersion -le $currentVersion) {
    throw "Version $Version must be greater than current version $($currentManifest.tool_version)."
}

Push-Location $SourceRoot
try {
    $fishTests = @(
        Get-ChildItem -LiteralPath (Join-Path $SourceRoot 'tests') -File -Filter 'test_fish*.py' |
            Select-Object -ExpandProperty FullName
    )
    $operatorTest = Join-Path $SourceRoot 'tests\test_operator_toolkit.py'
    Invoke-Checked 'running Fish and operator-toolkit regressions' {
        & $PythonPath -m pytest @fishTests $operatorTest -q
    }
    Invoke-Checked "exporting GameBalancer $Version" {
        & $PythonPath -m igess.cli export-operator-toolkit `
            --project (Join-Path $SourceRoot 'projects\fish') `
            --out $DistributionRoot `
            --version $Version `
            --python $PythonPath
    }
} finally {
    Pop-Location
}

$forbidden = @(
    Get-ChildItem -LiteralPath $DistributionRoot -Recurse -Force -File |
        Where-Object {
            $_.FullName -notmatch '[\\/]\.git[\\/]' -and (
                $_.Extension.ToLowerInvariant() -in @('.py', '.pyi', '.map') -or
                $_.FullName -match '[\\/]tests?([\\/]|$)'
            )
        }
)
if ($forbidden.Count -gt 0) {
    throw "Forbidden delivery files found: $($forbidden.FullName -join ', ')"
}
$startScript = Get-Content -LiteralPath (Join-Path $DistributionRoot 'start.bat') -Raw
if ($startScript -notmatch '--bundle "\."' -or $startScript -match '--bundle "%~dp0"') {
    throw 'start.bat does not use the validated relative bundle argument.'
}
$exportedManifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($exportedManifest.tool_version -ne $Version) {
    throw "Exported version mismatch: $($exportedManifest.tool_version)"
}

$inputBefore = @(Get-InputFingerprint -Root $JsonRoot)
$historyRoot = Join-Path $env:LOCALAPPDATA 'IGESS Operator\fish\runs'
$runsBefore = if (Test-Path -LiteralPath $historyRoot) {
    @(Get-ChildItem -LiteralPath $historyRoot -Directory | Select-Object -ExpandProperty Name)
} else {
    @()
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdoutPath = Join-Path $env:TEMP "gamebalancer-release-$stamp.out.log"
$stderrPath = Join-Path $env:TEMP "gamebalancer-release-$stamp.err.log"
$env:PYTHONUNBUFFERED = '1'
$serverProcess = Start-Process -FilePath $PythonPath `
    -ArgumentList @('-m', 'igess.operator_cli', '--bundle', '.', '--no-browser') `
    -WorkingDirectory $DistributionRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath `
    -PassThru

try {
    $url = $null
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        Start-Sleep -Milliseconds 200
        $serverProcess.Refresh()
        $normalOutput = Get-Content -LiteralPath $stdoutPath -Raw -ErrorAction SilentlyContinue
        $errorOutput = Get-Content -LiteralPath $stderrPath -Raw -ErrorAction SilentlyContinue
        if ($null -eq $normalOutput) { $normalOutput = '' }
        if ($null -eq $errorOutput) { $errorOutput = '' }
        $urlMatch = [regex]::Match($normalOutput, 'http://127\.0\.0\.1:(\d+)/')
        if ($urlMatch.Success) {
            $url = $urlMatch.Value
            break
        }
        if ($serverProcess.HasExited) {
            throw "Workbench startup failed: $errorOutput"
        }
    }
    if (-not $url) {
        throw 'Workbench did not provide a loopback URL in time.'
    }
    $loopbackPort = ([uri]$url).Port
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $loopbackPort -ErrorAction SilentlyContinue)
    if (
        $listeners.Count -eq 0 -or
        @($listeners | Where-Object { $_.LocalAddress -ne '127.0.0.1' }).Count -gt 0
    ) {
        throw "Workbench is not exclusively listening on 127.0.0.1:$loopbackPort."
    }

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $homeResponse = Invoke-WebRequest -Uri $url -WebSession $session -UseBasicParsing -TimeoutSec 10
    $csrfMatch = [regex]::Match($homeResponse.Content, 'name="_csrf" value="([^"]+)"')
    if (-not $csrfMatch.Success) {
        throw 'Workbench home page did not contain a CSRF token.'
    }
    $postResponse = Invoke-WebRequest `
        -Uri ($url + 'run') `
        -Method Post `
        -WebSession $session `
        -UseBasicParsing `
        -TimeoutSec 120 `
        -MaximumRedirection 5 `
        -Headers @{ Origin = $url.TrimEnd('/') } `
        -ContentType 'application/x-www-form-urlencoded' `
        -Body @{
            _csrf = $csrfMatch.Groups[1].Value
            tables = $JsonRoot
            scenario = $Scenario
            baseline = ''
        }
    $serverProcess.Refresh()
    if ($serverProcess.HasExited) {
        throw 'Workbench exited while processing the simulation form.'
    }

    $runsAfter = @(Get-ChildItem -LiteralPath $historyRoot -Directory | Select-Object -ExpandProperty Name)
    $runId = @($runsAfter | Where-Object { $_ -notin $runsBefore } | Sort-Object) |
        Select-Object -Last 1
    if (-not $runId) {
        throw 'Workbench did not create a new run record.'
    }
    $runDirectory = Join-Path $historyRoot $runId
    $runStatus = Get-Content -LiteralPath (Join-Path $runDirectory 'run_status.json') -Raw |
        ConvertFrom-Json
    if ($runStatus.status -ne 'success') {
        throw "Smoke run failed: $($runStatus.message)"
    }
    $operatorRun = Get-Content -LiteralPath (Join-Path $runDirectory 'operator_run.json') -Raw |
        ConvertFrom-Json
    if ($operatorRun.tool_version -ne $Version) {
        throw "Run used unexpected tool version: $($operatorRun.tool_version)"
    }
    $runManifest = Get-Content -LiteralPath (Join-Path $runDirectory 'output\run_manifest.json') -Raw |
        ConvertFrom-Json
    if ($runManifest.production_data -ne $true -or $runManifest.matches_production_data -ne $true) {
        throw 'Smoke run was not marked as matching production data.'
    }
    $reportResponse = Invoke-WebRequest `
        -Uri ($url + 'reports/' + $runId + '/index.html') `
        -WebSession $session `
        -UseBasicParsing `
        -TimeoutSec 10
    if ($reportResponse.StatusCode -ne 200) {
        throw "Report returned HTTP $($reportResponse.StatusCode)."
    }
    if ($postResponse.Content -notmatch '运行完成') {
        throw 'Workbench did not show the successful-run notice.'
    }

    $inputAfter = @(Get-InputFingerprint -Root $JsonRoot)
    if (@(Compare-Object -ReferenceObject $inputBefore -DifferenceObject $inputAfter).Count -ne 0) {
        throw 'Production JSON changed during the smoke run.'
    }

    Write-Host "[GameBalancer] E2E run succeeded: $runId"
    Write-Host "[GameBalancer] Report HTTP: $($reportResponse.StatusCode)"
    Write-Host '[GameBalancer] Production JSON unchanged: true'
} finally {
    Stop-ProcessTree -Process $serverProcess
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
}

Write-Host '[GameBalancer] Candidate prepared; review before committing or pushing.'
git -C $DistributionRoot status --short
git -C $DistributionRoot diff --stat
