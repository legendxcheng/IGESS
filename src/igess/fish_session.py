from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SECONDS_PER_DAY = 24 * 60 * 60


class FishSessionConfigError(ValueError):
    """Raised when a Fish player session pattern is invalid."""


@dataclass(frozen=True)
class FishDailySessionSchedule:
    """Deterministic daily online window used by the Fish behavior loop.

    Simulation time zero is the beginning of the player's first daily online
    session. A missing ``daily_online_seconds`` keeps legacy profiles online
    for the full simulation.
    """

    daily_online_seconds: int = SECONDS_PER_DAY

    def __post_init__(self) -> None:
        value = self.daily_online_seconds
        if (
            type(value) is not int
            or value <= 0
            or value > SECONDS_PER_DAY
        ):
            raise FishSessionConfigError(
                "daily_online_seconds must be an integer within "
                f"[1, {SECONDS_PER_DAY}]"
            )

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
    ) -> "FishDailySessionSchedule":
        if not isinstance(payload, Mapping):
            raise FishSessionConfigError(
                "Fish session pattern must be a mapping"
            )
        value = payload.get("daily_online_seconds", SECONDS_PER_DAY)
        return cls(daily_online_seconds=value)

    @property
    def always_online(self) -> bool:
        return self.daily_online_seconds == SECONDS_PER_DAY

    def is_online(self, time_seconds: int) -> bool:
        self._validate_time(time_seconds)
        if self.always_online:
            return True
        return (
            time_seconds % SECONDS_PER_DAY
            < self.daily_online_seconds
        )

    def next_transition_after(self, time_seconds: int) -> int | None:
        """Return the next strict online/offline boundary after ``time``."""

        self._validate_time(time_seconds)
        if self.always_online:
            return None
        day_start = (time_seconds // SECONDS_PER_DAY) * SECONDS_PER_DAY
        offline_start = day_start + self.daily_online_seconds
        if time_seconds < offline_start:
            return offline_start
        return day_start + SECONDS_PER_DAY

    def online_seconds_remaining(self, time_seconds: int) -> int:
        self._validate_time(time_seconds)
        if not self.is_online(time_seconds):
            return 0
        transition = self.next_transition_after(time_seconds)
        if transition is None:
            return SECONDS_PER_DAY
        return transition - time_seconds

    @staticmethod
    def _validate_time(time_seconds: int) -> None:
        if type(time_seconds) is not int or time_seconds < 0:
            raise ValueError("time_seconds must be a non-negative integer")
