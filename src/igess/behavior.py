from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, TypeAlias, TypeVar

from .numbers import SimNumber


IDLE_BEHAVIOR_ID = "idle"
_RANDOM_SCHEMA = "igess.behavior.v1"
_RUNTIME_SCHEMA_VERSION = 1
_DIGEST_MODULUS = 1 << 256


class NoAvailableBehaviorError(ValueError):
    """Raised when a profile has no positive-weight, available behavior."""


@dataclass(frozen=True)
class FixedDuration:
    """A behavior duration that always consumes the same positive number of seconds."""

    seconds: int

    def __post_init__(self) -> None:
        _positive_int(self.seconds, "seconds")


@dataclass(frozen=True)
class UniformIntDuration:
    """An inclusive uniform integer duration in seconds."""

    min_seconds: int
    max_seconds: int

    def __post_init__(self) -> None:
        _positive_int(self.min_seconds, "min_seconds")
        _positive_int(self.max_seconds, "max_seconds")
        if self.max_seconds < self.min_seconds:
            raise ValueError("max_seconds must be greater than or equal to min_seconds")


DurationSpec: TypeAlias = FixedDuration | UniformIntDuration
_Choice = TypeVar("_Choice")


@dataclass(frozen=True)
class BehaviorTarget:
    """One available target after a behavior has been selected."""

    target_id: str
    weight: SimNumber = field(default_factory=SimNumber.one)
    available: bool = True

    def __post_init__(self) -> None:
        _identifier(self.target_id, "target_id")
        _exact_bool(self.available, "available")
        object.__setattr__(self, "weight", _weight(self.weight, "weight"))


@dataclass(frozen=True)
class BehaviorCandidate:
    """A domain-provided behavior and its currently valid target choices."""

    behavior_id: str
    duration: DurationSpec
    available: bool = True
    targets: tuple[BehaviorTarget, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.behavior_id, "behavior_id")
        if not isinstance(self.duration, (FixedDuration, UniformIntDuration)):
            raise TypeError("duration must be FixedDuration or UniformIntDuration")
        _exact_bool(self.available, "available")
        targets = tuple(self.targets)
        if any(not isinstance(target, BehaviorTarget) for target in targets):
            raise TypeError("targets must contain only BehaviorTarget values")
        _reject_duplicate_ids(
            (target.target_id for target in targets),
            "target_id",
        )
        object.__setattr__(self, "targets", targets)

    @classmethod
    def idle(
        cls,
        duration: DurationSpec,
        *,
        available: bool = True,
    ) -> "BehaviorCandidate":
        """Build the targetless behavior used for waiting, observing, or hesitating."""

        return cls(
            behavior_id=IDLE_BEHAVIOR_ID,
            duration=duration,
            available=available,
        )


@dataclass(frozen=True)
class BehaviorProfile:
    """Player-specific behavior weights; weights need not already be normalized."""

    profile_id: str
    weights: Mapping[str, SimNumber]

    def __post_init__(self) -> None:
        _identifier(self.profile_id, "profile_id")
        if not isinstance(self.weights, Mapping):
            raise TypeError("weights must be a mapping")
        normalized: dict[str, SimNumber] = {}
        for behavior_id, value in self.weights.items():
            _identifier(behavior_id, "weights key")
            normalized[behavior_id] = _weight(
                value,
                f"weights[{behavior_id!r}]",
            )
        object.__setattr__(self, "weights", dict(sorted(normalized.items())))


@dataclass(frozen=True)
class WeightedBehaviorCandidate:
    """An available candidate paired with its normalized player probability."""

    candidate: BehaviorCandidate
    weight: SimNumber
    probability: SimNumber


@dataclass(frozen=True)
class BehaviorDecision:
    """A replayable discrete player action scheduled on the simulation clock."""

    sequence_id: int
    profile_id: str
    behavior_id: str
    target_id: str | None
    duration_seconds: int
    started_at_seconds: int
    completes_at_seconds: int

    def __post_init__(self) -> None:
        _non_negative_int(self.sequence_id, "sequence_id")
        _identifier(self.profile_id, "profile_id")
        _identifier(self.behavior_id, "behavior_id")
        if self.target_id is not None:
            _identifier(self.target_id, "target_id")
        _positive_int(self.duration_seconds, "duration_seconds")
        _non_negative_int(self.started_at_seconds, "started_at_seconds")
        _non_negative_int(self.completes_at_seconds, "completes_at_seconds")
        if (
            self.completes_at_seconds
            != self.started_at_seconds + self.duration_seconds
        ):
            raise ValueError(
                "completes_at_seconds must equal "
                "started_at_seconds + duration_seconds"
            )

    def to_dict(self) -> dict[str, int | str | None]:
        return {
            "sequence_id": self.sequence_id,
            "profile_id": self.profile_id,
            "behavior_id": self.behavior_id,
            "target_id": self.target_id,
            "duration_seconds": self.duration_seconds,
            "started_at_seconds": self.started_at_seconds,
            "completes_at_seconds": self.completes_at_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BehaviorDecision":
        if not isinstance(payload, Mapping):
            raise TypeError("active behavior must be a mapping")
        expected = {
            "sequence_id",
            "profile_id",
            "behavior_id",
            "target_id",
            "duration_seconds",
            "started_at_seconds",
            "completes_at_seconds",
        }
        if set(payload) != expected:
            raise ValueError("active behavior has invalid fields")
        return cls(
            sequence_id=payload["sequence_id"],
            profile_id=payload["profile_id"],
            behavior_id=payload["behavior_id"],
            target_id=payload["target_id"],
            duration_seconds=payload["duration_seconds"],
            started_at_seconds=payload["started_at_seconds"],
            completes_at_seconds=payload["completes_at_seconds"],
        )


@dataclass(frozen=True)
class BehaviorRuntimeState:
    """Serializable scheduler cursor and optional in-flight behavior."""

    next_sequence_id: int = 0
    active: BehaviorDecision | None = None

    def __post_init__(self) -> None:
        _non_negative_int(self.next_sequence_id, "next_sequence_id")
        if self.active is not None:
            if not isinstance(self.active, BehaviorDecision):
                raise TypeError("active must be a BehaviorDecision")
            if self.next_sequence_id != self.active.sequence_id + 1:
                raise ValueError(
                    "next_sequence_id must immediately follow active.sequence_id"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": _RUNTIME_SCHEMA_VERSION,
            "next_sequence_id": self.next_sequence_id,
            "active": None if self.active is None else self.active.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BehaviorRuntimeState":
        if not isinstance(payload, Mapping):
            raise TypeError("behavior runtime state must be a mapping")
        if set(payload) != {"version", "next_sequence_id", "active"}:
            raise ValueError("behavior runtime state has invalid fields")
        if (
            type(payload["version"]) is not int
            or payload["version"] != _RUNTIME_SCHEMA_VERSION
        ):
            raise ValueError("behavior runtime state version is unsupported")
        active_payload = payload["active"]
        active = (
            None
            if active_payload is None
            else BehaviorDecision.from_dict(active_payload)
        )
        return cls(
            next_sequence_id=payload["next_sequence_id"],
            active=active,
        )


class BehaviorScheduler:
    """Select behaviors, targets, and durations from independent stable RNG domains."""

    def __init__(self, root_seed: int):
        if type(root_seed) is not int:
            raise TypeError("root_seed must be an integer")
        self.root_seed = root_seed

    def normalized_candidates(
        self,
        candidates: tuple[BehaviorCandidate, ...] | list[BehaviorCandidate],
        profile: BehaviorProfile,
    ) -> tuple[WeightedBehaviorCandidate, ...]:
        """Filter unavailable/zero-weight candidates and normalize remaining weights."""

        if not isinstance(profile, BehaviorProfile):
            raise TypeError("profile must be a BehaviorProfile")
        supplied = tuple(candidates)
        if any(not isinstance(candidate, BehaviorCandidate) for candidate in supplied):
            raise TypeError("candidates must contain only BehaviorCandidate values")
        _reject_duplicate_ids(
            (candidate.behavior_id for candidate in supplied),
            "behavior_id",
        )

        eligible: list[tuple[BehaviorCandidate, SimNumber]] = []
        for candidate in sorted(supplied, key=lambda item: item.behavior_id):
            weight = profile.weights.get(candidate.behavior_id, SimNumber.zero())
            if (
                candidate.available
                and weight > SimNumber.zero()
                and _has_available_target(candidate)
            ):
                eligible.append((candidate, weight))

        total = sum((weight for _, weight in eligible), SimNumber.zero())
        if total <= SimNumber.zero():
            raise NoAvailableBehaviorError(
                f"profile {profile.profile_id!r} has no available positive-weight behavior"
            )
        return tuple(
            WeightedBehaviorCandidate(
                candidate=candidate,
                weight=weight,
                probability=weight / total,
            )
            for candidate, weight in eligible
        )

    def decide(
        self,
        candidates: tuple[BehaviorCandidate, ...] | list[BehaviorCandidate],
        profile: BehaviorProfile,
        *,
        sequence_id: int,
        started_at_seconds: int,
    ) -> BehaviorDecision:
        """Schedule one decision; the same inputs and sequence id replay identically."""

        _non_negative_int(sequence_id, "sequence_id")
        _non_negative_int(started_at_seconds, "started_at_seconds")
        weighted = self.normalized_candidates(candidates, profile)
        selected = _select_weighted(
            tuple((item.candidate, item.probability) for item in weighted),
            fraction=_stable_fraction(
                self.root_seed,
                profile.profile_id,
                sequence_id,
                "behavior_choice",
            ),
        )
        duration = _sample_duration(
            selected.duration,
            root_seed=self.root_seed,
            profile_id=profile.profile_id,
            sequence_id=sequence_id,
        )
        target_id = _select_target(
            selected,
            root_seed=self.root_seed,
            profile_id=profile.profile_id,
            sequence_id=sequence_id,
        )
        return BehaviorDecision(
            sequence_id=sequence_id,
            profile_id=profile.profile_id,
            behavior_id=selected.behavior_id,
            target_id=target_id,
            duration_seconds=duration,
            started_at_seconds=started_at_seconds,
            completes_at_seconds=started_at_seconds + duration,
        )


def _has_available_target(candidate: BehaviorCandidate) -> bool:
    if not candidate.targets:
        return True
    return any(
        target.available and target.weight > SimNumber.zero()
        for target in candidate.targets
    )


def _select_target(
    candidate: BehaviorCandidate,
    *,
    root_seed: int,
    profile_id: str,
    sequence_id: int,
) -> str | None:
    if not candidate.targets:
        return None
    targets = tuple(
        (target, target.weight)
        for target in sorted(candidate.targets, key=lambda item: item.target_id)
        if target.available and target.weight > SimNumber.zero()
    )
    total = sum((weight for _, weight in targets), SimNumber.zero())
    selected = _select_weighted(
        tuple((target, weight / total) for target, weight in targets),
        fraction=_stable_fraction(
            root_seed,
            profile_id,
            sequence_id,
            "behavior_target",
        ),
    )
    return selected.target_id


def _sample_duration(
    duration: DurationSpec,
    *,
    root_seed: int,
    profile_id: str,
    sequence_id: int,
) -> int:
    if isinstance(duration, FixedDuration):
        return duration.seconds
    width = duration.max_seconds - duration.min_seconds + 1
    offset = _stable_integer(
        root_seed,
        profile_id,
        sequence_id,
        "behavior_duration",
        width,
    )
    return duration.min_seconds + offset


def _select_weighted(
    choices: tuple[tuple[_Choice, SimNumber], ...],
    *,
    fraction: Decimal,
) -> _Choice:
    threshold = SimNumber.parse(fraction)
    cumulative = SimNumber.zero()
    for choice, probability in choices:
        cumulative += probability
        if threshold < cumulative:
            return choice
    # SimNumber normalization can differ from one at its last representable digits.
    return choices[-1][0]


def _stable_fraction(
    root_seed: int,
    profile_id: str,
    sequence_id: int,
    domain: str,
) -> Decimal:
    value = _digest(root_seed, profile_id, sequence_id, domain, 0)
    return Decimal(value) / Decimal(_DIGEST_MODULUS)


def _stable_integer(
    root_seed: int,
    profile_id: str,
    sequence_id: int,
    domain: str,
    upper_bound: int,
) -> int:
    if upper_bound <= 0 or upper_bound > _DIGEST_MODULUS:
        raise ValueError("random integer range must be between 1 and 2^256")
    limit = _DIGEST_MODULUS - (_DIGEST_MODULUS % upper_bound)
    nonce = 0
    while True:
        value = _digest(root_seed, profile_id, sequence_id, domain, nonce)
        if value < limit:
            return value % upper_bound
        nonce += 1


def _digest(
    root_seed: int,
    profile_id: str,
    sequence_id: int,
    domain: str,
    nonce: int,
) -> int:
    payload = json.dumps(
        [
            _RANDOM_SCHEMA,
            root_seed,
            profile_id,
            sequence_id,
            domain,
            nonce,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest(), "big")


def _weight(value: object, field_name: str) -> SimNumber:
    try:
        parsed = SimNumber.parse(value)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"{field_name} must be a non-negative number") from exc
    if parsed < SimNumber.zero():
        raise ValueError(f"{field_name} must be a non-negative number")
    return parsed


def _identifier(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed string")


def _positive_int(value: object, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _non_negative_int(value: object, field_name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")


def _exact_bool(value: object, field_name: str) -> None:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")


def _reject_duplicate_ids(values: object, field_name: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {field_name}: {value!r}")
        seen.add(value)
