param(
    [string]$Source = "E:\fish-oasis\igess_export"
)

$ErrorActionPreference = "Stop"

$sourceRoot = (Resolve-Path -LiteralPath $Source -ErrorAction Stop).Path
$jsonRoot = Join-Path $sourceRoot "json"
$schemaPath = Join-Path $sourceRoot "python\schema.py"

if (-not (Test-Path -LiteralPath $jsonRoot -PathType Container)) {
    throw "Production snapshot JSON directory is missing: $jsonRoot"
}
if (-not (Test-Path -LiteralPath $schemaPath -PathType Leaf)) {
    throw "Production snapshot Python schema is missing: $schemaPath"
}

$linkPath = Join-Path $PSScriptRoot "production_snapshot"
$existing = Get-Item -Force -LiteralPath $linkPath -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    if (-not ($existing.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to replace a real file or directory: $linkPath"
    }

    $target = @($existing.Target)
    if ($target.Count -ne 1) {
        throw "Production snapshot link has an unexpected target: $linkPath"
    }
    $targetPath = [string]$target[0]
    if (-not [IO.Path]::IsPathRooted($targetPath)) {
        $targetPath = Join-Path $PSScriptRoot $targetPath
    }
    $resolvedTarget = (Resolve-Path -LiteralPath $targetPath -ErrorAction Stop).Path
    if (-not [string]::Equals(
        $resolvedTarget,
        $sourceRoot,
        [StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Production snapshot link already points to: $resolvedTarget"
    }

    Write-Output "Production snapshot link is already ready: $linkPath -> $sourceRoot"
    exit 0
}

$created = New-Item -ItemType SymbolicLink -Path $linkPath -Target $sourceRoot
Write-Output "Created production snapshot link: $($created.FullName) -> $sourceRoot"
