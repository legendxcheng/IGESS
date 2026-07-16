import json
from pathlib import Path
from shutil import copytree

import yaml


CONFIG = "examples/shelldiver_v0/economy.yaml"
TABLES = "examples/shelldiver_v0/luban_exports"


def write_activity_fixture(tmp_path):
    tables = tmp_path / "tables"
    copytree(TABLES, tables)
    (tables / "activities.json").write_text(
        json.dumps(
            [
                {
                    "id": "dive",
                    "name": "Dive",
                    "source_type": "active",
                    "unlock_condition": "always",
                    "_source": {"table": "activities", "workbook": "activities.xlsx", "row": 4},
                },
                {
                    "id": "sort_shells",
                    "name": "Sort Shells",
                    "source_type": "active",
                    "unlock_condition": "owned(fisherman) >= 1",
                    "_source": {"table": "activities", "workbook": "activities.xlsx", "row": 5},
                },
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (tables / "activity_outputs.json").write_text(
        json.dumps(
            [
                {
                    "id": "dive_fish",
                    "activity_id": "dive",
                    "output_resource": "fish",
                    "amount_per_second": "10",
                    "_source": {
                        "table": "activity_outputs",
                        "workbook": "activity_outputs.xlsx",
                        "row": 4,
                    },
                },
                {
                    "id": "dive_prestige",
                    "activity_id": "dive",
                    "output_resource": "prestige_point",
                    "amount_per_second": "2",
                    "_source": {
                        "table": "activity_outputs",
                        "workbook": "activity_outputs.xlsx",
                        "row": 5,
                    },
                },
                {
                    "id": "sort_shells_fish",
                    "activity_id": "sort_shells",
                    "output_resource": "fish",
                    "amount_per_second": "2",
                    "_source": {
                        "table": "activity_outputs",
                        "workbook": "activity_outputs.xlsx",
                        "row": 6,
                    },
                },
            ],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    config_data = yaml.safe_load(Path(CONFIG).read_text(encoding="utf-8"))
    config_data["player_profiles"]["casual"]["activity_weights"] = {
        "dive": "3",
        "sort_shells": "1",
    }
    config_data["player_profiles"]["optimizer"]["activity_weights"] = {
        "dive": "1",
        "sort_shells": "3",
    }
    config_data["player_profiles"]["explorer"]["activity_weights"] = {
        "dive": "1",
    }
    config = tmp_path / "economy.yaml"
    config.write_text(
        yaml.safe_dump(config_data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return config, tables
