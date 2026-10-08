"""Reward saturation rules, independent of resource prices and route ranking."""

from __future__ import annotations

from typing import Any


SLOT_BENEFIT_LIMIT = 13


def slot_reward(
    resource: str, current: int, increase: int, *, carry_slots: int | None = None,
) -> dict[str, Any]:
    """Evaluate each added slot at its preceding state; do not update Playtime."""
    if resource not in {"carrySlots", "deploymentSlots"}:
        raise ValueError("resource must be carrySlots or deploymentSlots")
    if any(type(value) is not int or value < 0 for value in (current, increase)):
        raise ValueError("slot counts and increases must be nonnegative integers")
    if resource == "deploymentSlots" and (type(carry_slots) is not int or carry_slots < 0):
        raise ValueError("deployment rewards require current carry slots")
    if resource == "carrySlots":
        actual_gain = min(increase, max(0, SLOT_BENEFIT_LIMIT - current))
        factors = [1.0] * actual_gain + [0.0] * (increase - actual_gain)
    else:
        actual_gain = increase
        factors = [
            0.0 if before >= SLOT_BENEFIT_LIMIT else (0.5 if before >= carry_slots else 1.0)
            for before in range(current, current + increase)
        ]
    return {
        "resource": resource, "current": current, "requestedIncrease": increase,
        "actualIncrease": actual_gain, "newValue": current + actual_gain,
        "marginalFactors": factors, "effectiveRewardUnits": sum(factors),
    }
