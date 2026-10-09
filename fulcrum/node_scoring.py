"""Read-only utility estimates from a confirmed snapshot, not a reward simulator."""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .battle_rewards import BattleRewardCatalog
from .node_rewards import NodeRewardPoolCatalog
from .operators import PERMANENT_SOURCES
from .team_status import team_status
from .goals import BEACON_DISPATCH_AREAS, goal_summary, planning_pursuit
from .relic_scoring import RelicScorer
from .scoring_profile import PROFILE, PROFILE_PATH, RESOURCE_POINTS, CASH_POINTS
from .diagnostics import localize_result, message
from .merchant_state import DEFAULT_INVESTMENT_BALANCE, SHOP_CATEGORIES, shelf_fraction, snapshot_shelves, withdrawal_quote
from .scoring_calibration import (
    DUAL_SQUADS, action_opportunity_score, component_reference_points,
    dispatch_reference_score, emergency_aid_score,
    expected_best_score, experience_reward_score, merchant_reference_score,
    painted_component_relic_bonus, safe_corner_score, ticket_reference_points,
)

ROOT = Path(__file__).resolve().parents[1]
ROMAN = ("I", "II", "III", "IV", "V", "VI")
UNKNOWN = {"unknown_mystery", "unknown_ferocity"}


@lru_cache(maxsize=2)
def _cached_catalogs(stamps):
    from .node_rewards import RULES_PATH
    pools = NodeRewardPoolCatalog()
    return pools, BattleRewardCatalog(), RelicScorer(catalog=pools), json.loads(RULES_PATH.read_text(encoding="utf-8"))


def _catalogs():
    from .node_rewards import DATA_PATH, RULES_PATH
    from .relic_scoring import CONFIG_PATH
    from .battle_rewards import DATA_PATH as BATTLE_PATH
    return _cached_catalogs(tuple(path.stat().st_mtime_ns for path in (DATA_PATH, RULES_PATH, CONFIG_PATH, BATTLE_PATH)))


@lru_cache(maxsize=2)
def _cached_events(stamps):
    definitions = json.loads((ROOT / "data/blackstream_encounter_pool.json").read_text(encoding="utf-8"))
    weights = json.loads((ROOT / "data/blackflow_encounter_weights.json").read_text(encoding="utf-8"))
    return {row["id"]: row for row in definitions["eventPool"]}, weights


def _events():
    return _cached_events(tuple((ROOT / "data" / name).stat().st_mtime_ns
                               for name in ("blackstream_encounter_pool.json", "blackflow_encounter_weights.json")))


def _finite(value: Any, name: str, *, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    if nonnegative and value < 0:
        raise ValueError(f"{name} must be nonnegative")
    return float(value)


def _value(parts=None, *, cash=0.0, appraisal=0.0, missing=(), **details):
    parts = parts or {}
    return {"points": sum(parts.values()), "parts": parts, "expectedCashDelta": cash,
            "expectedAppraisalDelta": appraisal, "missingTerms": [message(text) for text in missing], **details}


class SnapshotScorer:
    """Freeze ordinary rewards/probabilities; update merchant economy along each path."""

    def __init__(self, nodes: list[dict], context: Mapping[str, Any], state: Mapping[str, Any]):
        self.context = deepcopy(dict(context))
        self.options = self.context.get("options", {})
        if not isinstance(self.options, Mapping):
            raise ValueError("scoring options must be a mapping")
        self.area = self.context["areaKey"]
        self.floor = ROMAN.index(self.area.split("-")[0]) + 1
        self.nodes = {row["id"]: row for row in nodes}
        self.goals = goal_summary(self.context)
        self.milestones = {row["id"]: row for row in self.goals["milestones"]}
        self.true_fates = {key for key, row in self.nodes.items() if row.get("categoryId") == "node_type_012"
                           and (row.get("fateRole") == "true" or "node_mark_003" in row.get("confirmedMarkIds", []))}
        if len(self.true_fates) > 1:
            raise ValueError("multiple true fate nodes; confirm the truth mark before scoring")
        self.completed = set(state["completedNodes"])
        self.pursuit = planning_pursuit(self.goals, self.area, bool(state.get("pursuit")))
        self.action_points = int(state["actionPoints"])
        self.prediction = self.context.get("prediction", {})
        self.resources = self.context["resources"]
        self.cash = _finite(self.resources["originiumIngot"], "originiumIngot", nonnegative=True)
        self.investment_balance = _finite(self.resources.get("investmentBalance", DEFAULT_INVESTMENT_BALANCE),
                                          "investmentBalance", nonnegative=True)
        self.withdrawal_cash_points = _finite(self.options.get("withdrawalCashPointValue", PROFILE["merchants"]["withdrawalCashPoints"]),
                                               "withdrawalCashPointValue", nonnegative=True)
        self.merchant_shelves = {key: snapshot_shelves({**row, "completion": "completed"} if key in self.completed else row)
                                 for key, row in self.nodes.items()}
        self.level = self.resources["level"]
        self.experience = self.resources["experience"]["current"]
        experience_reward_score(level=self.level, experience=self.experience, reward=0,
                                below_threshold=False, hope_deficit=0)
        self.life = self.resources["life"]["current"]
        if type(self.life) is not int or self.life < 1:
            raise ValueError("positive confirmed life is required for scoring")
        self.squad = self.context.get("opening", {}).get("squadId")
        self.components = self.context.get("componentBox", {}).get("items", [])
        self.counts = Counter(item["componentId"] for item in self.components)
        self.natural_count_initial = sum(int(item["componentId"].split("_")[1]) <= 12 for item in self.components)
        self.dystopia = deepcopy(state.get("dystopia") or {})
        self.utopia = state.get("utopiaId") if "treehole" in self.area else None
        self.capacity = self.context.get("componentBox", {}).get("capacity", 8)
        self.warnings: set[str] = set()
        if "merchantRepeatFactor" in self.options:
            self.warnings.add("merchantRepeatFactor is superseded by per-node merchantViewedShelves")
        self.pools, self.battles, self.relics, self.reward_rules = _catalogs()
        self.definitions, self.weight_data = _events()
        self.operators = self.context.get("operators", [])
        permanent = [op for op in self.operators if op.get("source") in PERMANENT_SOURCES
                     and op.get("remainingBattles") is None]
        unknown_rarity = [op["name"] for op in permanent if op.get("rarity") is None]
        self.threshold = team_status(self.operators, self.floor, self.squad, self.options)
        self.threshold["unknownRarityOperators"] = unknown_rarity
        if unknown_rarity and "teamCounts" not in self.options:
            self.warnings.add("Unknown operator rarity: threshold uses confirmed six-stars only; add rarity or teamCounts")
        self.below = not self.threshold["met"]
        self.reference_cost = _finite(self.options.get("referenceSixStarHopeCost", 7 if self.squad in DUAL_SQUADS else 10),
                                      "referenceSixStarHopeCost", nonnegative=True)
        if self.reference_cost == 0:
            raise ValueError("referenceSixStarHopeCost must be positive")
        missing = self.threshold["deficits"]
        recruits = missing["sixStars"]
        promotions = missing["elite2SixStars"]
        recruit_cost = self.reference_cost - (2 if self.squad in DUAL_SQUADS else 3)
        hope = self.resources.get("hope")
        _finite(hope, "hope", nonnegative=True)
        self.hope_deficit = _finite(self.options.get("hopeDeficit", max(0, recruits * recruit_cost
                                    + promotions * (2 if self.squad in DUAL_SQUADS else 3) - hope)),
                                    "hopeDeficit", nonnegative=True)
        self.exit_hope_floor = _finite(self.options.get("exitHopePointFloor", RESOURCE_POINTS["exitHopePointFloor"]),
                                       "exitHopePointFloor", nonnegative=True)
        self.threshold["hopeDeficit"] = self.hope_deficit
        self.threshold["hopeCostAssumption"] = "missing six-stars/promotion only; other roster slots may use free recruits; dual-squad home cost proxy"
        self.mechanist = next((op for op in permanent if op["name"] == "机械师"), None)
        self.heavy_needed = 0 if self.mechanist and self.mechanist.get("elite") == 2 else 1 if self.mechanist else 2
        self.held_tickets = [({"name": row} if isinstance(row, str) else row)
                             for row in self.context.get("recruitmentTickets", [])]
        self.heavy_held = sum(row.get("count", 1) for row in self.held_tickets if row.get("name") == "重装招募券")
        self.ticket_total = self._held_ticket_value()
        self.has_e1_six = any(op.get("rarity") == 6 and op.get("elite") == 1 for op in permanent)
        self.initial_appraisal = self.resources.get("totalEstimatedValue")
        if self.initial_appraisal is None:
            self.initial_appraisal = sum(item.get("estimatedValue") or 0 for item in self.components)
            if any(item.get("estimatedValue") is None for item in self.components):
                self.warnings.add("Some component appraisals are unknown; merchant economy includes known appraisals only")
        self.initial_appraisal = _finite(self.initial_appraisal, "totalEstimatedValue", nonnegative=True)
        self.processed_available = any((item.get("remainingUses") or 0) > 0 for item in self.components)
        self.processed_available |= any((item.get("remainingUses") or 0) > 0 for item in state.get("items", []))
        self.pool_cache: dict[str, float] = {}
        self.probability_cache: dict[str, dict] = {}
        self.action_queue: list[float] = []
        self.weights = self.options.get("nodeWeights", {})
        self.overrides = self.options.get("nodeScores", {})
        for key, value in {**self.weights, **self.overrides}.items():
            if key not in self.nodes:
                raise ValueError(f"unknown node scoring override: {key}")
            _finite(value, key)
        self.event_distribution = self._event_distribution()
        if self.dystopia.get("active"):
            if self.dystopia.get("uncertainNodeIds"):
                self.warnings.add("Unconfirmed dystopia coverage has no policy adjustment until reviewed")
        # One nonrecursive pass: AP-bearing rewards cannot inflate their own marginal queue.
        preliminary = {node_id: self._node(row) for node_id, row in self.nodes.items()}
        preliminary = {key: self.with_policy(value, self.policy_effect(key, self.cash, self.completed), weighted=False)
                       for key, value in preliminary.items()}
        self.action_queue = [self.overrides.get(key, value["points"] * self.weights.get(key, 1))
                             for key, value in preliminary.items() if key not in self.completed
                             and self.nodes[key].get("categoryId") not in {"node_type_003", "node_type_012", "node_type_015", "node_type_016"}]
        self.pool_cache.clear()
        self.values = {node_id: self._node(row) for node_id, row in self.nodes.items()}
        self.reveal_coefficient = _finite(self.options.get("revealCoefficient", PROFILE["information"]["revealCoefficient"]), "revealCoefficient", nonnegative=True)
        self.step_ingot = _finite(self.options.get("stepIngotExpectation", PROFILE["information"]["pathStepIngotExpectation"]), "stepIngotExpectation", nonnegative=True)
        for key, value in self.values.items():
            factor = self.weights.get(key, 1)
            original = value["points"]
            points = self.overrides.get(key, original * factor)
            if points != original:
                value["parts"]["strategyAdjustment"] = points - original
                value["points"] = points
        self.base_values = self.values
        self.values = {key: self.with_policy(value, self.policy_effect(key, self.cash, self.completed))
                       for key, value in self.base_values.items()}

    def policy_active(self, done: set[str]) -> bool:
        if not self.dystopia.get("active"):
            return False
        if self.dystopia.get("ideologyId") == "dystopia_008":
            return True
        return self.dystopia.get("idealSourceNodeId") not in done

    def natural_count(self, done: set[str]) -> int:
        spent = sum(2 for key in done - self.completed if self.base_values.get(key, {}).get("plannedOption") == "tribute"
                    and self.base_values[key].get("expectedNaturalCountLost")) if hasattr(self, "base_values") else 0
        return max(0, self.natural_count_initial - spent)

    def policy_effect(self, key: str, cash: float, done: set[str]) -> dict | None:
        policy = self.dystopia.get("policyId")
        if (policy not in {"dystopia_011", "dystopia_014"} or not self.policy_active(done)
                or key not in self.dystopia.get("affectedNodeIds", [])):
            return None
        count = self.natural_count(done)
        cash_lost = min(2, max(0, cash)) if policy == "dystopia_011" else 0
        appraisal_gain = 2 * count if policy == "dystopia_014" else 0
        return {"policyId": policy, "cashBefore": max(0, cash), "cashLost": cash_lost,
                "naturalCount": count, "appraisalIncrease": appraisal_gain,
                "unitPoints": CASH_POINTS, "points": CASH_POINTS * (appraisal_gain - cash_lost),
                "sourceDestroyedAfter": key == self.dystopia.get("idealSourceNodeId")
                    and self.dystopia.get("ideologyId") != "dystopia_008"}

    def with_policy(self, value: dict, effect: dict | None, *, weighted=True) -> dict:
        if effect is None:
            return value
        value = {**value, "parts": dict(value["parts"])}
        points = effect["points"] * (self.weights.get(value.get("nodeId"), 1) if weighted else 1)
        term = "dystopiaCashCost" if effect["policyId"] == "dystopia_011" else "dystopiaNaturalAppraisal"
        value["parts"][term] = points
        value["points"] += points
        value["expectedCashDelta"] -= effect["cashLost"]
        value["expectedAppraisalDelta"] += effect["appraisalIncrease"]
        value["policyAdjustment"] = {**effect, "weightedPoints": points, "triggerTiming": "arrival_before_node_reward"}
        return value

    def preview_value(self, key: str, *, done=None, cash=None) -> dict:
        return self.with_policy(self.base_values[key], self.policy_effect(key,
            self.cash if cash is None else cash, self.completed if done is None else done))

    def action_value(self, gain: int) -> float:
        return action_opportunity_score(self.action_queue, action_points=self.action_points,
                                        gain=gain, pursuit=self.pursuit)["points"]

    def goal_pending(self, goal_id: str) -> bool:
        goal = self.milestones[goal_id]
        selected = self.options.get("planningGoalIds")
        desired = goal["priority"] != "ignored" if selected is None else goal_id in selected
        return desired and goal["status"] not in {"completed", "unavailable"}

    def natural_tribute(self) -> dict:
        natural = [item for item in self.components if int(item["componentId"].split("_")[1]) <= 12]
        if len(natural) < 2:
            return _value({"exchangeOpportunity": PROFILE["events"]["exchangeOpportunityPoints"]}, missing=["planned tribute needs two held natural components"],
                          goalId="ending3_trade", plannedOption="exchange", goalFeasible=False,
                          scoringBasis=[{"label": "自然物不足2件，按普通交换估值", "points": PROFILE["events"]["exchangeOpportunityPoints"]}])
        cost = 2 * sum(component_reference_points(item["componentId"],
            existing_same=max(0, self.counts[item["componentId"]] - 1)) for item in natural) / len(natural)
        appraisal_cost = 2 * sum(item.get("estimatedValue") or 0 for item in natural) / len(natural)
        limitations = ["random tribute assumes uniform selection of two held natural-component instances",
                       "tribute item identities remain frozen during search; confirm inventory and replan"]
        missing = []
        if any(item.get("estimatedValue") is None for item in natural):
            missing.append("tribute appraisal uses confirmed values only")
        return _value(appraisal=-appraisal_cost, missing=missing, modelLimitations=limitations,
                      goalId="ending3_trade", plannedOption="tribute", goalFeasible=True,
                      naturalCount=len(natural), expectedNaturalCountLost=2,
                      scoringBasis=[{"label": f"选择失与得上贡，不计普通交换的{PROFILE['events']['exchangeOpportunityPoints']}分", "points": 0},
                                    {"label": "获得焚毁“文明”（结局前置）", "points": 0}],
                      referenceLoss={"points": -cost, "parts": {"naturalTributeCost": -cost},
                                     "includedInPlanningScore": False, "expectedNaturalCountLost": 2,
                                     "expectedAppraisalLost": appraisal_cost,
                                     "cashEquivalentPoints": -CASH_POINTS * appraisal_cost, "cashUnitPoints": CASH_POINTS,
                                     "componentUnitPoints": cost / 2,
                                     "basis": "current_inventory_uniform_two_naturals"})

    def cash_tribute(self, cash: float) -> dict:
        selected = self.options.get("planningGoalIds")
        reference_only = selected is None or self.goal_pending("ending3_tribute")
        return _value({} if reference_only else {"cashCost": -CASH_POINTS * cash}, cash=-cash,
                      goalId="ending3_tribute", plannedOption="tribute", goalFeasible=True,
                      scoringBasis=[{"label": "倾囊资助，获得击坠“神明”（结局前置）", "points": 0}],
                      referenceLoss={"points": -CASH_POINTS * cash, "parts": {"cashCost": -CASH_POINTS * cash},
                                     "includedInPlanningScore": not reference_only, "expectedCashLost": cash,
                                     "cashUnitPoints": CASH_POINTS,
                                     "basis": "current_cash"})

    def hope_value(self, amount: float) -> float:
        return min(amount, self.hope_deficit) * RESOURCE_POINTS["completeSixStarPoints"] / self.reference_cost if self.below else 0

    def ticket(self, name: str, *, heavy_special: bool | None = None) -> float:
        points = ticket_reference_points(name, squad_id=self.squad, below_threshold=self.below)
        special = self.heavy_held < self.heavy_needed if heavy_special is None else heavy_special
        return points * (PROFILE["tickets"]["mechanistHeavyFactor"] if name == "重装招募券" and special else 1)

    def _held_ticket_value(self) -> float:
        heavy = 0
        points = 0.0
        for row in self.held_tickets:
            name = row.get("name")
            if name is None:
                self.warnings.add("Held recruitment ticket missing name; end-node recruitment utility is partial")
                continue
            for _ in range(row.get("count", 1)):
                points += self.ticket(name, heavy_special=heavy < self.heavy_needed)
                if name == "重装招募券":
                    heavy += 1
        return points

    def pool(self, context_id: str) -> float:
        if context_id in self.pool_cache:
            return self.pool_cache[context_id]
        pool = self.pools.by_id[context_id]
        if pool["members"] and all(row["dataType"] == "藏品" for row in pool["members"]):
            points = self.relics.pool_score(context_id)
        else:
            observed = [row for row in pool["members"] if row.get("occurrenceCount") is not None]
            total = sum(row["occurrenceCount"] for row in observed)
            if not total:
                raise ValueError(f"missing reward frequencies for {context_id}")
            outcomes = []
            for row in observed:
                if row["dataType"] == "零件":
                    points = component_reference_points(row["itemId"], existing_same=self.counts[row["itemId"]],
                                                        action_unit=self.action_value(1))
                elif row["dataType"] == "招募券":
                    points = self.ticket(row["name"])
                else:
                    raise ValueError(f"unpriced reward in {context_id}: {row['dataType']}")
                outcomes.append((points, row["occurrenceCount"] / total))
            selection = pool.get("selection") or {}
            if selection.get("takeCount", 1) != 1:
                raise ValueError(f"unsupported reward selection in {context_id}")
            points = expected_best_score(outcomes, candidate_count=selection.get("candidateCount", 1))["expectedBest"]
        self.pool_cache[context_id] = points
        return points

    def battle(self, mode: str, *, stage=None, area=None, components=(), relic_context=None, relic_count=0,
               ticket_context="node_battle_recruit", node=None) -> dict:
        key = area or self.area
        missing = []
        if "treehole" in key and stage is None and mode in {"normal", "emergency"}:
            entry = ROMAN.index(key.split("-")[0])
            rule = PROFILE["overlays"]["unconfirmedTreeholeBattle"]
            rows = [{"areaKey": region, "probability": probability,
                     "score": self.battle(mode, area=region, components=components, relic_context=relic_context,
                                          relic_count=relic_count, ticket_context=ticket_context, node=node)}
                    for region, probability in ((ROMAN[entry], rule["entryLayerProbability"]),
                                                (ROMAN[entry + 1], rule["nextLayerProbability"]))]
            value = self._weighted_value(rows, "treeholeCombatExpectation", battleOutcomes=rows,
                                         branches=[{"name": f"{row['areaKey']}层战斗奖励", **row} for row in rows],
                                         rewardBasis="entry_next_layer_equal_mean")
            value["experienceAward"] = sum(row["probability"] * row["score"]["experienceAward"] for row in rows)
            return value
        try:
            reward = self.battles.resolve(area_key=key, mode=mode, stage_name=stage,
                experience_multipliers=self.options.get("experienceMultipliers"))
        except ValueError as error:
            return _value(missing=[str(error)])
        if reward.get("terminalRewardOverride"):
            return _value({"finalBattle": PROFILE["exits"]["finalBattlePoints"]}, experienceAward=0, stage=stage)
        cash = reward["originiumIngot"]
        if cash["kind"] == "fixed":
            ingots = cash["value"]
        elif stage == self.reward_rules["battles"]["stranger_companion"]["stageName"]:
            rule = self.reward_rules["battles"]["stranger_companion"]
            ingots = self.battles.resolve(area_key=key.split("-")[0], mode=rule["ingotsReferenceMode"],
                                         experience_multipliers=self.options.get("experienceMultipliers"))["originiumIngot"]["value"]
            reward["cashReference"] = {"areaKey": key.split("-")[0], **rule}
        else:
            ingots = 0
            missing.append("variable combat cash distribution unpriced")
        xp = experience_reward_score(level=self.level, experience=self.experience, reward=reward["experienceAward"],
             below_threshold=self.below, hope_deficit=self.hope_deficit, reference_six_star_cost=self.reference_cost)
        value = _value({"experience": xp["points"], "cash": ingots * CASH_POINTS,
                       "tickets": self.pool(ticket_context) if ticket_context else 0,
                       "components": sum(self.pool(context) for context in components),
                       "relics": relic_count * self.relics.pool_score(relic_context) if relic_count else 0},
                      cash=ingots, missing=missing, experienceAward=reward["experienceAward"], stage=stage,
                      **({"cashReference": reward["cashReference"]} if "cashReference" in reward else {}))
        return self.with_soil_reward(value, node)

    def with_soil_reward(self, value: dict, node: dict | None) -> dict:
        rule = PROFILE["overlays"]["hopefulSoil"]
        if (not node or not self.dystopia.get("active") or self.dystopia.get("ideologyId") != rule["ideologyId"]
                or node["id"] not in self.dystopia.get("affectedNodeIds", [])):
            return value
        points = rule["componentCount"] * self.pool(rule["componentContextId"])
        return {**value, "points": value["points"] + points,
                "parts": {**value["parts"], "hopefulSoilComponent": points},
                "extraComponentContextIds": [rule["componentContextId"]]}

    def fruit_reward(self) -> dict:
        rule = PROFILE["overlays"]["fruitMark"]
        members = self.pools.by_id[rule["contextId"]]["members"]
        total = sum(row.get("occurrenceCount") or 0 for row in members)
        if not total:
            return _value(missing=["藏果地零件池缺少统计频次"])
        rows = [{"itemId": row["itemId"], "probability": (row.get("occurrenceCount") or 0) / total,
                 "cashEquivalent": rule["cashEquivalents"][row["itemId"]],
                 "points": rule["cashEquivalents"][row["itemId"]] * CASH_POINTS} for row in members]
        return _value({"fruitMarkNatural": sum(row["probability"] * row["points"] for row in rows)}, fruitOutcomes=rows,
                      rewardContextId=rule["contextId"], cashUnitPoints=CASH_POINTS)

    def utopia_cash(self, category: str | None) -> float:
        rule = PROFILE["overlays"]["utopiaCash"].get(self.utopia)
        if not rule or category in {None, "start", "node_type_020"}:
            return 0
        return rule["ingots"] if not rule.get("categoryId") or category == rule["categoryId"] else 0

    def healing_heart(self) -> dict:
        rule = self.reward_rules["events"]["encounter_012"]
        costs = rule["remembranceCosts"]
        legal_costs = []
        if self.action_points >= costs["actionPoints"]:
            legal_costs.append("消耗3行动力")
        processing_count = sum(13 <= int(item["componentId"].split("_")[1]) <= 24 for item in self.components)
        if processing_count >= costs["processingCount"]:
            legal_costs.append("消耗2件加工品")
        if any(row.get("id") == costs["relicId"] and row.get("count", 1) > 0 for row in self.context.get("relics", [])):
            legal_costs.append("消耗源私钥")
        options = []
        if legal_costs:
            points = PROFILE["events"]["remembrancePoints"]
            options.append(_value({"remembrance": points}, plannedOption="remembrance",
                                  eligibleCosts=legal_costs, scoringBasis=[{"label": "取得追忆（合法选项）", "points": points}]))
        for gain in ([5, 1] if self.counts[rule["controllerItemId"]] else [1]):
            options.append(_value({"actionOpportunity": self.action_value(gain)}, actionGainEstimate=gain,
                                  plannedOption=f"actionGain{gain}"))
        selected = max(options, key=lambda row: row["points"])
        return {**selected, "legalOptions": options, "selectionBasis": "highest_legal_option_at_snapshot"}

    def _event_distribution(self) -> dict:
        area = "IV" if self.area == "IV-remembrance" else self.area
        if area != self.area:
            self.warnings.add("Remembrance event weights use ordinary IV evidence; node-distance frequencies stay separate")
        weights = self.weight_data["areas"].get(area, {})
        pool = self.prediction.get("encounterPool")
        allowed = {row["id"] for row in pool["candidates"]} if pool is not None else {
            key for key, row in self.definitions.items()
            if ROMAN[self.floor - 1] in row["floors"] and not row.get("specialMarkId")}
        ever_controller = bool(self.options.get("controllerEverObtained")) or self.counts["component_012"] > 0
        obtained_outcomes = {"obtained_controller", "controller_obtained", "获得笼控器", "笼控器已获得"}
        ever_controller |= any(outcome in obtained_outcomes
            for row in self.context.get("globalEncounterPool", []) if row["id"] == "encounter_008"
            for outcome in row.get("outcomes", {}).values())
        if not ever_controller:
            allowed.discard("encounter_010")
        rows = [{"eventId": key, "weight": row["weight"]} for key, row in weights.items()
                if key in allowed and row["weight"] > 0]
        total = sum(row["weight"] for row in rows)
        for row in rows:
            row["probability"] = row["weight"] / total
        missing = sorted(allowed - weights.keys())
        if missing:
            self.warnings.add(f"Events without sampled weights are not silently redistributed: {', '.join(missing)}")
        return {"events": rows, "unweightedEventIds": missing, "sourceCheckedAt": self.weight_data.get("checkedAt")}

    def encounter(self, event_id: str, node=None) -> dict:
        cash, life = self.cash, self.life
        score = _value(missing=[f"event not priced: {event_id}"])
        if event_id == "encounter_001":
            score = _value({"chosenOption": max(10 * CASH_POINTS, self.hope_value(3))}, cash=10 if 10 * CASH_POINTS >= self.hope_value(3) else 0)
        elif event_id == "encounter_002":
            score = _value({"lifeShieldExcluded": 0})
        elif event_id == "encounter_003":
            best = max(self.pool(f"node_incident_goods_from_mouth_{kind}") for kind in ("natural", "concept", "processing"))
            score = _value({"component": best, "cashCost": -4 * CASH_POINTS}, cash=-4) if cash >= 4 else self.empty_event()
        elif event_id == "encounter_004":
            gain = 5
            score = _value({"actionOpportunity": self.action_value(gain)}, actionGainEstimate=gain)
        elif event_id == "encounter_012":
            score = self.healing_heart()
        elif event_id == "encounter_005":
            count, cost = (3, 10) if cash >= 10 else (1, 4) if cash >= 4 else (0, 0)
            score = (_value({"relics": count * self.relics.pool_score("node_incident_knock_lever"), "cashCost": -CASH_POINTS * cost},
                            cash=-cost) if count else self.empty_event())
        elif event_id in {"encounter_006", "encounter_007"}:
            score = _value({"relics": self.options.get("eventRelicScores", {}).get(event_id, PROFILE["events"]["eventRelicScores"][event_id])})
        elif event_id == "encounter_008":
            cost = 0 if life >= 3 else 8 if cash >= 8 else None
            score = _value({"controller": PROFILE["components"]["fixedPoints"]["component_012"], "cashCost": -cost * CASH_POINTS}, cash=-cost) if cost is not None else self.empty_event()
        elif event_id == "encounter_010":
            if self.counts["component_012"]:
                score = _value({"cash": 30 * CASH_POINTS, "hopefulSoil": self.options.get("hopefulSoilOpportunityPoints", PROFILE["events"]["hopefulSoilOpportunityPoints"])}, cash=30,
                               scoringBasis=[{"label": "持有笼控器，免费触发下一层希望的沃土", "points": self.options.get("hopefulSoilOpportunityPoints", PROFILE["events"]["hopefulSoilOpportunityPoints"])}])
            elif self.counts["component_001"]:
                seed = PROFILE["components"]["fixedPoints"]["component_001"]
                points = self.options.get("hopefulSoilOpportunityPoints", PROFILE["events"]["hopefulSoilOpportunityPoints"])
                score = _value({"seedCost": -seed, "hopefulSoil": points},
                               scoringBasis=[{"label": "消耗1种子，触发下一层希望的沃土", "points": points - seed}])
            else:
                score = self.empty_event("no seed/controller: empty event penalty pending")
        elif event_id == "encounter_011":
            score = self._shadow()
        elif event_id in {"encounter_009", "encounter_013", "encounter_014", "encounter_015", "encounter_016"}:
            urgent = event_id == "encounter_015" or event_id == "encounter_016" and cash >= 50
            stage, relic_count = {"encounter_009": ("“闹乐”", 1), "encounter_013": ("陌生旅伴", 1),
                "encounter_014": ("安保措施", 3), "encounter_015": ("开业剪彩", 3),
                "encounter_016": ("合伙人会议", 4 if urgent else 3)}[event_id]
            score = self.battle("specialEmergency" if urgent else "specialNormal", stage=stage, node=node)
            points = self.relics.fixed_score("relic_209") if event_id == "encounter_009" else self.relics.pool_score(self.relics.event_pool(event_id)) * relic_count
            score["parts"]["relics"] = points
            score["points"] += points
        elif event_id == "encounter_017":
            urgent = cash >= 3
            combat = self.battle("specialEmergency" if urgent else "specialNormal", stage="湖中魇",
                 components=("node_battle_elite_scrap",), relic_context="node_incident_lake_fairy_emergency" if urgent else "node_incident_lake_fairy",
                 relic_count=1 if urgent else 5 / 11, node=node)
            if urgent:
                score = _value({"combat80Percent": .8 * combat["points"], "directRelic20Percent": .2 * self.relics.pool_score("node_incident_lake_fairy_direct"),
                                "cashCost": -3 * CASH_POINTS}, cash=.8 * combat["expectedCashDelta"] - 3,
                               missing=combat["missingTerms"], outcomes=[{"probability": .8, "combat": combat}, {"probability": .2, "relicOnly": True}])
            else:
                score = combat
        elif event_id == "encounter_018":
            combat = self.battle("normal", area=ROMAN[min(self.floor, 5)], node=node)
            score = _value({"cash": 2.5 * CASH_POINTS, "relics": .5 * self.relics.pool_score("node_incident_cave_treasure"),
                            "nextLayerCombat": .5 * combat["points"]}, cash=2.5 + .5 * combat["expectedCashDelta"], missing=combat["missingTerms"])
        elif event_id == "encounter_019":
            score = _value({"temporarySixStar": PROFILE["tickets"]["temporarySixStarFactor"] * ticket_reference_points("先锋招募券", below_threshold=self.below)})
        elif event_id in {"encounter_020", "encounter_021"}:
            category = "node_type_019" if event_id == "encounter_020" else "node_type_017"
            targets = [row for row in self.nodes.values() if row.get("categoryId") == category and row["id"] not in self.completed]
            extra = self.category(category, targets[0]) if targets else _value()
            score = _value({"relics": self.relics.fixed_score("relic_208" if event_id == "encounter_020" else "relic_207"),
                            "freeVisit": extra["points"]}, cash=extra["expectedCashDelta"], appraisal=extra["expectedAppraisalDelta"],
                           missing=extra["missingTerms"])
        elif event_id == "encounter_022":
            score = (_value({"sandboxAlpha": 0}, goalId="ending2_sandbox", plannedOption="sandboxAlpha",
                            scoringBasis=[{"label": "计划取得沙盘α（结局前置），不计高稀有度加工品选项", "points": 0}])
                     if self.goal_pending("ending2_sandbox") else
                     _value({"processing": self.pool("node_incident_informant_processing")}, plannedOption="processing"))
        elif event_id == "encounter_023":
            score = self.cash_tribute(cash)
        extra = _finite(self.options.get("eventExtraScores", {}).get(event_id, PROFILE["events"]["extraScores"].get(event_id, 0)), "eventExtraScore")
        score["parts"]["eventExtra"] = extra
        score["points"] += extra
        return {**score, "eventId": event_id}

    def empty_event(self, note="empty event penalty pending") -> dict:
        points = PROFILE["events"]["emptyEventPenaltyPoints"]
        return _value({"emptyEventPenalty": points or 0}, missing=[note] if points is None else [])

    def _shadow(self) -> dict:
        natural = self.pool("node_incident_praised_shadow_random_natural")
        processed = self.pool("node_incident_praised_shadow_random_processing")
        relic = self.relics.pool_score("node_incident_praised_shadow_random_collectible")
        costs = (1, 1, 2, 2, 2, 3, 3, 3)
        @lru_cache(maxsize=None)
        def visit(index, hp, deficit):
            if index == 8 or hp <= costs[index]:
                return 0.0, 0.0
            hp -= costs[index]
            rows = {0: [(0, 1, 0, 0), (4 * CASH_POINTS, 0, 0, 4)], 1: [(0, 1, 0, 0), (0, 0, 2, 0)],
                    2: [(0, 2, 0, 0), (natural, 0, 0, 0)], 3: [(0, 2, 0, 0), (processed, 0, 0, 0), (12 * CASH_POINTS, 0, 0, 12)],
                    4: [(0, 5, 0, 0), (relic, 0, 0, 0)], 5: [(0, 3, 0, 0), (0, 0, 8, 0), (0, 0, 0, 0)],
                    6: [(3 * relic, 0, 0, 0)], 7: [(self.relics.fixed_score("relic_215"), 0, 0, 0)]}[index]
            points = cash = 0.0
            for value, heal, hope, money in rows:
                after = visit(index + 1, min(self.resources["life"].get("max") or self.life, hp + heal), max(0, deficit - hope))
                points += value + (min(hope, deficit) * RESOURCE_POINTS["completeSixStarPoints"] / self.reference_cost if self.below else 0) + after[0]
                cash += money + after[1]
            return points / len(rows), cash / len(rows)
        points, cash = visit(0, self.life, self.hope_deficit)
        return _value({"conditionalRounds": points}, cash=cash)

    def category(self, category: str | None, node: dict) -> dict:
        value = self._category(category, node)
        cash = self.utopia_cash(category) if self.utopia == "utopia_009" else 0
        if cash:
            value = {**value, "points": value["points"] + CASH_POINTS * cash,
                     "parts": {**value["parts"], "utopiaCash": CASH_POINTS * cash},
                     "expectedCashDelta": value["expectedCashDelta"] + cash}
        return value

    def _category(self, category: str | None, node: dict) -> dict:
        stage = node.get("stageName")
        if category == "node_type_001":
            return self.battle("normal", stage=stage, node=node)
        if category == "node_type_002":
            return self.battle("emergency", stage=stage, components=("node_battle_elite_scrap",), relic_count=1, relic_context="node_battle_elite", node=node)
        if category == "node_type_003":
            if self.floor == 6:
                return _value({"finalBattle": PROFILE["exits"]["finalBattlePoints"]}, stage=stage)
            return self.battle("boss", stage=stage, components=("node_battle_boss_scrap",), relic_count=1,
                               relic_context="pool_boss", ticket_context="node_battle_boss_recruit", node=node)
        if category in {"node_type_004", "node_type_013"}:
            shop = self.shop(category, self.cash, self.initial_appraisal, done=self.completed, repeated=False,
                             node_id=node["id"])
            return _value(shop["parts"], merchant=shop)
        if category == "node_type_005":
            safe = safe_corner_score(two_action_points_value=self.action_value(2), hope_points=self.hope_value(3),
                                      has_elite1_six_star=self.has_e1_six, offered_option_ids=node.get("offeredOptionIds"))
            return _value({"bestMenuExpectation": safe["points"]}, options=safe, actionRewardIsEstimate=True)
        if category == "node_type_006":
            event = node.get("encounterId")
            if event:
                return self.encounter(event, node)
            rows = [{**row, "score": self.encounter(row["eventId"], node)} for row in self.event_distribution["events"]]
            marked = self.probabilities(node).get("markedEventProbabilities", {}) if node.get("categoryId") in UNKNOWN else {}
            remainder = max(0, 1 - sum(marked.values()))
            rows = [{**row, "probability": row["probability"] * remainder} for row in rows if remainder > 0]
            rows += [{"eventId": key, "probability": probability, "score": self.encounter(key, node), "placementBasis": "ending_uniform_slots"}
                     for key, probability in marked.items() if probability > 0]
            value = self._weighted_value(rows, "encounterExpectation", events=rows)
            value["missingTerms"] += ((["empty sampled encounter pool"] if not rows else []) +
                (["eligible events missing weight"] if self.event_distribution["unweightedEventIds"] and remainder > 0 else []))
            return value
        if category == "node_type_007":
            wish = self.relics.wish_score(self.cash)
            return _value({"relics": wish["relicPoints"], "cashCost": -wish["cashCostPoints"]}, cash=-4 if self.cash >= 4 else 0)
        if category == "node_type_008":
            if "node_mark_006" in node.get("confirmedMarkIds", []) and self.goal_pending("ending3_trade"):
                return self.natural_tribute()
            return _value({"exchangeOpportunity": PROFILE["events"]["exchangeOpportunityPoints"]}, plannedOption="exchange")
        if category == "node_type_009":
            choose_beacon = (self.goal_pending("ending3_beacon") or
                             self.options.get("planningGoalIds") is None and self.options.get("chooseEnding3Dispatch", False))
            choose_beacon &= self.milestones["ending3_beacon"]["status"] not in {"completed", "unavailable"}
            choose_beacon &= self.area in BEACON_DISPATCH_AREAS
            dispatch = dispatch_reference_score(processed_points=self.pool("pool_scrap_3"), hope_points=self.hope_value(2),
                grants_promotion=not choose_beacon)
            return _value(dispatch["parts"], plannedOption="beacon" if choose_beacon else "promotion",
                          **({"scoringBasis": [{"label": "派遣取得怦然信标（结局前置）", "points": 0},
                                               {"label": "归队不进阶，不计普通派遣的进阶价值", "points": 0}]}
                             if choose_beacon else {}),
                          **({"goalId": "ending3_beacon"} if choose_beacon else {}))
        if category == "node_type_010":
            return _value({"treeholeActionProxy": self.action_value(PROFILE["exits"]["treeholeEntryAPProxy"]) if self.processed_available else 0}, actionRewardIsEstimate=True)
        if category == "node_type_011":
            base = self.pool("node_battle_recruit")
            choices = {"low": self.pool("node_duel_left") + 2 * base,
                       "middle": self.pool("node_duel_center") + 2 * base,
                       "high": self.relics.pool_score("node_duel_right") + base + PROFILE["tickets"]["duelTemporaryElitePoints"] * (RESOURCE_POINTS["belowThresholdFactor"] if self.below else 1)}
            selected = node.get("duelTier") or max(choices, key=choices.get)
            return self.with_soil_reward(_value({"duelReward": choices[selected]}, selectedTier=selected, choices=choices), node)
        if category == "node_type_012":
            role = ("true" if node["id"] in self.true_fates else "fake" if self.true_fates else node.get("fateRole", "unknown"))
            probability = 0 if role == "true" else 1 if role == "fake" else 2 / 3
            return _value({"fakeFateRelic": probability * self.relics.pool_score("node_story_curiosity_and_death")},
                          fateRole=role, fakeFateProbability=probability,
                          **({"goalId": "ending2_final", "finalBattleValueExcluded": True} if role == "true" else {}))
        if category == "node_type_015":
            return _value({"heldRecruitmentTickets": node.get("recruitmentScore", self.ticket_total)})
        if category == "node_type_017":
            aid = emergency_aid_score(self.counts["component_004"])
            return _value({"cornAppraisal": aid["points"]}, appraisal=aid["estimatedValueIncrease"])
        if category in {"node_type_019", "node_type_021"}:
            outpost = category == "node_type_019"
            convergence = stage == "进退趋同" or self.area == "VI" and not outpost
            stage = stage or ("败叶" if self.floor >= 4 else "枯枝") if outpost else stage or ("进退趋同" if convergence else "强买强卖")
            suffix = "convergence_" if convergence else ""
            return self.battle("specialNormal", stage=stage,
                components=("node_battle_savage_scrap_left", "node_battle_savage_scrap_right") if outpost else (f"node_wandering_resident_{suffix}scrap",),
                relic_count=1, relic_context="node_battle_savage" if outpost else f"node_wandering_resident_{suffix}relic",
                ticket_context="node_battle_savage_recruit" if outpost else f"node_wandering_resident_{suffix}recruit", node=node)
        return _value()

    def probabilities(self, node: dict) -> dict:
        if node["id"] not in self.probability_cache:
            self.probability_cache[node["id"]] = self._probabilities(node)
        return self.probability_cache[node["id"]]

    @staticmethod
    def _weighted_value(rows, part, **details):
        value = _value({part: sum(row["probability"] * row["score"]["points"] for row in rows)},
            cash=sum(row["probability"] * row["score"]["expectedCashDelta"] for row in rows),
            appraisal=sum(row["probability"] * row["score"]["expectedAppraisalDelta"] for row in rows),
            missing=sorted({term for row in rows if row["probability"] for term in row["score"]["missingTerms"]}),
            modelLimitations=sorted({term for row in rows if row["probability"] for term in row["score"].get("modelLimitations", [])}), **details)
        loss = sum(row["probability"] * row["score"].get("referenceLoss", {}).get("points", 0) for row in rows)
        if loss:
            included = sum(row["probability"] * row["score"].get("referenceLoss", {}).get("includedPoints",
                row["score"].get("referenceLoss", {}).get("points", 0)
                if row["score"].get("referenceLoss", {}).get("includedInPlanningScore") else 0) for row in rows)
            value["referenceLoss"] = {"points": loss, "includedPoints": included,
                                      "includedInPlanningScore": abs(loss - included) < 1e-9,
                                      "basis": "weighted_ending_outcomes"}
        return value

    def _probabilities(self, node: dict) -> dict:
        explicit = node.get("categoryProbabilities")
        if explicit is not None:
            weights = {key: _finite(value, "categoryProbability", nonnegative=True) for key, value in explicit.items()}
            basis = "manual_relative_weights"
        elif "treehole" in self.area:
            if node.get("categoryId") == "unknown_ferocity":
                weights = {"node_type_001": 2, "node_type_002": 1}
            else:
                from .node_predictor import TYPE_TO_CATEGORY
                # Use supplied rule candidates; do not invent eligibility from no evidence.
                candidates = self.options.get("treeholeMysteryCandidates", [])
                weights = {TYPE_TO_CATEGORY.get(key, key): 1 for key in candidates}
            basis = "temporary_treehole_rules"
        else:
            predicted = self.prediction.get("unknownNodes", {}).get(node["id"], {})
            candidates = predicted.get("candidates", [])
            weights = predicted.get("ordinaryProbabilities", {
                row["categoryId"]: row.get("distanceFrequency") or 0 for row in candidates})
            basis = predicted.get("probabilityBasis", "normalized_lubiao_distance_frequency_not_calibrated_posterior")
        total = sum(weights.values())
        for key, value in weights.items():
            _finite(value, f"type weight for {key}", nonnegative=True)
        if any(key not in {f"node_type_{i:03}" for i in range(1, 22)} for key in weights):
            raise ValueError("unknown/nonvisual category in scoring probability weights")
        ordinary = {key: value / total if total else 0 for key, value in weights.items()}
        occupancy = self.prediction.get("unknownNodes", {}).get(node["id"], {}).get("endingOccupancy", [])
        occupied = sum(row["probability"] for row in occupancy)
        valid = occupied <= 1 + 1e-9
        special = occupancy if valid else []
        occupied = min(1, occupied) if valid else 0
        probabilities = dict(ordinary)
        encounter_probability = probabilities.get("node_type_006", 0)
        marked_events = {row["eventId"]: row["probability"] / encounter_probability for row in special
                        if row.get("eventId") and encounter_probability > 0}
        return {"basis": basis, "probabilities": probabilities, "rawWeights": weights,
                "ordinaryProbabilities": ordinary, "endingOccupancy": special,
                "conditionalEndingPlacements": self.prediction.get("unknownNodes", {}).get(node["id"], {}).get("conditionalEndingPlacements", []),
                "markedEventProbabilities": marked_events,
                "missingTerms": (["结局前置超过未知位置容量，请修正地图或进度"] if not valid else []) +
                    (["no nonzero category evidence; no invented posterior"] if not total and occupied < 1 else [])}

    def _node_reward(self, node: dict) -> dict:
        marks = node.get("confirmedMarkIds", [])
        if "node_mark_001" in marks:
            value = self.category("node_type_021", node)
        elif "node_mark_004" in marks:
            value = self.battle("specialNormal", stage="无效验尸", components=("node_battle_boss_scrap",),
                relic_count=1, relic_context="node_battle_normal_invalid_autopsy", ticket_context="node_battle_boss_recruit", node=node)
            value["goalId"] = "ending3_autopsy"
            value["goalFeasible"] = True
        elif node.get("categoryId") in UNKNOWN:
            probabilities = self.probabilities(node)
            rows = []
            for key, probability in probabilities["probabilities"].items():
                if probability <= 0:
                    continue
                spec = next((row for row in probabilities["endingOccupancy"] + probabilities["conditionalEndingPlacements"]
                             if row["categoryId"] == key and not row.get("eventId")), None)
                ordinary_value = self.category(key, node)
                if spec:
                    conditional = min(1, spec["probability"] / probability)
                    marked_node = {**node, "categoryId": key, "confirmedMarkIds": [spec["markId"]]}
                    special_value = self._node_reward(marked_node)
                    branches = [{"name": "结局前置", "probability": conditional, "score": special_value},
                                {"name": "普通节点", "probability": 1 - conditional, "score": ordinary_value}]
                    ordinary_value = self._weighted_value(branches, "endingPlacementExpectation", branches=branches)
                rows.append({"categoryId": key, "probability": probability, "score": ordinary_value})
            value = self._weighted_value(rows, "typeExpectation", classification=probabilities, types=rows)
            value["missingTerms"] += probabilities["missingTerms"]
        else:
            marked = "encounter_023" if "node_mark_005" in marks else "encounter_022" if "node_mark_002" in marks else None
            value = self.category(node.get("categoryId"), {**node, **({"encounterId": marked} if marked else {})})
            conditional = self.prediction.get("endingCategoryMarks", {}).get(node["id"], [])
            if conditional and "node_mark_006" not in marks:
                spec = conditional[0]
                marked_value = self._node_reward({**node, "confirmedMarkIds": [spec["markId"]]})
                probability = spec["probability"]
                branches = [
                    {"name": "结局前置", "probability": probability, "score": marked_value},
                    {"name": "普通节点", "probability": 1 - probability, "score": value},
                ]
                value = marked_value if probability >= 1 - 1e-9 else self._weighted_value(
                    branches, "conditionalMarkExpectation", branches=branches)
            if node.get("categoryId") is None and node["id"] not in self.completed:
                value["missingTerms"].append(message("unclassified node; confirm its category before interpreting its utility"))
        return value

    def _node(self, node: dict) -> dict:
        value = self._node_reward(node)
        marks = node.get("confirmedMarkIds", [])
        if "node_mark_007" in marks:
            reward = self.fruit_reward()
            value = {**value, "points": value["points"] + reward["points"],
                     "parts": {**value["parts"], **reward["parts"]}, "fruitReward": reward,
                     "missingTerms": value["missingTerms"] + reward["missingTerms"]}
        cash = self.utopia_cash(node.get("categoryId")) if self.utopia == "utopia_007" else 0
        if cash:
            value = {**value, "points": value["points"] + CASH_POINTS * cash,
                     "parts": {**value["parts"], "utopiaCash": CASH_POINTS * cash},
                     "expectedCashDelta": value["expectedCashDelta"] + cash}
        value["nodeId"] = node["id"]
        return value

    def shop(self, category: str, cash: float, appraisal: float, *, done: set[str], repeated: bool,
             box_count: int | None = None, node_id: str | None = None,
             viewed_shelves: int | None = None, investment_balance: float | None = None) -> dict:
        viewed = (self.merchant_shelves.get(node_id, int(repeated)) if viewed_shelves is None else viewed_shelves)
        fraction = shelf_fraction(viewed)
        balance = self.investment_balance if investment_balance is None else investment_balance
        withdrawal = withdrawal_quote(balance) if category == "node_type_004" else withdrawal_quote(balance, 0)
        yellow_done = any(row.get("categoryId") == "node_type_013" and key in done for key, row in self.nodes.items())
        yellow_possible = any(row.get("categoryId") == "node_type_013" for row in self.nodes.values()) or any(
            "node_type_013" in self.probabilities(row)["probabilities"] for row in self.nodes.values() if row.get("categoryId") in UNKNOWN)
        unresolved_evidence = any(row.get("categoryId") in UNKNOWN and self.probabilities(row)["missingTerms"]
                                  for row in self.nodes.values())
        availability = self.options.get("yellowShopAvailable", False if self.floor == 6
                                        or not yellow_possible and not unresolved_evidence else None)
        result = merchant_reference_score(category_id=category, floor=self.floor,
             cash=max(0, cash) + withdrawal["cash"], estimated_value=max(0, appraisal),
             box_capacity=self.capacity, box_count=len(self.components) if box_count is None else box_count,
             yellow_visited=yellow_done,
             yellow_shop_available=availability,
             eligible_event_ids=[row["eventId"] for row in self.event_distribution["events"]],
             below_threshold=self.below, squad_id=self.squad, first_visit=viewed == 0 and not repeated,
             repeat_factor=fraction,
             reserve_entries=self.options.get("merchantReserveEntries"), reserve_override=self.options.get("merchantReserve"))
        if category == "node_type_004" and result["qualified"] and viewed == 0 and not repeated:
            professions = ("先锋", "近卫", "重装", "狙击", "术师", "医疗", "辅助", "特种")
            random_ticket = sum(self.ticket(f"{profession}招募券") for profession in professions) / 8
            home = DUAL_SQUADS.get(self.squad)
            second = sum(self.ticket(f"{profession}招募券") for profession in home[:2]) / 2 if home else random_ticket
            result["rawPoints"] += random_ticket + second - result["randomTicket"] - result["secondTicket"]
            result["parts"]["tickets"] = (random_ticket + second) * result["repeatFactor"]
            result["points"] = sum(result["parts"].values())
            result["randomTicket"], result["secondTicket"] = random_ticket, second
        stock_adjusted_points = result["points"]
        withdrawal_points = withdrawal["cash"] * self.withdrawal_cash_points
        result["parts"]["withdrawalCash"] = withdrawal_points
        result["points"] += withdrawal_points
        result.update(stockAdjustedPoints=stock_adjusted_points, withdrawalPoints=withdrawal_points,
                      viewedShelves=viewed, remainingShelfFraction=fraction, withdrawal=withdrawal,
                      investmentBalanceBefore=balance, cashBeforeWithdrawal=max(0, cash))
        return result

    def step(self, entered: list[str], fresh: set[str], revealed: list[str], *, before_done: set[str],
             prefix_cash: float, appraisal: float, path_steps: int, processing: bool,
             box_count: int | None = None, investment_balance: float | None = None,
             merchant_shelves: Mapping[str, int] | None = None) -> dict:
        rows = []
        cash_delta = appraisal_delta = 0.0
        balance = self.investment_balance if investment_balance is None else investment_balance
        shelves = dict(self.merchant_shelves if merchant_shelves is None else merchant_shelves)
        cash_after, appraisal_after, proxy_after = prefix_cash, appraisal, path_steps
        retained_appraisal_fraction = 1.0
        policy_done = set(before_done)
        for key in entered:
            node = self.nodes[key]
            category = node.get("categoryId")
            effect = self.policy_effect(key, cash_after + proxy_after * self.step_ingot, policy_done)
            if effect:
                if effect["cashLost"]:
                    cash_after = max(0, cash_after + proxy_after * self.step_ingot - effect["cashLost"])
                    proxy_after = 0.0
                appraisal_after += effect["appraisalIncrease"]
            if category in {"node_type_004", "node_type_013"} and "node_mark_001" not in node.get("confirmedMarkIds", []):
                shop = self.shop(category, cash_after + proxy_after * self.step_ingot, appraisal_after,
                                 done=before_done, repeated=key not in fresh, box_count=box_count,
                                 node_id=key, viewed_shelves=shelves[key], investment_balance=balance)
                value = _value(shop["parts"], merchant=shop)
                if key in fresh:
                    extras = {name: points for name, points in self.base_values[key]["parts"].items()
                              if name in {"utopiaCash", "fruitMarkNatural"}}
                    value["parts"].update(extras)
                    value["points"] = sum(value["parts"].values())
                    value["expectedCashDelta"] = self.utopia_cash(category) if self.utopia == "utopia_007" else 0
                original = value["points"]
                value["parts"]["strategyAdjustment"] = self.overrides.get(key, original * self.weights.get(key, 1)) - original
                value["points"] = sum(value["parts"].values())
            elif key in fresh:
                value = {**self.base_values[key], "parts": dict(self.base_values[key]["parts"])}
                if value.get("eventId") == "encounter_023":
                    # A later tribute spends predicted cash, not the opening snapshot again.
                    tribute = self.cash_tribute(max(0, cash_after + proxy_after * self.step_ingot))
                    delta = tribute["parts"].get("cashCost", 0) - value["parts"].get("cashCost", 0)
                    value["parts"]["tributePrefixAdjustment"] = delta * self.weights.get(key, 1) if key not in self.overrides else 0
                    value["points"] += value["parts"]["tributePrefixAdjustment"]
                    value.update({name: tribute[name] for name in ("referenceLoss", "expectedCashDelta")})
                    proxy_after = 0.0
                    value["referenceLoss"]["basis"] = "predicted_cash_at_arrival"
                if category in UNKNOWN:
                    merchant_delta = 0.0
                    dynamic_types = []
                    for row in value.get("types", []):
                        if row["categoryId"] in {"node_type_004", "node_type_013"}:
                            shop = self.shop(row["categoryId"], cash_after + proxy_after * self.step_ingot, appraisal_after,
                                             done=before_done, repeated=False, box_count=box_count,
                                             node_id=key, viewed_shelves=shelves[key], investment_balance=balance)
                            merchant_delta += row["probability"] * (shop["points"] - row["score"]["points"])
                            dynamic_types.append({"categoryId": row["categoryId"], "probability": row["probability"], "merchant": shop})
                    value["parts"]["merchantPrefixAdjustment"] = (merchant_delta * self.weights.get(key, 1)
                                                                    if key not in self.overrides else 0)
                    value["points"] += value["parts"]["merchantPrefixAdjustment"]
                    value["merchantTypes"] = dynamic_types
                if category == "node_type_010":
                    value = _value()  # Entry utility belongs only to the actual treehole branch.
                bonus = painted_component_relic_bonus(category, painted_agor=self.counts["component_030"],
                    painted_perro=self.counts["component_029"], arrives_by_processing=processing)
                value["parts"]["paintedBonus"] = bonus["points"]
                value["points"] += bonus["points"]
            else:
                value = _value()
            shop_types = ([{"categoryId": category, "probability": 1.0, "merchant": value["merchant"]}]
                          if "merchant" in value else value.get("merchantTypes", []))
            shop_probability = min(1.0, sum(row["probability"] for row in shop_types))
            balance_cost = sum(row["probability"] * row["merchant"]["withdrawal"]["investmentCost"] for row in shop_types)
            if shop_probability:
                shelves[key] = min(5, shelves[key] + 1)
            # Unknown shops settle proportionally under the existing mean-state approximation.
            cash_after = max(0, cash_after * (1 - shop_probability) + value["expectedCashDelta"])
            appraisal_after = max(0, appraisal_after * (1 - shop_probability) + value["expectedAppraisalDelta"])
            proxy_after *= 1 - shop_probability
            retained_appraisal_fraction *= 1 - shop_probability
            balance = max(0, balance - balance_cost)
            policy_done.add(key)
            value = self.with_policy({**value, "nodeId": key}, effect)
            rows.append({"nodeId": key, "points": value["points"], "parts": value["parts"],
                         "missingTerms": value["missingTerms"],
                         "expectedCashDelta": value["expectedCashDelta"],
                         "expectedAppraisalDelta": value["expectedAppraisalDelta"],
                         **({"merchant": value["merchant"]} if "merchant" in value else {}),
                         **({"merchantTypes": value["merchantTypes"]} if value.get("merchantTypes") else {}),
                         **{name: value[name] for name in ("goalId", "plannedOption", "goalFeasible", "fateRole", "fakeFateProbability", "referenceLoss", "scoringBasis", "policyAdjustment", "modelLimitations", "extraComponentContextIds", "fruitReward", "legalOptions", "cashReference", "battleOutcomes") if name in value},
                         "frozenBreakdownNodeId": key if key in fresh else None})
            cash_delta += value["expectedCashDelta"]
            appraisal_delta += value["expectedAppraisalDelta"]
        info = []
        for key in revealed:
            if self.nodes[key].get("categoryId") in UNKNOWN:
                opportunity = max(0, self.preview_value(key, done=policy_done,
                    cash=cash_after + proxy_after * self.step_ingot)["points"])
                info.append({"nodeId": key, "opportunityPoints": opportunity,
                             "points": self.reveal_coefficient * opportunity})
        recruitment = sum(row["parts"].get("heldRecruitmentTickets", 0) for row in rows)
        return {"nodeValue": sum(row["points"] for row in rows) - recruitment, "revealValue": sum(row["points"] for row in info),
                "recruitmentValue": recruitment, "nodeTerms": rows, "revealTerms": info,
                "referenceLossPoints": sum(row.get("referenceLoss", {}).get("points", 0) for row in rows),
                "expectedCashDelta": cash_delta, "expectedAppraisalDelta": appraisal_delta,
                "merchantTransition": {"cashAfter": cash_after, "appraisalAfter": appraisal_after,
                    "movementProxyStepsAfter": proxy_after, "investmentBalanceAfter": balance,
                    "viewedShelvesAfter": shelves, "retainedAppraisalFraction": retained_appraisal_fraction},
                "dystopiaTransition": {"policyActiveBefore": self.policy_active(before_done),
                    "policyActiveAfter": self.policy_active(policy_done),
                    "idealSourceNodeId": self.dystopia.get("idealSourceNodeId")}}

    def terminal(self, node_id: str, remaining_ap: int, *, pursuit: bool, treehole: bool = False,
                 done: set[str] | None = None) -> dict:
        if treehole:
            return _value({"treeholeActionProxy": self.action_value(PROFILE["exits"]["treeholeEntryAPProxy"])})
        category = self.nodes[node_id].get("categoryId")
        if pursuit:
            if "treehole" in self.area:
                return _value()
            if self.floor in (3, 5):
                return self.battle("boss", components=("node_battle_boss_scrap",), relic_count=1,
                                   relic_context="pool_boss", ticket_context="node_battle_boss_recruit")
            if self.floor in (1, 2, 4) and "treehole" not in self.area:
                return _value({"pursuitTicket": self.pool("node_battle_recruit")})
            return _value({"finalBattle": PROFILE["exits"]["finalBattlePoints"]})
        if category == "node_type_015":
            needed = min(remaining_ap, self.hope_deficit) if self.below else 0
            hope_points = (remaining_ap * self.exit_hope_floor
                           + needed * max(0, RESOURCE_POINTS["completeSixStarPoints"] / self.reference_cost - self.exit_hope_floor))
            return _value({"exitProcessing": self.pool("node_final_scrap"), "remainingHope": hope_points},
                          convertedHope=remaining_ap, exitHopePointFloor=self.exit_hope_floor)
        if category == "node_type_016":
            core = {"node_type_004", "node_type_006", "node_type_008", "node_type_009", "node_type_010", "node_type_011", "node_type_013"}
            done = self.completed if done is None else done
            count = sum(key not in done and (row.get("categoryId") in core or any(
                candidate in core for candidate, probability in self.probabilities(row)["probabilities"].items() if probability))
                for key, row in self.nodes.items())
            factor = max(0, 1 - PROFILE["exits"]["pathCarryDeficitPenalty"] * max(0, count - remaining_ap))
            return _value({"exitProcessing": self.pool("node_evacuate_scrap"), "nextLayerAP": RESOURCE_POINTS["carryAPPoints"] * remaining_ap * factor},
                          carryFactor=factor, remainingCoreNodeCount=count)
        return _value()

    def report(self) -> dict:
        missing = {key: value["missingTerms"] for key, value in self.values.items() if value["missingTerms"]}
        return localize_result({"mode": "snapshot_expected_utility", "scoreUnit": f"普通藏品={RESOURCE_POINTS['relicPoints']}分，源石锭={CASH_POINTS}分；其他藏品按池配置",
                "profile": {"name": PROFILE["name"], "path": str(PROFILE_PATH.relative_to(ROOT)), "reload": "application_restart"},
                "nodeValues": self.values, "threshold": self.threshold, "eventDistribution": self.event_distribution,
                "actionOpportunity": {"queue": sorted(self.action_queue, reverse=True), "onePoint": self.action_value(1)},
                "revealCoefficient": self.reveal_coefficient, "exitHopePointFloor": self.exit_hope_floor,
                "withdrawalCashPointValue": self.withdrawal_cash_points,
                "goalOptionScoring": True, "prerequisitePriorityRanking": bool(self.options.get("planningGoalIds")),
                "planningGoalIds": self.options.get("planningGoalIds", []),
                "tributeLossIncludedInPlanningScore": any(value.get("referenceLoss", {}).get("includedInPlanningScore")
                    or value.get("referenceLoss", {}).get("includedPoints", 0) for value in self.values.values()),
                "dystopiaPolicyScoring": {"supportedPolicies": ["dystopia_011", "dystopia_014"],
                    "active": self.policy_active(self.completed), "cashUnitPoints": CASH_POINTS,
                    "naturalCount": self.natural_count_initial,
                    "naturalInventoryAssumption": "confirmed inventory minus planned known tributes; unknown acquired items not simulated"},
                "missingTermsByNode": missing,
                "coverage": "partial" if missing else "complete_for_configured_approximation",
                "warnings": sorted(self.warnings), "mutatesPlaytime": False,
                "assumptions": ["ordinary reward conditions and type/event probabilities frozen at latest snapshot",
                    "merchant score uses mean prefix cash, not the full nonlinear outcome distribution",
                    "prefix movement adds 1 expected ingot for forecast economy, including policy cash costs",
                    "shops spend/reset predicted cash and appraisal; shelf stock and investment persist in search labels",
                    "unknown shop outcomes use probability-weighted economy resets, not a full conditional state tree",
                    "expected action/item rewards do not change executable movement budget/inventory",
                    "selected tribute goals use reference-only loss; unselected mandatory cash tribute deducts utility; payments reduce predicted shop economy",
                    "covered arrivals settle policy before node rewards; the ideal source disables policy after its own arrival",
                    "benefit uses confirmed natural inventory minus known planned tributes, not unknown future item acquisitions",
                    "reward-pool candidate selection uses weighted sampling without replacement; joint pair frequencies unavailable"]})
