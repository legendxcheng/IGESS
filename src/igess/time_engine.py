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

    def recurring_event_times(
        self,
        start_seconds: int,
        end_seconds: int,
        interval_seconds: int,
    ) -> range:
        """Return absolute recurring boundaries in ``(start, end]``."""

        if type(start_seconds) is not int or start_seconds < 0:
            raise ValueError("event start_seconds must be a non-negative integer")
        if type(end_seconds) is not int or end_seconds < start_seconds:
            raise ValueError("event end_seconds must not precede start_seconds")
        if type(interval_seconds) is not int or interval_seconds <= 0:
            raise ValueError("event interval_seconds must be a positive integer")
        first = ((start_seconds // interval_seconds) + 1) * interval_seconds
        return range(first, end_seconds + 1, interval_seconds)

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
