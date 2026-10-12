"""Snapshot power proxy and a separate per-layer player judgement."""

from decimal import Decimal

from .combat_bonuses import number, summarize_combat_bonuses
from .operators import PERMANENT_SOURCES
from .scoring_profile import PROFILE

OVERRIDES = ("auto", "enough", "insufficient")


def threshold_floor(area):
    if type(area) is int and 1 <= area <= 6:
        return area
    if isinstance(area, str):
        main = area.split("-")[0]
        if main in ("I", "II", "III", "IV", "V", "VI"):
            return ("I", "II", "III", "IV", "V", "VI").index(main) + 1
    raise ValueError("战力门槛仅支持一至六主层及所属树洞、追忆层")


def team_status(operators, floor, squad_id=None, options=None, *, combat_state=None, attribute_summary=None):
    options = options or {}
    override = options.get("teamThresholdOverride", "auto")
    if override not in OVERRIDES:
        raise ValueError("invalid team threshold override")
    permanent = [op for op in operators if op.get("source") in PERMANENT_SOURCES
                 and op.get("remainingBattles") is None]
    actual = {
        "totalOperators": len(permanent),
        "sixStars": sum(op.get("rarity") == 6 and op.get("elite") in (1, 2) for op in permanent),
        "elite2SixStars": sum(op.get("rarity") == 6 and op.get("elite") == 2 for op in permanent),
    }
    floor = threshold_floor(floor)
    weights = PROFILE["teamPower"]["operatorWeights"]
    contributions = []
    for op in permanent:
        rarity = op.get("rarity")
        group = str(rarity) if rarity in (5, 6) else "other"
        weight = number(weights[group]["promoted" if op.get("elite") == 2 else "unpromoted"])
        contributions.append({"name": op["name"], "instanceId": op.get("instanceId"),
                              "rarity": rarity, "promoted": op.get("elite") == 2, "weight": float(weight)})
    weighted = sum((number(row["weight"]) for row in contributions), Decimal(0))
    if attribute_summary is None:
        attribute_summary = summarize_combat_bonuses(combat_state or {}, include_operator_views=False)["global"]["attributeSummary"]
    multipliers = {}
    pending = 0
    for metric in ("max_hp", "attack"):
        for domain in ("outside_battle", "inside_battle"):
            cell = next(row for row in attribute_summary if row["metric"] == metric and row["domain"] == domain)
            multiplier = number(cell["relativeFactor"])
            multipliers[f"{domain}_{metric}"] = float(max(Decimal(0), multiplier))
            pending += cell.get("pendingCount", 0)
    factor = Decimal(1)
    for multiplier in multipliers.values():
        factor *= number(multiplier)
    power = weighted * factor
    target = number(PROFILE["teamThresholds"][floor - 1][2])
    gap = max(Decimal(0), target - power)
    weighted_gap = max(Decimal(0), target / factor - weighted) if factor > 0 else target
    met = power >= target
    result = {"floor": floor, "squadId": squad_id, "model": "weighted_roster_attributes",
              "required": {"power": float(target)}, "weightedOperators": float(weighted),
              "multipliers": multipliers, "attributeFactor": float(factor), "power": float(power),
              "deficits": {"power": float(gap), "weightedOperators": float(weighted_gap)},
              "operatorContributions": contributions, "pendingAttributeTerms": pending}
    result.update(actualCounts=actual, automaticMet=met, override=override,
                  unknownRarityOperators=[op["name"] for op in permanent if op.get("rarity") is None])
    result["met"] = result["automaticMet"] if override == "auto" else override == "enough"
    return result
