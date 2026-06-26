$ErrorActionPreference = "Stop"

if (Test-Path ".\.venv\Scripts\python.exe") {
  $Python = ".\.venv\Scripts\python.exe"
  $PythonArgs = @()
} else {
  $Python = "py"
  $PythonArgs = @("-3.12")
}

& $Python @PythonArgs -m igess.cli lint `
  --config examples/shelldiver_v0/economy.yaml `
  --tables examples/shelldiver_v0/luban_exports

& $Python @PythonArgs -m igess.cli run `
  --config examples/shelldiver_v0/economy.yaml `
  --tables examples/shelldiver_v0/luban_exports `
  --scenario day_1_progression `
  --out .tmp/sim
