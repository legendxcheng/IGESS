"""Opt-in Fish engine: schedule player intents, execute source Lua rules."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointCodec, SimulationCheckpoint
from .engines import EngineAdapterError, EngineExecution, PreparedEngine
from .fish_source_eggs import EggObservations
from .fish_source_tides import TIDE_POLICY, TideObservations
from .fish_source_guns import GunMilestones, choose_gun_action
from .fish_source_runtime import (
    FishSourceRejection,
    FishSourceRuntime,
    FishSourceRuntimeError,
    data_snapshot_digest,
    source_code_digest,
    source_runtime_entry,
)
from .fish_source_income import SourceIncome
from .schema import EconomyModel, Event, SimulationResult, TimelineRow

_BEHAVIORS = frozenset({
    "manual_throw", "sell_fish", "upgrade_fish", "upgrade_fish_hall",
    "purchase_torpedo", "synthesize_barbell", "exercise_barbell",
    "strength_rebirth", "trash_man_rebirth", "fund_trash_man_breakthrough",
})
_SOURCE_POLICY = "source_priority_v1"
_MAX_REPLAY_BYTES = 256 * 1024 * 1024
_REQUIRED_OPERATIONS = frozenset({
    "query", "query_actions", "query_codex", "claim_fish_reward", "advance", "checkpoint", "restore",
    "claim_gun_reward", "equip_gun", "grant_random_egg", "settle_eggs", "start_tide", "complete_tide",
    "go_online", "go_offline", "claim_offline_reward", "collect_slot",
    "deploy_fish", "prepare_throw", "begin_throw_flight",
    "select_throw_landing", "finalize_throw_landing", "complete_throw",
    "sell_fish", "upgrade_fish", "upgrade_hall", "purchase_torpedo",
    "synthesize_barbell", "start_exercise", "stop_exercise",
    "start_breakthrough", "rebirth_strength", "rebirth_trash_man",
})


def _pack_session(session: dict[str, Any]) -> dict[str, str]:
    contents = json.dumps(session, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {
        "codec": "zlib-json-v1",
        "data": base64.b64encode(zlib.compress(contents, level=6)).decode("ascii"),
    }


def _unpack_session(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("codec") != "zlib-json-v1" or not isinstance(payload.get("data"), str):
        raise EngineAdapterError("fish_source_checkpoint_invalid", "Unsupported source session format")
    try:
        compressed = base64.b64decode(payload["data"], validate=True)
        decoder = zlib.decompressobj()
        contents = decoder.decompress(compressed, _MAX_REPLAY_BYTES + 1)
        if len(contents) > _MAX_REPLAY_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError("Oversized or trailing source session data")
        session = json.loads(contents)
    except (ValueError, binascii.Error, zlib.error, UnicodeError) as error:
        raise EngineAdapterError("fish_source_checkpoint_invalid", str(error)) from error
    if not isinstance(session, dict):
        raise EngineAdapterError("fish_source_checkpoint_invalid", "Source session must be an object")
    return session


def _decimal(dto: Mapping[str, Any]) -> Decimal:
    return Decimal(str(dto["coeff"])).scaleb(int(dto["exp"])) * int(dto["sign"])


def _number(dto: Mapping[str, Any]) -> str:
    return str(_decimal(dto))


def _affords(wallet: Mapping[str, Any], quote: Mapping[str, Any]) -> bool:
    return _decimal(wallet[quote["resource"]]) >= _decimal(quote["cost"])


def _integration_code_digest() -> str:
    digest = hashlib.sha256()
    for name in ("fish_source_engine.py", "fish_source_runtime.py", "fish_source_reports.py", "fish_source_income.py", "fish_source_guns.py", "fish_source_eggs.py", "fish_source_tides.py"):
        path = Path(__file__).parent / name
        if not path.is_file():
            path = path.with_suffix(".pyc")
        contents = path.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


@dataclass(frozen=True)
class _SourceInputs:
    project_root: Path
    data_root: Path
    code_digest: str
    data_digest: str
    integration_digest: str
    lua_executable: str
    fishing_area: bool
    landing_distance_cm: int | None
    collect_interval_seconds: int
    idle_seconds: int
    fast_advance: bool
    sampling_time_basis: str
    room_origin_seconds: int


class FishSourceEngineAdapter:
    engine_id = "fish_source"

    def prepare(
        self,
        model: EconomyModel,
        *,
        source_digest: str,
        base_dir: Path,
        overrides: Sequence[str] = (),
        selected_data_root: Path | None = None,
    ) -> PreparedEngine:
        settings = model.engine_settings
        if overrides:
            raise EngineAdapterError(
                "fish_source_overrides_unsupported",
                "Source runs consume the selected exported tables; use authoring exports for edits.",
            )
        if "active_throw" in settings or "behavior_scheduler" in settings:
            raise EngineAdapterError(
                "fish_source_legacy_settings",
                "Remove Python Fish active_throw/behavior_scheduler assumptions from this source-engine config.",
            )
        source_settings = settings.get("source_runtime")
        if not isinstance(source_settings, dict):
            raise EngineAdapterError("fish_source_config_missing", "engine.source_runtime is required")
        root_value = source_settings.get("project_root")
        if not isinstance(root_value, str) or not root_value:
            raise EngineAdapterError("fish_source_root_missing", "engine.source_runtime.project_root is required")
        project_root = Path(root_value)
        if not project_root.is_absolute():
            project_root = base_dir / project_root
        if not project_root.is_dir():
            raise EngineAdapterError("fish_source_root_missing", str(project_root))
        project_root = project_root.resolve(strict=True)
        data_value = source_settings.get("data_root")
        if data_value is not None:
            if not isinstance(data_value, str) or not data_value:
                raise EngineAdapterError("fish_source_data_missing", "Invalid source export root")
            data_root = Path(data_value)
            if not data_root.is_absolute():
                data_root = base_dir / data_root
        elif selected_data_root is not None:
            data_root = Path(selected_data_root)
        else:
            raise EngineAdapterError("fish_source_data_missing", "Selected Fish export root is required")
        if not data_root.is_dir():
            raise EngineAdapterError("fish_source_data_missing", str(data_root))
        data_root = data_root.resolve(strict=True)
        if not source_runtime_entry(project_root).is_file():
            raise EngineAdapterError("fish_source_host_missing", str(project_root))
        if not (data_root / "tbfish.json").is_file():
            raise EngineAdapterError("fish_source_data_missing", str(data_root))
        lua_executable = source_settings.get("lua_executable", "lua55")
        if not isinstance(lua_executable, str) or not lua_executable:
            raise EngineAdapterError("fish_source_lua_invalid", "Invalid Lua executable")
        if "single_tide_at_seconds" in source_settings:
            raise EngineAdapterError("fish_source_policy_invalid", "Use the source periodic tide schedule")
        room_origin = source_settings.get("room_origin_seconds", 0)
        if type(room_origin) is not int or room_origin < 0:
            raise EngineAdapterError("fish_source_policy_invalid", "Invalid room time origin")
        fishing_area = source_settings.get("in_fishing_area", True)
        landing_distance = source_settings.get("landing_distance_cm")
        collect_interval = source_settings.get("collect_interval_seconds", 300)
        idle_seconds = source_settings.get("idle_seconds", 30)
        advance_mode = source_settings.get("advance_mode", "accurate")
        sampling_time_basis = source_settings.get("sampling_time_basis", "wall")
        if type(fishing_area) is not bool or any(
            type(value) is not int or value <= 0
            for value in (collect_interval, idle_seconds)
        ) or (landing_distance is not None and (type(landing_distance) is not int or landing_distance <= 0)):
            raise EngineAdapterError("fish_source_policy_invalid", "Invalid source player policy setting")
        if advance_mode not in ("accurate", "equivalent_batch_v1"):
            raise EngineAdapterError("fish_source_advance_mode_invalid", str(advance_mode))
        if sampling_time_basis not in ("wall", "online"):
            raise EngineAdapterError("fish_source_sampling_invalid", str(sampling_time_basis))
        if model.behavior_policies.get(_SOURCE_POLICY, {}).get("type") != _SOURCE_POLICY:
            raise EngineAdapterError("fish_source_policy_invalid", "Source player policy definition is missing")
        for scenario in model.scenarios.values():
            if scenario.start_state != "new_player" or scenario.time_mode != "tick":
                raise EngineAdapterError(
                    "fish_source_scenario_unsupported",
                    f"{scenario.id}: only new_player/tick is supported",
                )
            for profile_id in scenario.profiles:
                profile = model.player_profiles[profile_id]
                if profile.behavior_policy != _SOURCE_POLICY:
                    raise EngineAdapterError(
                        "fish_source_profile_unsupported",
                        f"{profile_id}: behavior_policy must be {_SOURCE_POLICY}",
                    )
                unknown = set(profile.behavior_weights) - _BEHAVIORS
                if unknown:
                    raise EngineAdapterError(
                        "fish_source_behavior_unsupported",
                        f"{profile_id}: {', '.join(sorted(unknown))}",
                    )
                if profile.behavior_target_policies:
                    raise EngineAdapterError(
                        "fish_source_target_policy_unsupported",
                        f"{profile_id}: legacy Fish target policies do not apply to source_priority_v1",
                    )
                for behavior, duration in profile.behavior_durations.items():
                    if (
                        behavior not in _BEHAVIORS
                        or duration.get("type") != "fixed"
                        or type(duration.get("seconds")) is not int
                        or duration["seconds"] <= 0
                    ):
                        raise EngineAdapterError(
                            "fish_source_duration_unsupported",
                            f"{profile_id}: {behavior} requires a positive fixed second duration",
                        )
                if str(profile.luck.to_decimal_string()) != "1" or any(
                    value.to_decimal_string() != "1"
                    for value in profile.source_efficiency.values()
                ):
                    raise EngineAdapterError(
                        "fish_source_profile_unsupported",
                        f"{profile_id}: hypothetical luck/efficiency multipliers require a source-owned benefit",
                    )
                session = model.session_patterns[profile.session_pattern]
                if session.get("offline_duration_seconds", 0) != 0:
                    raise EngineAdapterError(
                        "fish_source_session_unsupported",
                        f"{profile_id}: periodic offline sessions are not implemented",
                    )
                online = session.get("daily_online_seconds")
                if type(online) is not int or online <= 0 or online > 86400:
                    raise EngineAdapterError("fish_source_session_unsupported", f"{profile_id}: invalid daily online time")
        try:
            with FishSourceRuntime(project_root, data_root, lua_executable=lua_executable) as probe:
                capabilities = probe.capabilities or {}
                missing = sorted(_REQUIRED_OPERATIONS - set(capabilities.get("actions", [])))
                if missing or capabilities.get("tideScheduleVersion") != 1 or capabilities.get("naturalLandingVersion") != 1:
                    raise EngineAdapterError(
                        "fish_source_capability_missing", ", ".join(missing) or "tideScheduleVersion=1 and naturalLandingVersion=1",
                    )
                probe.create(start_at=0, in_fishing_area=fishing_area, fast_advance=advance_mode == "equivalent_batch_v1")
        except FishSourceRuntimeError as error:
            raise EngineAdapterError(error.code, str(error)) from error
        code_digest = source_code_digest(project_root)
        data_digest = data_snapshot_digest(data_root)
        integration_digest = _integration_code_digest()
        fingerprint = hashlib.sha256(json.dumps({
            "model": source_digest,
            "code": code_digest,
            "data": data_digest,
            "integration": integration_digest,
            "lua": "Lua 5.5",
            "executable": lua_executable,
            "policy": _SOURCE_POLICY,
            "settings": source_settings,
        }, sort_keys=True).encode("utf-8")).hexdigest()
        inputs = _SourceInputs(
            project_root, data_root, code_digest, data_digest, integration_digest,
            lua_executable, fishing_area, landing_distance,
            collect_interval, idle_seconds,
            advance_mode == "equivalent_batch_v1",
            sampling_time_basis, room_origin,
        )
        metadata = {
            "engine_id": self.engine_id,
            "source_runtime": {
                "code_sha256": code_digest,
                "integration_code_sha256": integration_digest,
                "selected_export_sha256": data_digest,
                "selected_export_root": str(data_root),
                "lua_version": "Lua 5.5",
                "lua_executable": lua_executable,
                "policy": _SOURCE_POLICY,
                "tide_policy": TIDE_POLICY,
                "tide_schedule": {"policy": "absolute_opening_only_v1", "room_origin_seconds": room_origin},
                "gun_policy": "claim_stable_reward_id_then_highest_source_attack_v1",
                "gun_claim_seconds": 1,
                "gun_equip_seconds": 1,
                "in_fishing_area": fishing_area,
                "landing_distance_cm": landing_distance,
                "landing_policy": "source_natural_v1" if landing_distance is None else "explicit_distance_v1",
                "collect_interval_seconds": collect_interval,
                "idle_seconds": idle_seconds,
                "advance_mode": advance_mode,
                "sampling_time_basis": sampling_time_basis,
                "generated_money_definition": "source_collected_slot_receipts_plus_current_unclaimed",
                "codex_claim_policy": "stable_reward_id_one_second_v1",
                "online_acquisition_definition": "observed_balance_increases_plus_receipt_spending_excludes_offline_claims",
            },
        }
        package_manifest = project_root / "runtime.json"
        if (project_root / "runtime.luac").is_file():
            packaged = json.loads(package_manifest.read_text(encoding="utf-8"))
            metadata["source_runtime"]["packaged_source_code_sha256"] = packaged["source_code_sha256"]
        return PreparedEngine(
            self.engine_id, model, f"sha256:{fingerprint}",
            metadata, inputs,
        )

    def run_scenario(
        self,
        prepared: PreparedEngine,
        scenario_id: str,
        *,
        checkpoint_input: str | Path | None = None,
        until_seconds: int | None = None,
    ) -> EngineExecution:
        run_started = time.perf_counter()
        inputs = prepared.domain_model
        if not isinstance(inputs, _SourceInputs):
            raise TypeError("Fish source engine requires prepared source inputs")
        if data_snapshot_digest(inputs.data_root) != inputs.data_digest:
            raise EngineAdapterError("fish_source_data_changed", "Selected export changed after preparation")
        if source_code_digest(inputs.project_root) != inputs.code_digest:
            raise EngineAdapterError("fish_source_code_changed", "Fish source changed after preparation")
        if _integration_code_digest() != inputs.integration_digest:
            raise EngineAdapterError("fish_source_integration_changed", "IGESS source adapter changed after preparation")
        scenario = prepared.model.scenarios[scenario_id]
        scenario_end = round(scenario.duration_hours * 3600)
        if until_seconds is not None and (type(until_seconds) is not int or not 0 < until_seconds <= scenario_end):
            raise EngineAdapterError("execution_window_invalid", "until_seconds must be within the scenario")
        execution_end = scenario_end if until_seconds is None else until_seconds
        prepared.manifest_metadata["source_runtime"]["record_interval_seconds"] = scenario.record_interval_seconds
        if checkpoint_input is not None and len(scenario.profiles) != 1:
            raise EngineAdapterError(
                "fish_source_checkpoint_profiles_unsupported",
                "Resume one profile at a time",
            )
        existing = None
        if checkpoint_input is not None:
            existing = CheckpointCodec.read(
                checkpoint_input,
                expected_engine_id=self.engine_id,
                expected_model_digest=prepared.model_digest,
            )
            if existing.scenario_id != scenario_id or existing.profile_id != scenario.profiles[0]:
                raise EngineAdapterError("fish_source_checkpoint_scope_mismatch", "Checkpoint scenario/profile differs")
        execution_start = existing.simulated_time_seconds if existing else 0
        if execution_end < execution_start:
            raise EngineAdapterError("execution_window_invalid", "Cannot stop before the checkpoint time")
        prepared.manifest_metadata["execution_window"] = {
            "requested_until_seconds": until_seconds,
            "scenario_end_seconds": scenario_end,
            "start_seconds": execution_start,
            "end_seconds": execution_end,
            "event_scope": "current_execution_segment",
            "accepted_commands_scope": "current_execution_segment",
            "cumulative_fields": ["wallet", "online_acquisition", "active_time_seconds", "source_total_throws"],
        }
        checked_at = time.perf_counter()
        timings = {"input_check": checked_at - run_started, "process_start": 0.0,
                   "source_execution": 0.0, "checkpoint": 0.0, "process_close": 0.0}
        timeline: list[TimelineRow] = []
        events: list[Event] = []
        checkpoint = None
        for profile_id in scenario.profiles:
            seed = int.from_bytes(hashlib.sha256(
                f"{prepared.model.config.random_seed}:{profile_id}".encode()
            ).digest()[:4], "big")
            opening = time.perf_counter()
            with FishSourceRuntime(
                inputs.project_root, inputs.data_root,
                lua_executable=inputs.lua_executable,
            ) as runtime:
                entered = time.perf_counter()
                timings["process_start"] += entered - opening
                if runtime.source_digest != inputs.code_digest:
                    raise EngineAdapterError("fish_source_code_changed", "Frozen code differs from preparation")
                if runtime.data_digest != inputs.data_digest:
                    raise EngineAdapterError("fish_source_data_changed", "Frozen export differs from preparation")
                available = set((runtime.capabilities or {}).get("actions", []))
                if (runtime.capabilities or {}).get("naturalLandingVersion") != 1:
                    raise EngineAdapterError("fish_source_capability_missing", "naturalLandingVersion=1")
                missing = sorted(_REQUIRED_OPERATIONS - available)
                if missing:
                    raise EngineAdapterError(
                        "fish_source_capability_missing",
                        ", ".join(missing),
                    )
                runner = _ProfileRun(
                    runtime, prepared.model, scenario_id, profile_id, inputs,
                    timeline, events, seed, existing, execution_end,
                )
                prepared.manifest_metadata["source_runtime"]["tide_schedule"].update({
                    "interval_seconds": runner.tide_interval,
                    "spawn_window_seconds": runner.state["tides"]["config"]["spawnWindowSeconds"],
                })
                runner.execute()
                executed = time.perf_counter()
                timings["source_execution"] += executed - entered
                if len(scenario.profiles) == 1:
                    checkpoint = runner.checkpoint(prepared.model_digest)
                checkpointed = time.perf_counter()
                timings["checkpoint"] += checkpointed - executed
            timings["process_close"] += time.perf_counter() - checkpointed
        timings["adapter_total"] = time.perf_counter() - run_started
        runtime_metadata = prepared.manifest_metadata.get("source_runtime")
        if isinstance(runtime_metadata, dict):
            runtime_metadata["timings_seconds"] = {
                key: round(value, 3) for key, value in timings.items()
            }
        return EngineExecution(SimulationResult(scenario_id, timeline, events), checkpoint)

    def write_checkpoint(
        self,
        execution: EngineExecution,
        path: str | Path,
        *,
        model_digest: str,
    ) -> Path | None:
        if execution.checkpoint is None:
            return None
        execution.checkpoint.validate(
            expected_engine_id=self.engine_id,
            expected_model_digest=model_digest,
        )
        return CheckpointCodec.write(execution.checkpoint, path)


class _ProfileRun:
    def __init__(
        self, runtime: FishSourceRuntime, model: EconomyModel,
        scenario_id: str, profile_id: str, inputs: _SourceInputs,
        timeline: list[TimelineRow], events: list[Event], seed: int,
        existing: SimulationCheckpoint | None, execution_end: int,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.scenario = model.scenarios[scenario_id]
        self.profile = model.player_profiles[profile_id]
        self.inputs = inputs
        self.timeline = timeline
        self.events = events
        self.seed = seed
        self.end = execution_end
        self.record_interval = self.scenario.record_interval_seconds
        self.request_number = 0
        self.behavior_turn = 0
        self.active_time_seconds = 0
        self.last_collect = -inputs.collect_interval_seconds
        self.blocked: dict[str, int] = {}
        self.egg_observations = EggObservations(existing.behavior_state.get("egg_observations") if existing else None)
        self.tide_observations = TideObservations(existing.behavior_state.get("tide_observations") if existing else None)
        self.pending_tide: dict[str, Any] | None = None
        self.next_tide_at = inputs.room_origin_seconds
        self.pending_throw: dict[str, Any] | None = None
        self.pending_action: dict[str, Any] | None = None
        self.last_receipt: dict[str, Any] = {}
        self.gun_milestones = GunMilestones(existing.behavior_state.get("gun_milestones") if existing else None)
        self.income = SourceIncome(
            dict(existing.behavior_state.get("online_acquisition", {})) if existing else None
        )
        if existing is None:
            self.state = runtime.create(
                start_at=0, random_seed=seed,
                in_fishing_area=inputs.fishing_area,
                fast_advance=inputs.fast_advance,
            )
        else:
            self.state = runtime.restore(_unpack_session(existing.engine_state))
            self.request_number = int(existing.behavior_state["request_number"])
            self.behavior_turn = int(existing.behavior_state["behavior_turn"])
            self.last_collect = int(existing.behavior_state["last_collect"])
            self.blocked = dict(existing.behavior_state.get("blocked", {}))
            self.active_time_seconds = int(existing.behavior_state.get("active_time_seconds", 0))
            self.pending_throw = existing.behavior_state.get("pending_throw")
            self.pending_action = existing.behavior_state.get("pending_action")
            self.pending_tide = existing.behavior_state.get("pending_tide")
            self.next_tide_at = existing.behavior_state["next_tide_at"]
        self.tide_interval = int(self.state["tides"]["config"]["intervalSeconds"])
        sample_time = self.active_time_seconds if inputs.sampling_time_basis == "online" else self.state["time"]
        self.next_record = (sample_time // self.record_interval + 1) * self.record_interval
        self._record()

    def _observe_guns(self) -> None:
        self.tide_observations.observe(self.state, self.active_time_seconds, self.scenario.id, self.profile.id, self.events)
        self.egg_observations.observe(self.state, self.active_time_seconds, self.scenario.id, self.profile.id, self.events)
        self.gun_milestones.observe(self.state, self.active_time_seconds, self.scenario.id, self.profile.id, self.events)

    def _record(self) -> None:
        self._observe_guns()
        if "luck" not in self.state:
            self.state = self.runtime.request({"op": "query"})
        state = self.state
        inventory = state["inventory"]["items"]
        resources = {
            name: _number(state["wallet"][name])
            for name in ("money", "material", "strength")
        }
        resources.update({
            "unclaimed_money": _number(state["unclaimedMoney"]),
            "collected_money": _number(state["collectedMoney"]),
            "generated_money": _number(state["generatedMoney"]),
            "online_money_acquired_cumulative": str(self.income.totals["money"]),
            "online_resource_acquired_cumulative": str(self.income.totals["material"]),
            "online_fish_sale_material_cumulative": str(self.income.totals["fish_sale_material"]),
            "egg_inventory_count": str(len(state["eggs"]["items"])),
            "egg_hatched_count": str(len(state["eggs"]["hatched"])),
            "egg_capacity_blocked": str(int(state["eggs"]["capacityBlocked"])),
            "online_tide_reload_material_cumulative": str(self.income.totals["tide_reload_material"]),
            "online_codex_money_cumulative": str(self.income.totals["codex_money"]),
            "online_codex_material_cumulative": str(self.income.totals["codex_material"]),
            "codex_unlocked_count": str(len(state["codex"]["unlockedEntries"])),
            "codex_claimed_count": str(len(state["codex"]["claimedRewardIds"])),
            "total_throws": str(state["totalThrows"]),
            "trash_realm": str(state["trashMan"]["realmId"]),
            "treasure_beast_unlocked": "1" if state["trashMan"]["unlocked"] else "0",
            "strength_rebirth_count": str(state["rebirth"]["strength"]["completedCount"]),
            "trash_man_rebirth_count": str(state["rebirth"]["trashMan"]["completedCount"]),
        })
        if "fishLuck" in state["luck"]:
            resources["fish_luck"] = _number(state["luck"]["fishLuck"])
            resources["trash_luck"] = str(state["luck"]["trashLuck"])
        hall_level = state["hall"]["currentLevel"]["upgradeLevel"]
        row = TimelineRow(
            self.scenario.id, self.profile.id, int(state["time"]),
            resources,
            {"deployed_fish": sum(item.get("hallSlot", 0) > 0 for item in inventory)},
            [f"fish_hall:{hall_level}"] if hall_level else [],
            _number(state["hall"]["currentRatePerSecond"]),
            {
                "strength": state["rebirth"]["strength"]["completedCount"],
                "trash_man": state["rebirth"]["trashMan"]["completedCount"],
            },
        )
        if not self.timeline or self.timeline[-1] != row:
            self.timeline.append(row)

    def _advance(self, target: int) -> None:
        online_sampling = self.inputs.sampling_time_basis == "online"
        if online_sampling and not self.state["online"]:
            self._advance_to(target)
            self._record()
            return
        sample_time = self.active_time_seconds if online_sampling else self.state["time"]
        next_at = self.state["time"] + self.next_record - sample_time
        while next_at <= target:
            self._advance_to(next_at, include_luck=True)
            self._record()
            self.next_record += self.record_interval
            next_at += self.record_interval
        if target != self.state["time"]:
            self._advance_to(target)

    def _advance_to(self, target: int, *, include_luck: bool = False) -> None:
        # Source hatching can unlock codex entries between report samples.
        # Observe its deadline independently of the sampling cadence.
        while self.state["online"]:
            deadlines = [math.ceil(egg["hatchAt"]) for egg in self.state["eggs"]["items"]
                         if self.state["time"] < math.ceil(egg["hatchAt"]) < target]
            if not deadlines:
                break
            self._advance_to(min(deadlines))
        before = self.state
        elapsed = target - self.state["time"]
        online = self.state["online"]
        self.runtime.request({"op": "advance", "time": target})
        self.state = self.runtime.request({"op": "query", "includeLuck": include_luck})
        self.income.observe(before, self.state)
        self._observe_codex(before)
        if online:
            self.active_time_seconds += elapsed
        self._observe_guns()

    def _command(self, op: str, *, target: str = "", **arguments: Any) -> bool:
        before = self.state
        observe_boundary = self.inputs.sampling_time_basis == "online" and op in {
            "rebirth_strength", "rebirth_trash_man", "claim_offline_reward",
        }
        if observe_boundary:
            self._record()
        self.request_number += 1
        command = {
            "op": op,
            "requestId": f"source:{self.profile.id}:{self.request_number}",
            "revision": self.state["revision"],
            **arguments,
        }
        try:
            receipt = self.runtime.request(command)
        except FishSourceRejection as error:
            self.blocked[f"{op}:{target}"] = int(self.state["time"]) + 60
            self.events.append(Event(
                self.scenario.id, self.profile.id, int(self.state["time"]),
                "source_rejected", op, {"code": error.code, "target": target},
            ))
            return False
        self.events.append(Event(
            self.scenario.id, self.profile.id, int(self.state["time"]),
            op, target, {"receipt": json.dumps(receipt, ensure_ascii=False, sort_keys=True)},
        ))
        self.state = self.runtime.request({"op": "query", "includeLuck": False})
        self.last_receipt = receipt
        self.income.observe(before, self.state, op=op, receipt=receipt)
        self._observe_codex(before)
        if not before["trashMan"]["unlocked"] and self.state["trashMan"]["unlocked"]:
            self.events.append(Event(
                self.scenario.id, self.profile.id, int(self.state["time"]),
                "treasure_beast_unlocked", "treasure_beast", {"receipt": json.dumps({
                    **receipt.get("landing", {}),
                    "distanceCm": receipt.get("targetDistanceCm"),
                    "activeTimeSeconds": self.active_time_seconds,
                }, sort_keys=True)},
            ))
            self._record()
        self._observe_guns()
        if observe_boundary or (self.inputs.sampling_time_basis == "online" and op in {"go_online", "go_offline"}):
            self._record()
        if op in {"start_tide", "complete_tide"} and not receipt.get("success"):
            raise EngineAdapterError("fish_source_tide_incomplete", json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return True

    def _observe_codex(self, before: dict[str, Any]) -> None:
        previous = {entry["collectionKey"] for entry in before["codex"]["unlockedEntries"]}
        for entry in self.state["codex"]["unlockedEntries"]:
            if entry["collectionKey"] not in previous:
                self.events.append(Event(
                    self.scenario.id, self.profile.id, int(self.state["time"]),
                    "codex_fish_unlocked", entry["collectionKey"],
                    {"receipt": json.dumps(entry, ensure_ascii=False, sort_keys=True),
                     "source": "observation"},
                ))

    def _allowed(self, op: str, target: str = "") -> bool:
        return self.blocked.get(f"{op}:{target}", -1) <= self.state["time"]

    def _duration(self, behavior: str) -> int:
        value = self.profile.behavior_durations.get(behavior, {})
        return max(1, int(value.get("seconds", self.inputs.idle_seconds)))

    def _choose(self) -> tuple[str, str, dict[str, Any]] | None:
        state = self.state
        gun_action = choose_gun_action(state, self._allowed)
        claims = []
        if gun_action is not None and gun_action[0] == "claim_gun_reward":
            claims.append(gun_action)
        for reward in state["codex"]["claimableRewards"]:
            target = str(reward["rewardId"])
            if self._allowed("claim_fish_reward", target):
                claims.append(("claim_fish_reward", target, {"op": "claim_fish_reward", "rewardId": reward["rewardId"]}))
                break
        if claims:
            return min(claims, key=lambda action: (int(action[1]), action[0]))
        if gun_action is not None:
            return gun_action
        wallet = state["wallet"]
        inventory = state["inventory"]["items"]
        slots = state["hall"]["slotBalances"]
        if state["time"] - self.last_collect >= self.inputs.collect_interval_seconds:
            for slot in slots:
                if _decimal(slot["money"]) > 0 and self._allowed("collect_slot", str(slot["slot"])):
                    return "collect_slot", str(slot["slot"]), {"op": "collect_slot", "slot": slot["slot"]}
        occupied = {item.get("hallSlot") for item in inventory if item.get("hallSlot", 0) > 0}
        for item in inventory:
            if item.get("hallSlot", 0) == 0:
                for slot in range(1, state["hall"]["currentLevel"]["capacity"] + 1):
                    if slot not in occupied and self._allowed("deploy_fish", str(item["instanceId"])):
                        return "deploy_fish", str(item["instanceId"]), {
                            "op": "deploy_fish", "instanceId": item["instanceId"], "slot": slot,
                        }
        actions = self.runtime.request({"op": "query_actions"})
        weights = self.profile.behavior_weights
        candidates: list[tuple[Decimal, str, str, dict[str, Any]]] = []

        def add(behavior: str, op: str, target: str = "", **args: Any) -> None:
            configured = weights.get(behavior)
            if configured is None:
                return
            weight = Decimal(configured.to_decimal_string())
            if weight > 0 and self._allowed(op, target):
                candidates.append((weight, behavior, target, {"op": op, **args}))

        if state["rebirth"]["strength"]["eligible"]:
            add("strength_rebirth", "rebirth_strength")
        if state["trashMan"]["unlocked"] and state["rebirth"]["trashMan"]["eligible"]:
            add("trash_man_rebirth", "rebirth_trash_man")
        realm = state["trashMan"]["currentRealm"]
        if (
            state["trashMan"]["unlocked"]
            and not state["trashMan"]["breakthrough"]["active"]
            and not realm["isMax"]
            and state["trashMan"]["realmId"] == state["trashMan"]["highestRealmId"]
            and _decimal(wallet["material"]) >= _decimal(realm["breakthroughMaterialCost"])
        ):
            add("fund_trash_man_breakthrough", "start_breakthrough")
        hall_quote = actions.get("hallUpgrade")
        if hall_quote and _affords(wallet, hall_quote):
            add("upgrade_fish_hall", "upgrade_hall")
        for quote in actions["fishUpgrades"]:
            if _affords(wallet, quote):
                add("upgrade_fish", "upgrade_fish", str(quote["instanceId"]), instanceId=quote["instanceId"])
        owned_torpedoes = set(state["torpedo"]["ownedIds"])
        for quote in actions["torpedoes"]:
            if quote["torpedoId"] not in owned_torpedoes and _affords(wallet, quote):
                add("purchase_torpedo", "purchase_torpedo", str(quote["torpedoId"]), torpedoId=quote["torpedoId"])
        owned_barbells = {item["barbellId"] for item in state["barbell"]["owned"]}
        for quote in actions["barbells"]:
            if quote["barbellId"] not in owned_barbells and _affords(wallet, quote):
                add("synthesize_barbell", "synthesize_barbell", str(quote["barbellId"]), barbellId=quote["barbellId"])
        undeployed = [item for item in inventory if item.get("hallSlot", 0) == 0]
        if len(inventory) >= state["inventory"]["limit"] and undeployed:
            item = undeployed[0]
            add("sell_fish", "sell_fish", str(item["instanceId"]), instanceId=item["instanceId"])
        if len(inventory) < state["inventory"]["limit"] and self.inputs.fishing_area:
            add("manual_throw", "manual_throw")
        add("exercise_barbell", "exercise_barbell")
        if not candidates:
            return None
        priority = {
            "manual_throw": 0, "upgrade_fish": 1, "exercise_barbell": 2,
            "sell_fish": 3,
        }
        maximum = max(row[0] for row in candidates)
        tied = [row for row in candidates if row[0] == maximum]
        tied.sort(key=lambda row: (priority.get(row[1], 4), row[1], row[2]))
        behaviors = list(dict.fromkeys(row[1] for row in tied))
        chosen = behaviors[self.behavior_turn % len(behaviors)]
        self.behavior_turn += 1
        _, behavior, target, payload = next(row for row in tied if row[1] == chosen)
        return behavior, target, payload

    def _act(self, behavior: str, target: str, payload: dict[str, Any], limit: int) -> None:
        start = int(self.state["time"])
        duration = 1 if behavior in ("collect_slot", "deploy_fish", "claim_fish_reward", "claim_gun_reward", "equip_gun") else self._duration(behavior)
        if behavior != "exercise_barbell" and start + duration > limit:
            self._wait_until(limit)
            return
        end = min(start + duration, limit)
        if behavior == "manual_throw":
            self.request_number += 1
            throw_id = f"throw:{self.profile.id}:{self.request_number}"
            if self._command("prepare_throw", target=throw_id, requestId=throw_id):
                plan = self.last_receipt["naturalLanding"]
                if self._command("begin_throw_flight", target=throw_id, requestId=throw_id):
                    landing_at = start + max(1, math.ceil(plan["flightSeconds"]))
                    self.pending_throw = {
                        "request_id": throw_id, "landing_at": landing_at,
                        "end_at": max(start + duration, landing_at),
                        "distance_cm": self.inputs.landing_distance_cm or plan["distanceCm"],
                    }
                    self._continue_throw(min(limit, self.end))
                    return
            self._wait_until(end)
        elif behavior == "exercise_barbell":
            if self._command("start_exercise"):
                self._wait_until(end, kind="exercise")
            else:
                self._wait_until(end)
        else:
            self._command(payload["op"], target=target, **{
                key: value for key, value in payload.items() if key != "op"
            })
            if behavior == "collect_slot":
                self.last_collect = start
            self._wait_until(end)

    def _wait_until(self, end: int, *, kind: str = "wait") -> None:
        self.pending_action = {"end_at": end, "kind": kind}
        self._continue_action(min(end, self.end))

    def _continue_action(self, limit: int) -> None:
        pending = self.pending_action
        assert pending is not None
        self._advance(min(pending["end_at"], limit))
        if self.state["time"] >= pending["end_at"]:
            if pending["kind"] == "exercise":
                self._command("stop_exercise")
            self.pending_action = None

    def _continue_throw(self, limit: int) -> None:
        pending = self.pending_throw
        assert pending is not None
        if not pending.get("landed"):
            self._advance(min(pending["landing_at"], limit))
            if self.state["time"] < pending["landing_at"]:
                return
            throw_id = pending["request_id"]
            if (
                self._command("select_throw_landing", target=throw_id, requestId=throw_id,
                              distanceCm=pending["distance_cm"])
                and self._command("finalize_throw_landing", target=throw_id, requestId=throw_id)
            ):
                self._command("complete_throw", target=throw_id, requestId=throw_id)
            pending["landed"] = True
        self._advance(min(pending["end_at"], limit))
        if self.state["time"] >= pending["end_at"]:
            self.pending_throw = None

    def _round_id(self, opening: int) -> str:
        origin = self.inputs.room_origin_seconds
        return f"room:{origin}:round:{(opening - origin) // self.tide_interval}"

    def _skip_tide(self, opening: int, reason: str) -> None:
        row = {
            "roundId": self._round_id(opening), "openedAt": opening,
            "endsAt": opening + 120, "phase": "skipped", "success": True,
            "reason": reason, "occupied_seconds": 0,
            "online_time_seconds": self.active_time_seconds,
            "reloads": [], "eggs": [],
            "totalMaterialSpent": {"sign": 0, "coeff": "0", "exp": 0},
            "approximation": TIDE_POLICY["model"],
        }
        self.events.append(Event(
            self.scenario.id, self.profile.id, opening, "tide_observed", row["roundId"],
            {"receipt": json.dumps(row, ensure_ascii=False, sort_keys=True), "source": "observation"},
        ))

    def _start_tide(self, round_id: str) -> None:
        if self.state.get("gameplay", {}).get("foregroundActivity"):
            if not self._command("stop_exercise"):
                raise EngineAdapterError("fish_source_tide_busy", round_id)
        if not self._command("start_tide", target=round_id, roundId=round_id):
            raise EngineAdapterError("fish_source_tide_rejected", round_id)
        if self.last_receipt["phase"] == "participating":
            self.pending_tide = {"roundId": round_id, "endsAt": self.last_receipt["endsAt"]}

    def _continue_tide(self, limit: int) -> None:
        pending = self.pending_tide
        assert pending is not None
        self._advance(min(pending["endsAt"], limit))
        if self.state["time"] >= pending["endsAt"]:
            if not self._command("complete_tide", target=pending["roundId"], roundId=pending["roundId"]):
                raise EngineAdapterError("fish_source_tide_rejected", pending["roundId"])
            self.pending_tide = None

    def execute(self) -> None:
        online_seconds = self.model.session_patterns[self.profile.session_pattern]["daily_online_seconds"]
        while self.state["time"] < self.end:
            now = int(self.state["time"])
            day_start = now // 86400 * 86400
            planned_logout = day_start + online_seconds
            day_end = min(day_start + 86400, self.end)
            if now >= planned_logout:
                if self.state["online"] and not self._command("go_offline"):
                    raise EngineAdapterError("fish_source_session_failed", "Source rejected go_offline")
                self.pending_throw = None
                self.pending_action = None
                while self.next_tide_at < day_end:
                    self._skip_tide(self.next_tide_at, "offline")
                    self.next_tide_at += self.tide_interval
                self._advance(day_end)
                continue
            if not self.state["online"]:
                if not self._command("go_online"):
                    raise EngineAdapterError("fish_source_session_failed", "Source rejected go_online")
                pending = self.state["offlineReward"].get("pendingOfflineReward")
                if pending:
                    self._command("claim_offline_reward", target=pending["settlementId"],
                                  settlementId=pending["settlementId"], mode="normal")
            # Complete already-started work before considering the opening at this second.
            if self.pending_throw and self.pending_throw["end_at"] <= now:
                self._continue_throw(now)
            if self.pending_action and self.pending_action["end_at"] <= now:
                self._continue_action(now)
            if self.pending_tide and self.pending_tide["endsAt"] <= now:
                self._continue_tide(now)
            if now == self.next_tide_at:
                round_id = self._round_id(now)
                self.next_tide_at += self.tide_interval
                if planned_logout - now < 120:
                    self._skip_tide(now, "insufficient_online_time")
                elif self.pending_throw or self.pending_action or self.pending_tide:
                    self._skip_tide(now, "foreground_busy")
                elif not self.state["guns"]["tideEligible"]:
                    self._skip_tide(now, "not_unlocked")
                else:
                    self._start_tide(round_id)
            boundary = min(planned_logout, self.next_tide_at)
            advance_limit = min(boundary, self.end)
            if self.pending_tide:
                self._continue_tide(advance_limit)
            elif self.pending_throw:
                self._continue_throw(advance_limit)
            elif self.pending_action:
                self._continue_action(advance_limit)
            else:
                selected = self._choose()
                if selected is None:
                    self._wait_until(min(now + self.inputs.idle_seconds, boundary))
                else:
                    self._act(*selected, boundary)
        self._record()
        self.tide_observations.observe(
            self.state, self.active_time_seconds, self.scenario.id, self.profile.id, self.events, final=True,
        )

    def checkpoint(self, model_digest: str) -> SimulationCheckpoint:
        session = self.runtime.checkpoint()
        return SimulationCheckpoint(
            engine_id="fish_source",
            model_digest=model_digest,
            scenario_id=self.scenario.id,
            profile_id=self.profile.id,
            simulated_time_seconds=int(self.state["time"]),
            root_random_seed=self.seed,
            next_throw_id=self.request_number,
            engine_state=_pack_session(session),
            behavior_state={
                "request_number": self.request_number,
                "behavior_turn": self.behavior_turn,
                "active_time_seconds": self.active_time_seconds,
                "last_collect": self.last_collect,
                "blocked": self.blocked,
                "pending_throw": self.pending_throw,
                "pending_action": self.pending_action,
                "pending_tide": self.pending_tide,
                "next_tide_at": self.next_tide_at,
                "tide_observations": self.tide_observations.save(),
                "online_acquisition": self.income.save(),
                "gun_milestones": self.gun_milestones.save(),
                "egg_observations": self.egg_observations.save(),
            },
        )
