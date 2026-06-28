# Stone Realm Progression Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `stone` realm progression model that reads `RoleRealm.xlsx` and writes an independent realm combat-power curve under `projects/stone`.

**Architecture:** Reuse the runtime-compatible workbook parsing and combat-power calculation already established by `igess.stone_role_level`. Add a focused realm model API and CLI command that only reports realm combat-power contribution, leaving level and realm combination to a later aggregate simulation.

**Tech Stack:** Python 3.12, `openpyxl`, `igess.numbers.SimNumber`, stdlib JSON/CSV/pathlib, pytest.

---

## Chunk 1: Realm Progression Model

### Task 1: Add Realm Workbook Parsing And Combat Power Calculation

**Files:**
- Modify: `src/igess/stone_role_level.py`
- Test: `tests/test_stone_realm_progression.py`

- [ ] **Step 1: Write the failing test**

Create a test that loads:

```python
from pathlib import Path

from igess.numbers import SimNumber
from igess.stone_role_level import build_realm_progression_curve

STONE_DATAS = Path(r"E:\stone-oasis\data-tables\Datas")


def test_build_realm_progression_curve_keeps_realm_power_independent():
    result = build_realm_progression_curve(
        STONE_DATAS / "RoleRealm.xlsx",
        STONE_DATAS / "CharacterAttributeDef.xlsx",
    )

    assert len(result.rows) == 31
    assert result.rows[0].realm_id == 0
    assert result.rows[0].realm_name == "凡人"
    assert result.rows[0].level_cap == 10
    assert result.rows[0].realm_combat_power == SimNumber.zero()
    assert result.rows[1].realm_combat_power == SimNumber.parse("360000")
    assert result.rows[-2].realm_combat_power == SimNumber.parse("5400000000000000000")
    assert result.rows[-1].realm_combat_power == SimNumber.parse("3600000000000000000")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: fail because `build_realm_progression_curve` does not exist.

- [ ] **Step 3: Write minimal implementation**

Add dataclasses and helpers for realm rows:

- parse marker rows from `RoleRealm.xlsx`
- convert `BigNumberParts` with `SimNumber`
- include only attribute-definition keys in combat-power calculation
- preserve `lvl_up` as `level_cap` metadata
- calculate `realm_combat_power_delta` between adjacent realm rows

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: pass.

### Task 2: Add Artifact Writer

**Files:**
- Modify: `src/igess/stone_role_level.py`
- Test: `tests/test_stone_realm_progression.py`

- [ ] **Step 1: Write the failing test**

Add a test that writes artifacts to `tmp_path` and asserts:

- `realm_progression_curve.json` exists
- `realm_progression_curve.csv` exists
- `realm_progression_summary.md` exists
- `source_manifest.json` exists
- JSON contains 31 rows
- JSON rows do not contain level combat-power fields
- manifest uses `bignum_log`

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: fail because artifact writer does not exist.

- [ ] **Step 3: Write minimal implementation**

Add `write_realm_progression_artifacts(result, output_dir)` that creates the four
files with deterministic ordering and newline handling.

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: pass.

### Task 3: Add CLI Command And Generate Stone Baseline

**Files:**
- Modify: `src/igess/cli.py`
- Test: `tests/test_stone_realm_progression.py`
- Create outputs at runtime: `projects/stone/runs/realm_progression_baseline/*`

- [ ] **Step 1: Write the failing test**

Add a CLI subprocess test for:

```text
igess stone-realm-progression --role-realm <RoleRealm.xlsx> --attribute-def <CharacterAttributeDef.xlsx> --out <output_dir>
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: fail because the CLI command is unknown.

- [ ] **Step 3: Write minimal implementation**

Add CLI parser and command branch for `stone-realm-progression`.

- [ ] **Step 4: Run targeted test to verify it passes**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py -q
```

Expected: pass.

- [ ] **Step 5: Generate the requested baseline output**

Run:

```powershell
E:\IGESS\.venv\Scripts\python.exe -m igess.cli stone-realm-progression --role-realm E:\stone-oasis\data-tables\Datas\RoleRealm.xlsx --attribute-def E:\stone-oasis\data-tables\Datas\CharacterAttributeDef.xlsx --out projects\stone\runs\realm_progression_baseline
```

Expected: writes the four output artifacts.

### Task 4: Final Verification

**Files:**
- Verify all changed files and generated artifacts.

- [ ] **Step 1: Run targeted tests**

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest tests\test_stone_realm_progression.py tests\test_stone_role_level.py -q
```

- [ ] **Step 2: Run full test suite**

```powershell
E:\IGESS\.venv\Scripts\python.exe -m pytest
```

- [ ] **Step 3: Inspect artifacts**

Open:

```text
projects/stone/runs/realm_progression_baseline/realm_progression_summary.md
projects/stone/runs/realm_progression_baseline/source_manifest.json
```

Confirm the summary names the source workbooks, uses `SimNumber`, and says level
combat power is not included.
