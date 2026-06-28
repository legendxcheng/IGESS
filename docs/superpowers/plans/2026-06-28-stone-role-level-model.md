# Stone Role Level Model Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first `stone` project model that reads role level and attribute definition workbooks and writes a combat-power curve under `projects/stone`.

**Architecture:** Add a focused `igess.stone_role_level` module for workbook parsing, combat-power calculation, and deterministic artifact writing. Expose it through a small CLI command so agents can run the model without touching IGESS sample projects or stone-oasis source workbooks.

**Tech Stack:** Python 3.12, `openpyxl`, `Decimal`, stdlib JSON/CSV/pathlib, pytest.

---

## Chunk 1: Role Level Model

### Task 1: Add Workbook Parsing And Combat Power Calculation

**Files:**
- Create: `src/igess/stone_role_level.py`
- Test: `tests/test_stone_role_level.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_stone_role_level.py` with a test that loads:

```python
from decimal import Decimal
from pathlib import Path

from igess.stone_role_level import build_role_level_curve


STONE_DATAS = Path(r"E:\stone-oasis\data-tables\Datas")


def test_build_role_level_curve_uses_runtime_power_formula():
    result = build_role_level_curve(
        STONE_DATAS / "RoleLv.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    assert len(result.rows) == 300
    assert result.rows[0].level == 1
    assert result.rows[0].combat_power == Decimal("4310")
    assert result.rows[-1].level == 300
    assert result.rows[-1].combat_power == Decimal("1067640000000000000")
    assert result.rows[-1].cumulative_exp_to_level_start == Decimal("3524129224321067851402093")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'igess.stone_role_level'`.

- [ ] **Step 3: Write minimal implementation**

Implement:

- `BigNumberParts` conversion as `sign * coeff * 10 ** exp`
- marker-row aware column parsing for `RoleLv.xlsx`
- attribute definition loading from `CharacterAttributeDef.xlsx`
- combat-power contribution logic:
  - `ratio_bps`: `value / 10000 * powerValue`
  - all other contributing numeric types: `value * powerValue`
- result dataclasses for rows and model result.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: pass.

### Task 2: Add Artifact Writer

**Files:**
- Modify: `src/igess/stone_role_level.py`
- Test: `tests/test_stone_role_level.py`

- [ ] **Step 1: Write the failing test**

Add a test that writes artifacts to `tmp_path` and asserts:

- `role_level_curve.json` exists
- `role_level_curve.csv` exists
- `role_level_summary.md` exists
- `source_manifest.json` exists
- JSON contains 300 rows
- summary mentions `Level count: 300`

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: fail because artifact writer does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `write_role_level_artifacts(result, output_dir)` that creates the four
files with deterministic ordering and newline handling.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: pass.

### Task 3: Add CLI Command And Generate Stone Baseline

**Files:**
- Modify: `src/igess/cli.py`
- Test: `tests/test_stone_role_level.py`
- Create outputs at runtime: `projects/stone/runs/role_level_baseline/*`

- [ ] **Step 1: Write the failing test**

Add a CLI subprocess test:

```python
import subprocess
import sys


def test_cli_stone_role_level_writes_artifacts(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "igess.cli",
            "stone-role-level",
            "--role-lv",
            str(STONE_DATAS / "RoleLv.xlsx"),
            "--attribute-def",
            str(STONE_DATAS / "CharacterAttributeDef.xlsx"),
            "--out",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Wrote stone role level model" in result.stdout
    assert (tmp_path / "role_level_curve.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: fail because the CLI command is unknown.

- [ ] **Step 3: Write minimal implementation**

Add CLI parser and command branch:

```text
igess stone-role-level --role-lv <RoleLv.xlsx> --attribute-def <CharacterAttributeDef.xlsx> --out <output_dir>
```

- [ ] **Step 4: Run targeted test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

Expected: pass.

- [ ] **Step 5: Generate the requested baseline output**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m igess.cli stone-role-level --role-lv E:\stone-oasis\data-tables\Datas\RoleLv.xlsx --attribute-def E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx --out projects\stone\runs\role_level_baseline
```

Expected: writes the four output artifacts.

### Task 4: Final Verification

**Files:**
- Verify all changed files and generated artifacts.

- [ ] **Step 1: Run targeted tests**

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_role_level.py -q
```

- [ ] **Step 2: Run full test suite**

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest
```

- [ ] **Step 3: Inspect artifacts**

Open:

```text
projects/stone/runs/role_level_baseline/role_level_summary.md
projects/stone/runs/role_level_baseline/source_manifest.json
```

Confirm the summary names the source workbooks and the level count/max level.
