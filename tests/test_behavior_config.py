from pathlib import Path

import pytest
import yaml

from igess.linter import ConfigError, ConfigLinter
from igess.loader import ConfigLoader
from igess.numbers import SimNumber


SAMPLE_CONFIG = Path("examples/shelldiver_v0/economy.yaml")


def _write_config(tmp_path: Path, profile_fields: dict[str, object]) -> Path:
    data = yaml.safe_load(SAMPLE_CONFIG.read_text(encoding="utf-8"))
    data["player_profiles"]["casual"].update(profile_fields)
    config = tmp_path / "economy.yaml"
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return config


def test_loader_reads_player_behavior_profile_separately_from_activity_weights(
    tmp_path: Path,
) -> None:
    config = _write_config(
        tmp_path,
        {
            "behavior_weights": {
                "upgrade_fish": "5",
                "manual_throw": "50",
                "idle": 0,
            },
            "behavior_durations": {
                "upgrade_fish": {
                    "type": "uniform",
                    "min_seconds": 3,
                    "max_seconds": 8,
                },
                "manual_throw": {"type": "fixed", "seconds": 12},
            },
            "behavior_target_policies": {
                "upgrade_fish": "fastest_payback",
            },
        },
    )

    raw = ConfigLoader.load_rules_only(config)
    ConfigLinter.validate(raw)
    profile = raw.rules.player_profiles["casual"]

    assert list(profile.behavior_weights) == ["idle", "manual_throw", "upgrade_fish"]
    assert profile.behavior_weights["manual_throw"] == SimNumber.parse(50)
    assert profile.behavior_weights["idle"] == SimNumber.zero()
    assert profile.behavior_durations == {
        "manual_throw": {"type": "fixed", "seconds": 12},
        "upgrade_fish": {
            "type": "uniform",
            "min_seconds": 3,
            "max_seconds": 8,
        },
    }
    assert profile.behavior_target_policies == {
        "upgrade_fish": "fastest_payback",
    }
    assert {
        key: value.to_decimal_string()
        for key, value in profile.activity_weights.items()
    } == {
        "deep_dive": "1",
        "gather_shells": "3",
    }


def test_legacy_profiles_default_to_empty_behavior_configuration() -> None:
    raw = ConfigLoader.load_rules_only(SAMPLE_CONFIG)

    ConfigLinter.validate(raw)

    for profile in raw.rules.player_profiles.values():
        assert profile.behavior_weights == {}
        assert profile.behavior_durations == {}
        assert profile.behavior_target_policies == {}


def test_linter_rejects_negative_behavior_weight() -> None:
    raw = ConfigLoader.load_rules_only(SAMPLE_CONFIG)
    raw.rules.player_profiles["casual"].behavior_weights["upgrade_fish"] = SimNumber.parse("-1")

    with pytest.raises(ConfigError, match="behavior_weight 'upgrade_fish' must be non-negative"):
        ConfigLinter.validate(raw)


@pytest.mark.parametrize(
    ("duration", "message"),
    [
        ({"type": "fixed", "seconds": 0}, "seconds must be a positive integer"),
        ({"type": "fixed", "seconds": True}, "seconds must be a positive integer"),
        ({"type": "fixed", "seconds": 1.5}, "seconds must be a positive integer"),
        ({"type": "fixed"}, "must contain only type and seconds"),
        (
            {"type": "fixed", "seconds": 5, "extra": 1},
            "must contain only type and seconds",
        ),
        (
            {"type": "uniform", "min_seconds": 0, "max_seconds": 5},
            "min_seconds must be a positive integer",
        ),
        (
            {"type": "uniform", "min_seconds": 5, "max_seconds": 0},
            "max_seconds must be a positive integer",
        ),
        (
            {"type": "uniform", "min_seconds": 8, "max_seconds": 3},
            "min_seconds must not exceed max_seconds",
        ),
        (
            {"type": "uniform", "min_seconds": 3, "max_seconds": 8, "extra": 1},
            "must contain only type, min_seconds, and max_seconds",
        ),
        ({"type": "normal", "seconds": 5}, "type must be 'fixed' or 'uniform'"),
        ("5 seconds", "must be a mapping"),
    ],
)
def test_linter_strictly_validates_behavior_durations(
    duration: object, message: str
) -> None:
    raw = ConfigLoader.load_rules_only(SAMPLE_CONFIG)
    raw.rules.player_profiles["casual"].behavior_durations["upgrade_fish"] = duration  # type: ignore[assignment]

    with pytest.raises(ConfigError, match=message):
        ConfigLinter.validate(raw)


@pytest.mark.parametrize("policy", ["", "   ", None, 3])
def test_linter_rejects_empty_or_non_string_target_policy(policy: object) -> None:
    raw = ConfigLoader.load_rules_only(SAMPLE_CONFIG)
    raw.rules.player_profiles["casual"].behavior_target_policies["upgrade_fish"] = policy  # type: ignore[assignment]

    with pytest.raises(
        ConfigError,
        match="behavior_target_policy 'upgrade_fish' must be non-empty",
    ):
        ConfigLinter.validate(raw)


def test_loader_preserves_invalid_target_policy_for_linter(tmp_path: Path) -> None:
    config = _write_config(
        tmp_path,
        {"behavior_target_policies": {"upgrade_fish": None}},
    )
    raw = ConfigLoader.load_rules_only(config)

    with pytest.raises(ConfigError, match="must be non-empty"):
        ConfigLinter.validate(raw)
