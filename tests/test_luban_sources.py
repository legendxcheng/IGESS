import json
from pathlib import Path
from shutil import copytree

from openpyxl import load_workbook

from igess.loader import ConfigLoader


DATAS = Path("data-tables/Datas")


def test_luban_source_workbooks_have_marker_rows():
    for path in sorted(DATAS.glob("*.xlsx")):
        workbook = load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.active

        assert sheet["A1"].value == "##var", path
        assert sheet["A2"].value == "##", path
        assert sheet["A3"].value == "##type", path
        assert sheet["B1"].value not in (None, ""), path
        assert sheet["B3"].value not in (None, ""), path


def test_luban_registry_lists_runtime_tables():
    workbook = load_workbook(DATAS / "__tables__.xlsx", read_only=True, data_only=True)
    sheet = workbook.active
    registered = {row[1] for row in sheet.iter_rows(min_row=4, values_only=True)}

    assert {
        "resources",
        "generators",
        "upgrades",
        "constants",
        "milestones",
        "prestige_layers",
    }.issubset(registered)


def test_resources_workbook_has_populated_dimension_column():
    workbook = load_workbook(DATAS / "resources.xlsx", read_only=True, data_only=True)
    sheet = workbook.active
    headers = [cell.value for cell in sheet[1]]
    dimension_index = headers.index("dimension") + 1

    dimensions = [
        sheet.cell(row=row, column=dimension_index).value
        for row in range(4, sheet.max_row + 1)
    ]

    assert dimensions
    assert all(str(value).strip() for value in dimensions)


def test_luban_export_rows_carry_source_metadata():
    raw = ConfigLoader.load(
        "examples/shelldiver_v0/economy.yaml",
        "examples/shelldiver_v0/luban_exports",
    )

    fisherman = next(row for row in raw.generators if row.id == "fisherman")

    assert fisherman.source_ref is not None
    assert fisherman.source_ref.table == "generators"
    assert fisherman.source_ref.workbook == "generators.xlsx"
    assert fisherman.source_ref.row == 4


def test_sample_json_exports_include_explicit_source_metadata():
    for path in sorted(Path("examples/shelldiver_v0/luban_exports").glob("*.json")):
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert rows, path
        for row in rows:
            source = row.get("_source")
            assert source is not None, (path, row["id"])
            assert source["table"] == path.stem
            assert source["workbook"] == f"{path.stem}.xlsx"
            assert isinstance(source["row"], int)


def test_loader_trusts_explicit_source_metadata(tmp_path):
    tables = tmp_path / "tables"
    copytree("examples/shelldiver_v0/luban_exports", tables)
    generator_path = tables / "generators.json"
    generators = json.loads(generator_path.read_text(encoding="utf-8"))
    generators[0]["_source"] = {
        "table": "generators",
        "workbook": "generators.xlsx",
        "row": 44,
    }
    generator_path.write_text(
        json.dumps(generators, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    raw = ConfigLoader.load("examples/shelldiver_v0/economy.yaml", tables)
    fisherman = next(row for row in raw.generators if row.id == "fisherman")

    assert fisherman.source_ref is not None
    assert fisherman.source_ref.row == 44
