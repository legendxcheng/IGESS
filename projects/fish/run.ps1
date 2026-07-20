$ErrorActionPreference = "Stop"

& igess model status --project $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

& igess model simulate --project $PSScriptRoot --scenario smoke
exit $LASTEXITCODE
