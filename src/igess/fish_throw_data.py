from __future__ import annotations

import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from .fish_data import FishDataError, FishDataSnapshot
from .fish_throw import (
    BonusResult,
    Mutation,
    StrengthLuckPool,
    ThresholdItem,
    ThrowInput,
    ThrowOutcome,
    ThrowRules,
    TrashLuckMapping,
    TrashLuckPool,
    map_torpedo_power_to_trash_luck,
    resolve_throw,
)


@dataclass(frozen=True)
class ProductionThrowConfig:
    """Non-table rules and start facts for the active-throw loop."""

    initial_strength: float
    interval_seconds: int
    regular_luck_multiplier: float
    bonus_base_luck: float
    max_bonus_layers: int

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ProductionThrowConfig":
        if not isinstance(value, Mapping):
            raise FishDataError("engine.active_throw must be an object")
        required = {
            "initial_strength",
            "interval_seconds",
            "regular_luck_multiplier",
            "bonus_base_luck",
            "max_bonus_layers",
        }
        missing = sorted(required - set(value))
        if missing:
            raise FishDataError(
                "engine.active_throw is missing fields: " + ", ".join(missing)
            )
        unknown = sorted(set(value) - required)
        if unknown:
            raise FishDataError(
                "engine.active_throw has unknown fields: " + ", ".join(unknown)
            )
        max_bonus_layers = _positive_int(
            value["max_bonus_layers"], "max_bonus_layers"
        )
        return cls(
            initial_strength=_positive_number(
                value["initial_strength"], "initial_strength"
            ),
            interval_seconds=_positive_int(
                value["interval_seconds"], "interval_seconds"
            ),
            regular_luck_multiplier=_positive_number(
                value["regular_luck_multiplier"], "regular_luck_multiplier"
            ),
            bonus_base_luck=_positive_number(
                value["bonus_base_luck"], "bonus_base_luck"
            ),
            max_bonus_layers=max_bonus_layers,
        )

    def manifest_parameters(self) -> dict[str, str | int]:
        return {
            "initial_strength": _format_float(self.initial_strength),
            "interval_seconds": self.interval_seconds,
            "regular_luck_multiplier": _format_float(
                self.regular_luck_multiplier
            ),
            "bonus_base_luck": _format_float(self.bonus_base_luck),
            "max_bonus_layers": self.max_bonus_layers,
        }


@dataclass(frozen=True)
class ProductionThrowRequest:
    root_random_seed: int
    throw_id: int
    strength: float
    torpedo_id: int
    regular_luck_multiplier: float = 1.0


@dataclass(frozen=True)
class ProductionThrowResolution:
    request: ProductionThrowRequest
    torpedo_name: str
    torpedo_power: float
    trash_luck_mapping: TrashLuckMapping
    outcome: ThrowOutcome
    fish_weight_gram: int
    fish_mutation_id: int

    def event_details(self) -> dict[str, str]:
        outcome = self.outcome
        mutation_id = outcome.mutation.id if outcome.mutation is not None else "0"
        bonus_events = [
            {
                "layer": event.layer,
                "result_type": event.result_type,
                "roll_power": _format_float(event.roll_power),
                "mutation_id": event.mutation_id,
                "fish_luck_after": (
                    None
                    if event.fish_luck_after is None
                    else _format_float(event.fish_luck_after)
                ),
            }
            for event in outcome.bonus_events
        ]
        return {
            "root_random_seed": str(self.request.root_random_seed),
            "throw_id": str(self.request.throw_id),
            "input_strength": _format_float(self.request.strength),
            "regular_luck_multiplier": _format_float(
                self.request.regular_luck_multiplier
            ),
            "fish_luck_pool_id": str(outcome.strength_luck.pool_id),
            "base_fish_luck": _format_float(
                outcome.strength_luck.base_fish_luck
            ),
            "fish_luck": _format_float(outcome.strength_luck.fish_luck),
            "bonus_events": json.dumps(
                bonus_events,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "bonus_double_count": str(outcome.bonus_double_count),
            "mutation_id": mutation_id,
            "final_fish_luck": _format_float(outcome.final_fish_luck),
            "fish_roll_power": _format_float(outcome.fish_roll_power),
            "fish_id": outcome.fish_reward.id,
            "fish_name": outcome.fish_reward.name,
            "fish_rarity_id": str(outcome.fish_reward.rarity_id),
            "fish_denominator": _format_float(
                outcome.fish_reward.denominator
            ),
            "fish_weight_gram": str(self.fish_weight_gram),
            "fish_mutation_id": str(self.fish_mutation_id),
            "fish_pool_scope": "all_tbfish_rows",
            "torpedo_id": str(self.request.torpedo_id),
            "torpedo_name": self.torpedo_name,
            "torpedo_power": _format_float(self.torpedo_power),
            "trash_luck_pool_id": str(self.trash_luck_mapping.pool_id),
            "base_trash_luck": _format_float(
                self.trash_luck_mapping.base_trash_luck
            ),
            "trash_luck": _format_float(self.trash_luck_mapping.trash_luck),
            "trash_roll_power": _format_float(outcome.trash_roll_power),
            "trash_id": outcome.trash_reward.id,
            "trash_name": outcome.trash_reward.name,
            "trash_rarity_id": str(outcome.trash_reward.rarity_id),
            "trash_denominator": _format_float(
                outcome.trash_reward.denominator
            ),
            "trash_luck_interpolation": "log_smoothstep",
            "trash_pool_scope": "all_tbtrash_rows",
            "trash_selection": "denominator_threshold",
        }


@dataclass(frozen=True)
class _Torpedo:
    id: int
    name: str
    power: float


class FishThrowDataAdapter:
    """Adapt Luban-generated Fish rows to the authoritative throw function.

    This adapter only reads generated row objects already loaded in a
    :class:`FishDataSnapshot`; it never parses Fish JSON or supplies missing
    production values.
    """

    def __init__(
        self,
        snapshot: FishDataSnapshot,
        *,
        bonus_base_luck: float,
        max_bonus_layers: int,
    ) -> None:
        self.snapshot = snapshot
        mutations, normal_mutation_id = self._mutations()
        self.normal_mutation_id = normal_mutation_id
        self._fish_weights_gram = self._fish_weights()
        self.rules = ThrowRules(
            strength_luck_pools=self._strength_luck_pools(),
            bonus_base_luck=_positive_number(
                bonus_base_luck, "bonus_base_luck"
            ),
            max_bonus_layers=_positive_int(
                max_bonus_layers, "max_bonus_layers"
            ),
            bonus_results=self._bonus_results(),
            mutations=mutations,
            fish_pool=self._threshold_pool("tbfish"),
            trash_pool=self._threshold_pool("tbtrash"),
        )
        self.trash_luck_pools = self._trash_luck_pools()
        torpedoes = self._torpedoes()
        if not torpedoes:
            raise FishDataError("tbtorpedo must contain an initial row")
        self._torpedoes_by_id = {row.id: row for row in torpedoes}
        if len(self._torpedoes_by_id) != len(torpedoes):
            raise FishDataError("tbtorpedo contains duplicate ids")
        self.initial_torpedo_id = torpedoes[0].id

    def resolve(self, request: ProductionThrowRequest) -> ProductionThrowResolution:
        if not isinstance(request, ProductionThrowRequest):
            raise FishDataError(
                "request must be a ProductionThrowRequest"
            )
        if type(request.root_random_seed) is not int:
            raise FishDataError("root_random_seed must be an integer")
        if type(request.throw_id) is not int or request.throw_id < 0:
            raise FishDataError("throw_id must be a non-negative integer")
        if type(request.torpedo_id) is not int or request.torpedo_id <= 0:
            raise FishDataError("torpedo_id must be a positive integer")
        try:
            torpedo = self._torpedoes_by_id[request.torpedo_id]
        except KeyError as exc:
            raise FishDataError(
                f"unknown production torpedo id: {request.torpedo_id}"
            ) from exc
        multiplier = _positive_number(
            request.regular_luck_multiplier, "regular_luck_multiplier"
        )
        normalized_request = ProductionThrowRequest(
            root_random_seed=request.root_random_seed,
            throw_id=request.throw_id,
            strength=_finite_number(request.strength, "strength"),
            torpedo_id=request.torpedo_id,
            regular_luck_multiplier=multiplier,
        )
        trash_luck = map_torpedo_power_to_trash_luck(
            torpedo.power,
            self.trash_luck_pools,
            multiplier,
        )
        outcome = resolve_throw(
            ThrowInput(
                root_random_seed=request.root_random_seed,
                throw_id=request.throw_id,
                strength=normalized_request.strength,
                regular_luck_multiplier=multiplier,
                trash_luck=trash_luck.trash_luck,
            ),
            self.rules,
        )
        fish_mutation_id = (
            self.normal_mutation_id
            if outcome.mutation is None
            else _positive_int(int(outcome.mutation.id), "fish_mutation_id")
        )
        return ProductionThrowResolution(
            request=normalized_request,
            torpedo_name=torpedo.name,
            torpedo_power=torpedo.power,
            trash_luck_mapping=trash_luck,
            outcome=outcome,
            fish_weight_gram=self._fish_weights_gram[outcome.fish_reward.id],
            fish_mutation_id=fish_mutation_id,
        )

    def verify_resolution(self, resolution: ProductionThrowResolution) -> None:
        """Reject a result that is not the authoritative replay of its request."""

        if not isinstance(resolution, ProductionThrowResolution):
            raise FishDataError(
                "resolution must be a ProductionThrowResolution"
            )
        if self.resolve(resolution.request) != resolution:
            raise FishDataError(
                "resolution does not match its authoritative replay"
            )

    def _strength_luck_pools(self) -> tuple[StrengthLuckPool, ...]:
        rows = self.snapshot.table("tbfishrandompool")
        result = tuple(
            StrengthLuckPool(
                id=_row_id(row, "tbfishrandompool"),
                name=f"FishRandomPool:{_row_id(row, 'tbfishrandompool')}",
                strength_upper_bound=_generated_number(
                    _field(row, "strengthUpperBound", "tbfishrandompool"),
                    "tbfishrandompool.strengthUpperBound",
                ),
                start_luck=_positive_number(
                    _field(row, "startLuck", "tbfishrandompool"),
                    "tbfishrandompool.startLuck",
                ),
                end_luck=_positive_number(
                    _field(row, "endLuck", "tbfishrandompool"),
                    "tbfishrandompool.endLuck",
                ),
            )
            for row in rows
        )
        _validate_contiguous_ids(result, "tbfishrandompool")
        return result

    def _trash_luck_pools(self) -> tuple[TrashLuckPool, ...]:
        rows = self.snapshot.table("tbtrashrandompool")
        result = tuple(
            TrashLuckPool(
                id=_row_id(row, "tbtrashrandompool"),
                name=_required_name(row, "tbtrashrandompool"),
                power_upper_bound=_generated_number(
                    _field(row, "powerUpperBound", "tbtrashrandompool"),
                    "tbtrashrandompool.powerUpperBound",
                ),
                start_luck=_positive_number(
                    _field(row, "startLuck", "tbtrashrandompool"),
                    "tbtrashrandompool.startLuck",
                ),
                end_luck=_positive_number(
                    _field(row, "endLuck", "tbtrashrandompool"),
                    "tbtrashrandompool.endLuck",
                ),
            )
            for row in rows
        )
        _validate_contiguous_ids(result, "tbtrashrandompool")
        return result

    def _bonus_results(self) -> tuple[BonusResult, ...]:
        result_types = {0: "no_bonus", 1: "mutation", 2: "luck_double"}
        result: list[BonusResult] = []
        for row in self.snapshot.table("tbbonusfirstlayer"):
            row_id = _row_id(row, "tbbonusfirstlayer")
            raw_type = _field(row, "resultType", "tbbonusfirstlayer")
            if type(raw_type) is not int or raw_type not in result_types:
                raise FishDataError(
                    f"tbbonusfirstlayer.{row_id}.resultType is unsupported"
                )
            continue_chain = _field(
                row, "continueChain", "tbbonusfirstlayer"
            )
            if not isinstance(continue_chain, bool):
                raise FishDataError(
                    f"tbbonusfirstlayer.{row_id}.continueChain must be boolean"
                )
            result.append(
                BonusResult(
                    id=str(row_id),
                    name=_required_name(row, "tbbonusfirstlayer"),
                    result_type=result_types[raw_type],
                    roll_power_requirement=_positive_number(
                        _field(
                            row,
                            "rollPowerRequirement",
                            "tbbonusfirstlayer",
                        ),
                        "tbbonusfirstlayer.rollPowerRequirement",
                    ),
                    continue_chain=continue_chain,
                    luck_multiplier=_positive_number(
                        _field(row, "luckMultiplier", "tbbonusfirstlayer"),
                        "tbbonusfirstlayer.luckMultiplier",
                    ),
                )
            )
        return tuple(result)

    def _mutations(self) -> tuple[tuple[Mutation, ...], int]:
        result: list[Mutation] = []
        normal_ids: list[int] = []
        for row in self.snapshot.table("tbmutation"):
            row_id = _row_id(row, "tbmutation")
            weight = _nonnegative_int(
                _field(row, "mutationWeight", "tbmutation"),
                "tbmutation.mutationWeight",
            )
            if weight == 0:
                normal_ids.append(row_id)
                continue
            result.append(
                Mutation(
                    id=str(row_id),
                    name=_required_name(row, "tbmutation"),
                    weight=weight,
                    income_multiplier=_positive_number(
                        _field(row, "incomeMultiplier", "tbmutation"),
                        "tbmutation.incomeMultiplier",
                    ),
                )
            )
        if len(normal_ids) != 1:
            raise FishDataError(
                "tbmutation must contain exactly one zero-weight normal row"
            )
        return tuple(result), normal_ids[0]

    def _fish_weights(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in self.snapshot.table("tbfish"):
            fish_id = str(_row_id(row, "tbfish"))
            if fish_id in result:
                raise FishDataError(f"tbfish contains duplicate id: {fish_id}")
            result[fish_id] = _positive_int(
                _field(row, "weight", "tbfish"),
                f"tbfish.{fish_id}.weight",
            )
        return result

    def _threshold_pool(self, table_name: str) -> tuple[ThresholdItem, ...]:
        return tuple(
            ThresholdItem(
                id=str(_row_id(row, table_name)),
                name=_required_name(row, table_name),
                denominator=_generated_number(
                    _field(row, "Denominator", table_name),
                    f"{table_name}.Denominator",
                ),
                rarity_id=_positive_int(
                    _field(row, "rarityId", table_name),
                    f"{table_name}.rarityId",
                ),
            )
            for row in self.snapshot.table(table_name)
        )

    def _torpedoes(self) -> tuple[_Torpedo, ...]:
        return tuple(
            _Torpedo(
                id=_row_id(row, "tbtorpedo"),
                name=_required_name(row, "tbtorpedo"),
                power=_generated_number(
                    _field(row, "power", "tbtorpedo"),
                    "tbtorpedo.power",
                ),
            )
            for row in self.snapshot.table("tbtorpedo")
        )


def _field(row: Any, name: str, table_name: str) -> Any:
    try:
        return getattr(row, name)
    except AttributeError as exc:
        raise FishDataError(
            f"generated {table_name} row is missing field: {name}"
        ) from exc


def _row_id(row: Any, table_name: str) -> int:
    return _positive_int(_field(row, "id", table_name), f"{table_name}.id")


def _required_name(row: Any, table_name: str) -> str:
    value = _field(row, "name", table_name)
    if not isinstance(value, str) or not value:
        raise FishDataError(f"{table_name}.name must be a non-empty string")
    return value


def _generated_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise FishDataError(f"{field} must be a generated number")
    if isinstance(value, (int, float, Decimal, str)):
        return _positive_number(value, field)
    try:
        sign = getattr(value, "sign")
        digits = getattr(value, "digits")
        scale = getattr(value, "scale")
    except AttributeError as exc:
        raise FishDataError(f"{field} must be a generated big number") from exc
    if type(sign) is not int or sign not in {-1, 0, 1}:
        raise FishDataError(f"{field}.sign must be -1, 0, or 1")
    if not isinstance(digits, str) or not digits or not digits.isdigit():
        raise FishDataError(f"{field}.digits must contain decimal digits")
    if type(scale) is not int:
        raise FishDataError(f"{field}.scale must be an integer")
    try:
        parsed = Decimal(sign) * Decimal(digits).scaleb(scale)
    except (InvalidOperation, ValueError) as exc:
        raise FishDataError(f"{field} is not a valid generated big number") from exc
    return _positive_number(parsed, field)


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise FishDataError(f"{field} must be a finite number")
    try:
        parsed = float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise FishDataError(f"{field} must be a finite number") from exc
    if not math.isfinite(parsed):
        raise FishDataError(f"{field} must be a finite number")
    return parsed


def _positive_number(value: Any, field: str) -> float:
    parsed = _finite_number(value, field)
    if parsed <= 0:
        raise FishDataError(f"{field} must be a positive number")
    return parsed


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise FishDataError(f"{field} must be a positive integer")
    return value


def _nonnegative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise FishDataError(f"{field} must be a non-negative integer")
    return value


def _validate_contiguous_ids(rows: Sequence[Any], table_name: str) -> None:
    ids = [row.id for row in rows]
    if ids != list(range(1, len(ids) + 1)):
        raise FishDataError(f"{table_name} ids must be contiguous from 1")


def _format_float(value: float) -> str:
    return format(value, ".17g")
