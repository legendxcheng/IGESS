from pathlib import Path

from openpyxl import load_workbook


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
