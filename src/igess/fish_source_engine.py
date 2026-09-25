"""Opt-in Fish engine: schedule player intents, execute source Lua rules."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointCodec, SimulationCheckpoint
from .engines import EngineAdapterError, EngineExecution, PreparedEngine
from .fish_source_runtime import (
    FishSourceRejection,
    FishSourceRuntime,
    data_snapshot_digest,
    source_code_digest,
    source_runtime_entry,
)
from .schema import EconomyModel, Event, SimulationResult, TimelineRow

_BEHAVIORS = frozenset({
    "manual_throw", "sell_fish", "upgrade_fish", "upgrade_fish_hall",
    "purchase_torpedo", "synthesize_barbell", "exercise_barbell",
    "strength_rebirth", "trash_man_rebirth", "fund_trash_man_breakthrough",
})
_SOURCE_POLICY = "source_priority_v1"
_MAX_REPLAY_BYTES = 256 * 1024 * 1024
_REQUIRED_OPERATIONS = frozenset({
    "query", "query_actions", "advance", "checkpoint", "restore",
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
    for name in ("fish_source_engine.py", "fish_source_runtime.py", "fish_source_reports.py"):
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
    landing_distance_cm: int
    collect_interval_seconds: int
    idle_seconds: int
    fast_advance: bool
    sampling_time_basis: str


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
        fishing_area = source_settings.get("in_fishing_area", True)
        landing_distance = source_settings.get("landing_distance_cm", 100)
        collect_interval = source_settings.get("collect_interval_seconds", 300)
        idle_seconds = source_settings.get("idle_seconds", 30)
        advance_mode = source_settings.get("advance_mode", "accurate")
        sampling_time_basis = source_settings.get("sampling_time_basis", "wall")
        if type(fishing_area) is not bool or any(
            type(value) is not int or value <= 0
            for value in (landing_distance, collect_interval, idle_seconds)
        ):
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
            sampling_time_basis,
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
                "in_fishing_area": fishing_area,
                "landing_distance_cm": landing_distance,
                "collect_interval_seconds": collect_interval,
                "idle_seconds": idle_seconds,
                "advance_mode": advance_mode,
                "sampling_time_basis": sampling_time_basis,
                "generated_money_definition": "source_collected_slot_receipts_plus_current_unclaimed",
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
                missing = sorted(_REQUIRED_OPERATIONS - available)
                if missing:
                    raise EngineAdapterError(
                        "fish_source_capability_missing",
                        ", ".join(missing),
                    )
                runner = _ProfileRun(
                    runtime, prepared.model, scenario_id, profile_id, inputs,
                    timeline, events, seed, existing,
                )
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
        existing: SimulationCheckpoint | None,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.scenario = model.scenarios[scenario_id]
        self.profile = model.player_profiles[profile_id]
        self.inputs = inputs
        self.timeline = timeline
        self.events = events
        self.seed = seed
        self.end = round(self.scenario.duration_hours * 3600)
        self.record_interval = self.scenario.record_interval_seconds
        self.request_number = 0
        self.behavior_turn = 0
        self.active_time_seconds = 0
        self.last_collect = -inputs.collect_interval_seconds
        self.blocked: dict[str, int] = {}
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
        sample_time = self.active_time_seconds if inputs.sampling_time_basis == "online" else self.state["time"]
        self.next_record = (sample_time // self.record_interval + 1) * self.record_interval
        self._record()

    def _record(self) -> None:
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
            "total_throws": str(state["totalThrows"]),
            "trash_realm": str(state["trashMan"]["realmId"]),
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
        elapsed = target - self.state["time"]
        online = self.state["online"]
        self.runtime.request({"op": "advance", "time": target})
        self.state = self.runtime.request({"op": "query", "includeLuck": include_luck})
        if online:
            self.active_time_seconds += elapsed

    def _command(self, op: str, *, target: str = "", **arguments: Any) -> bool:
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
        if observe_boundary or (self.inputs.sampling_time_basis == "online" and op in {"go_online", "go_offline"}):
            self._record()
        return True

    def _allowed(self, op: str, target: str = "") -> bool:
        return self.blocked.get(f"{op}:{target}", -1) <= self.state["time"]

    def _duration(self, behavior: str) -> int:
        value = self.profile.behavior_durations.get(behavior, {})
        return max(1, int(value.get("seconds", self.inputs.idle_seconds)))

    def _choose(self) -> tuple[str, str, dict[str, Any]] | None:
        state = self.state
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
        if state["rebirth"]["trashMan"]["eligible"]:
            add("trash_man_rebirth", "rebirth_trash_man")
        realm = state["trashMan"]["currentRealm"]
        if (
            not state["trashMan"]["breakthrough"]["active"]
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
        duration = 1 if behavior in ("collect_slot", "deploy_fish") else self._duration(behavior)
        end = min(start + duration, limit)
        if behavior == "manual_throw":
            self.request_number += 1
            throw_id = f"throw:{self.profile.id}:{self.request_number}"
            if (
                self._command("prepare_throw", target=throw_id, requestId=throw_id)
                and self._command("begin_throw_flight", target=throw_id, requestId=throw_id)
            ):
                landing = min(start + 1, end)
                self._advance(landing)
                if (
                    self._command(
                        "select_throw_landing", target=throw_id,
                        requestId=throw_id, distanceCm=self.inputs.landing_distance_cm,
                    )
                    and self._command("finalize_throw_landing", target=throw_id, requestId=throw_id)
                    and self._command("complete_throw", target=throw_id, requestId=throw_id)
                ):
                    self._deploy_new_fish()
            self._advance(end)
        elif behavior == "exercise_barbell":
            if self._command("start_exercise"):
                self._advance(end)
                if end < limit:
                    self._command("stop_exercise")
        else:
            self._command(payload["op"], target=target, **{
                key: value for key, value in payload.items() if key != "op"
            })
            if behavior == "collect_slot":
                self.last_collect = start
            self._advance(end)

    def _deploy_new_fish(self) -> None:
        inventory = self.state["inventory"]["items"]
        occupied = {item.get("hallSlot") for item in inventory if item.get("hallSlot", 0) > 0}
        for item in inventory:
            if item.get("hallSlot", 0) == 0:
                for slot in range(1, self.state["hall"]["currentLevel"]["capacity"] + 1):
                    if slot not in occupied:
                        self._command("deploy_fish", target=str(item["instanceId"]),
                                      instanceId=item["instanceId"], slot=slot)
                        return

    def execute(self) -> None:
        online_seconds = self.model.session_patterns[self.profile.session_pattern]["daily_online_seconds"]
        while self.state["time"] < self.end:
            now = int(self.state["time"])
            day_start = now // 86400 * 86400
            online_end = min(day_start + online_seconds, self.end)
            day_end = min(day_start + 86400, self.end)
            if now < online_end:
                if not self.state["online"]:
                    if not self._command("go_online"):
                        raise EngineAdapterError("fish_source_session_failed", "Source rejected go_online")
                    pending = self.state["offlineReward"].get("pendingOfflineReward")
                    if pending:
                        self._command("claim_offline_reward", target=pending["settlementId"],
                                      settlementId=pending["settlementId"], mode="normal")
                selected = self._choose()
                if selected is None:
                    self._advance(min(now + self.inputs.idle_seconds, online_end))
                else:
                    self._act(*selected, online_end)
            else:
                if self.state["online"] and now < self.end and not self._command("go_offline"):
                    raise EngineAdapterError("fish_source_session_failed", "Source rejected go_offline")
                self._advance(day_end)
        self._record()

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
            },
        )
