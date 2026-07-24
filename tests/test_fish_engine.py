from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

import pytest
import yaml

from igess.compare import compare_runs
from igess.engines import EngineRegistry
from igess.fish_data import (
    FISH_REQUIRED_TABLES,
    FishDataError,
    FishDataLoader,
    FishDataOverride,
    GeneratedLubanProvider,
)
from igess.fish_simulator import FishEconomySimulator
from igess.fish_state import FishInstance, PlayerState, TrashStock
from igess.workflows import WorkflowService


CONFIG = Path("examples/shelldiver_v0/economy.yaml")
TABLES = Path("examples/shelldiver_v0/luban_exports")


@dataclass(frozen=True)
class _FishRandomPoolRow:
    id: int
    startLuck: int


class _GeneratedLubanFixture:
    """Stand-in for generated Luban classes; it never decodes JSON itself."""

    def load_tables(self, data_root: Path, required_tables: tuple[str, ...]):
        assert data_root.is_dir()
        return {
            name: (_FishRandomPoolRow(id=1, startLuck=1),)
            for name in required_tables
        }

    def apply_overrides(self, tables, assignments):
        updated = {name: tuple(rows) for name, rows in tables.items()}
        details = []
        for assignment in assignments:
            path, encoded = assignment.split("=", 1)
            table, row_id, field = path.split(".")
            assert row_id == "1"
            assert field == "startLuck"
            row = updated[table][0]
            value = int(encoded)
            updated[table] = (replace(row, startLuck=value),)
            details.append(FishDataOverride(path, row.startLuck, value))
        return updated, details


def _generated_to_plain(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_generated_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _generated_to_plain(item) for key, item in value.items()
        }
    return {
        key: _generated_to_plain(item)
        for key, item in vars(value).items()
        if not key.startswith("_")
    }


def _fish_config(tmp_path: Path, data_root: Path) -> Path:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    payload["model"]["engine_id"] = "fish"
    payload["engine"] = {
        "data_root": str(data_root),
        "production_data": False,
        "strategy_id": "fixture_smoke",
        "required_tables": ["tbfishrandompool"],
    }
    payload["scenarios"]["day_1_progression"]["profiles"] = ["casual"]
    path = tmp_path / "fish.yaml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def test_fish_data_loader_delegates_decoding_and_hashes_original_bytes(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    source = data_root / "tbfishrandompool.json"
    source.write_bytes(b"not JSON; generated provider owns decoding")

    snapshot = FishDataLoader(_GeneratedLubanFixture()).load(
        data_root,
        production_data=False,
        required_tables=["tbfishrandompool"],
        overrides=["tbfishrandompool.1.startLuck=2"],
    )

    assert snapshot.table("tbfishrandompool")[0].startLuck == 2
    assert snapshot.files[0].sha256 == (
        "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    )
    assert snapshot.overrides[0].manifest_entry() == {
        "path": "tbfishrandompool.1.startLuck",
        "original": 1,
        "value": 2,
    }


def test_fish_data_loader_requires_generated_luban_provider(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()

    with pytest.raises(FishDataError, match="generated Python loader"):
        FishDataLoader(None).load(
            data_root,
            production_data=False,
            required_tables=["tbfishrandompool"],
        )


@pytest.mark.external_data
def test_generated_luban_provider_loads_current_fish_export() -> None:
    snapshot = FishDataLoader(
        GeneratedLubanProvider(
            "E:/fish-oasis/igess_export/python/schema.py"
        )
    ).load(
        "E:/fish-oasis/igess_export/json",
        production_data=True,
        required_tables=FISH_REQUIRED_TABLES,
    )

    first_pool = snapshot.table("tbfishrandompool")[0]
    assert first_pool.id == 1
    assert first_pool.strengthUpperBound.digits == "5"
    assert first_pool.startLuck == 1
    assert first_pool.endLuck == 3
    first_trash_pool = snapshot.table("tbtrashrandompool")[0]
    assert first_trash_pool.powerUpperBound.digits == "5"
    assert first_trash_pool.startLuck == 1
    assert first_trash_pool.endLuck == 3
    fish_rows = snapshot.table("tbfish")
    assert len(fish_rows) == 121
    assert fish_rows[0].Denominator.digits == "1"
    assert fish_rows[-1].Denominator.digits == "10000000"
    assert all(
        type(row.weight) is int and row.weight > 0 for row in fish_rows
    )
    assert snapshot.loader_files[0].path.name == "schema.py"
    for table_name in FISH_REQUIRED_TABLES:
        export_path = Path(
            f"E:/fish-oasis/igess_export/json/{table_name}.json"
        )
        source_rows = json.loads(export_path.read_text(encoding="utf-8"))
        actual_rows = [
            _generated_to_plain(row) for row in snapshot.table(table_name)
        ]
        assert actual_rows == source_rows


def test_fish_workflow_writes_registry_artifacts_checkpoint_and_compare(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "tbfishrandompool.json").write_text(
        "decoded by generated Luban code",
        encoding="utf-8",
    )
    config = _fish_config(tmp_path, data_root)
    service = WorkflowService(
        project_root=".",
        runs_root=tmp_path / "runs",
        engine_registry=EngineRegistry.standard(
            fish_luban_provider=_GeneratedLubanFixture()
        ),
    )

    first = service.run_scenario(
        config,
        TABLES,
        "day_1_progression",
        overrides=("tbfishrandompool.1.startLuck=2",),
    )

    assert first.status == "success", first.message
    assert first.engine_id == "fish"
    assert first.model_digest is not None
    checkpoint = first.output_dir / "final_checkpoint.json"
    assert checkpoint.is_file()
    manifest = json.loads(
        (first.output_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["engine_id"] == "fish"
    assert manifest["data_loader"] == "luban_generated_python"
    assert manifest["model_digest"] == first.model_digest
    assert manifest["production_data"] is False
    assert manifest["overrides"] == ["tbfishrandompool.1.startLuck=2"]
    assert manifest["artifacts"][-1] == "final_checkpoint.json"
    assert first.report_index.is_file()

    second = service.run_scenario(
        config,
        TABLES,
        "day_1_progression",
        checkpoint_input=checkpoint,
        overrides=("tbfishrandompool.1.startLuck=2",),
    )
    assert second.status == "success"
    assert second.model_digest == first.model_digest

    comparison = tmp_path / "comparison"
    index = compare_runs(first.output_dir, second.output_dir, comparison)
    assert index.is_file()
    assert (comparison / "comparison.json").is_file()


def test_authoring_workflow_dispatches_fish_engine(tmp_path: Path) -> None:
    project = tmp_path / "fish-project"
    project.mkdir()
    shutil.copytree("projects/fish/Datas", project / "Datas")
    shutil.copytree("projects/fish/luban_exports", project / "luban_exports")
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "tbfishrandompool.json").write_text(
        "loaded by generated code",
        encoding="utf-8",
    )
    payload = yaml.safe_load(
        Path("projects/fish/economy.yaml").read_text(encoding="utf-8")
    )
    payload["engine"].pop("active_throw", None)
    payload["engine"].update(
        {
            "data_root": str(data_root),
            "production_data": False,
            "required_tables": ["tbfishrandompool"],
        }
    )
    (project / "economy.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    service = WorkflowService(
        project,
        runs_root=tmp_path / "authoring-runs",
        engine_registry=EngineRegistry.standard(
            fish_luban_provider=_GeneratedLubanFixture()
        ),
    )

    response = service.run_authoring_scenario("smoke")

    assert response.ok is True
    assert response.result["engine_id"] == "fish"
    record = service.list_runs()[-1]
    assert record.engine_id == "fish"
    assert record.model_digest == response.result["model_digest"]
    assert (record.output_dir / "final_checkpoint.json").is_file()

    payload["engine"].pop("python_schema", None)
    (project / "economy.yaml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    blocked = WorkflowService(
        project,
        runs_root=tmp_path / "blocked-runs",
    ).run_authoring_scenario("smoke")
    assert blocked.ok is False
    assert blocked.code == "fish_data_unavailable"
    assert "engine.python_schema" in blocked.message


def test_active_throw_checkpoint_progress_must_be_consistent() -> None:
    empty = PlayerState.new(initial_torpedo_id=1)

    with pytest.raises(ValueError, match="progress"):
        FishEconomySimulator._validate_active_throw_checkpoint(
            empty,
            1,
            1,
            {},
            1,
        )

    with pytest.raises(ValueError, match="progress"):
        FishEconomySimulator._validate_active_throw_checkpoint(
            empty,
            1,
            1,
            {"active_throw_resolved": 1},
            1,
        )

    with pytest.raises(ValueError, match="non-negative"):
        FishEconomySimulator._validate_active_throw_checkpoint(
            empty,
            0,
            0,
            {"active_throw_resolved": -1},
            1,
        )

    committed = PlayerState.new(initial_torpedo_id=1)
    committed.fish.items = [
        FishInstance(
            instance_id=1,
            fish_id=1,
            mutation_id=1,
            level=1,
            weight_gram=1,
        )
    ]
    committed.fish.next_instance_id = 2
    committed.trash_man.processing.stocks = [
        TrashStock(trash_id=1, count=1)
    ]
    committed.statistics.total_throws = 1
    committed.statistics.total_fish_caught = 1
    committed.production.last_settled_at = 1
    committed.meta.revision = 2
    committed.validate()

    with pytest.raises(ValueError, match="progress"):
        FishEconomySimulator._validate_active_throw_checkpoint(
            committed,
            1,
            1,
            {},
            1,
        )

    FishEconomySimulator._validate_active_throw_checkpoint(
        committed,
        1,
        1,
        {"active_throw_resolved": 1, "fish_hall_settled": 1},
        1,
    )


@pytest.mark.external_data
def test_production_workflow_records_one_resolved_throw(tmp_path: Path) -> None:
    service = WorkflowService(
        "projects/fish",
        runs_root=tmp_path / "runs",
    )

    response = service.run_authoring_scenario("smoke")

    assert response.ok is True, response.message
    record = service.list_runs()[-1]
    events = json.loads(
        (record.output_dir / "events.json").read_text(encoding="utf-8")
    )
    throw_events = [
        event for event in events if event["kind"] == "fish_throw_resolved"
    ]
    assert len(throw_events) == 10
    assert [event["time_seconds"] for event in throw_events] == list(
        range(1, 11)
    )
    assert [event["details"]["throw_id"] for event in throw_events] == [
        str(index) for index in range(10)
    ]
    details = throw_events[0]["details"]
    assert details["throw_id"] == "0"
    assert details["torpedo_id"] == "1"
    assert details["fish_id"]
    assert details["trash_id"]
    production_fish = json.loads(
        Path("E:/fish-oasis/igess_export/json/tbfish.json").read_text(
            encoding="utf-8"
        )
    )
    expected_weight = next(
        row["weight"]
        for row in production_fish
        if row["id"] == int(details["fish_id"])
    )
    assert details["fish_weight_gram"] == str(expected_weight)
    assert details["reward_application"] == "applied_to_player_state"
    assert details["fish_instance_id"] == "1"
    assert details["trash_stock_count"] == "1"
    assert details["player_state_revision"] == "2"
    assert details["strength_source"] == "player_state_snapshot"
    assert details["fish_hall_capacity_after_throw"] == "10"
    assert details["fish_hall_policy_after_throw"] == "fixed_max_income"
    assert details["fish_hall_tie_breaker_after_throw"] == (
        "instance_id_ascending"
    )
    assert details["fish_hall_deployed_instance_ids_after_throw"] == "[1]"
    assert details["fish_hall_income_per_second_before_throw"] == "0"
    assert details["fish_hall_money_added"] == "0"
    assert details["trash_processing_queue_policy"] == "trash_id_ascending"
    assert details["trash_material_added"] == "0"
    assert "base_money_per_second*1.25^(level-1)" in details[
        "fish_hall_formula_trace_after_throw"
    ]
    assert "collection_key" not in details

    checkpoint = json.loads(
        (record.output_dir / "final_checkpoint.json").read_text(
            encoding="utf-8"
        )
    )
    assert checkpoint["next_throw_id"] == 10
    assert checkpoint["event_counters"]["active_throw_resolved"] == 10
    assert checkpoint["event_counters"]["fish_hall_settled"] == 10
    assert checkpoint["engine_state"]["torpedo"] == {
        "ownedIds": [1],
        "selectedId": 1,
    }
    fish_state = checkpoint["engine_state"]["fish"]
    assert fish_state["nextInstanceId"] == 11
    assert len(fish_state["items"]) == 10
    deployed_ids = json.loads(
        throw_events[-1]["details"][
            "fish_hall_deployed_instance_ids_after_throw"
        ]
    )
    deployed_slots = {
        instance_id: slot
        for slot, instance_id in enumerate(deployed_ids, start=1)
    }
    for index, (item, event) in enumerate(
        zip(fish_state["items"], throw_events, strict=True),
        start=1,
    ):
        event_details = event["details"]
        assert item == {
            "instanceId": index,
            "fishId": int(event_details["fish_id"]),
            "mutationId": int(event_details["fish_mutation_id"]),
            "level": 1,
            "weightGram": int(event_details["fish_weight_gram"]),
            "hallSlot": deployed_slots.get(index, 0),
        }
    trash_stocks = checkpoint["engine_state"]["trashMan"]["processing"][
        "stocks"
    ]
    assert sum(stock["count"] for stock in trash_stocks) == 10
    processing = checkpoint["engine_state"]["trashMan"]["processing"]
    assert processing["activeTrashId"] == int(
        throw_events[0]["details"]["trash_id"]
    )
    assert processing["activeProgressSeconds"] == 9
    assert checkpoint["engine_state"]["trashMan"]["realmId"] == 1
    assert checkpoint["engine_state"]["trashMan"]["highestRealmId"] == 1
    assert checkpoint["engine_state"]["wallet"]["material"]["sign"] == 1
    assert checkpoint["engine_runtime_state"] == {
        "version": 1,
        "trash_processing": {
            "version": 1,
            "progress_remainder": "0",
        },
    }
    assert checkpoint["engine_state"]["statistics"]["totalThrows"] == 10
    assert checkpoint["engine_state"]["statistics"][
        "totalFishCaught"
    ] == 10
    assert checkpoint["engine_state"]["meta"]["revision"] == 20
    assert checkpoint["engine_state"]["production"]["lastSettledAt"] == 10
    assert checkpoint["engine_state"]["wallet"]["money"] == {
        "sign": 1,
        "coeff": 9800,
        "exp": -2,
    }
    assert checkpoint["engine_state"]["wallet"]["strength"] == {
        "sign": 1,
        "coeff": 5000,
        "exp": -2,
    }

    timeline = json.loads(
        (record.output_dir / "timeline.json").read_text(encoding="utf-8")
    )
    assert timeline[0]["total_cps"] == "0"
    assert timeline[-1]["total_cps"] == "21"
    assert timeline[-1]["resources"]["money"] == "9800E-2"
    assert timeline[-1]["resources"]["material"] != "0"

    manifest = json.loads(
        (record.output_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["production_data"] is True
    assert manifest["strategy"]["id"] == "production_active_throw_loop"
    assert manifest["strategy"]["parameters"]["active_throw"] == {
        "bonus_base_luck": "1",
        "initial_strength": "50",
        "interval_seconds": 1,
        "max_bonus_layers": 4,
        "regular_luck_multiplier": "1",
    }
    assert manifest["strategy"]["parameters"]["trash_processing"] == {
        "formula": "fixed_base_work_continuous_yield_v1",
        "queue_policy": "trash_id_ascending",
        "fractional_progress": "engine_runtime_state",
        "rebirth_mapping": (
            "completed_count_0_is_1x;"
            "completed_count_n_uses_table_id_n_minus_1"
        ),
    }

    resumed = service.run_authoring_scenario(
        "smoke",
        checkpoint_input=record.output_dir / "final_checkpoint.json",
    )
    assert resumed.ok is True, resumed.message
    resumed_record = service.list_runs()[-1]
    resumed_events = json.loads(
        (resumed_record.output_dir / "events.json").read_text(
            encoding="utf-8"
        )
    )
    assert not any(
        event["kind"] == "fish_throw_resolved" for event in resumed_events
    )
    resumed_checkpoint = json.loads(
        (resumed_record.output_dir / "final_checkpoint.json").read_text(
            encoding="utf-8"
        )
    )
    assert resumed_checkpoint["next_throw_id"] == 10
    assert resumed_checkpoint["root_random_seed"] == 20260626
    assert resumed_checkpoint["engine_state"] == checkpoint["engine_state"]
