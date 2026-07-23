from igess.numbers import SimNumber
from igess.time_engine import TimeEngine


def test_time_engine_calculates_next_affordable_seconds():
    engine = TimeEngine(tick_seconds=1)

    assert engine.seconds_until_affordable(
        current=SimNumber.parse("10"),
        cost=SimNumber.parse("25"),
        cps=SimNumber.parse("3"),
    ) == 5


def test_time_engine_returns_none_when_income_cannot_reach_cost():
    engine = TimeEngine(tick_seconds=1)

    assert engine.seconds_until_affordable(
        current=SimNumber.parse("10"),
        cost=SimNumber.parse("25"),
        cps=SimNumber.zero(),
    ) is None


def test_tick_mode_exact_duration_clamp_is_explicit():
    engine = TimeEngine(tick_seconds=5)

    assert list(engine.tick_steps_for_duration(12)) == [5, 10, 12]


def test_recurring_events_use_absolute_open_closed_boundaries():
    engine = TimeEngine(tick_seconds=1)

    assert list(engine.recurring_event_times(0, 10, 2)) == [2, 4, 6, 8, 10]
    assert list(engine.recurring_event_times(4, 10, 2)) == [6, 8, 10]
