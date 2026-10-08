"""Shop-entry preference signals; no purchase, sale, refresh, or resource update."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .resource_scoring import _nonnegative


EVENT_CASH_REQUIREMENTS = {
    "encounter_005": {"preferredCash": 10, "fallbackCash": 4, "cashCost": 10},
    "encounter_016": {"preferredCash": 50, "fallbackCash": 0, "cashCost": 0},
    "encounter_017": {"preferredCash": 3, "fallbackCash": 0, "cashCost": 3},
}


def merchant_entry_preferences(
    *, floor: int, cash: float, estimated_value: float, box_capacity: int, box_count: int,
    yellow_visited: bool, eligible_event_ids: Iterable[str],
    team_below_threshold: bool | None = None, reserve_override: float | None = None,
    yellow_shop_available: bool | None = None, reserve_entries: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    if type(floor) is not int or not 1 <= floor <= 6:
        raise ValueError("floor must be between one and six")
    cash = _nonnegative(cash, "cash")
    estimated_value = _nonnegative(estimated_value, "estimated value")
    if any(type(value) is not int or value < 0 for value in (box_capacity, box_count)):
        raise ValueError("invalid component-box capacity or occupancy")
    if type(yellow_visited) is not bool or (team_below_threshold is not None and type(team_below_threshold) is not bool):
        raise ValueError("shop history and team threshold must be confirmed booleans or an unknown threshold")
    if isinstance(eligible_event_ids, str):
        raise ValueError("eligible events must be a collection, not a single string")
    events = list(eligible_event_ids)
    if any(not isinstance(event_id, str) for event_id in events):
        raise ValueError("eligible events must contain event IDs")
    requirements = [{"eventId": event_id, **EVENT_CASH_REQUIREMENTS[event_id]}
                    for event_id in sorted(set(events) & EVENT_CASH_REQUIREMENTS.keys())]
    if yellow_shop_available is not None and type(yellow_shop_available) is not bool:
        raise ValueError("yellow shop availability must be boolean or unknown")
    available = floor != 6 if yellow_shop_available is None else yellow_shop_available
    if reserve_entries is not None and not isinstance(reserve_entries, Mapping):
        raise ValueError("reserve entries must be a mapping")
    if reserve_entries is not None and reserve_override is not None:
        raise ValueError("use named reserve entries or a total override, not both")
    entries = {"yellow_shop": 20} if reserve_entries is None else dict(reserve_entries)
    for name, amount in entries.items():
        if not isinstance(name, str) or not name:
            raise ValueError("reserve entries need nonempty names")
        entries[name] = _nonnegative(amount, f"reserve {name}")
    ignored = {}
    if yellow_visited or not available:
        if "yellow_shop" in entries:
            ignored["yellow_shop"] = entries.pop("yellow_shop")
    reserve = sum(entries.values())
    if reserve_override is not None:
        reserve = _nonnegative(reserve_override, "reserve override")
    free = max(0, box_capacity - box_count)
    wealth = cash + estimated_value
    yellow_preferred = available and not yellow_visited and wealth > 20
    return {
        "cashReserve": reserve, "reserveIsOverridden": reserve_override is not None,
        "reserveEntries": entries, "ignoredReserveEntries": ignored,
        "reserveShortfall": max(0.0, reserve - cash),
        "unreservedCash": max(0.0, cash - reserve), "eventCashRequirements": requirements,
        "unreservedEconomy": max(0.0, wealth - reserve),
        "reservePolicy": "sum_player_selected_entries_default_yellow_20",
        "yellow": {
            "categoryId": "node_type_013", "firstLayerVisit": not yellow_visited,
            "cashPlusEstimatedValue": wealth, "stronglyPreferred": yellow_preferred,
            "freeBoxSlots": free, "emptyBoxFraction": free / box_capacity if box_capacity else 0.0,
            "earlyArrivalPreferenceApplies": yellow_preferred,
            "developmentPreferenceBeforeFloorIV": floor < 4,
            "availableOrPossible": available,
        },
        "green": {
            "categoryId": "node_type_004", "afterYellowWithCash": yellow_visited and cash > 0,
            "teamBelowThreshold": team_below_threshold,
            "priorityForTeamDeficit": team_below_threshold is True and cash > 0,
            "cashLimitedByReserve": cash > 0 and cash <= reserve,
            "considerEntry": wealth > reserve,
        },
        "transactionModelEnabled": False, "mutatesPlaytime": False,
    }
