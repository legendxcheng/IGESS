from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
from datetime import date
import json

import pytest

from igess.authoring.probe import (
    EligibilityFinding,
    EligibilityResult,
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
    FormulaDef,
    GeneratorRow,
    ModelSettings,
    PlayerProfile,
    RawConfig,
    ResourceRow,
    Rules,
    Scenario,
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
