"""Pure utility calculations shared by score probes and read-only snapshot scoring."""

from __future__ import annotations

from itertools import combinations
from math import isclose, isfinite, log1p
from typing import Iterable, Mapping

from .component_box import INITIAL_USES
from .merchant_preferences import merchant_entry_preferences


DUAL_SQUADS = {
    "squad_005": ("先锋", "近卫", "突击"),
    "squad_006": ("重装", "辅助", "堡垒"),
    "squad_007": ("狙击", "医疗", "远程"),
    "squad_008": ("术师", "特种", "破坏"),
}
# E2 six-stars, all six-stars (including E2), permanent roster size.
TEAM_THRESHOLDS = ((0, 0, 0), (1, 2, 5), (2, 4, 6), (3, 6, 8), (5, 8, 10), (7, 9, 13))
LEVEL_COSTS = (10, 24, 36, 40, 55, 65, 75, 90, 95)
LEVEL_HOPE = (4, 4, 5, 5, 6, 6, 6, 6, 8)
SEED_POINTS = 250
DELAYED_REWARD_DISCOUNT = 0.7
EXCHANGE_OPPORTUNITY_POINTS = 200
REVEAL_VALUE_COEFFICIENT = 0.2
MERCHANT_REPEAT_FACTOR = 0.8  # Default after viewing one of five shelf faces.
PATH_STEP_INGOT_EXPECTATION = 1
GREEN_LOG_SCALE = 301.87354704659674
GREEN_LOG_OFFSET = 21.28357517084065
FIXED_COMPONENT_POINTS = dict(zip(
    [f"component_{i:03}" for i in (*range(1, 13), *range(25, 31))],
    (250, 125, 150, 500, 150, 250, 200, 15, 2000, 200, 250, 250, 125, 100, 25, 10, 250, 500),
))
MOVEMENT_POINTS = dict(zip(
    [f"component_{i:03}" for i in range(13, 25)],
    (10, 10, 10, 20, 20, 15, 20, 100, 50, 40, 100, 10),
))
ACTION_UNITS = {"component_016": 1, "component_019": 1, "component_020": 1, "component_024": 4}
SYNERGY_COMPONENTS = {"component_004", "component_006", "component_007", "component_029", "component_030"}
TICKET_WEIGHTS = {
    **{f"{name}招募券": 1 for name in ("先锋", "近卫", "重装", "狙击", "术师", "医疗", "辅助", "特种")},
    **{f"{name}协议招募券": 1.5 for name in ("突击", "堡垒", "远程", "破坏")},
    "前线统合招募券": 2, "后方协调招募券": 2, "高级人事调度函": 3.5,
    "前线统合资深招募券": 2.5, "后方协调资深招募券": 2.5, "高级人事资深招募券": 4,
    **{f"精英{name}招募券": 3 for name in ("突击", "堡垒", "远程", "破坏")},
}


def _integer(value: int, name: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _number(value: float, name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        raise ValueError(f"{name} must be finite")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name} must be {'positive' if positive else 'nonnegative'}")


def team_threshold(floor: int, squad_id: str | None = None) -> dict[str, int]:
    _integer(floor, "floor", 1)
    if floor > 6:
        raise ValueError("floor must be 1..6; treeholes use their entry floor")
    e2, six, total = TEAM_THRESHOLDS[floor - 1]
    if squad_id in DUAL_SQUADS:
        if floor == 2:
            e2, six = e2 + 1, six + 1
        elif floor == 3:
            e2, six = e2 + 1, six + 2
    return {"elite2SixStars": e2, "sixStars": six, "totalOperators": total}


def evaluate_team_threshold(
    *, floor: int, total_operators: int, six_star_operators: int,
    elite2_six_star_operators: int, squad_id: str | None = None,
) -> dict:
    """Use confirmed permanent counts; six_star_operators counts only E1/E2."""
    counts = {"elite2SixStars": elite2_six_star_operators,
              "sixStars": six_star_operators, "totalOperators": total_operators}
    for key, value in counts.items():
        _integer(value, key)
    if not elite2_six_star_operators <= six_star_operators <= total_operators:
        raise ValueError("E2 six-stars <= all six-stars <= roster size is required")
    required = team_threshold(floor, squad_id)
    deficits = {key: max(0, required[key] - counts[key]) for key in counts}
    return {"required": required, "counts": counts, "deficits": deficits,
            "met": not any(deficits.values())}


def experience_reward_score(
    *, level: int, experience: int, reward: int, below_threshold: bool,
    hope_deficit: float, reference_six_star_cost: float = 10,
) -> dict:
    """Value incremental progress, not HUD XP accumulation after reaching level 10."""
    for name, value, minimum in (("level", level, 1), ("experience", experience, 0), ("reward", reward, 0)):
        _integer(value, name, minimum)
    if level > 10 or (level < 10 and experience >= LEVEL_COSTS[level - 1]):
        raise ValueError("level/experience must already be normalized")
    if type(below_threshold) is not bool:
        raise ValueError("below_threshold must be boolean")
    _number(hope_deficit, "hope_deficit")
    _number(reference_six_star_cost, "reference_six_star_cost", positive=True)
    remaining, shadow, actual = reward, 0.0, 0
    segments = []
    while level < 10 and remaining:
        cost, hope = LEVEL_COSTS[level - 1], LEVEL_HOPE[level - 1]
        progress = min(remaining, cost - experience)
        value = hope * progress / cost
        segments.append({"level": level, "experience": progress, "hopeEquivalent": value})
        shadow += value
        remaining -= progress
        experience += progress
        if experience == cost:
            actual += hope
            level, experience = level + 1, 0
    useful = min(shadow, hope_deficit) if below_threshold else 0.0
    return {"levelAfter": level, "experienceAfter": experience, "actualHopeAward": actual,
            "progressHopeEquivalent": shadow, "usefulHopeEquivalent": useful,
            "points": useful * 500 / reference_six_star_cost * (1.25 if below_threshold else 1),
            "segments": segments}


def component_reference_points(
    component_id: str, *, action_unit: float = 200, small_movement: float = 20,
    existing_same: int = 0, remaining_uses: int | None = None,
) -> float:
    """Fixed-context calibration only; small-teleport/AP prices are not live-map prices."""
    _number(action_unit, "action_unit")
    _number(small_movement, "small_movement")
    _integer(existing_same, "existing_same")
    if component_id in FIXED_COMPONENT_POINTS:
        if remaining_uses is not None:
            raise ValueError("Only processed components have remaining uses")
        multiplier = 1 + 0.05 * existing_same if component_id in SYNERGY_COMPONENTS else 1
        return FIXED_COMPONENT_POINTS[component_id] * multiplier
    if component_id not in MOVEMENT_POINTS:
        raise ValueError(f"Unpriced component: {component_id}")
    uses = INITIAL_USES[component_id] if remaining_uses is None else remaining_uses
    _integer(uses, "remaining_uses")
    if uses > INITIAL_USES[component_id]:
        raise ValueError("Remaining uses exceed initial uses")
    movement = small_movement if component_id == "component_019" else MOVEMENT_POINTS[component_id]
    return uses * (movement + ACTION_UNITS.get(component_id, 0) * action_unit)


def ticket_reference_points(name: str, *, squad_id: str | None = None, below_threshold: bool = False) -> float:
    """Ticket reference with an already-E2 Mechanist (no demand multiplier)."""
    if name not in TICKET_WEIGHTS:
        raise ValueError(f"Unpriced ticket: {name}")
    if type(below_threshold) is not bool:
        raise ValueError("below_threshold must be boolean")
    home = DUAL_SQUADS.get(squad_id, ())
    home_ticket = any(name == f"{profession}招募券" for profession in home[:2])
    if home:
        home_ticket |= name in {f"{home[2]}协议招募券", f"精英{home[2]}招募券"}
    return 50 * TICKET_WEIGHTS[name] * (1.5 if home_ticket else 1) * (1.25 if below_threshold else 1)


def dispatch_reference_score(
    *, processed_points: float, hope_points: float, grants_promotion: bool,
) -> dict:
    """Delayed rewards are discounted; promotion uses the fixed deficit reference."""
    _number(processed_points, "processed_points")
    _number(hope_points, "hope_points")
    if type(grants_promotion) is not bool:
        raise ValueError("grants_promotion must be boolean")
    promotion = 1.5 * ticket_reference_points("先锋招募券", below_threshold=True) if grants_promotion else 0
    parts = {"delayedProcessing": DELAYED_REWARD_DISCOUNT * processed_points,
             "delayedHope": DELAYED_REWARD_DISCOUNT * hope_points, "promotion": promotion}
    return {"points": sum(parts.values()), "parts": parts, "delayDiscount": DELAYED_REWARD_DISCOUNT,
            "promotionUsesFixedDeficitReference": True}


def action_opportunity_score(
    node_scores: list[float], *, action_points: int, gain: int, pursuit: bool = False,
) -> dict:
    """Use a caller-filtered, frozen queue without reveal or recursive AP values."""
    _integer(action_points, "action_points")
    _integer(gain, "gain")
    if type(pursuit) is not bool:
        raise ValueError("pursuit must be boolean")
    for value in node_scores:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
            raise ValueError("node scores must be finite")
    queue = sorted((score for score in node_scores if score > 0), reverse=True)
    covered = action_points if pursuit else max(0, action_points - 1)
    selected = queue[covered:covered + gain]
    return {"points": sum(selected), "coveredCount": covered, "marginals": selected,
            "queue": queue, "unusedGain": gain - len(selected)}


def reveal_information_score(
    node_opportunity_points: Mapping[str, float], *, newly_revealed_ids: Iterable[str],
    already_revealed_ids: Iterable[str] = (), entered_node_id: str | None = None,
    coefficient: float = REVEAL_VALUE_COEFFICIENT,
) -> dict:
    """Price first revelations from nonnegative, frozen values without recursive information."""
    _number(coefficient, "reveal coefficient")
    if not isinstance(node_opportunity_points, Mapping):
        raise ValueError("node opportunity points must be a mapping")
    collections = []
    for values in (newly_revealed_ids, already_revealed_ids):
        if isinstance(values, str):
            raise ValueError("node IDs must be a collection, not a string")
        values = list(values)
        if any(not isinstance(value, str) or not value for value in values):
            raise ValueError("node IDs must be nonempty strings")
        collections.append(set(values))
    if entered_node_id is not None and (not isinstance(entered_node_id, str) or not entered_node_id):
        raise ValueError("entered node ID must be a nonempty string or None")
    new, old = collections
    selected = sorted(new - old - {entered_node_id})
    terms = []
    for node_id in selected:
        if node_id not in node_opportunity_points:
            raise ValueError(f"missing opportunity points for revealed node: {node_id}")
        value = node_opportunity_points[node_id]
        _number(value, f"opportunity points for {node_id}")
        terms.append({"nodeId": node_id, "opportunityPoints": value, "points": coefficient * value})
    return {"points": sum(row["points"] for row in terms), "coefficient": coefficient,
            "countedNodeIds": selected, "terms": terms, "mutatesPlaytime": False}


def safe_corner_score(
    *, two_action_points_value: float, hope_points: float, has_elite1_six_star: bool,
    offered_option_ids: Iterable[str] | None = None,
) -> dict:
    """A fixed rest option plus two uniformly drawn, distinct options; choose the best."""
    _number(two_action_points_value, "two action points value")
    _number(hope_points, "three hope value")
    if type(has_elite1_six_star) is not bool:
        raise ValueError("E1 six-star presence must be boolean")
    options = {
        "rest": 0, "carry_slot": 0, "hope": hope_points,
        "advanced_supply_ticket": 150 if has_elite1_six_star else 75,
        "action_points": two_action_points_value, "box_capacity": 100,
    }
    if offered_option_ids is None:
        menus = [("rest", *pair) for pair in combinations(list(options)[1:], 2)]
        model = "uniform_two_of_five_without_replacement"
    else:
        if isinstance(offered_option_ids, str):
            raise ValueError("offered options must be a collection")
        menu = list(offered_option_ids)
        if (len(menu) != 3 or any(not isinstance(item, str) for item in menu)
                or len(set(menu)) != 3 or "rest" not in menu or set(menu) - options.keys()):
            raise ValueError("a safe-corner menu requires rest plus two distinct known options")
        menus, model = [tuple(menu)], "confirmed_menu"
    outcomes = []
    for menu in menus:
        choice = max(menu, key=lambda option: options[option])
        outcomes.append({"optionIds": list(menu), "probability": 1 / len(menus),
                         "chosenOptionId": choice, "points": options[choice]})
    return {"points": sum(row["probability"] * row["points"] for row in outcomes),
            "options": options, "menus": outcomes, "model": model, "mutatesPlaytime": False}


def emergency_aid_score(corn_count: int) -> dict:
    """Three free hires; estimate corn growth without settling actual inventory."""
    from .component_box import APPRAISAL_EVENTS
    _integer(corn_count, "corn count")
    gain = 3 * APPRAISAL_EVENTS["recruit"]["component_004"] * corn_count
    return {"points": gain * 8, "estimatedValueIncrease": gain,
            "freeHireCount": 3, "cornCount": corn_count, "actualCashAward": 0,
            "mutatesPlaytime": False}


def green_merchant_base_score(economy: float) -> float:
    """A monotone logarithm through (0, 0), (20, 200), and (280, 800)."""
    _number(economy, "spendable scoring economy")
    return GREEN_LOG_SCALE * log1p(economy / GREEN_LOG_OFFSET)


def painted_component_relic_bonus(
    category_id: str, *, painted_agor: int = 0, painted_perro: int = 0,
    arrives_by_processing: bool = False, first_reward: bool = True,
) -> dict:
    for name, count in (("painted_agor", painted_agor), ("painted_perro", painted_perro)):
        _integer(count, name)
    if type(arrives_by_processing) is not bool or type(first_reward) is not bool:
        raise ValueError("arrival and reward state must be boolean")
    count = 0
    if arrives_by_processing and first_reward:
        if category_id == "node_type_008":
            count = 2 * painted_agor
        elif category_id == "node_type_007":
            count = painted_perro
    return {"extraRelics": count, "points": 100 * count}


def merchant_reference_score(
    *, category_id: str, floor: int, cash: float, estimated_value: float,
    box_capacity: int, box_count: int, yellow_visited: bool,
    eligible_event_ids: list[str], below_threshold: bool, squad_id: str | None = None,
    first_visit: bool = True, reserve_override: float | None = None,
    yellow_shop_available: bool | None = None, reserve_entries: Mapping[str, float] | None = None,
    repeat_factor: float = MERCHANT_REPEAT_FACTOR,
) -> dict:
    """Entry/coupon opportunities, not purchases or granted ticket inventory."""
    if category_id not in {"node_type_013", "node_type_004"}:
        raise ValueError("Only yellow and green merchants have reference entry prices")
    if type(first_visit) is not bool or type(below_threshold) is not bool:
        raise ValueError("first visit and team deficit must be booleans")
    _number(repeat_factor, "merchant repeat factor")
    preference = merchant_entry_preferences(
        floor=floor, cash=cash, estimated_value=estimated_value,
        box_capacity=box_capacity, box_count=box_count, yellow_visited=yellow_visited,
        eligible_event_ids=eligible_event_ids, team_below_threshold=below_threshold,
        reserve_override=reserve_override,
        yellow_shop_available=yellow_shop_available, reserve_entries=reserve_entries,
    )
    factor = 1 if first_visit else repeat_factor
    if category_id == "node_type_013":
        economy = cash + estimated_value
        base = min(1000, 30 * economy)
        return {"points": base * factor, "qualified": economy > 0,
                "parts": {"entry": base * factor, "tickets": 0}, "rawPoints": base,
                "repeatFactor": factor, "economyInput": economy, "preferences": preference}
    economy = preference["unreservedEconomy"]
    qualified = economy > 0
    professions = ("先锋", "近卫", "重装", "狙击", "术师", "医疗", "辅助", "特种")
    random_ticket = sum(ticket_reference_points(f"{name}招募券", squad_id=squad_id,
                                               below_threshold=below_threshold)
                        for name in professions) / len(professions)
    home = DUAL_SQUADS.get(squad_id)
    second_ticket = (sum(ticket_reference_points(f"{name}招募券", squad_id=squad_id,
                                                 below_threshold=below_threshold)
                         for name in home[:2]) / 2) if home else random_ticket
    tickets = random_ticket + second_ticket if qualified and first_visit else 0
    base = green_merchant_base_score(economy)
    return {"points": (base + tickets) * factor, "qualified": qualified,
            "parts": {"entry": base * factor, "tickets": tickets * factor},
            "rawPoints": base + tickets, "repeatFactor": factor, "economyInput": economy,
            "randomTicket": random_ticket, "secondTicket": second_ticket,
            "ticketMix": "random_single_plus_home_single" if home else "two_random_singles",
            "sampling": "temporary_uniform_eight_professions", "preferences": preference}


def merchant_prefix_score(
    *, category_id: str, floor: int, cash: float, estimated_value: float,
    box_capacity: int, box_count: int, yellow_visited: bool,
    eligible_event_ids: list[str], below_threshold: bool,
    prefix_cash_outcomes: list[tuple[float, float]], squad_id: str | None = None,
    first_visit: bool = True, reserve_override: float | None = None,
    yellow_shop_available: bool | None = None, reserve_entries: Mapping[str, float] | None = None,
    repeat_factor: float = MERCHANT_REPEAT_FACTOR, path_steps: int = 0,
    step_ingot_expectation: float = PATH_STEP_INGOT_EXPECTATION,
) -> dict:
    """Reprice arrival per net-cash branch; estimates do not unlock executable actions."""
    _number(cash, "initial cash")
    _integer(path_steps, "path steps")
    _number(step_ingot_expectation, "step ingot expectation")
    step_cash = path_steps * step_ingot_expectation
    if not prefix_cash_outcomes:
        raise ValueError("prefix cash outcomes must sum to one")
    validated = []
    for delta, probability in prefix_cash_outcomes:
        if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not isfinite(delta):
            raise ValueError("prefix net cash change must be finite")
        _number(probability, "prefix probability")
        _number(cash + delta, "prefix cash before the step proxy")
        arrival_cash = cash + delta + step_cash
        _number(arrival_cash, "scoring arrival cash")
        validated.append((delta, probability, arrival_cash))
    if not isclose(sum(row[1] for row in validated), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("prefix cash outcomes must sum to one")
    branches = []
    for delta, probability, arrival_cash in validated:
        if not probability:
            continue
        score = merchant_reference_score(
            category_id=category_id, floor=floor, cash=arrival_cash, estimated_value=estimated_value,
            box_capacity=box_capacity, box_count=box_count, yellow_visited=yellow_visited,
            eligible_event_ids=eligible_event_ids, below_threshold=below_threshold,
            squad_id=squad_id, first_visit=first_visit, reserve_override=reserve_override,
            yellow_shop_available=yellow_shop_available, reserve_entries=reserve_entries,
            repeat_factor=repeat_factor,
        )
        branches.append({"netCashChange": delta, "probability": probability,
                         "arrivalCash": arrival_cash, "score": score})
    missing = any(row["score"]["points"] is None for row in branches)
    return {
        "points": None if missing else sum(row["probability"] * row["score"]["points"] for row in branches),
        "qualifiedProbability": sum(row["probability"] for row in branches if row["score"]["qualified"]),
        "expectedArrivalCash": sum(row["probability"] * row["arrivalCash"] for row in branches),
        "branches": branches, "cashModel": "caller_supplied_joint_net_prefix_outcomes",
        "pathSteps": path_steps, "stepIngotExpectation": step_ingot_expectation,
        "stepCashProxy": step_cash,
        "estimatedValueAndOtherConditions": "caller_supplied_arrival_scenario",
        "transactionModelEnabled": False, "mutatesPlaytime": False,
        "unlocksGuaranteedActions": False,
    }


def expected_best_score(outcomes: list[tuple[float, float]], *, candidate_count: int = 1) -> dict:
    """Explicit IID candidate approximation, not a reconstructed joint game distribution."""
    _integer(candidate_count, "candidate_count", 1)
    for points, probability in outcomes:
        _number(points, "points")
        _number(probability, "probability")
    if not outcomes or not isclose(sum(p for _, p in outcomes), 1, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Outcome probabilities must sum to one")
    mean = sum(points * probability for points, probability in outcomes)
    # Sorting a marginal CDF avoids enumerating the Cartesian product of candidates.
    cdf, result = 0.0, 0.0
    for points, probability in sorted(outcomes):
        next_cdf = cdf + probability
        result += points * (next_cdf ** candidate_count - cdf ** candidate_count)
        cdf = next_cdf
    positive_support = [points for points, p in outcomes if p > 0]
    return {"mean": mean, "iidBest": result, "candidateCount": candidate_count,
            "lowerBound": mean, "upperBound": min(candidate_count * mean, max(positive_support))}
