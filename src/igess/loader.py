from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .numbers import SimNumber
from .schema import (
    ActivityOutputRow,
    ActivityRow,
    ConstantRow,
    FormulaDef,
    GeneratorRow,
    MilestoneRow,
    ModelSettings,
    PlayerProfile,
    PrestigeLayerRow,
    RawConfig,
    ResourceRow,
    RngRarity,
    RngScenario,
    RngTable,
    Rules,
    Scenario,
    SourceRef,
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
            activities=cls._load_optional_table(tables_dir / "activities.json", ActivityRow),
            activity_outputs=cls._load_optional_table(
                tables_dir / "activity_outputs.json", ActivityOutputRow
            ),
            upgrades=cls._load_table(tables_dir / "upgrades.json", UpgradeRow),
            constants=cls._load_table(tables_dir / "constants.json", ConstantRow),
            milestones=cls._load_optional_table(tables_dir / "milestones.json", MilestoneRow),
            prestige_layers=cls._load_optional_table(
                tables_dir / "prestige_layers.json", PrestigeLayerRow
            ),
        )

    @classmethod
    def load_rules_only(cls, config_path: str | Path) -> RawConfig:
        config_path = Path(config_path)
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        return RawConfig(
            rules=cls._load_rules(data),
            resources=[],
            generators=[],
            activities=[],
            activity_outputs=[],
            upgrades=[],
            constants=[],
            milestones=[],
            prestige_layers=[],
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
                activity_weights={
                    key: SimNumber.parse(value)
                    for key, value in sorted(profile_data.get("activity_weights", {}).items())
                },
                behavior_policy=str(profile_data["behavior_policy"]),
                session_pattern=str(profile_data["session_pattern"]),
                prestige_policy=str(profile_data["prestige_policy"]),
                luck=SimNumber.parse(profile_data.get("luck", 1)),
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
                time_mode=str(scenario_data.get("time_mode", "tick")),
            )
            for scenario_id, scenario_data in sorted(data.get("scenarios", {}).items())
        }
        rng_tables = {
            table_id: RngTable(
                id=table_id,
                algorithm=str(table_data["algorithm"]),
                rarities=sorted(
                    (
                        RngRarity(id=str(rarity_id), denominator=SimNumber.parse(denominator))
                        for rarity_id, denominator in table_data.get("rarities", {}).items()
                    ),
                    key=lambda rarity: rarity.denominator,
                ),
            )
            for table_id, table_data in sorted(data.get("rng_tables", {}).items())
        }
        rng_scenarios = {
            scenario_id: RngScenario(
                id=scenario_id,
                table=str(scenario_data["table"]),
                rolls=int(scenario_data["rolls"]),
                trials=int(scenario_data["trials"]),
                profiles=list(scenario_data["profiles"]),
                event_threshold=(
                    str(scenario_data["event_threshold"])
                    if scenario_data.get("event_threshold") is not None
                    else None
                ),
            )
            for scenario_id, scenario_data in sorted(data.get("rng_scenarios", {}).items())
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
            rng_tables=rng_tables,
            rng_scenarios=rng_scenarios,
            regression_gates=dict(sorted(data.get("regression_gates", {}).items())),
        )

    @classmethod
    def _load_table(cls, path: Path, row_type: type) -> list:
        rows = json.loads(path.read_text(encoding="utf-8"))
        loaded = []
        for row in rows:
            source = row.pop("_source", None)
            if source is None:
                raise ValueError(f"{path} row '{row.get('id')}' is missing _source metadata")
            loaded.append(
                row_type(
                    **row,
                    source_ref=SourceRef(
                        table=str(source["table"]),
                        workbook=str(source["workbook"]),
                        row=int(source["row"]),
                    ),
                )
            )
        return sorted(loaded, key=lambda item: item.id)

    @classmethod
    def _load_optional_table(cls, path: Path, row_type: type) -> list:
        if not path.exists():
            return []
        return cls._load_table(path, row_type)
