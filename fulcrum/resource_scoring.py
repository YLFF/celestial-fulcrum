"""Fixed-reference resource utilities, independent of route search and Playtime."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Iterable, Mapping
from .scoring_profile import RESOURCE_POINTS


REFERENCE_POINTS = float(RESOURCE_POINTS["relicPoints"])
DEFAULT_UNIT_VALUES = {"relicCount": 1.0, "originiumIngot": RESOURCE_POINTS["cashPoints"] / REFERENCE_POINTS}


def _nonnegative(value: float, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} must be finite") from error
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")
    return result


@dataclass(frozen=True)
class UtilityCurve:
    """Bands of (exclusive upper bound, marginal relic-equivalent value)."""

    bands: tuple[tuple[float | None, float], ...]

    def __post_init__(self) -> None:
        normalized = []
        previous = 0.0
        for index, (end, marginal) in enumerate(self.bands):
            marginal = _nonnegative(marginal, "marginal value")
            if end is None:
                if index != len(self.bands) - 1:
                    raise ValueError("only the final band may be unbounded")
            else:
                end = _nonnegative(end, "band end")
                if end <= previous:
                    raise ValueError("band ends must be strictly increasing above zero")
                previous = end
            normalized.append((end, marginal))
        if not normalized or normalized[-1][0] is not None:
            raise ValueError("a curve requires an unbounded final band")
        object.__setattr__(self, "bands", tuple(normalized))

    @classmethod
    def linear(cls, unit_value: float) -> UtilityCurve:
        return cls(((None, unit_value),))

    def value(self, quantity: float) -> float:
        quantity = _nonnegative(quantity, "resource quantity")
        total, start = 0.0, 0.0
        for end, marginal in self.bands:
            stop = quantity if end is None else min(quantity, end)
            total += max(0.0, stop - start) * marginal
            if end is None or quantity <= end:
                return total
            start = end
        raise AssertionError("validated curves always cover the quantity")


class IncompleteResourceScore(ValueError):
    def __init__(self, resource_ids: Iterable[str]) -> None:
        self.resource_ids = tuple(sorted(resource_ids))
        super().__init__(f"resource values are not configured: {', '.join(self.resource_ids)}")


class ResourceScorer:
    """Keep curves/context fixed for both sides of a settlement comparison."""

    def __init__(
        self, curves: Mapping[str, UtilityCurve], *, reference_points: float = REFERENCE_POINTS,
    ) -> None:
        self.reference_points = _nonnegative(reference_points, "reference points")
        if not self.reference_points:
            raise ValueError("reference points must be positive")
        self.curves = dict(curves)
        if any(not isinstance(key, str) or not key or not isinstance(curve, UtilityCurve)
               for key, curve in self.curves.items()):
            raise ValueError("curves must map resource IDs to UtilityCurve instances")

    def score_change(
        self, before: Mapping[str, float], after: Mapping[str, float], *, benefit_factor: float = 1.0,
    ) -> dict[str, Any]:
        if set(before) != set(after):
            raise ValueError("before and after must contain the same explicit resource keys")
        factor = _nonnegative(benefit_factor, "benefit factor")
        changes = {}
        for resource_id in sorted(before):
            old = _nonnegative(before[resource_id], "resource quantity")
            new = _nonnegative(after[resource_id], "resource quantity")
            if old != new:
                changes[resource_id] = (old, new)
        missing = set(changes) - self.curves.keys()
        if missing:
            raise IncompleteResourceScore(missing)
        parts = []
        for resource_id, (old, new) in changes.items():
            curve = self.curves[resource_id]
            points = self.reference_points * (curve.value(new) - curve.value(old))
            if not math.isfinite(points):
                raise ValueError("resource score overflow")
            parts.append({"resourceId": resource_id, "before": old, "after": new,
                          "delta": new - old, "netPoints": points,
                          "adjustedPoints": points * factor if points > 0 else points})
        gains = math.fsum(max(0.0, part["netPoints"]) for part in parts)
        losses = math.fsum(max(0.0, -part["netPoints"]) for part in parts)
        adjusted = gains * factor - losses
        if not math.isfinite(adjusted):
            raise ValueError("resource score overflow")
        return {"referencePoints": self.reference_points, "parts": parts,
                "gainPoints": gains, "lossPoints": losses, "netPoints": gains - losses,
                "benefitFactor": factor, "adjustedPoints": adjusted}

    def expected_change(
        self, before: Mapping[str, float], outcomes: Iterable[tuple[float, Mapping[str, float]]],
        *, benefit_factor: float = 1.0,
    ) -> dict[str, Any]:
        outcomes = [(_nonnegative(probability, "probability"), after)
                    for probability, after in outcomes]
        if not math.isclose(math.fsum(p for p, _ in outcomes), 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("outcome probabilities must sum to one")
        factor = _nonnegative(benefit_factor, "benefit factor")
        # Score each real branch; never make thresholds depend on mean inventory.
        branches = [{"probability": p, "score": self.score_change(before, after, benefit_factor=factor)}
                    for p, after in outcomes if p > 0]
        return {"referencePoints": self.reference_points, "branches": branches,
                **{field: math.fsum(row["probability"] * row["score"][field] for row in branches)
                   for field in ("gainPoints", "lossPoints", "netPoints", "adjustedPoints")}}


def default_resource_scorer() -> ResourceScorer:
    """Only the two player-confirmed prices; other changed resources stay missing."""
    return ResourceScorer({key: UtilityCurve.linear(value) for key, value in DEFAULT_UNIT_VALUES.items()})


def slot_value_curves(
    carry_slots: int, *, carry_unit_value: float, deployment_unit_value: float,
) -> dict[str, UtilityCurve]:
    if type(carry_slots) is not int or carry_slots < 0:
        raise ValueError("carry slots must be a nonnegative integer")
    carry = _nonnegative(carry_unit_value, "carry unit value")
    deployment = _nonnegative(deployment_unit_value, "deployment unit value")
    split = min(carry_slots, 13)
    bands = []
    if split:
        bands.append((split, deployment))
    if split < 13:
        bands.append((13, deployment * 0.5))
    bands.append((None, 0.0))
    return {"carrySlots": UtilityCurve(((13, carry), (None, 0.0))),
            "deploymentSlots": UtilityCurve(tuple(bands))}
