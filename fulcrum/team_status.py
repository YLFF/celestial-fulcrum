"""Roster threshold facts and a separate per-layer player judgement."""

from .operators import PERMANENT_SOURCES
from .scoring_calibration import evaluate_team_threshold

OVERRIDES = ("auto", "enough", "insufficient")


def team_status(operators, floor, squad_id=None, options=None):
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
    counts = options.get("teamCounts", actual)
    result = evaluate_team_threshold(floor=floor, total_operators=counts["totalOperators"],
        six_star_operators=counts["sixStars"], elite2_six_star_operators=counts["elite2SixStars"], squad_id=squad_id)
    result.update(actualCounts=actual, automaticMet=result["met"], override=override,
                  unknownRarityOperators=[op["name"] for op in permanent if op.get("rarity") is None])
    result["met"] = result["automaticMet"] if override == "auto" else override == "enough"
    return result
