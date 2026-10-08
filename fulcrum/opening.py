"""Deterministic opening state from the playtime defaults and handbook choices."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .component_box import add_component, new_component_box, set_capacity
from .operators import add_operator, promote_operator
from .merchant_state import DEFAULT_INVESTMENT_BALANCE
from .lookout_rules import lookout_radii


SQUAD_NAMES = {
    "squad_001": "指挥分队", "squad_002": "特勤分队", "squad_003": "后勤分队",
    "squad_004": "矛头分队", "squad_005": "突击战术分队", "squad_006": "堡垒战术分队",
    "squad_007": "远程战术分队", "squad_008": "破坏战术分队",
    "squad_009": "高台突破分队", "squad_010": "地面突破分队",
    "squad_011": "本源研修分队", "squad_012": "文明开化分队",
    "squad_013": "开拓者分队", "squad_014": "多边贸易分队",
    "squad_015": "地质调查分队",
}
COCOON_NAMES = {
    "relic_032": "襁褓天马", "relic_033": "襁褓骏鹰", "relic_034": "襁褓巨龙",
    "relic_035": "襁褓九头蛇", "relic_036": "襁褓白泽", "relic_037": "襁褓金乌",
    "relic_240": "襁褓中的猫", "relic_241": "襁褓中的狗",
    "relic_242": "襁褓三头犬", "relic_243": "襁褓羽蛇",
}
COCOON_ALIASES = {name: relic_id for relic_id, name in COCOON_NAMES.items()}
COCOON_ALIASES.update({
    "猫": "relic_240", "狗": "relic_241", "天马": "relic_032",
    "骏鹰": "relic_033", "巨龙": "relic_034", "九头蛇": "relic_035",
    "白泽": "relic_036", "金乌": "relic_037", "三头犬": "relic_242",
    "羽蛇": "relic_243",
})
SUPPORT_RELICS = frozenset(f"relic_{number:03d}" for number in range(32, 38))
DEFAULT_TECHNOLOGY_COMBAT_BONUSES = {"attackPercent": 20, "defensePercent": 20, "maxHpPercent": 25}
INITIAL_SUPPORTS = {
    "ordinary_relic": "获得1件普通收藏品",
    "cash": "获得8源石锭",
    "capacity": "消耗6源石锭，零件箱容量+2",
    "life_relic": "消耗2目标生命值上限，获得1件随机收藏品",
    "processing": "获得1件加工品",
    "rare_relic": "零件箱容量-1，获得1件稀有收藏品",
}


def normalize_technology_combat_bonuses(bonuses: Mapping[str, int | float] | None) -> dict[str, int | float]:
    if bonuses is not None and not isinstance(bonuses, Mapping):
        raise ValueError("technology combat bonuses must be a mapping")
    if bonuses is not None and set(bonuses) - set(DEFAULT_TECHNOLOGY_COMBAT_BONUSES):
        raise ValueError("unknown technology combat bonus")
    result = {**DEFAULT_TECHNOLOGY_COMBAT_BONUSES, **(bonuses or {})}
    for field, value in result.items():
        if type(value) not in (int, float):
            raise ValueError(f"invalid technology combat bonus: {field}")
        try:
            valid = math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError(f"invalid technology combat bonus: {field}")
    return result


def normalize_cocoons(cocoons: Mapping[str, int] | None) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for name, count in (cocoons or {}).items():
        relic_id = COCOON_ALIASES.get(name, name)
        if relic_id not in COCOON_NAMES or type(count) is not int or count < 1:
            raise ValueError(f"invalid opening cocoon: {name}={count}")
        normalized[relic_id] = normalized.get(relic_id, 0) + count
    return normalized


def opening_action_points(opening: Mapping[str, Any], area_key: str) -> int | None:
    if area_key != "I":
        return None
    return 6 + opening.get("cocoons", {}).get("relic_032", 0)


def build_opening(
    *, difficulty: int = 15, squad_id: str | None = None,
    cocoons: Mapping[str, int] | None = None,
    technology_combat_bonuses: Mapping[str, int | float] | None = None,
    lookout_split_unlocked: bool = True,
    initial_operators: list[dict[str, Any]] | None = None,
    investment_balance: int = DEFAULT_INVESTMENT_BALANCE,
    initial_supports: list[str] | None = None,
    initial_tickets: list[str] | None = None,
    promote_initial_mechanist: bool = False,
) -> dict[str, Any]:
    if type(difficulty) is not int or difficulty < 0:
        raise ValueError("difficulty must be a nonnegative integer")
    lookout_radii(difficulty, lookout_split_unlocked)
    if squad_id is not None and squad_id not in SQUAD_NAMES:
        raise ValueError(f"unknown squad {squad_id}")
    if type(investment_balance) is not int or investment_balance < 0:
        raise ValueError("investment balance must be a nonnegative integer")
    cocoon_counts = normalize_cocoons(cocoons)
    supports = initial_supports or []
    if not isinstance(supports, list) or len(set(supports)) != len(supports) or set(supports) - set(INITIAL_SUPPORTS):
        raise ValueError("invalid initial supports")
    from .scoring_calibration import TICKET_WEIGHTS
    tickets = list(initial_tickets or [])
    if len(tickets) > 3 or any(ticket not in TICKET_WEIGHTS for ticket in tickets):
        raise ValueError("invalid initial recruitment tickets")
    if promote_initial_mechanist and (squad_id != "squad_002" or "重装招募券" not in tickets):
        raise ValueError("initial Mechanist promotion requires special operations and a defender ticket")
    box = new_component_box()
    add_component(box, "component_001", estimated_value=2)
    add_component(box, "component_001", estimated_value=2)
    resources = {
        "life": {"current": 4, "max": 4}, "shield": 2,
        "level": 1, "experience": {"current": 0, "max": 10},
        "hope": 6, "originiumIngot": 20,
        "carrySlots": 7, "deploymentSlots": 6, "recruitmentTicketCapacity": 3,
        "investmentBalance": investment_balance,
    }
    relics: list[dict[str, Any]] = []
    operators: list[dict[str, Any]] = []
    pending: list[str] = []

    if squad_id == "squad_001":
        resources["life"] = {"current": 6, "max": 6}
    elif squad_id == "squad_002":
        resources["carrySlots"] += 2
        resources["deploymentSlots"] += 2
        operators = [
            {"instanceId": f"reserve-{number}", "name": "罗德岛预备干员", "elite": None, "source": "squad_002"}
            for number in range(1, 6)
        ]
    elif squad_id == "squad_003":
        resources["originiumIngot"] += 20
        resources["hope"] += 2
        add_component(box, "component_007", estimated_value=5)
        for _ in range(3):
            add_component(box, "component_008", estimated_value=2)
    elif squad_id == "squad_004":
        resources["life"]["current"] = 1
    elif squad_id == "squad_011":
        relics.append({"id": "relic_134", "count": 1, "state": None, "source": squad_id})
    elif squad_id == "squad_013":
        pending.extend(("initial_random_processing", "first_area_random_processing_or_concept"))
    elif squad_id == "squad_014":
        set_capacity(box, 12)
    elif squad_id == "squad_015":
        relics.append({"id": "relic_211", "count": 1, "state": None, "source": squad_id})

    resources["originiumIngot"] += 5 * cocoon_counts.get("relic_240", 0)
    resources["hope"] += cocoon_counts.get("relic_241", 0) + cocoon_counts.get("relic_033", 0)
    if "cash" in supports:
        resources["originiumIngot"] += 8
    if "capacity" in supports:
        resources["originiumIngot"] -= 6
        set_capacity(box, box["capacity"] + 2)
    if "life_relic" in supports:
        resources["life"]["max"] -= 2
        resources["life"]["current"] = min(resources["life"]["current"], resources["life"]["max"])
    if "rare_relic" in supports:
        set_capacity(box, box["capacity"] - 1)
    pending.extend(f"support_{key}" for key in supports if key in {"ordinary_relic", "life_relic", "processing", "rare_relic"})
    for relic_id, count in cocoon_counts.items():
        if relic_id in SUPPORT_RELICS:
            relics.append({"id": relic_id, "count": count, "state": None, "source": "opening_support"})
    state = {
        "opening": {"difficulty": difficulty, "squadId": squad_id, "cocoons": cocoon_counts,
                    "initialSupports": supports,
                    "technologyCombatBonuses": normalize_technology_combat_bonuses(technology_combat_bonuses),
                    "lookoutSplitUnlocked": lookout_split_unlocked,
                    "mechanistMasteryPreset": "full"},
        "resources": resources,
        "componentBox": box,
        "relics": relics,
        "operators": operators,
        "recruitmentTickets": tickets,
        "pendingOpeningRewards": pending,
    }
    if initial_operators is not None:
        if not isinstance(initial_operators, list):
            raise ValueError("initial_operators must be a list")
        fields = {"name", "source", "elite", "profession", "rarity", "instanceId", "hopeCost", "originiumIngotCost"}
        for operator in initial_operators:
            if not isinstance(operator, dict) or "name" not in operator or set(operator) - fields:
                raise ValueError("invalid initial operator input")
    initial_operators = initial_operators or []
    if squad_id == "squad_002" and not any(operator["name"] == "机械师" for operator in initial_operators):
        add_operator(state, "机械师", source="temporary", instance_id="initial-machinist", initial=True)
    for operator in initial_operators:
        default_source = "temporary" if squad_id == "squad_002" and operator["name"] == "机械师" else "normal"
        add_operator(state, operator["name"], source=operator.get("source", default_source),
                     elite=operator.get("elite", 1), profession=operator.get("profession"),
                     rarity=operator.get("rarity"),
                     instance_id=operator.get("instanceId"), initial=True,
                     hope_cost=operator.get("hopeCost"), ingot_cost=operator.get("originiumIngotCost", 0))
    if not any(operator["name"] == "机械师" for operator in state["operators"]):
        add_operator(state, "机械师", source="assistance", elite=2, profession="重装", rarity=6,
                     instance_id="opening-machinist-assistance", initial=True)
    if promote_initial_mechanist:
        machinist = next(row for row in state["operators"] if row["name"] == "机械师")
        promote_operator(state, machinist["instanceId"], hope_cost=2)
        state["recruitmentTickets"].remove("重装招募券")
    return state
