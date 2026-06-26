from __future__ import annotations

from dataclasses import dataclass


class AnalyticLeapNotAvailable(NotImplementedError):
    pass


@dataclass(frozen=True)
class TimeEngine:
    tick_seconds: int

    def ticks_for_duration(self, duration_seconds: int) -> range:
        return range(0, duration_seconds + 1, self.tick_seconds)

    def analytic_leap(self, *_args, **_kwargs) -> None:
        raise AnalyticLeapNotAvailable("analytic leap is reserved for a later version")
