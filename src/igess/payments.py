"""Explicit purchases and time-bounded entitlements, independent of game state."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, localcontext
from functools import cached_property
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import yaml

from .numbers import SimNumber


@dataclass(frozen=True)
class Product:
    id: str
    price: Decimal
    grants: dict[str, SimNumber]
    multipliers: dict[str, SimNumber]
    duration_seconds: int | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "price": str(self.price),
            "grants": {key: value.to_decimal_string() for key, value in self.grants.items()},
            "multipliers": {key: value.to_decimal_string() for key, value in self.multipliers.items()},
            "duration_seconds": self.duration_seconds,
        }


@dataclass(frozen=True)
class Purchase:
    at_seconds: int
    product: Product
    quantity: int = 1

    @property
    def cost(self) -> Decimal:
        with localcontext() as context:
            context.prec = 256
            return self.product.price * self.quantity

    @property
    def expires_at(self) -> int | None:
        duration = self.product.duration_seconds
        return None if duration is None else self.at_seconds + duration

    def payload(self) -> dict[str, Any]:
        return {"at_seconds": self.at_seconds, "product_id": self.product.id, "quantity": self.quantity}


@dataclass(frozen=True)
class PaymentPlan:
    id: str
    currency: str
    data_status: str
    source: str
    purchases: tuple[Purchase, ...] = ()

    def effective_profile(self, profile, seconds: int):
        values = dict(profile.source_efficiency)
        for key, multiplier in self.multipliers_at(seconds).items():
            values[key] = values.get(key, SimNumber.one()) * multiplier
        return replace(profile, source_efficiency=values)

    @cached_property
    def boundaries(self) -> tuple[int, ...]:
        return tuple(sorted(
            {purchase.at_seconds for purchase in self.purchases}
            | {purchase.expires_at for purchase in self.purchases if purchase.expires_at is not None}
        ))

    def multipliers_at(self, seconds: int) -> dict[str, SimNumber]:
        result: dict[str, SimNumber] = {}
        for purchase in self.purchases:
            if purchase.at_seconds <= seconds and (purchase.expires_at is None or seconds < purchase.expires_at):
                for key, value in purchase.product.multipliers.items():
                    result[key] = result.get(key, SimNumber.one()) * value ** SimNumber.parse(purchase.quantity)
        return result

    def spent_at(self, seconds: int) -> Decimal:
        with localcontext() as context:
            context.prec = 256
            return sum((item.cost for item in self.purchases if item.at_seconds <= seconds), Decimal(0))

    def count_at(self, seconds: int) -> int:
        return sum(item.quantity for item in self.purchases if item.at_seconds <= seconds)

    def grants_at(self, seconds: int) -> dict[str, SimNumber]:
        result: dict[str, SimNumber] = {}
        for purchase in self.purchases:
            if purchase.at_seconds == seconds:
                for key, value in purchase.product.grants.items():
                    result[key] = result.get(key, SimNumber.zero()) + value * SimNumber.parse(purchase.quantity)
        return result

    def events_at(self, seconds: int, scenario_id: str, profile_id: str) -> list:
        from .schema import Event

        result = []
        spent = self.spent_at(seconds - 1)
        for index, purchase in enumerate(self.purchases):
            if purchase.expires_at == seconds:
                result.append(Event(scenario_id, profile_id, seconds, "paid_entitlement_expired", f"purchase:{index}", {
                    "product_id": purchase.product.id,
                    "plan_id": self.id,
                }))
        for index, purchase in enumerate(self.purchases):
            if purchase.at_seconds != seconds:
                continue
            cost = purchase.cost
            with localcontext() as context:
                context.prec = 256
                spent += cost
            result.append(Event(scenario_id, profile_id, seconds, "paid_purchase", f"purchase:{index}", {
                "plan_id": self.id, "product_id": purchase.product.id,
                "quantity": str(purchase.quantity), "cost": str(cost),
                "currency": self.currency, "cumulative_spend": str(spent),
                "data_status": self.data_status,
                "expires_at_seconds": "" if purchase.expires_at is None else str(purchase.expires_at),
                "grants": json.dumps({key: (value * SimNumber.parse(purchase.quantity)).to_decimal_string() for key, value in purchase.product.grants.items()}, sort_keys=True),
                "multipliers": json.dumps(purchase.product.payload()["multipliers"], sort_keys=True),
            }))
        return result

    def payload(self) -> dict[str, Any]:
        return {
            "id": self.id, "currency": self.currency,
            "data_status": self.data_status, "source": self.source,
            "products": {item.product.id: item.product.payload() for item in self.purchases},
            "purchases": [item.payload() for item in self.purchases],
            "clock": "wall_seconds", "stacking": "multiply_independent_purchases",
        }

    def digest(self, source_digest: str) -> str:
        payload = json.dumps({"source_digest": source_digest, "plan": self.payload()}, sort_keys=True, ensure_ascii=False)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def validate_model(self, model, profile_id: str) -> None:
        if model.config.engine_id == "fish":
            resources = {"money", "material", "strength"}
            sources = {"fish_hall_money", "trash_material", "barbell_strength"}
            if self.purchases and not model.player_profiles[profile_id].behavior_weights:
                raise ValueError("Paid Fish simulation requires the weighted behavior loop")
        elif model.config.engine_id == "generic":
            resources = set(model.resources)
            sources = set(model.source_types)
            if any(seconds % model.config.tick_seconds for seconds in self.boundaries):
                raise ValueError("Generic purchase/expiry times must align with model.tick_seconds")
        else:
            raise ValueError("Paid simulation supports generic and fish engines")
        for item in self.purchases:
            if set(item.product.grants) - resources:
                raise ValueError(f"Product {item.product.id}: unknown grant resources {sorted(set(item.product.grants) - resources)}")
            if set(item.product.multipliers) - sources:
                raise ValueError(f"Product {item.product.id}: unknown multiplier sources {sorted(set(item.product.multipliers) - sources)}")


@dataclass(frozen=True)
class PaymentExperiment:
    profile: str
    scenarios: tuple[str, ...]
    plans: tuple[PaymentPlan, ...]

    @classmethod
    def read(cls, path: str | Path) -> "PaymentExperiment":
        class UniqueLoader(yaml.SafeLoader):
            def construct_mapping(self, node, deep=False):
                keys = [self.construct_object(key, deep=deep) for key, _value in node.value]
                if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
                    raise ValueError("Payment YAML keys must be unique strings")
                return super().construct_mapping(node, deep=deep)

        return cls.from_mapping(yaml.load(Path(path).read_text(encoding="utf-8"), Loader=UniqueLoader))

    @classmethod
    def from_mapping(cls, payload: Any) -> "PaymentExperiment":
        data = _mapping(payload, {"schema_version", "profile", "scenarios", "currency", "data_status", "source", "products", "plans"}, "experiment")
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ValueError("experiment.schema_version must be 1")
        profile = _id(data.get("profile"), "profile")
        scenarios = data.get("scenarios")
        if not isinstance(scenarios, list) or not 1 <= len(scenarios) <= 10:
            raise ValueError("scenarios must contain 1..10 unique scenario ids")
        scenarios = tuple(_id(value, "scenario") for value in scenarios)
        if len(set(scenarios)) != len(scenarios):
            raise ValueError("scenarios must be unique")
        currency = _text(data.get("currency"), "currency")
        source = _text(data.get("source"), "source")
        status = data.get("data_status")
        if not isinstance(status, str) or status not in {"example", "production"}:
            raise ValueError("data_status must be example or production")
        products_data = _mapping(data.get("products"), None, "products")
        if not 1 <= len(products_data) <= 100:
            raise ValueError("products must contain 1..100 products")
        products = {}
        for product_id, value in products_data.items():
            _id(product_id, "product id")
            row = _mapping(value, {"price", "grants", "multipliers", "duration_seconds"}, f"product {product_id}")
            price = _decimal(row.get("price"), "price")
            grants = _numbers(row.get("grants", {}), "grants")
            multipliers = _numbers(row.get("multipliers", {}), "multipliers")
            if not grants and not multipliers:
                raise ValueError(f"Product {product_id} has no benefits")
            duration = row.get("duration_seconds")
            if duration is not None:
                duration = _integer(duration, "duration_seconds", 1)
                if not multipliers:
                    raise ValueError("duration_seconds requires multiplier benefits")
            products[product_id] = Product(product_id, price, grants, multipliers, duration)
        plans_data = _mapping(data.get("plans"), None, "plans")
        if not 1 <= len(plans_data) <= 20 or "free" in plans_data:
            raise ValueError("plans must contain 1..20 plans; 'free' is reserved for the automatic baseline")
        plans = [PaymentPlan("free", currency, status, source)]
        for plan_id, value in plans_data.items():
            _id(plan_id, "plan id")
            row = _mapping(value, {"purchases"}, f"plan {plan_id}")
            items = row.get("purchases")
            if not isinstance(items, list) or len(items) > 1000:
                raise ValueError("purchases must be a list with at most 1000 entries")
            purchases = []
            for item in items:
                item = _mapping(item, {"at_seconds", "product_id", "quantity"}, "purchase")
                seconds = _integer(item.get("at_seconds"), "at_seconds", 0)
                product_id = _id(item.get("product_id"), "product_id")
                if product_id not in products:
                    raise ValueError(f"Unknown product_id: {product_id}")
                quantity = _integer(item.get("quantity", 1), "quantity", 1)
                if quantity > 1000:
                    raise ValueError("quantity must not exceed 1000")
                purchases.append(Purchase(seconds, products[product_id], quantity))
            plans.append(PaymentPlan(plan_id, currency, status, source, tuple(sorted(purchases, key=lambda item: item.at_seconds))))
        return cls(profile, scenarios, tuple(plans))


def _mapping(value: Any, fields: set[str] | None, label: str) -> dict:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be a string-keyed mapping")
    if fields is not None and set(value) - fields:
        raise ValueError(f"{label} has unknown fields: {sorted(set(value) - fields)}")
    return value


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}", value):
        raise ValueError(f"{label} must be a safe non-empty identifier")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000:
        raise ValueError(f"{label} must be non-empty text (up to 2000 characters)")
    return value


def _integer(value: Any, label: str, minimum: int) -> int:
    if type(value) is not int or not minimum <= value <= 315360000:
        raise ValueError(f"{label} must be an integer between {minimum} and 315360000")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None or len(str(value)) > 100:
        raise ValueError(f"{label} must be a positive finite decimal")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a positive finite decimal") from None
    if not number.is_finite() or number <= 0 or abs(number.adjusted()) > 100:
        raise ValueError(f"{label} must be a positive finite decimal with bounded magnitude")
    return number


def _numbers(value: Any, label: str) -> dict[str, SimNumber]:
    return {_id(key, label): SimNumber.parse(str(_decimal(number, label))) for key, number in _mapping(value, None, label).items()}
