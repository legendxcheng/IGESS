from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError, replace
from datetime import date
import json
import os
from pathlib import Path

import pytest

from igess.authoring.probe import (
    EligibilityFinding,
    EligibilityResult,
    TenTickProbeResult,
    run_ten_tick_probe,
    static_smoke_eligibility,
)
from igess.authoring.response import AuthoringError
from igess.builder import ModelBuilder
from igess.linter import ConfigLinter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber
from igess.schema import (
    ActivityOutputRow,
    ActivityRow,
    ConstantRow,
    EconomyModel,
    FormulaDef,
    GeneratorRow,
    ModelSettings,
    PlayerProfile,
    RawConfig,
    ResourceRow,
    Rules,
    Scenario,
    Event,
    SimulationResult,
    SimulationState,
    TimelineRow,
)


def _number(value: str | int) -> SimNumber:
    return SimNumber.parse(value)


def _profile(
    profile_id: str,
    *,
    efficiencies: dict[str, str | int] | None = None,
    weights: dict[str, str | int] | None = None,
) -> PlayerProfile:
    return PlayerProfile(
        id=profile_id,
        source_efficiency={
            key: _number(value) for key, value in (efficiencies or {}).items()
        },
        activity_weights={key: _number(value) for key, value in (weights or {}).items()},
        behavior_policy="default",
        session_pattern="default",
        prestige_policy="conservative",
    )


def _raw(
    *,
    route: str = "none",
    resources: bool = True,
    profiles: tuple[PlayerProfile, ...] | None = None,
    starting_cost: str | None = None,
) -> RawConfig:
    if profiles is None:
        if route == "activity":
            profiles = (
                _profile("alpha", efficiencies={"active": "1"}, weights={"gather": "1"}),
                _profile("beta", efficiencies={"active": "2"}, weights={"gather": "3"}),
            )
        elif route == "generator":
            profiles = (
                _profile("alpha", efficiencies={"generator": "1"}),
                _profile("beta", efficiencies={"generator": "0.5"}),
            )
        else:
            profiles = (_profile("alpha"),)

    resource_rows = [ResourceRow("gold", "Gold", "currency")]
    if route == "generator":
        resource_rows.append(ResourceRow("energy", "Energy", "currency"))
    if not resources:
        resource_rows = []

    activities: list[ActivityRow] = []
    activity_outputs: list[ActivityOutputRow] = []
    generators: list[GeneratorRow] = []
    constants: list[ConstantRow] = []
    generator_types: dict[str, dict[str, str]] = {}
    if route == "activity":
        activities = [ActivityRow("gather", "Gather", "active", "always")]
        activity_outputs = [
            ActivityOutputRow("gather_gold", "gather", "gold", "0.125")
        ]
    elif route == "generator":
        generators = [
            GeneratorRow(
                "mine",
                "Mine",
                "building",
                "gold",
                "generator",
                "0.2",
                "10",
                "energy",
                "1.15",
                "always",
            )
        ]
        generator_types = {
            "building": {
                "cost_formula": "generator_cost",
                "production_formula": "generator_output",
            }
        }
        if starting_cost is not None:
            constants = [ConstantRow("starting_energy", starting_cost)]

    profile_map = {profile.id: profile for profile in profiles}
    rules = Rules(
        model=ModelSettings("test", 1, "bignum_log", 7),
        formulas={
            "generator_cost": FormulaDef(
                ["base_cost", "growth", "owned"], "base_cost * growth ^ owned"
            ),
            "generator_output": FormulaDef(
                ["base_output", "owned", "multiplier"],
                "base_output * owned * multiplier",
            ),
        },
        generator_types=generator_types,
        source_types={
            "active": {},
            "generator": {},
            "event": {},
            "offline": {},
            "time": {},
        },
        modifier_pipeline=[],
        modifier_types={},
        behavior_policies={"default": {"type": "cheap_unlock_first"}},
        session_patterns={"default": {}},
        player_profiles=profile_map,
        scenarios={
            "smoke": Scenario(
                "smoke", 0.1, list(profile_map), "new_player", 1, ["timeline"]
            )
        },
        rng_tables={},
        rng_scenarios={},
        regression_gates={},
    )
    return RawConfig(
        rules=rules,
        resources=resource_rows,
        generators=generators,
        activities=activities,
        activity_outputs=activity_outputs,
        upgrades=[],
        constants=constants,
        milestones=[],
        prestige_layers=[],
    )


def _evaluate(raw: RawConfig) -> EligibilityResult:
    return static_smoke_eligibility(raw, ModelBuilder.build(raw))


def _codes(result: EligibilityResult) -> list[str]:
    return [finding.code for finding in result.findings]


def _assert_model_invalid(raw: RawConfig, model=None) -> AuthoringError:
    if model is None:
        model = ModelBuilder.build(_raw(route="activity"))
    with pytest.raises(AuthoringError) as caught:
        static_smoke_eligibility(raw, model)
    assert caught.value.code == "model_invalid"
    json.dumps(dict(caught.value.details))
    return caught.value


def test_eligibility_payloads_are_frozen_json_safe_and_defensive() -> None:
    finding = EligibilityFinding("missing", "Add a resource", "resource", "gold")
    result = EligibilityResult(False, (finding,))

    assert finding.to_payload() == {
        "code": "missing",
        "message": "Add a resource",
        "entity": "resource",
        "id": "gold",
    }
    assert result.to_payload() == {
        "eligible": False,
        "findings": [finding.to_payload()],
    }
    json.dumps(result.to_payload())
    with pytest.raises(FrozenInstanceError):
        finding.code = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.eligible = True  # type: ignore[misc]

    source_findings = [finding]
    normalized = EligibilityResult(False, source_findings)  # type: ignore[arg-type]
    source_findings.clear()
    assert normalized.findings == (finding,)


@pytest.mark.parametrize(
    "values",
    [
        ("", "message", None, None),
        ("code", "", None, None),
        ("code", "message", 1, None),
        ("code", "message", None, []),
    ],
)
def test_finding_rejects_non_json_safe_or_empty_contract_values(values) -> None:
    with pytest.raises((TypeError, ValueError)):
        EligibilityFinding(*values)


def test_positive_activity_is_eligible_for_every_smoke_profile() -> None:
    result = _evaluate(_raw(route="activity"))

    assert result == EligibilityResult(True, ())


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda raw: setattr(raw.activities[0], "unlock_condition", "owned(ghost) >= 1"), None),
        (lambda raw: raw.activity_outputs.clear(), "activity_no_positive_output"),
        (
            lambda raw: raw.rules.player_profiles["beta"].activity_weights.pop("gather"),
            "activity_weight_nonpositive",
        ),
        (
            lambda raw: raw.rules.player_profiles["beta"].activity_weights.__setitem__(
                "gather", _number("0")
            ),
            "activity_weight_nonpositive",
        ),
        (
            lambda raw: raw.rules.player_profiles["beta"].source_efficiency.pop("active"),
            "activity_efficiency_nonpositive",
        ),
        (
            lambda raw: raw.rules.player_profiles["beta"].source_efficiency.__setitem__(
                "active", _number("-0.0000000000000000001")
            ),
            "activity_efficiency_nonpositive",
        ),
    ],
)
def test_activity_route_requires_every_dimension(mutate, expected_code) -> None:
    raw = _raw(route="activity")
    mutate(raw)
    if expected_code is None:
        _assert_model_invalid(raw)
        return

    result = _evaluate(raw)
    assert not result.eligible
    assert expected_code in _codes(result)
    assert _codes(result)[-1] == "no_executable_behavior"


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_invalid_activity_output_amount_is_structural(amount: str) -> None:
    raw = _raw(route="activity")
    raw.activity_outputs[0].amount_per_second = amount

    _assert_model_invalid(raw)


def test_one_good_activity_route_is_enough() -> None:
    raw = _raw(route="activity")
    raw.activities.insert(0, ActivityRow("blocked", "Blocked", "active", "always"))
    for profile in raw.rules.player_profiles.values():
        profile.activity_weights["blocked"] = _number("0")

    result = _evaluate(raw)

    assert result.eligible
    assert result.findings == ()


def test_affordable_positive_generator_is_eligible_for_every_profile() -> None:
    result = _evaluate(_raw(route="generator", starting_cost="10"))

    assert result == EligibilityResult(True, ())


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (lambda raw: setattr(raw.generators[0], "unlock_condition", "owned(mine) >= 1"), None),
        (lambda raw: setattr(raw.generators[0], "base_output", "0"), "generator_output_nonpositive"),
        (lambda raw: setattr(raw.generators[0], "base_output", "-1e-40"), "generator_output_nonpositive"),
        (lambda raw: setattr(raw.generators[0], "base_cost", "-1"), "generator_cost_negative"),
        (
            lambda raw: raw.rules.player_profiles["beta"].source_efficiency.pop("generator"),
            "generator_efficiency_nonpositive",
        ),
        (
            lambda raw: raw.rules.player_profiles["beta"].source_efficiency.__setitem__(
                "generator", _number("0")
            ),
            "generator_efficiency_nonpositive",
        ),
        (lambda raw: raw.constants.clear(), "generator_unaffordable"),
        (
            lambda raw: setattr(raw.constants[0], "value", "9.999999999999999999999999999"),
            "generator_unaffordable",
        ),
    ],
)
def test_generator_route_requires_every_dimension(mutate, expected_code) -> None:
    raw = _raw(route="generator", starting_cost="10")
    mutate(raw)
    if expected_code is None:
        _assert_model_invalid(raw)
        return

    result = _evaluate(raw)
    assert not result.eligible
    assert expected_code in _codes(result)
    assert _codes(result)[-1] == "no_executable_behavior"


def test_free_generator_is_affordable_with_no_starting_constant() -> None:
    raw = _raw(route="generator")
    raw.generators[0].base_cost = "0"

    assert _evaluate(raw).eligible


def test_generator_computed_cost_must_be_nonnegative() -> None:
    raw = _raw(route="generator", starting_cost="10")
    raw.rules.formulas["generator_cost"].expr = "-base_cost"

    result = _evaluate(raw)

    assert not result.eligible
    assert "generator_cost_negative" in _codes(result)


def test_generator_affordability_uses_computed_cost_when_formula_multiplies() -> None:
    raw = _raw(route="generator", starting_cost="15")
    raw.rules.formulas["generator_cost"].expr = "base_cost * 2"

    result = _evaluate(raw)

    assert not result.eligible
    assert "generator_unaffordable" in _codes(result)
    finding = next(
        item for item in result.findings if item.code == "generator_unaffordable"
    )
    assert "costs 20 energy" in finding.message


def test_generator_affordability_uses_computed_cost_when_formula_divides() -> None:
    raw = _raw(route="generator", starting_cost="6")
    raw.rules.formulas["generator_cost"].expr = "base_cost / 2"

    assert _evaluate(raw).eligible


@pytest.mark.parametrize("expr", ["base_output * 0", "-base_output"])
def test_generator_computed_production_must_be_positive(expr: str) -> None:
    raw = _raw(route="generator", starting_cost="10")
    raw.rules.formulas["generator_output"].expr = expr

    result = _evaluate(raw)

    assert not result.eligible
    assert "generator_output_nonpositive" in _codes(result)


def test_generator_production_formula_evaluation_error_is_structural() -> None:
    raw = _raw(route="generator", starting_cost="10")
    raw.rules.formulas["generator_output"].expr = "base_output / (owned - 1)"
    model = ModelBuilder.build(raw)

    _assert_model_invalid(raw, model)


def test_activity_or_generator_alone_is_enough() -> None:
    activity = _raw(route="activity")
    generator = _raw(
        route="generator",
        profiles=tuple(activity.rules.player_profiles.values()),
        starting_cost=None,
    )
    activity.generators = generator.generators
    activity.resources.append(ResourceRow("energy", "Energy", "currency"))
    activity.rules.generator_types = generator.rules.generator_types

    result = _evaluate(activity)

    assert result.eligible
    assert result.findings == ()


def test_zero_resources_is_independently_ineligible() -> None:
    result = _evaluate(_raw(resources=False))

    assert not result.eligible
    assert _codes(result)[0] == "no_resources"
    assert _codes(result)[-1] == "no_executable_behavior"


def test_event_time_and_starting_value_are_not_production_paths() -> None:
    raw = _raw()
    raw.constants = [ConstantRow("starting_gold", "100")]
    raw.rules.player_profiles["alpha"].source_efficiency.update(
        {"event": _number("1"), "offline": _number("1"), "time": _number("1")}
    )

    result = _evaluate(raw)

    assert not result.eligible
    assert "no_production_path" in _codes(result)
    assert _codes(result)[-1] == "no_executable_behavior"


@pytest.mark.parametrize(
    "break_raw",
    [
        lambda raw: raw.rules.scenarios.pop("smoke"),
        lambda raw: raw.rules.scenarios["smoke"].profiles.clear(),
        lambda raw: raw.rules.scenarios["smoke"].profiles.append("missing"),
        lambda raw: setattr(raw.activity_outputs[0], "output_resource", "missing"),
        lambda raw: setattr(raw.activities[0], "source_type", "missing"),
        lambda raw: setattr(raw.rules.formulas["generator_cost"], "expr", "base_cost + @"),
    ],
)
def test_missing_scenario_profile_reference_or_bad_formula_is_structural(break_raw) -> None:
    raw = _raw(route="activity")
    break_raw(raw)

    _assert_model_invalid(raw)


def test_malformed_numeric_runtime_value_is_structural() -> None:
    raw = _raw(route="generator", starting_cost="10")
    raw.generators[0].base_cost = "ten"

    _assert_model_invalid(raw)


def test_duplicate_raw_id_is_structural() -> None:
    raw = _raw(route="activity")
    raw.resources.append(copy.deepcopy(raw.resources[0]))

    _assert_model_invalid(raw)


def test_malformed_runtime_object_is_structural_not_attribute_error() -> None:
    raw = _raw(route="activity")
    raw.activities[0] = object()  # type: ignore[list-item]

    _assert_model_invalid(raw)


def test_malformed_profile_number_is_structural_not_type_error() -> None:
    raw = _raw(route="activity")
    raw.rules.player_profiles["alpha"].activity_weights["gather"] = "many"  # type: ignore[assignment]

    _assert_model_invalid(raw)


def test_malformed_condition_is_structural_not_type_error() -> None:
    raw = _raw(route="activity")
    raw.activities[0].unlock_condition = None  # type: ignore[assignment]

    _assert_model_invalid(raw)


def test_malformed_model_config_is_structural_not_attribute_error() -> None:
    raw = _raw(route="activity")
    model = ModelBuilder.build(raw)
    model.config = object()  # type: ignore[assignment]

    _assert_model_invalid(raw, model)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: setattr(raw.resources[0], "id", None),
        lambda raw: setattr(raw.rules.formulas["generator_cost"], "args", None),
        lambda raw: raw.rules.generator_types.__setitem__("broken", []),
        lambda raw: setattr(raw.rules.scenarios["smoke"], "duration_hours", "soon"),
    ],
)
def test_malformed_nested_shapes_are_structural_not_runtime_exceptions(mutate) -> None:
    raw = _raw(route="activity")
    mutate(raw)

    _assert_model_invalid(raw)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: setattr(raw.generators[0], "output_resource", []),
        lambda raw: setattr(raw.generators[0], "cost_resource", {}),
        lambda raw: setattr(raw.generators[0], "source_type", True),
        lambda raw: setattr(raw.generators[0], "generator_type", date(2026, 7, 15)),
        lambda raw: setattr(raw.generators[0], "unlock_condition", {}),
        lambda raw: setattr(raw.generators[0], "base_output", []),
        lambda raw: setattr(raw.generators[0], "base_cost", {}),
        lambda raw: setattr(raw.generators[0], "cost_growth", True),
    ],
)
def test_generator_input_shapes_are_rejected_before_lint(mutate) -> None:
    raw = _raw(route="generator", starting_cost="10")
    mutate(raw)

    error = _assert_model_invalid(raw)

    assert error.details["reason"] == "malformed_raw_config"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: setattr(raw.activities[0], "source_type", []),
        lambda raw: setattr(raw.activities[0], "unlock_condition", {}),
        lambda raw: setattr(raw.activity_outputs[0], "activity_id", []),
        lambda raw: setattr(raw.activity_outputs[0], "output_resource", {}),
        lambda raw: setattr(raw.activity_outputs[0], "amount_per_second", date(2026, 7, 15)),
        lambda raw: setattr(raw.rules.player_profiles["alpha"], "source_efficiency", []),
        lambda raw: raw.rules.player_profiles["alpha"].source_efficiency.__setitem__(True, _number("1")),
        lambda raw: raw.rules.player_profiles["alpha"].activity_weights.__setitem__("gather", date(2026, 7, 15)),
        lambda raw: setattr(raw.rules.scenarios["smoke"], "profiles", {}),
        lambda raw: setattr(raw.rules.scenarios["smoke"], "profiles", [True]),
        lambda raw: setattr(raw.constants[0], "value", []),
    ],
)
def test_activity_profile_scenario_and_constant_shapes_are_rejected_before_lint(
    mutate,
) -> None:
    raw = _raw(route="activity")
    raw.constants = [ConstantRow("starting_gold", "1")]
    mutate(raw)

    error = _assert_model_invalid(raw)

    assert error.details["reason"] == "malformed_raw_config"


def test_loader_linter_builder_support_activity_tables_and_legacy_profiles(tmp_path) -> None:
    config = tmp_path / "economy.yaml"
    tables = tmp_path / "tables"
    tables.mkdir()
    config.write_text(
        """
model:
  id: activity_clean_tree
  tick_seconds: 1
  number_backend: bignum_log
  random_seed: 7
formulas: {}
generator_types: {}
source_types:
  active: {}
modifier_pipeline:
  order: []
modifier_types: {}
behavior_policies:
  default:
    type: cheap_unlock_first
session_patterns:
  default: {}
player_profiles:
  alpha:
    source_efficiency:
      active: "1"
    behavior_policy: default
    session_pattern: default
    prestige_policy: conservative
scenarios:
  smoke:
    duration_hours: 0.1
    profiles: [alpha]
    start_state: new_player
    record_interval_seconds: 1
    outputs: [timeline]
""".lstrip(),
        encoding="utf-8",
    )
    source = {"table": "resources", "workbook": "resources.xlsx", "row": 4}
    (tables / "resources.json").write_text(
        json.dumps(
            [
                {
                    "id": "gold",
                    "name": "Gold",
                    "dimension": "currency",
                    "_source": source,
                }
            ]
        ),
        encoding="utf-8",
    )
    for name in ("generators", "upgrades", "constants"):
        (tables / f"{name}.json").write_text("[]", encoding="utf-8")
    (tables / "activities.json").write_text(
        json.dumps(
            [
                {
                    "id": "gather",
                    "name": "Gather",
                    "source_type": "active",
                    "unlock_condition": "always",
                    "_source": {
                        "table": "activities",
                        "workbook": "activities.xlsx",
                        "row": 4,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )
    (tables / "activity_outputs.json").write_text(
        json.dumps(
            [
                {
                    "id": "gather_gold",
                    "activity_id": "gather",
                    "output_resource": "gold",
                    "amount_per_second": "1",
                    "_source": {
                        "table": "activity_outputs",
                        "workbook": "activity_outputs.xlsx",
                        "row": 4,
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    raw = ConfigLoader.load(config, tables)
    ConfigLinter.validate(raw)
    model = ModelBuilder.build(raw)

    assert raw.rules.player_profiles["alpha"].activity_weights == {}
    assert set(model.activities) == {"gather"}
    assert set(model.activity_outputs) == {"gather_gold"}


def test_activity_schema_additions_preserve_all_legacy_constructor_signatures() -> None:
    profile_positional = PlayerProfile(
        "legacy",
        {"active": _number("1")},
        "default",
        "default",
        "conservative",
    )
    profile_keyword = PlayerProfile(
        id="legacy",
        source_efficiency={"active": _number("1")},
        behavior_policy="default",
        session_pattern="default",
        prestige_policy="conservative",
    )
    profile_modern = PlayerProfile(
        id="modern",
        source_efficiency={"active": _number("1")},
        behavior_policy="default",
        session_pattern="default",
        prestige_policy="conservative",
        activity_weights={"gather": _number("2")},
    )
    assert profile_positional.activity_weights == {}
    assert profile_keyword.activity_weights == {}
    assert profile_modern.activity_weights == {"gather": _number("2")}

    source = _raw()
    raw_values = (
        source.rules,
        source.resources,
        source.generators,
        source.upgrades,
        source.constants,
        source.milestones,
        source.prestige_layers,
    )
    raw_positional = RawConfig(*raw_values)
    raw_keyword = RawConfig(
        rules=source.rules,
        resources=source.resources,
        generators=source.generators,
        upgrades=source.upgrades,
        constants=source.constants,
        milestones=source.milestones,
        prestige_layers=source.prestige_layers,
    )
    raw_modern = RawConfig(
        *raw_values,
        activities=[ActivityRow("gather", "Gather", "active")],
        activity_outputs=[
            ActivityOutputRow("gather_gold", "gather", "gold", "1")
        ],
    )
    assert raw_positional.activities == raw_positional.activity_outputs == []
    assert raw_keyword.activities == raw_keyword.activity_outputs == []
    assert [item.id for item in raw_modern.activities] == ["gather"]

    built = ModelBuilder.build(source)
    model_values = (
        built.config,
        built.resources,
        built.generators,
        built.upgrades,
        built.constants,
        built.milestones,
        built.prestige_layers,
        built.formulas,
        built.generator_types,
        built.source_types,
        built.modifier_pipeline,
        built.modifier_types,
        built.behavior_policies,
        built.session_patterns,
        built.player_profiles,
        built.scenarios,
        built.rng_tables,
        built.rng_scenarios,
    )
    model_positional = EconomyModel(*model_values)
    model_keyword = EconomyModel(
        config=built.config,
        resources=built.resources,
        generators=built.generators,
        upgrades=built.upgrades,
        constants=built.constants,
        milestones=built.milestones,
        prestige_layers=built.prestige_layers,
        formulas=built.formulas,
        generator_types=built.generator_types,
        source_types=built.source_types,
        modifier_pipeline=built.modifier_pipeline,
        modifier_types=built.modifier_types,
        behavior_policies=built.behavior_policies,
        session_patterns=built.session_patterns,
        player_profiles=built.player_profiles,
        scenarios=built.scenarios,
        rng_tables=built.rng_tables,
        rng_scenarios=built.rng_scenarios,
    )
    model_modern = EconomyModel(
        *model_values,
        activities={"gather": ActivityRow("gather", "Gather", "active")},
        activity_outputs={
            "gather_gold": ActivityOutputRow(
                "gather_gold", "gather", "gold", "1"
            )
        },
    )
    assert model_positional.activities == model_positional.activity_outputs == {}
    assert model_keyword.activities == model_keyword.activity_outputs == {}
    assert set(model_modern.activities) == {"gather"}

    state_values = (
        {"gold": _number("1")},
        {"mine": 1},
        {"upgrade"},
        {"mine"},
        {"upgrade"},
        {"milestone"},
        {"prestige": 1},
    )
    state_positional = SimulationState(*state_values)
    state_keyword = SimulationState(
        resources=state_values[0],
        generators_owned=state_values[1],
        upgrades_purchased=state_values[2],
        unlocked_generators=state_values[3],
        unlocked_upgrades=state_values[4],
        milestones_claimed=state_values[5],
        prestige_counts=state_values[6],
    )
    state_modern = SimulationState(
        *state_values, unlocked_activities={"gather"}
    )
    assert state_positional.unlocked_activities == set()
    assert state_keyword.unlocked_activities == set()
    assert state_modern.unlocked_activities == {"gather"}


def test_raw_and_model_must_correspond() -> None:
    raw = _raw(route="activity")
    model = ModelBuilder.build(raw)
    model.resources.clear()

    error = _assert_model_invalid(raw, model)

    assert "model" in error.message.lower()


def test_findings_are_deterministic_across_source_insertion_order() -> None:
    first = _raw(route="activity")
    first.activities.extend(
        [
            ActivityRow("zeta", "Zeta", "active", "always"),
            ActivityRow("aardvark", "Aardvark", "active", "always"),
        ]
    )
    for profile in first.rules.player_profiles.values():
        profile.activity_weights.update(
            {"zeta": _number("0"), "aardvark": _number("0")}
        )
    first.activity_outputs.clear()
    second = copy.deepcopy(first)
    second.activities.reverse()
    second.rules.player_profiles = dict(
        reversed(list(second.rules.player_profiles.items()))
    )
    second.rules.scenarios["smoke"].profiles.reverse()

    first_payload = _evaluate(first).to_payload()
    second_payload = _evaluate(second).to_payload()

    assert first_payload == second_payload
    assert len(first_payload["findings"]) == len(
        {(item["code"], item.get("entity"), item.get("id")) for item in first_payload["findings"]}
    )


def test_programmer_type_error_is_not_silently_converted(monkeypatch) -> None:
    raw = _raw(route="activity")
    model = ModelBuilder.build(raw)

    def broken_validate(_raw: RawConfig) -> None:
        raise TypeError("programmer mistake")

    monkeypatch.setattr(ConfigLinter, "validate", broken_validate)

    with pytest.raises(TypeError, match="programmer mistake"):
        static_smoke_eligibility(raw, model)


def test_ten_tick_probe_is_frozen_json_safe_exact_and_non_mutating(tmp_path) -> None:
    raw = _raw(route="activity")
    raw.rules.model.tick_seconds = 3
    raw.rules.scenarios["smoke"].duration_hours = 999
    raw.rules.scenarios["smoke"].record_interval_seconds = 17
    raw.rules.scenarios["smoke"].time_mode = "analytic"
    model = ModelBuilder.build(raw)
    scenario_before = copy.deepcopy(model.scenarios["smoke"])

    result = run_ten_tick_probe(model)

    assert isinstance(result, TenTickProbeResult)
    assert result.observable_change is True
    assert result.findings == ()
    assert result.artifacts == ()
    assert result.report_index is None
    assert model.scenarios["smoke"] == scenario_before
    assert list(tmp_path.iterdir()) == []
    payload = result.to_payload()
    assert payload == {
        "observable_change": True,
        "findings": [],
        "artifacts": [],
        "report_index": None,
    }
    json.dumps(payload)
    with pytest.raises(FrozenInstanceError):
        result.observable_change = False  # type: ignore[misc]


def test_ten_tick_probe_result_defensively_normalizes_only_path_values(tmp_path) -> None:
    finding = EligibilityFinding("notice", "Notice")
    source_findings = [finding]
    source_artifacts = [tmp_path / "b.json", str(tmp_path / "a.json")]

    result = TenTickProbeResult(
        False,
        source_findings,  # type: ignore[arg-type]
        source_artifacts,  # type: ignore[arg-type]
        tmp_path / "index.html",  # type: ignore[arg-type]
    )
    source_findings.clear()
    source_artifacts.clear()

    assert result.findings == (finding,)
    assert result.artifacts == (
        str(tmp_path / "b.json"),
        str(tmp_path / "a.json"),
    )
    assert result.report_index == str(tmp_path / "index.html")
    json.dumps(result.to_payload())
    with pytest.raises(TypeError):
        TenTickProbeResult(False, (), (123,))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        TenTickProbeResult(False, (), (), 123)  # type: ignore[arg-type]


def _timeline_row(
    profile_id: str,
    time_seconds: int,
    *,
    resource: str = "0",
    owned: int = 0,
    purchased: tuple[str, ...] = (),
    prestige: int = 0,
) -> TimelineRow:
    return TimelineRow(
        scenario_id="smoke",
        profile_id=profile_id,
        time_seconds=time_seconds,
        resources={"gold": resource},
        generators_owned={"mine": owned},
        upgrades_purchased=list(purchased),
        total_cps="999",
        prestige_counts={"rebirth": prestige},
    )


@pytest.mark.parametrize(
    "final",
    [
        _timeline_row("alpha", 10, resource="0.0000000000000000000000000001"),
        _timeline_row("alpha", 10, owned=1),
        _timeline_row("alpha", 10, purchased=("boost",)),
        _timeline_row("alpha", 10, prestige=1),
    ],
    ids=("resource", "owned_generator", "purchased_upgrade", "prestige_count"),
)
def test_ten_tick_probe_detects_each_exact_state_category(monkeypatch, final) -> None:
    model = ModelBuilder.build(_raw())
    simulation = SimulationResult(
        "smoke",
        [_timeline_row("alpha", 0), final],
        [],
    )
    monkeypatch.setattr(
        "igess.authoring.probe.Simulator.run_scenario",
        lambda self, scenario_id: simulation,
    )

    result = run_ten_tick_probe(model)

    assert result.observable_change is True
    assert result.findings == ()


def test_elapsed_cps_unlocks_events_and_decimal_spelling_do_not_count(monkeypatch) -> None:
    model = ModelBuilder.build(_raw())
    simulation = SimulationResult(
        "smoke",
        [
            _timeline_row("zeta", 0, resource="1"),
            _timeline_row("zeta", 10, resource="1.0"),
            _timeline_row("alpha", 0, resource="0"),
            _timeline_row("alpha", 10, resource="0e99"),
        ],
        [Event("smoke", "alpha", 0, "unlock_generator", "mine", {})],
    )
    monkeypatch.setattr(
        "igess.authoring.probe.Simulator.run_scenario",
        lambda self, scenario_id: simulation,
    )

    result = run_ten_tick_probe(model)

    assert result.observable_change is False
    assert [finding.code for finding in result.findings] == ["smoke_no_state_change"]
    assert result.to_payload()["findings"] == [
        {
            "code": "smoke_no_state_change",
            "message": "The ten-tick smoke probe completed without an observable state change.",
        }
    ]


@pytest.mark.parametrize(
    "break_model",
    [
        lambda model: replace(model, config=replace(model.config, tick_seconds=0)),
        lambda model: replace(model, scenarios={}),
        lambda model: replace(
            model,
            scenarios={"smoke": replace(model.scenarios["smoke"], profiles=[])},
        ),
        lambda model: replace(
            model,
            scenarios={"smoke": replace(model.scenarios["smoke"], profiles=["missing"])},
        ),
    ],
    ids=("nonpositive_tick", "missing_scenario", "empty_profiles", "unknown_profile"),
)
def test_ten_tick_probe_reports_build_setup_failures(break_model) -> None:
    model = break_model(ModelBuilder.build(_raw(route="activity")))

    with pytest.raises(AuthoringError) as caught:
        run_ten_tick_probe(model)

    assert caught.value.code == "smoke_failed"
    assert caught.value.details["phase"] == "build"
    assert isinstance(caught.value.details["original_type"], str)
    json.dumps(dict(caught.value.details))


def test_ten_tick_probe_splits_simulator_construction_and_execution_failures(
    monkeypatch,
) -> None:
    model = ModelBuilder.build(_raw(route="activity"))

    class BrokenSimulator:
        def __init__(self, model) -> None:
            raise LookupError("could not build")

    monkeypatch.setattr("igess.authoring.probe.Simulator", BrokenSimulator)
    with pytest.raises(AuthoringError) as build:
        run_ten_tick_probe(model)
    assert dict(build.value.details) == {
        "original_type": "LookupError",
        "phase": "build",
    }

    class RunBrokenSimulator:
        def __init__(self, model) -> None:
            pass

        def run_scenario(self, scenario_id):
            raise RuntimeError("could not execute")

    monkeypatch.setattr("igess.authoring.probe.Simulator", RunBrokenSimulator)
    with pytest.raises(AuthoringError) as execution:
        run_ten_tick_probe(model)
    assert dict(execution.value.details) == {
        "original_type": "RuntimeError",
        "phase": "execution",
    }


def test_ten_tick_probe_does_not_convert_cancellation(monkeypatch) -> None:
    model = ModelBuilder.build(_raw(route="activity"))

    class CancelledSimulator:
        def __init__(self, model) -> None:
            raise KeyboardInterrupt()

    monkeypatch.setattr("igess.authoring.probe.Simulator", CancelledSimulator)
    with pytest.raises(KeyboardInterrupt):
        run_ten_tick_probe(model)


def test_ten_tick_probe_atomically_publishes_complete_run_and_report(tmp_path) -> None:
    model = ModelBuilder.build(_raw(route="activity"))
    artifact_root = tmp_path / "probe"

    result = run_ten_tick_probe(model, artifact_root=artifact_root)

    assert artifact_root.is_dir()
    assert result.report_index == str(artifact_root / "report" / "index.html")
    assert result.artifacts == tuple(sorted(result.artifacts))
    assert result.artifacts
    assert all(Path(path).is_file() for path in result.artifacts)
    assert str(artifact_root / "run" / "timeline.json") in result.artifacts
    assert result.report_index in result.artifacts
    timeline = json.loads(
        (artifact_root / "run" / "timeline.json").read_text(encoding="utf-8")
    )
    assert {row["time_seconds"] for row in timeline} == set(range(11))
    json.loads((artifact_root / "report" / "report_data.json").read_text(encoding="utf-8"))
    assert not list(tmp_path.glob(".probe-probe-*"))


@pytest.mark.parametrize("failure_point", ["writer", "report"])
def test_ten_tick_probe_artifact_failures_leave_no_partial_target(
    tmp_path, monkeypatch, failure_point
) -> None:
    model = ModelBuilder.build(_raw(route="activity"))
    artifact_root = tmp_path / "probe"

    if failure_point == "writer":
        def fail_writer(result, output_dir, model=None, overrides=None):
            output = Path(output_dir)
            output.mkdir(parents=True)
            (output / "partial.txt").write_text("partial", encoding="utf-8")
            raise OSError("writer failed")

        monkeypatch.setattr("igess.authoring.probe.OutputWriter.write_all", fail_writer)
    else:
        def fail_report(run_dir, output_dir, title=None):
            output = Path(output_dir)
            output.mkdir(parents=True)
            (output / "partial.txt").write_text("partial", encoding="utf-8")
            raise ValueError("report failed")

        monkeypatch.setattr("igess.authoring.probe.generate_static_report", fail_report)

    with pytest.raises(AuthoringError) as caught:
        run_ten_tick_probe(model, artifact_root=artifact_root)

    assert caught.value.code == "smoke_failed"
    assert dict(caught.value.details) == {
        "original_type": "OSError" if failure_point == "writer" else "ValueError",
        "phase": "artifact",
    }
    assert not artifact_root.exists()
    assert not list(tmp_path.glob(".probe-probe-*"))


def test_ten_tick_probe_preserves_preexisting_nonempty_artifact_target(tmp_path) -> None:
    model = ModelBuilder.build(_raw(route="activity"))
    artifact_root = tmp_path / "probe"
    artifact_root.mkdir()
    sentinel = artifact_root / "mine.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(AuthoringError) as caught:
        run_ten_tick_probe(model, artifact_root=artifact_root)

    assert caught.value.code == "smoke_failed"
    assert caught.value.details["phase"] == "artifact"
    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert list(artifact_root.iterdir()) == [sentinel]


def test_ten_tick_probe_treats_publish_replace_then_raise_as_committed(
    tmp_path, monkeypatch
) -> None:
    model = ModelBuilder.build(_raw(route="activity"))
    artifact_root = tmp_path / "probe"
    real_replace = os.replace

    def replace_then_raise(source, target):
        real_replace(source, target)
        if Path(target) == artifact_root:
            raise OSError("reported failure after rename")

    monkeypatch.setattr("igess.authoring.probe.os.replace", replace_then_raise)

    result = run_ten_tick_probe(model, artifact_root=artifact_root)

    assert Path(result.report_index).is_file()
    assert artifact_root.is_dir()
