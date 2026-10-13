"""Held, unconditional battle reward modifiers from confirmed relic clauses."""

from fractions import Fraction
from functools import lru_cache

from .relic_effects import load_definitions

REWARD_METRICS = {"battle_experience_reward", "battle_cash_reward"}


@lru_cache(maxsize=1)
def _definitions():
    return load_definitions()


def battle_reward_modifiers(relics, *, definitions=None):
    result = {metric: [] for metric in REWARD_METRICS}
    definitions = _definitions() if definitions is None else definitions
    held = {row["id"] for row in relics if row.get("count", 1) > 0}
    for relic_id in sorted(held):
        definition = definitions.get(relic_id)
        if not definition:
            continue
        for clause in definition["effects"]:
            metric = clause["target"]["metric"]
            if (clause["category"] == "development" and metric in result
                    and clause["operation"] in {"flat_delta", "base_ratio_delta", "factor"}
                    and clause["trigger"] == clause["lifetime"] == "while_held"
                    and not clause["conditions"] and not clause["target"].get("scope")):
                result[metric].append({"relicId": relic_id, "name": definition["name"], "clauseId": clause["id"],
                                       "operation": clause["operation"], "value": clause["value"]})
    return result


def reward_amount(base, terms=(), *, multipliers=()):
    value = Fraction(str(base))
    value += sum((Fraction(str(term["value"])) for term in terms if term["operation"] == "flat_delta"), Fraction(0))
    value *= 1 + sum((Fraction(str(term["value"])) for term in terms
                      if term["operation"] == "base_ratio_delta"), Fraction(0))
    factors = [term["value"] for term in terms if term["operation"] == "factor"]
    for multiplier in [*multipliers, *factors]:
        factor = Fraction(str(multiplier))
        if factor < 0:
            raise ValueError("战斗奖励倍率不能为负数")
        value *= factor
    return max(0, value.numerator // value.denominator)
