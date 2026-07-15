"""Deterministic readiness probes for incrementally authored economy models."""

from __future__ import annotations

import ast
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, DecimalException
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, NoReturn

from ..formula import CompiledFormula, FormulaCompileError, FormulaEngine
from ..linter import ConfigError, ConfigLinter
from ..numbers import SimNumber
from ..outputs import OutputWriter
from ..reporting.static import generate_static_report
from ..simulator import Simulator
from ..schema import (
    ActivityOutputRow,
    ActivityRow,
    ConstantRow,
    EconomyModel,
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
    RuntimeConfig,
    Scenario,
    UpgradeRow,
)
from .response import AuthoringError


@dataclass(frozen=True, slots=True)
class EligibilityFinding:
    """One deterministic, JSON-safe reason a model cannot run a smoke probe."""

    code: str
    message: str
    entity: str | None = None
    id: str | None = None

    def __post_init__(self) -> None:
        for name in ("code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise TypeError(f"{name} must be a string")
            if not value:
                raise ValueError(f"{name} must not be empty")
        for name in ("entity", "id"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"{name} must be a string or None")

    def to_payload(self) -> dict[str, str]:
        payload = {"code": self.code, "message": self.message}
        if self.entity is not None:
            payload["entity"] = self.entity
        if self.id is not None:
            payload["id"] = self.id
        return payload


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """The static smoke decision and its ordered blocking findings."""

    eligible: bool
    findings: tuple[EligibilityFinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.eligible, bool):
            raise TypeError("eligible must be a bool")
        normalized = tuple(self.findings)
        if any(not isinstance(finding, EligibilityFinding) for finding in normalized):
            raise TypeError("findings must contain EligibilityFinding values")
        object.__setattr__(self, "findings", normalized)

    def to_payload(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "findings": [finding.to_payload() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class TenTickProbeResult:
    """Outcome of one deterministic, in-memory ten-tick simulation."""

    observable_change: bool
    findings: tuple[EligibilityFinding, ...]
    artifacts: tuple[str, ...] = ()
    report_index: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.observable_change, bool):
            raise TypeError("observable_change must be a bool")
        findings = tuple(self.findings)
        if any(not isinstance(finding, EligibilityFinding) for finding in findings):
            raise TypeError("findings must contain EligibilityFinding values")
        if isinstance(self.artifacts, (str, bytes, bytearray)):
            raise TypeError("artifacts must be a collection of string or Path values")
        artifact_values = tuple(self.artifacts)
        if any(not isinstance(path, (str, Path)) for path in artifact_values):
            raise TypeError("artifacts must contain only string or Path values")
        artifacts = tuple(str(path) for path in artifact_values)
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "artifacts", artifacts)
        if self.report_index is not None:
            if not isinstance(self.report_index, (str, Path)):
                raise TypeError("report_index must be a string, Path, or None")
            object.__setattr__(self, "report_index", str(self.report_index))

    def to_payload(self) -> dict[str, Any]:
        return {
            "observable_change": self.observable_change,
            "findings": [finding.to_payload() for finding in self.findings],
            "artifacts": list(self.artifacts),
            "report_index": self.report_index,
        }


def run_ten_tick_probe(
    model: EconomyModel,
    scenario: str = "smoke",
    artifact_root: str | Path | None = None,
) -> TenTickProbeResult:
    """Run exactly ten fixed ticks without mutating the caller's model."""

    scenario_id = scenario
    try:
        probe_model = _build_probe_model(model, scenario_id)
        simulator = Simulator(probe_model)
    except Exception as exc:
        _raise_smoke_failed("build", exc)

    try:
        result = simulator.run_scenario(scenario_id)
        observable = _probe_has_observable_change(result.timeline)
    except Exception as exc:
        _raise_smoke_failed("execution", exc)

    findings = () if observable else (
        EligibilityFinding(
            "smoke_no_state_change",
            "The ten-tick smoke probe completed without an observable state change.",
        ),
    )
    if artifact_root is None:
        return TenTickProbeResult(observable, findings)

    try:
        artifacts, report_index = _write_probe_artifacts(
            result,
            probe_model,
            Path(artifact_root),
        )
    except Exception as exc:
        if isinstance(exc, AuthoringError) and exc.code == "smoke_failed":
            raise
        _raise_smoke_failed("artifact", exc)
    return TenTickProbeResult(observable, findings, artifacts, report_index)


def _build_probe_model(model: EconomyModel, scenario_id: str) -> EconomyModel:
    if not isinstance(model, EconomyModel):
        raise TypeError("model must be an EconomyModel")
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("scenario_id must be a non-empty string")
    tick_seconds = model.config.tick_seconds
    if isinstance(tick_seconds, bool) or not isinstance(tick_seconds, int) or tick_seconds <= 0:
        raise ValueError("model tick_seconds must be a positive integer")
    if scenario_id not in model.scenarios:
        raise KeyError(f"unknown scenario '{scenario_id}'")
    scenario = model.scenarios[scenario_id]
    if not isinstance(scenario, Scenario):
        raise TypeError(f"scenario '{scenario_id}' is malformed")
    if not isinstance(scenario.profiles, list) or not scenario.profiles:
        raise ValueError(f"scenario '{scenario_id}' must reference at least one profile")
    if any(
        not isinstance(profile_id, str) or not profile_id or profile_id not in model.player_profiles
        for profile_id in scenario.profiles
    ):
        raise KeyError(f"scenario '{scenario_id}' references an unknown profile")
    if not isinstance(scenario.outputs, list):
        raise TypeError(f"scenario '{scenario_id}' outputs must be a list")

    probe_scenario = replace(
        scenario,
        duration_hours=_duration_hours_for_exact_seconds(tick_seconds * 10),
        profiles=list(scenario.profiles),
        outputs=list(scenario.outputs),
        record_interval_seconds=tick_seconds,
        time_mode="tick",
    )
    return replace(
        model,
        scenarios={**model.scenarios, scenario_id: probe_scenario},
    )


def _duration_hours_for_exact_seconds(seconds: int) -> float:
    """Return hours whose existing Simulator conversion recovers *seconds*."""

    try:
        hours = seconds / 3600.0
    except OverflowError as exc:
        raise OverflowError("probe duration is too large for the simulator") from exc
    if not math.isfinite(hours):
        raise OverflowError("probe duration is too large for the simulator")
    for _ in range(64):
        recovered = int(hours * 3600.0)
        if recovered == seconds:
            return hours
        direction = math.inf if recovered < seconds else -math.inf
        adjusted = math.nextafter(hours, direction)
        if adjusted == hours or not math.isfinite(adjusted):
            break
        hours = adjusted
    raise OverflowError("probe duration cannot be represented as exact simulator seconds")


def _raise_smoke_failed(phase: str, exc: Exception) -> NoReturn:
    raise AuthoringError(
        "smoke_failed",
        f"The ten-tick smoke probe failed during {phase}.",
        {"phase": phase, "original_type": type(exc).__name__},
    ) from exc


_RUN_ARTIFACTS = (
    "analysis.json",
    "analysis.md",
    "events.csv",
    "events.json",
    "payback.csv",
    "run_manifest.json",
    "timeline.csv",
    "timeline.json",
)
_REPORT_ARTIFACTS = (
    "assets/echarts.min.js",
    "assets/report.css",
    "assets/report.js",
    "index.html",
    "report_data.json",
)


def _write_probe_artifacts(
    result: Any,
    model: EconomyModel,
    target: Path,
) -> tuple[tuple[str, ...], str]:
    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    target_identity = _publishable_target_identity(target)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name or 'probe'}-probe-", dir=parent)
    )
    staging_identity = staging.lstat()
    published = False
    relative_artifacts: tuple[Path, ...] = ()
    try:
        run_dir = staging / "run"
        report_dir = staging / "report"
        OutputWriter.write_all(result, run_dir, model)
        report_index = generate_static_report(run_dir, report_dir)
        relative_artifacts = _validate_probe_artifacts(
            staging,
            report_index,
        )
        _publish_probe_tree(staging, target, target_identity, staging_identity)
        published = True
    finally:
        if not published and _path_matches_identity(staging, staging_identity):
            shutil.rmtree(staging)

    artifacts = tuple(str(target / path) for path in relative_artifacts)
    return artifacts, str(target / "report" / "index.html")


def _publishable_target_identity(target: Path) -> os.stat_result | None:
    try:
        identity = target.lstat()
    except FileNotFoundError:
        return None
    if target.is_symlink() or not target.is_dir():
        raise FileExistsError(f"artifact target is not a directory: {target}")
    try:
        next(target.iterdir())
    except StopIteration:
        return identity
    raise FileExistsError(f"artifact target is not empty: {target}")


def _validate_probe_artifacts(staging: Path, report_index: Path) -> tuple[Path, ...]:
    expected = tuple(Path("run") / name for name in _RUN_ARTIFACTS) + tuple(
        Path("report") / name for name in _REPORT_ARTIFACTS
    )
    if report_index != staging / "report" / "index.html":
        raise ValueError("static report returned an unexpected index path")
    for relative in expected:
        path = staging / relative
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"missing staged probe artifact: {relative.as_posix()}")
    for relative, expected_type in (
        (Path("run/timeline.json"), list),
        (Path("run/events.json"), list),
        (Path("run/analysis.json"), dict),
        (Path("run/run_manifest.json"), dict),
        (Path("report/report_data.json"), dict),
    ):
        payload = json.loads((staging / relative).read_text(encoding="utf-8"))
        if not isinstance(payload, expected_type):
            raise ValueError(f"staged artifact has invalid shape: {relative.as_posix()}")
    return tuple(sorted(expected, key=lambda path: path.as_posix()))


def _publish_probe_tree(
    staging: Path,
    target: Path,
    target_identity: os.stat_result | None,
    staging_identity: os.stat_result,
) -> None:
    if target_identity is None:
        if _path_lexists(target):
            raise FileExistsError(f"artifact target appeared before publication: {target}")
        try:
            os.replace(staging, target)
        except BaseException:
            if _path_matches_identity(target, staging_identity):
                return
            raise
        if not _path_matches_identity(target, staging_identity):
            raise OSError("staged probe artifact tree was not published")
        return

    if not _path_matches_identity(target, target_identity):
        raise FileExistsError(f"artifact target changed before publication: {target}")
    descriptor, backup_name = tempfile.mkstemp(
        prefix=f".{target.name or 'probe'}-backup-", dir=target.parent
    )
    os.close(descriptor)
    backup = Path(backup_name)
    backup.unlink()
    try:
        os.replace(target, backup)
    except BaseException as primary:
        if _path_matches_identity(backup, target_identity):
            _restore_empty_target_after_primary(
                primary,
                backup,
                target,
                target_identity,
            )
        raise

    try:
        os.replace(staging, target)
    except BaseException as primary:
        if _path_matches_identity(target, staging_identity):
            _cleanup_empty_backup(backup, target_identity)
            return
        _restore_empty_target_after_primary(primary, backup, target, target_identity)
        raise
    if not _path_matches_identity(target, staging_identity):
        primary = OSError("staged probe artifact tree was not published")
        _restore_empty_target_after_primary(primary, backup, target, target_identity)
        raise primary
    _cleanup_empty_backup(backup, target_identity)


def _restore_empty_target_after_primary(
    primary: BaseException,
    backup: Path,
    target: Path,
    target_identity: os.stat_result,
) -> None:
    if not _path_matches_identity(backup, target_identity):
        primary.add_note(
            f"Original empty artifact target could not be identified at {backup}; "
            "recovery paths were left untouched."
        )
        return
    if _path_lexists(target):
        primary.add_note(
            f"Original empty artifact target remains recoverable at {backup}, "
            f"but {target} is occupied."
        )
        return
    try:
        os.replace(backup, target)
    except BaseException as rollback_error:
        if _path_matches_identity(target, target_identity):
            primary.add_note(
                "Rollback restored the original empty artifact target but its "
                f"rename raised {type(rollback_error).__name__}: {rollback_error}"
            )
        else:
            primary.add_note(
                f"Rollback failed with {type(rollback_error).__name__}: "
                f"{rollback_error}. Original target remains recoverable at {backup}."
            )
        return
    if not _path_matches_identity(target, target_identity):
        primary.add_note(
            f"Rollback returned without restoring the original target; its backup "
            f"may remain recoverable at {backup}."
        )


def _cleanup_empty_backup(backup: Path, target_identity: os.stat_result) -> None:
    if not _path_matches_identity(backup, target_identity):
        return
    try:
        backup.rmdir()
    except OSError:
        # Publication is already committed.  Preserve the known empty backup
        # if Windows still has an open handle rather than failing the probe.
        pass


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _path_matches_identity(path: Path, identity: os.stat_result) -> bool:
    try:
        current = path.lstat()
    except OSError:
        return False
    return (
        current.st_dev == identity.st_dev
        and current.st_ino == identity.st_ino
        and current.st_mode == identity.st_mode
    )


def _probe_has_observable_change(timeline: Sequence[Any]) -> bool:
    by_profile: dict[str, list[Any]] = {}
    for row in timeline:
        by_profile.setdefault(row.profile_id, []).append(row)
    for profile_id in sorted(by_profile):
        rows = by_profile[profile_id]
        first, last = rows[0], rows[-1]
        first_resources = {
            key: SimNumber.parse(value) for key, value in first.resources.items()
        }
        last_resources = {
            key: SimNumber.parse(value) for key, value in last.resources.items()
        }
        if first_resources != last_resources:
            return True
        if first.generators_owned != last.generators_owned:
            return True
        if set(first.upgrades_purchased) != set(last.upgrades_purchased):
            return True
        if getattr(first, "prestige_counts", {}) != getattr(last, "prestige_counts", {}):
            return True
    return False


def static_smoke_eligibility(raw: RawConfig, model: EconomyModel) -> EligibilityResult:
    """Return whether *model* has a deterministic path that can change smoke state.

    Malformed or inconsistent source/runtime inputs raise ``model_invalid``.  A
    structurally valid but incomplete economy instead returns ordered findings.
    """

    _validate_input_shapes(raw, model)
    _validate_unique_ids(raw)
    try:
        ConfigLinter.validate(raw)
    except (ConfigError, FormulaCompileError, DecimalException) as exc:
        _raise_invalid(f"Model validation failed: {exc}", "config_invalid")

    smoke = raw.rules.scenarios.get("smoke")
    if smoke is None:
        _raise_invalid("Model must define the 'smoke' scenario", "missing_smoke_scenario")
    if not smoke.profiles:
        _raise_invalid(
            "Scenario 'smoke' must reference at least one player profile",
            "missing_smoke_profile",
        )
    _validate_model_correspondence(raw, model)

    profile_ids = tuple(sorted(set(smoke.profiles)))
    profiles = tuple((profile_id, model.player_profiles[profile_id]) for profile_id in profile_ids)

    findings: list[EligibilityFinding] = []
    if not model.resources:
        findings.append(
            EligibilityFinding(
                "no_resources",
                "Add at least one resource before running the smoke scenario.",
                "resource",
            )
        )

    activity_eligible, activity_findings = _check_activity_routes(model, profiles)
    generator_eligible, generator_findings = _check_generator_routes(model, profiles)

    if model.resources and (activity_eligible or generator_eligible):
        return EligibilityResult(True, ())

    findings.extend(activity_findings)
    findings.extend(generator_findings)
    if not model.activities and not model.generators:
        findings.append(
            EligibilityFinding(
                "no_production_path",
                "Add an always-available activity or generator production path.",
            )
        )
    findings.append(
        EligibilityFinding(
            "no_executable_behavior",
            "No executable economy behavior is currently available for the smoke scenario.",
        )
    )
    return EligibilityResult(False, _deduplicate(findings))


def _check_activity_routes(
    model: EconomyModel,
    profiles: tuple[tuple[str, PlayerProfile], ...],
) -> tuple[bool, list[EligibilityFinding]]:
    outputs_by_activity: dict[str, list[ActivityOutputRow]] = {}
    for output in sorted(model.activity_outputs.values(), key=lambda row: row.id):
        outputs_by_activity.setdefault(output.activity_id, []).append(output)

    findings: list[EligibilityFinding] = []
    for activity_id in sorted(model.activities):
        activity = model.activities[activity_id]
        blockers: list[EligibilityFinding] = []
        if activity.unlock_condition != "always":
            blockers.append(
                EligibilityFinding(
                    "activity_not_always",
                    f"Activity '{activity_id}' is not available at smoke start.",
                    "activity",
                    activity_id,
                )
            )

        outputs = outputs_by_activity.get(activity_id, ())
        positive_output = any(
            _parse_number(
                output.amount_per_second,
                f"activity_output '{output.id}' amount_per_second",
            )
            > SimNumber.zero()
            for output in outputs
        )
        if not positive_output:
            blockers.append(
                EligibilityFinding(
                    "activity_no_positive_output",
                    f"Activity '{activity_id}' needs a positive linked resource output.",
                    "activity",
                    activity_id,
                )
            )

        for profile_id, profile in profiles:
            weight = _mapping_number(
                profile.activity_weights,
                activity_id,
                f"profile '{profile_id}' activity weight '{activity_id}'",
            )
            if weight <= SimNumber.zero():
                blockers.append(
                    EligibilityFinding(
                        "activity_weight_nonpositive",
                        f"Profile '{profile_id}' needs a positive weight for activity '{activity_id}'.",
                        "player_profile",
                        profile_id,
                    )
                )
            efficiency = _mapping_number(
                profile.source_efficiency,
                activity.source_type,
                f"profile '{profile_id}' source efficiency '{activity.source_type}'",
            )
            if efficiency <= SimNumber.zero():
                blockers.append(
                    EligibilityFinding(
                        "activity_efficiency_nonpositive",
                        f"Profile '{profile_id}' needs positive '{activity.source_type}' efficiency for activity '{activity_id}'.",
                        "player_profile",
                        profile_id,
                    )
                )

        if not blockers:
            return True, []
        findings.extend(blockers)
    return False, findings


def _check_generator_routes(
    model: EconomyModel,
    profiles: tuple[tuple[str, PlayerProfile], ...],
) -> tuple[bool, list[EligibilityFinding]]:
    findings: list[EligibilityFinding] = []
    zero = SimNumber.zero()
    for generator_id in sorted(model.generators):
        generator = model.generators[generator_id]
        blockers: list[EligibilityFinding] = []
        if generator.unlock_condition != "always":
            blockers.append(
                EligibilityFinding(
                    "generator_not_always",
                    f"Generator '{generator_id}' is not available at smoke start.",
                    "generator",
                    generator_id,
                )
            )

        base_output = _parse_number(
            generator.base_output, f"generator '{generator_id}' base_output"
        )
        if base_output <= zero:
            blockers.append(
                EligibilityFinding(
                    "generator_output_nonpositive",
                    f"Generator '{generator_id}' needs positive base output.",
                    "generator",
                    generator_id,
                )
            )

        base_cost = _parse_number(
            generator.base_cost, f"generator '{generator_id}' base_cost"
        )
        _parse_number(generator.cost_growth, f"generator '{generator_id}' cost_growth")
        if base_cost < zero:
            blockers.append(
                EligibilityFinding(
                    "generator_cost_negative",
                    f"Generator '{generator_id}' needs a non-negative base cost.",
                    "generator",
                    generator_id,
                )
            )

        computed_cost, _computed_output = _validate_generator_formula_runtime(
            model, generator_id
        )
        if computed_cost < zero:
            blockers.append(
                EligibilityFinding(
                    "generator_cost_negative",
                    f"Generator '{generator_id}' has a negative computed starting cost.",
                    "generator",
                    generator_id,
                )
            )
        if _computed_output <= zero:
            blockers.append(
                EligibilityFinding(
                    "generator_output_nonpositive",
                    f"Generator '{generator_id}' has non-positive computed production.",
                    "generator",
                    generator_id,
                )
            )
        for profile_id, profile in profiles:
            efficiency = _mapping_number(
                profile.source_efficiency,
                generator.source_type,
                f"profile '{profile_id}' source efficiency '{generator.source_type}'",
            )
            if efficiency <= zero:
                blockers.append(
                    EligibilityFinding(
                        "generator_efficiency_nonpositive",
                        f"Profile '{profile_id}' needs positive '{generator.source_type}' efficiency for generator '{generator_id}'.",
                        "player_profile",
                        profile_id,
                    )
                )

        starting_amount = model.constants.get(f"starting_{generator.cost_resource}", zero)
        if not isinstance(starting_amount, SimNumber):
            _raise_invalid(
                f"Model constant 'starting_{generator.cost_resource}' is malformed",
                "model_mismatch",
            )
        if computed_cost >= zero and starting_amount < computed_cost:
            blockers.append(
                EligibilityFinding(
                    "generator_unaffordable",
                    f"Generator '{generator_id}' costs {computed_cost} {generator.cost_resource}, but the smoke start has {starting_amount}.",
                    "generator",
                    generator_id,
                )
            )

        if not blockers:
            return True, []
        findings.extend(blockers)
    return False, findings


def _validate_generator_formula_runtime(
    model: EconomyModel, generator_id: str
) -> tuple[SimNumber, SimNumber]:
    try:
        cost = model.generator_cost(generator_id, 0)
        output = model.generator_output(generator_id, 1, SimNumber.one())
    except (FormulaCompileError, DecimalException, ArithmeticError, ValueError) as exc:
        _raise_invalid(
            f"Generator '{generator_id}' formula cannot be evaluated: {exc}",
            "formula_evaluation_failed",
        )
    if not isinstance(cost, SimNumber) or not isinstance(output, SimNumber):
        _raise_invalid(
            f"Generator '{generator_id}' formula returned a malformed value",
            "formula_evaluation_failed",
        )
    return cost, output


def _mapping_number(
    values: Mapping[str, Any], key: str, context: str
) -> SimNumber:
    if key not in values:
        return SimNumber.zero()
    return _parse_number(values[key], context)


def _parse_number(value: Any, context: str) -> SimNumber:
    try:
        return SimNumber.parse(value)
    except (DecimalException, ValueError) as exc:
        _raise_invalid(f"{context} is not a valid exact number", "invalid_number")


def _validate_input_shapes(raw: RawConfig, model: EconomyModel) -> None:
    if not isinstance(raw, RawConfig):
        _raise_invalid("Raw configuration is malformed", "malformed_raw_config")
    if not isinstance(model, EconomyModel):
        _raise_invalid("Runtime model is malformed", "malformed_runtime_model")
    if not isinstance(raw.rules, Rules) or not isinstance(raw.rules.model, ModelSettings):
        _raise_invalid("Raw rules are malformed", "malformed_raw_config")
    if not isinstance(model.config, RuntimeConfig):
        _raise_invalid("Runtime model settings are malformed", "malformed_runtime_model")
    settings = raw.rules.model
    if (
        not isinstance(settings.id, str)
        or not isinstance(settings.tick_seconds, int)
        or isinstance(settings.tick_seconds, bool)
        or not isinstance(settings.number_backend, str)
        or (
            settings.random_seed is not None
            and (
                not isinstance(settings.random_seed, int)
                or isinstance(settings.random_seed, bool)
            )
        )
    ):
        _raise_invalid("Raw model settings are malformed", "malformed_raw_config")

    table_types = (
        ("resources", ResourceRow),
        ("generators", GeneratorRow),
        ("activities", ActivityRow),
        ("activity_outputs", ActivityOutputRow),
        ("upgrades", UpgradeRow),
        ("constants", ConstantRow),
        ("milestones", MilestoneRow),
        ("prestige_layers", PrestigeLayerRow),
    )
    for table_name, row_type in table_types:
        rows = getattr(raw, table_name)
        if not isinstance(rows, list) or any(not isinstance(row, row_type) for row in rows):
            _raise_invalid(
                f"Raw table '{table_name}' contains a malformed row",
                "malformed_raw_config",
            )
        if any(not isinstance(row.id, str) or not row.id for row in rows):
            _raise_invalid(
                f"Raw table '{table_name}' contains a malformed id",
                "malformed_raw_config",
            )
    _validate_raw_table_fields(raw)

    rule_maps: tuple[tuple[str, type[Any] | None], ...] = (
        ("formulas", FormulaDef),
        ("generator_types", None),
        ("source_types", None),
        ("modifier_types", None),
        ("behavior_policies", None),
        ("session_patterns", None),
        ("player_profiles", PlayerProfile),
        ("scenarios", Scenario),
        ("rng_tables", RngTable),
        ("rng_scenarios", RngScenario),
        ("regression_gates", None),
    )
    for name, value_type in rule_maps:
        value = getattr(raw.rules, name)
        if not isinstance(value, Mapping):
            _raise_invalid(f"Raw rule map '{name}' is malformed", "malformed_raw_config")
        if any(not isinstance(key, str) or not key for key in value):
            _raise_invalid(f"Raw rule map '{name}' has a malformed id", "malformed_raw_config")
        if value_type is not None and any(not isinstance(item, value_type) for item in value.values()):
            _raise_invalid(f"Raw rule map '{name}' contains a malformed value", "malformed_raw_config")

    for formula_id, formula in raw.rules.formulas.items():
        if (
            not isinstance(formula.args, (list, tuple))
            or any(not isinstance(arg, str) or not arg for arg in formula.args)
            or not isinstance(formula.expr, str)
        ):
            _raise_invalid(
                f"Formula '{formula_id}' is malformed", "malformed_raw_config"
            )
    for name in (
        "generator_types",
        "source_types",
        "behavior_policies",
        "session_patterns",
        "regression_gates",
    ):
        if any(not isinstance(item, Mapping) for item in getattr(raw.rules, name).values()):
            _raise_invalid(
                f"Raw rule map '{name}' contains a malformed value",
                "malformed_raw_config",
            )
    for generator_type, data in raw.rules.generator_types.items():
        for field in ("cost_formula", "production_formula"):
            if field in data and not isinstance(data[field], str):
                _raise_invalid(
                    f"Generator type '{generator_type}' field '{field}' is malformed",
                    "malformed_raw_config",
                )
    for policy_id, policy in raw.rules.behavior_policies.items():
        if "type" in policy and not isinstance(policy["type"], str):
            _raise_invalid(
                f"Behavior policy '{policy_id}' type is malformed",
                "malformed_raw_config",
            )
    if any(not isinstance(item, str) for item in raw.rules.modifier_types.values()):
        _raise_invalid("Raw modifier types are malformed", "malformed_raw_config")

    if not isinstance(raw.rules.modifier_pipeline, list) or any(
        not isinstance(value, str) for value in raw.rules.modifier_pipeline
    ):
        _raise_invalid("Raw modifier pipeline is malformed", "malformed_raw_config")
    for profile_id, profile in raw.rules.player_profiles.items():
        if not isinstance(profile.source_efficiency, Mapping) or not isinstance(
            profile.activity_weights, Mapping
        ):
            _raise_invalid(
                f"Profile '{profile_id}' numeric mappings are malformed",
                "malformed_raw_config",
            )
        if (
            profile.id != profile_id
            or any(not isinstance(key, str) or not key for key in profile.source_efficiency)
            or any(not isinstance(value, SimNumber) for value in profile.source_efficiency.values())
            or any(not isinstance(key, str) or not key for key in profile.activity_weights)
            or any(not isinstance(value, SimNumber) for value in profile.activity_weights.values())
            or not isinstance(profile.behavior_policy, str)
            or not isinstance(profile.session_pattern, str)
            or not isinstance(profile.prestige_policy, str)
            or not isinstance(profile.luck, SimNumber)
        ):
            _raise_invalid(
                f"Profile '{profile_id}' is malformed", "malformed_raw_config"
            )
    for scenario_id, scenario in raw.rules.scenarios.items():
        if not isinstance(scenario.profiles, list) or any(
            not isinstance(profile_id, str) for profile_id in scenario.profiles
        ):
            _raise_invalid(
                f"Scenario '{scenario_id}' profiles are malformed",
                "malformed_raw_config",
            )
        if (
            scenario.id != scenario_id
            or not isinstance(scenario.duration_hours, (int, float))
            or isinstance(scenario.duration_hours, bool)
            or not isinstance(scenario.start_state, str)
            or not isinstance(scenario.record_interval_seconds, int)
            or isinstance(scenario.record_interval_seconds, bool)
            or not isinstance(scenario.outputs, list)
            or any(not isinstance(output, str) for output in scenario.outputs)
            or not isinstance(scenario.time_mode, str)
        ):
            _raise_invalid(
                f"Scenario '{scenario_id}' is malformed", "malformed_raw_config"
            )
    for table_id, table in raw.rules.rng_tables.items():
        if (
            table.id != table_id
            or not isinstance(table.algorithm, str)
            or not isinstance(table.rarities, list)
            or any(not isinstance(rarity, RngRarity) for rarity in table.rarities)
            or any(
                not isinstance(rarity.id, str)
                or not isinstance(rarity.denominator, SimNumber)
                for rarity in table.rarities
            )
        ):
            _raise_invalid(
                f"RNG table '{table_id}' is malformed", "malformed_raw_config"
            )
    for scenario_id, scenario in raw.rules.rng_scenarios.items():
        if (
            scenario.id != scenario_id
            or not isinstance(scenario.table, str)
            or not isinstance(scenario.rolls, int)
            or isinstance(scenario.rolls, bool)
            or not isinstance(scenario.trials, int)
            or isinstance(scenario.trials, bool)
            or not isinstance(scenario.profiles, list)
            or any(not isinstance(profile_id, str) for profile_id in scenario.profiles)
            or (
                scenario.event_threshold is not None
                and not isinstance(scenario.event_threshold, str)
            )
        ):
            _raise_invalid(
                f"RNG scenario '{scenario_id}' is malformed",
                "malformed_raw_config",
            )

    model_maps = (
        "resources",
        "generators",
        "activities",
        "activity_outputs",
        "upgrades",
        "constants",
        "milestones",
        "prestige_layers",
        "formulas",
        "generator_types",
        "source_types",
        "modifier_types",
        "behavior_policies",
        "session_patterns",
        "player_profiles",
        "scenarios",
        "rng_tables",
        "rng_scenarios",
    )
    for name in model_maps:
        if not isinstance(getattr(model, name), Mapping):
            _raise_invalid(f"Runtime model map '{name}' is malformed", "malformed_runtime_model")


def _validate_raw_table_fields(raw: RawConfig) -> None:
    for resource in raw.resources:
        _require_strings(resource, ("id", "name", "dimension"), "resource")
    for generator in raw.generators:
        _require_strings(
            generator,
            (
                "id",
                "name",
                "generator_type",
                "output_resource",
                "source_type",
                "cost_resource",
                "unlock_condition",
            ),
            "generator",
        )
        for field in ("base_output", "base_cost", "cost_growth"):
            _require_exact_number(getattr(generator, field), f"generator '{generator.id}' {field}")
    for activity in raw.activities:
        _require_strings(
            activity,
            ("id", "name", "source_type", "unlock_condition"),
            "activity",
        )
    for output in raw.activity_outputs:
        _require_strings(
            output,
            ("id", "activity_id", "output_resource"),
            "activity_output",
        )
        _require_exact_number(
            output.amount_per_second,
            f"activity_output '{output.id}' amount_per_second",
        )
    for upgrade in raw.upgrades:
        _require_strings(
            upgrade,
            (
                "id",
                "name",
                "target",
                "modifier_type",
                "cost_resource",
                "unlock_condition",
            ),
            "upgrade",
        )
        _require_exact_number(upgrade.value, f"upgrade '{upgrade.id}' value")
        _require_exact_number(upgrade.base_cost, f"upgrade '{upgrade.id}' base_cost")
    for constant in raw.constants:
        _require_strings(constant, ("id",), "constant")
        _require_exact_number(constant.value, f"constant '{constant.id}' value")
    for milestone in raw.milestones:
        _require_strings(
            milestone,
            ("id", "name", "condition", "reward_resource"),
            "milestone",
        )
        _require_exact_number(
            milestone.reward_amount, f"milestone '{milestone.id}' reward_amount"
        )
    for prestige in raw.prestige_layers:
        _require_strings(
            prestige,
            (
                "id",
                "name",
                "trigger_resource",
                "reward_resource",
                "formula",
                "unlock_condition",
            ),
            "prestige_layer",
        )
        for field in ("divisor", "exponent", "min_gain"):
            _require_exact_number(
                getattr(prestige, field), f"prestige '{prestige.id}' {field}"
            )
        if not isinstance(prestige.reset_resources, list) or any(
            not isinstance(resource_id, str) or not resource_id
            for resource_id in prestige.reset_resources
        ):
            _raise_invalid(
                f"Prestige layer '{prestige.id}' reset_resources is malformed",
                "malformed_raw_config",
            )


def _require_strings(value: Any, fields: tuple[str, ...], entity: str) -> None:
    for field in fields:
        item = getattr(value, field)
        if not isinstance(item, str) or not item:
            _raise_invalid(
                f"{entity} field '{field}' is malformed", "malformed_raw_config"
            )


def _require_exact_number(value: Any, context: str) -> None:
    if isinstance(value, bool) or not isinstance(
        value, (str, int, float, Decimal, SimNumber)
    ):
        _raise_invalid(f"{context} is malformed", "malformed_raw_config")
    try:
        parsed = SimNumber.parse(value)
    except (DecimalException, ValueError, OverflowError):
        _raise_invalid(f"{context} is malformed", "malformed_raw_config")
    if parsed.log10_abs is not None and not parsed.log10_abs.is_finite():
        _raise_invalid(f"{context} is malformed", "malformed_raw_config")


def _validate_unique_ids(raw: RawConfig) -> None:
    for table_name in (
        "resources",
        "generators",
        "activities",
        "activity_outputs",
        "upgrades",
        "constants",
        "milestones",
        "prestige_layers",
    ):
        ids = [row.id for row in getattr(raw, table_name)]
        duplicates = sorted(
            row_id for row_id, count in Counter(ids).items() if count > 1
        )
        if duplicates:
            _raise_invalid(
                f"Raw table '{table_name}' has duplicate id '{duplicates[0]}'",
                "duplicate_id",
            )


def _validate_model_correspondence(raw: RawConfig, model: EconomyModel) -> None:
    expected_config = (
        raw.rules.model.id,
        raw.rules.model.tick_seconds,
        raw.rules.model.number_backend,
        int(raw.rules.model.random_seed or 0),
    )
    actual_config = (
        model.config.model_id,
        model.config.tick_seconds,
        model.config.number_backend,
        model.config.random_seed,
    )
    if actual_config != expected_config:
        _raise_model_mismatch("runtime settings")

    row_tables = (
        "resources",
        "generators",
        "activities",
        "activity_outputs",
        "upgrades",
        "milestones",
        "prestige_layers",
    )
    for name in row_tables:
        expected = {row.id: row for row in getattr(raw, name)}
        if dict(getattr(model, name)) != expected:
            _raise_model_mismatch(name)

    try:
        expected_constants = {
            row.id: SimNumber.parse(row.value) for row in raw.constants
        }
    except (DecimalException, ValueError) as exc:
        _raise_invalid(f"Model constant is not a valid exact number: {exc}", "invalid_number")
    if dict(model.constants) != expected_constants:
        _raise_model_mismatch("constants")

    rule_maps = (
        "generator_types",
        "source_types",
        "modifier_types",
        "behavior_policies",
        "session_patterns",
        "player_profiles",
        "scenarios",
        "rng_tables",
        "rng_scenarios",
    )
    for name in rule_maps:
        if dict(getattr(model, name)) != dict(getattr(raw.rules, name)):
            _raise_model_mismatch(name)
    if list(model.modifier_pipeline) != list(raw.rules.modifier_pipeline):
        _raise_model_mismatch("modifier_pipeline")

    if set(model.formulas) != set(raw.rules.formulas):
        _raise_model_mismatch("formulas")
    for formula_id in sorted(raw.rules.formulas):
        definition = raw.rules.formulas[formula_id]
        compiled = model.formulas[formula_id]
        if not isinstance(compiled, CompiledFormula):
            _raise_model_mismatch(f"formula '{formula_id}'")
        expected = FormulaEngine.compile(formula_id, definition.args, definition.expr)
        if (
            compiled.formula_id != expected.formula_id
            or compiled.args != expected.args
            or compiled.expr != expected.expr
            or ast.dump(compiled.tree) != ast.dump(expected.tree)
        ):
            _raise_model_mismatch(f"formula '{formula_id}'")


def _raise_model_mismatch(component: str) -> None:
    _raise_invalid(
        f"Runtime model does not correspond to raw {component}",
        "model_mismatch",
    )


def _raise_invalid(message: str, reason: str) -> NoReturn:
    raise AuthoringError("model_invalid", message, {"reason": reason})


def _deduplicate(findings: Sequence[EligibilityFinding]) -> tuple[EligibilityFinding, ...]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[EligibilityFinding] = []
    for finding in findings:
        key = (finding.code, finding.entity, finding.id)
        if key in seen:
            continue
        seen.add(key)
        result.append(finding)
    return tuple(result)


__all__ = [
    "EligibilityFinding",
    "EligibilityResult",
    "static_smoke_eligibility",
]
