from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .numbers import SimNumber
from .schema import (
    ConstantRow,
    FormulaDef,
    GeneratorRow,
    MilestoneRow,
    ModelSettings,
    PlayerProfile,
    PrestigeLayerRow,
    RawConfig,
    ResourceRow,
    Rules,
    Scenario,
    UpgradeRow,
)


class ConfigLoader:
    @classmethod
    def load(cls, config_path: str | Path, tables_dir: str | Path) -> RawConfig:
        config_path = Path(config_path)
        tables_dir = Path(tables_dir)
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        rules = cls._load_rules(data)
        return RawConfig(
            rules=rules,
            resources=cls._load_table(tables_dir / "resources.json", ResourceRow),
            generators=cls._load_table(tables_dir / "generators.json", GeneratorRow),
            upgrades=cls._load_table(tables_dir / "upgrades.json", UpgradeRow),
            constants=cls._load_table(tables_dir / "constants.json", ConstantRow),
            milestones=cls._load_optional_table(tables_dir / "milestones.json", MilestoneRow),
            prestige_layers=cls._load_optional_table(
                tables_dir / "prestige_layers.json", PrestigeLayerRow
            ),
        )

    @classmethod
    def _load_rules(cls, data: dict[str, Any]) -> Rules:
        formulas = {
            formula_id: FormulaDef(args=list(value["args"]), expr=str(value["expr"]))
            for formula_id, value in sorted(data.get("formulas", {}).items())
        }
        modifier_types = {
            key: str(value["stage"]) for key, value in sorted(data.get("modifier_types", {}).items())
        }
        profiles = {
            profile_id: PlayerProfile(
                id=profile_id,
                source_efficiency={
                    key: SimNumber.parse(value)
                    for key, value in sorted(profile_data["source_efficiency"].items())
                },
                behavior_policy=str(profile_data["behavior_policy"]),
                session_pattern=str(profile_data["session_pattern"]),
                prestige_policy=str(profile_data["prestige_policy"]),
            )
            for profile_id, profile_data in sorted(data.get("player_profiles", {}).items())
        }
        scenarios = {
            scenario_id: Scenario(
                id=scenario_id,
                duration_hours=float(scenario_data["duration_hours"]),
                profiles=list(scenario_data["profiles"]),
                start_state=str(scenario_data["start_state"]),
                record_interval_seconds=int(scenario_data["record_interval_seconds"]),
                outputs=list(scenario_data.get("outputs", [])),
            )
            for scenario_id, scenario_data in sorted(data.get("scenarios", {}).items())
        }
        return Rules(
            model=ModelSettings(
                id=str(data["model"]["id"]),
                tick_seconds=int(data["model"]["tick_seconds"]),
                number_backend=str(data["model"]["number_backend"]),
                random_seed=data["model"].get("random_seed"),
            ),
            formulas=formulas,
            generator_types=dict(sorted(data.get("generator_types", {}).items())),
            source_types=dict(sorted(data.get("source_types", {}).items())),
            modifier_pipeline=list(data.get("modifier_pipeline", {}).get("order", [])),
            modifier_types=modifier_types,
            behavior_policies=dict(sorted(data.get("behavior_policies", {}).items())),
            session_patterns=dict(sorted(data.get("session_patterns", {}).items())),
            player_profiles=profiles,
            scenarios=scenarios,
        )

    @classmethod
    def _load_table(cls, path: Path, row_type: type) -> list:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [row_type(**row) for row in sorted(rows, key=lambda item: item["id"])]

    @classmethod
    def _load_optional_table(cls, path: Path, row_type: type) -> list:
        if not path.exists():
            return []
        return cls._load_table(path, row_type)
