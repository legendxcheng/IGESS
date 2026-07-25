from __future__ import annotations

import heapq
from collections.abc import Callable

from .fish_state import FISH_MAX_LEVEL, FishInstance
from .numbers import SimNumber


class FishUpgradeRankingCache:
    """Track the cheapest upgradeable fish for an append-heavy owned list."""

    def __init__(
        self,
        price_for: Callable[[FishInstance], SimNumber],
    ) -> None:
        self._price_for = price_for
        self._items: list[FishInstance] | None = None
        self._item_count = 0
        self._items_by_id: dict[int, FishInstance] = {}
        self._heap: list[tuple[SimNumber, int, int]] = []
        self._pushed_level: dict[int, int] = {}

    def cheapest(
        self,
        items: list[FishInstance],
    ) -> tuple[FishInstance, SimNumber] | None:
        self._sync(items)
        while self._heap:
            price, instance_id, cached_level = self._heap[0]
            item = self._items_by_id.get(instance_id)
            if item is None:
                heapq.heappop(self._heap)
                continue
            if cached_level != item.level:
                heapq.heappop(self._heap)
                if (
                    item.level < FISH_MAX_LEVEL
                    and self._pushed_level.get(instance_id) != item.level
                ):
                    self._push(item)
                continue
            return item, price
        return None

    def _sync(self, items: list[FishInstance]) -> None:
        if self._items is not items or len(items) < self._item_count:
            self._items = items
            self._item_count = len(items)
            self._items_by_id = {
                item.instance_id: item for item in items
            }
            self._heap = []
            self._pushed_level = {}
            for item in items:
                if item.level < FISH_MAX_LEVEL:
                    self._push(item)
            return
        if len(items) == self._item_count:
            return
        for item in items[self._item_count :]:
            self._items_by_id[item.instance_id] = item
            if item.level < FISH_MAX_LEVEL:
                self._push(item)
        self._item_count = len(items)

    def _push(self, item: FishInstance) -> None:
        heapq.heappush(
            self._heap,
            (
                self._price_for(item),
                item.instance_id,
                item.level,
            ),
        )
        self._pushed_level[item.instance_id] = item.level
