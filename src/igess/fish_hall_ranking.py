from __future__ import annotations

import heapq
from collections.abc import Callable

from .fish_hall_model import FishIncomeTrace
from .fish_state import FishInstance
from .numbers import SimNumber


class FishHallRankingCache:
    """Exact lazy max-income ranking for simulator-owned Fish state."""

    def __init__(
        self,
        income_trace: Callable[[FishInstance], FishIncomeTrace],
    ) -> None:
        self._income_trace = income_trace
        self._items: list[FishInstance] | None = None
        self._item_count = 0
        self._items_by_id: dict[int, FishInstance] = {}
        self._heap: list[tuple[SimNumber, int, int]] = []
        self._pushed_level: dict[int, int] = {}

    def item(self, instance_id: int) -> FishInstance:
        return self._items_by_id[instance_id]

    def ranked(
        self,
        items: list[FishInstance],
        limit: int,
        *,
        use_cache: bool,
    ) -> list[FishIncomeTrace]:
        if use_cache:
            self.sync(items)
        else:
            self.reset(items)
        selected_entries: list[tuple[SimNumber, int, int]] = []
        selected_traces: list[FishIncomeTrace] = []
        selected_ids: set[int] = set()
        while self._heap and len(selected_traces) < limit:
            entry = heapq.heappop(self._heap)
            _negative_income, instance_id, cached_level = entry
            item = self._items_by_id.get(instance_id)
            if item is None:
                continue
            if cached_level != item.level:
                if self._pushed_level.get(instance_id) != item.level:
                    self._push(item)
                continue
            if instance_id in selected_ids:
                continue
            selected_entries.append(entry)
            selected_traces.append(self._income_trace(item))
            selected_ids.add(instance_id)
        for entry in selected_entries:
            heapq.heappush(self._heap, entry)
        return selected_traces

    def sync(self, items: list[FishInstance]) -> None:
        if self._items is not items or len(items) < self._item_count:
            self.reset(items)
            return
        if len(items) == self._item_count:
            return
        for item in items[self._item_count :]:
            self._items_by_id[item.instance_id] = item
            self._push(item)
        self._item_count = len(items)

    def note_updated(self, item: FishInstance) -> None:
        cached = self._items_by_id.get(item.instance_id)
        if cached is not item:
            raise ValueError(
                "updated fish item does not belong to cached PlayerState"
            )
        if self._pushed_level.get(item.instance_id) != item.level:
            self._push(item)

    def reset(self, items: list[FishInstance]) -> None:
        self._items = items
        self._item_count = len(items)
        self._items_by_id = {item.instance_id: item for item in items}
        self._heap = []
        self._pushed_level = {}
        for item in items:
            self._push(item)

    def _push(self, item: FishInstance) -> None:
        trace = self._income_trace(item)
        heapq.heappush(
            self._heap,
            (
                -trace.income_per_second,
                item.instance_id,
                item.level,
            ),
        )
        self._pushed_level[item.instance_id] = item.level
