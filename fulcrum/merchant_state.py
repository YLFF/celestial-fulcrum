"""Confirmed shop shelves and investment budget; separate from simulated spending."""

from __future__ import annotations

import math
from typing import Any


SHOP_CATEGORIES = {"node_type_004", "node_type_013"}
DEFAULT_INVESTMENT_BALANCE = 99
SHELF_COUNT = 5
WITHDRAWAL_COSTS = (1, 2, 3, 4, 5, 6, 7, 7, 7, 7, 7, 7)


def validate_viewed_shelves(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= SHELF_COUNT:
        raise ValueError("viewed shelves must be an integer between zero and five")
    return value


def shelf_fraction(viewed: int) -> float:
    return (SHELF_COUNT - validate_viewed_shelves(viewed)) / SHELF_COUNT


def snapshot_shelves(node: dict) -> int:
    category = node.get("resolvedCategoryId") or node.get("categoryId") or node.get("observedCategoryId")
    default = 1 if category in SHOP_CATEGORIES and node.get("completion") == "completed" else 0
    return validate_viewed_shelves(node.get("merchantViewedShelves", default))


def withdrawal_quote(balance: float, limit: int = 10) -> dict:
    if type(balance) not in (int, float) or not math.isfinite(balance) or balance < 0:
        raise ValueError("investment balance must be finite and nonnegative")
    if type(limit) is not int or not 0 <= limit <= len(WITHDRAWAL_COSTS):
        raise ValueError("withdrawal limit must be an integer between zero and twelve")
    count = cost = 0
    for price in WITHDRAWAL_COSTS[:limit]:
        if cost + price > balance:
            break
        count += 1
        cost += price
    return {"cash": count, "investmentCost": cost, "balanceAfter": balance - cost}


def set_investment_balance(state: dict, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError("confirmed investment balance must be a nonnegative integer")
    state["resources"]["investmentBalance"] = value


def _shop(state: dict, area_key: str, node_id: str) -> dict:
    from .playtime_state import active_instance
    node = active_instance(state, area_key)["nodes"].get(node_id)
    if node is None or (node.get("resolvedCategoryId") or node.get("observedCategoryId")) not in SHOP_CATEGORIES:
        raise ValueError("confirm a yellow or green merchant node before editing its shelves")
    return node


def set_shop_shelves(state: dict, area_key: str, node_id: str, viewed: int) -> None:
    from .playtime_state import rebuild_derived
    validate_viewed_shelves(viewed)
    node = _shop(state, area_key, node_id)
    node["merchantViewedShelves"] = viewed
    if viewed:
        node["completion"] = "completed"
    rebuild_derived(state)


def confirm_shop_visit(state: dict, area_key: str, node_id: str, *, viewed: int | None = None,
                       withdrawn_ingots: int = 0, record_only: bool = False) -> dict:
    from .playtime_state import rebuild_derived, validate_playtime
    validate_playtime(state)
    node = _shop(state, area_key, node_id)
    shelves = min(SHELF_COUNT, snapshot_shelves(node) + 1) if viewed is None else validate_viewed_shelves(viewed)
    if type(withdrawn_ingots) is not int or not 0 <= withdrawn_ingots <= 12 or type(record_only) is not bool:
        raise ValueError("confirm zero to twelve withdrawn ingots and a boolean record-only flag")
    category = node.get("resolvedCategoryId") or node.get("observedCategoryId")
    if withdrawn_ingots and category != "node_type_004":
        raise ValueError("investment withdrawals are only available at green merchants")
    balance = state["resources"].get("investmentBalance", DEFAULT_INVESTMENT_BALANCE)
    cost = sum(WITHDRAWAL_COSTS[:withdrawn_ingots])
    if cost > balance:
        raise ValueError("insufficient confirmed investment balance")
    cash = state["resources"].get("originiumIngot")
    if withdrawn_ingots and not record_only and type(cash) is not int:
        raise ValueError("confirm cash before crediting a withdrawal")
    node["merchantViewedShelves"] = shelves
    node["completion"] = "completed"
    state["resources"]["investmentBalance"] = balance - cost
    if withdrawn_ingots and not record_only:
        state["resources"]["originiumIngot"] = cash + withdrawn_ingots
    rebuild_derived(state)
    return {"viewedShelves": shelves, "remainingFraction": shelf_fraction(shelves),
            "withdrawnIngots": withdrawn_ingots, "investmentCost": cost, "investmentBalance": balance - cost}
