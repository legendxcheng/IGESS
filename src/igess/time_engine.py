from __future__ import annotations

from dataclasses import dataclass

from .numbers import SimNumber


class AnalyticLeapNotAvailable(NotImplementedError):
    pass


@dataclass(frozen=True)
class TimeEngine:
    tick_seconds: int

    def ticks_for_duration(self, duration_seconds: int) -> range:
        return range(0, duration_seconds + 1, self.tick_seconds)

    def tick_steps_for_duration(self, duration_seconds: int) -> list[int]:
        steps = list(range(self.tick_seconds, duration_seconds + 1, self.tick_seconds))
        if duration_seconds > 0 and (not steps or steps[-1] != duration_seconds):
            steps.append(duration_seconds)
        return steps

    def seconds_until_affordable(
        self, current: SimNumber, cost: SimNumber, cps: SimNumber
    ) -> int | None:
        if current >= cost:
            return 0
        if cps <= SimNumber.zero():
            return None
        needed = cost - current
        seconds = (needed / cps).ceil()
        return max(0, int(seconds.decimal))

    def analytic_leap(self, current_time: int, next_time: int) -> int:
        if next_time <= current_time:
            raise ValueError("analytic leap next_time must be greater than current_time")
        return next_time - current_time
