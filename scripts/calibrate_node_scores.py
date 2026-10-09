"""Write a separate score probe; never regenerate the manually maintained handbook."""

from __future__ import annotations

import argparse
from functools import lru_cache
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.battle_rewards import BattleRewardCatalog
from fulcrum.node_rewards import NodeRewardPoolCatalog
from fulcrum.relic_scoring import CONFIG_PATH as RELIC_CONFIG_PATH, RelicScorer
from fulcrum.scoring_calibration import (
    EXCHANGE_OPPORTUNITY_POINTS, action_opportunity_score, component_reference_points,
    dispatch_reference_score, expected_best_score,
    emergency_aid_score, experience_reward_score, merchant_prefix_score, merchant_reference_score,
    painted_component_relic_bonus, safe_corner_score,
    team_threshold, ticket_reference_points,
)

ROMAN = ("I", "II", "III", "IV", "V", "VI")


def pool_probe(catalog: NodeRewardPoolCatalog, context_id: str, *, below: bool = False,
               relic_scorer: RelicScorer | None = None) -> dict:
    pool = catalog.get(context_id)
    scorer = relic_scorer if relic_scorer is not None else RelicScorer(catalog=catalog)
    observed = [row for row in pool["members"] if row["occurrenceCount"] is not None]
    total = sum(row["occurrenceCount"] for row in observed)
    if pool["members"] and all(row["dataType"] == "藏品" for row in pool["members"]):
        points = scorer.pool_score(context_id)
        return {"contextId": context_id, "recordCount": total, "mean": points, "expectedBest": points,
                "lowerBound": points, "upperBound": points,
                "unobservedMembers": [row["name"] for row in pool["members"] if row["occurrenceCount"] is None],
                "scope": pool.get("statistics", {}).get("scopeLabel"),
                "observationSource": pool.get("statistics", {}).get("observationSource"),
                "assumption": "configured_per_received_relic_points"}
    if not total:
        raise ValueError(f"Missing frequencies for {context_id}; no automatic uniform fallback")
    outcomes = []
    for row in observed:
        if row["dataType"] == "零件":
            points = component_reference_points(row["itemId"])
        elif row["dataType"] == "招募券":
            points = ticket_reference_points(row["name"], below_threshold=below)
        elif row["dataType"] == "藏品":
            points = scorer.fixed_score(row["itemId"])
        else:
            raise ValueError(f"Unpriced reward: {row['name']}")
        outcomes.append((points, row["occurrenceCount"] / total))
    selection = pool.get("selection") or {}
    candidates = selection.get("candidateCount", 1)
    if selection.get("takeCount", 1) != 1:
        raise ValueError("This probe only supports taking one candidate")
    result = expected_best_score(outcomes, candidate_count=candidates)
    return {"contextId": context_id, "recordCount": total, **result,
            "unobservedMembers": [row["name"] for row in pool["members"] if row["occurrenceCount"] is None],
            "scope": pool.get("statistics", {}).get("scopeLabel"),
            "observationSource": pool.get("statistics", {}).get("observationSource"),
            "assumption": "weighted_without_replacement" if candidates > 1 else "empirical_single_draw"}


def encounter_probe(
    pools: NodeRewardPoolCatalog, battles: BattleRewardCatalog, *, below: bool,
    level: int, experience: int, hope_deficit: float, cash: float, life: int,
    action_value, aid_exists: bool = False, controller_ever_obtained: bool = False,
    aid_completed: bool = False, corn_count: int = 0,
    completed_events: tuple[str, ...] = (),
    relic_scorer: RelicScorer | None = None,
) -> dict:
    """III-layer calibration from the saved selector weights, with explicit missing terms."""
    source_path = ROOT / "work" / "lubiao_encounter_selector" / "report.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    definitions = json.loads((ROOT / "data" / "blackstream_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
    by_name = {row["name"]: row for row in definitions}
    scorer = relic_scorer if relic_scorer is not None else RelicScorer(catalog=pools)
    scene_to_event = {}
    for response in source["json_responses"]:
        for floor in response.get("floor_encounters", []):
            for event in floor["events"]:
                if event["classification"] != "不期而遇":
                    continue
                for scene in event["sceneIds"]:
                    if scene.endswith("_enter") and event["name"] in by_name:
                        scene_to_event[scene.removesuffix("_enter")] = by_name[event["name"]]

    def hope_value(amount: float, deficit: float = hope_deficit) -> float:
        return min(amount, deficit) * 50 if below else 0

    def pool_value(context: str) -> float:
        return pool_probe(pools, context, relic_scorer=scorer)["expectedBest"]

    def companion(stage: str, *, emergency: bool = False, relics: float = 0,
                  relic_context: str | None = None, fixed_relic: str | None = None) -> float:
        reward = battles.resolve(area_key="III", mode="specialEmergency" if emergency else "specialNormal", stage_name=stage)
        xp = experience_reward_score(level=level, experience=experience, reward=reward["experienceAward"],
                                     below_threshold=below, hope_deficit=hope_deficit)["points"]
        cash_reward = reward["originiumIngot"]
        if cash_reward["kind"] != "fixed":
            raise ValueError("Companion cash distribution needs explicit probabilities")
        # A single recruitment ticket is a calibration proxy; unbound component pools stay missing.
        relic_points = scorer.pool_score(relic_context) if relic_context else scorer.fixed_score(fixed_relic) if fixed_relic else scorer.default_points
        return xp + cash_reward["value"] * 8 + ticket_reference_points("先锋招募券", below_threshold=below) + relics * relic_points

    natural = pool_value("node_incident_praised_shadow_random_natural")
    processing = pool_value("node_incident_praised_shadow_random_processing")

    @lru_cache(maxsize=None)
    def shadow(round_index: int, hp: int, deficit: float) -> float:
        if round_index > 8:
            return 0.0
        cost = (1, 1, 2, 2, 2, 3, 3, 3)[round_index - 1]
        if hp <= cost:
            return 0.0
        hp -= cost
        rewards = {
            1: [(0, 1, 0), (32, 0, 0)],
            2: [(0, 1, 0), (0, 0, 2)],
            3: [(0, 2, 0), (natural, 0, 0)],
            4: [(0, 2, 0), (processing, 0, 0), (96, 0, 0)],
            5: [(0, 5, 0), (scorer.pool_score("node_incident_praised_shadow_random_collectible"), 0, 0)],
            6: [(0, 3, 0), (0, 0, 8), (0, 0, 0)],
            7: [(3 * scorer.pool_score("node_incident_praised_shadow_random_collectible"), 0, 0)],
            8: [(scorer.fixed_score("relic_215"), 0, 0)],
        }[round_index]
        return sum(points + hope_value(hope, deficit)
                   + shadow(round_index + 1, min(life, hp + heal), max(0, deficit - hope))
                   for points, heal, hope in rewards) / len(rewards)

    next_battle = battles.resolve(area_key="IV", mode="normal")
    next_xp = experience_reward_score(level=level, experience=experience, reward=next_battle["experienceAward"],
                                     below_threshold=below, hope_deficit=hope_deficit)["points"]
    next_score = next_xp + next_battle["originiumIngot"]["value"] * 8 + ticket_reference_points("先锋招募券", below_threshold=below)
    mouth = max(pool_value(f"node_incident_goods_from_mouth_{kind}") for kind in ("natural", "concept", "processing"))
    lake_components = pool_value("node_battle_elite_scrap")
    values = {
        "encounter_003": (mouth - 32 if cash >= 4 else 0, [], "货从口出：选当前最高合法零件期望，扣4钱"),
        "encounter_004": (action_value(5), [], "沉重的契约：默认+5，失血不评分但保留实际条件"),
        "encounter_005": (3 * scorer.pool_score("node_incident_knock_lever") - 80 if cash >= 10
                          else scorer.pool_score("node_incident_knock_lever") - 32 if cash >= 4 else 0,
                          [], "敲动杠杆：3藏−10钱 / 1藏−4钱"),
        "encounter_006": (100, [], "血衣之下：1藏"),
        "encounter_007": (100, [], "擒与缚：1藏，指定藏品覆盖后置"),
        "encounter_008": (250 if life >= 3 else 186 if cash >= 8 else 0, [], "沉寂之屋：合法且分最高的笼控器获取方式"),
        "encounter_009": (companion("“闹乐”", relics=1, fixed_relic="relic_209"), [], "黑诞：默认战斗，固定猎印单独估值"),
        "encounter_010": (None, [{"coefficient": 1, "label": "下一层希望沃土净机会分及物品支出"}], "红苔须取得过笼控器；下一层收益未量化"),
        "encounter_011": (shadow(1, life, hope_deficit), [], "影子：按真实各回血分支递推，携带位本阶段0分"),
        "encounter_014": (companion("安保措施", relics=3, relic_context=scorer.event_pool("encounter_014")), [], "划算买卖：隐藏池3藏＋伴生战斗"),
        "encounter_015": (companion("开业剪彩", emergency=True, relics=3, relic_context=scorer.event_pool("encounter_015")), [], "鸭托邦：临时现金门槛0，紧急隐藏池3藏，不叠通用紧急藏"),
        "encounter_017": (
            0.8 * (companion("湖中魇", emergency=True, relics=1, relic_context="node_incident_lake_fairy_emergency") + lake_components)
            + 0.2 * scorer.pool_score("node_incident_lake_fairy_direct") - 24 if cash >= 3
            else companion("湖中魇", relics=5 / 11, relic_context="node_incident_lake_fairy") + lake_components,
            [], "湖中仙女：付3现金后80%紧急/20%直接藏品；零件暂用一般紧急作战二选一池",
        ),
        "encounter_018": (20 + 0.5 * scorer.pool_score("node_incident_cave_treasure") + 0.5 * next_score, [], "洞中宝：四结果均分至终止，期望2.5钱＋0.5藏＋0.5下一层普通战"),
        "encounter_019": (2 * ticket_reference_points("先锋招募券", below_threshold=below), [], "临时中介所：随机临时六星暂按普通单券2倍，非精英直升券"),
        "encounter_021": (scorer.fixed_score("relic_207") + (emergency_aid_score(corn_count)["points"] if aid_exists and not aid_completed else 0),
                          [], "独活：先1藏；未完成助力按3名免费干员×每玉米4估价，已完成不重领"),
    }
    for event_id, blocked in (("encounter_003", cash < 4), ("encounter_005", cash < 4),
                              ("encounter_008", life < 3 and cash < 8)):
        if blocked:
            points, _, note = values[event_id]
            values[event_id] = (points, [{"coefficient": 1, "label": "空过事件附加负分"}], note)
    weights, excluded = [], []
    for raw in source["encounter_weight_rows"]:
        if raw["floor"] != 3 or raw["treehole"]:
            continue
        event = scene_to_event[raw["id"]]
        reason = None
        if event["id"] in completed_events and event["repeatability"] in {"once_per_run", "until_entered", "inside_and_outside_once"}:
            reason = "已在主层经历"
        elif event["id"] == "encounter_010" and not controller_ever_obtained:
            reason = "未取得过笼控器"
        elif event["id"] == "encounter_021" and not aid_exists:
            reason = "本层无应急助力"
        if reason:
            excluded.append({"id": event["id"], "name": event["name"], "reason": reason})
        else:
            weights.append({"id": event["id"], "name": event["name"], "weight": raw["weight"]})
    total_weight = sum(row["weight"] for row in weights)
    if not total_weight:
        return {"events": [], "knownContribution": 0, "points": None, "missingTerms": [],
                "excluded": excluded, "sourceCheckedAt": source["checked_at"], "emptyPool": True}
    rows, missing, known = [], [], 0.0
    for event in weights:
        points, terms, note = values[event["id"]]
        probability = event["weight"] / total_weight
        contribution = probability * (points or 0)
        known += contribution
        for term in terms:
            missing.append({"eventId": event["id"], "probabilityCoefficient": probability * term["coefficient"],
                            "label": term["label"]})
        rows.append({**event, "probability": probability, "knownPoints": points,
                     "contribution": contribution, "missingTerms": terms, "notes": note})
    return {"events": rows, "knownContribution": known, "points": known if not missing else None,
            "missingTerms": missing, "excluded": excluded, "sourceCheckedAt": source["checked_at"], "emptyPool": False}


def build_report(
    *, level: int = 4, experience: int = 0, hope_deficit: float = 20,
    painted_agor: int = 0, painted_perro: int = 0, arrives_by_processing: bool = True,
    processed_count: int = 1, cash: float = 50, life: int = 12,
    opportunity_scores: list[float] | None = None, action_points: int = 6, pursuit: bool = False,
    completed_events: tuple[str, ...] = (),
    relic_scores_path: Path = RELIC_CONFIG_PATH,
    corn_count: int = 0, has_elite1_six_star: bool = False, estimated_value: float = 0,
) -> dict:
    pools, battles = NodeRewardPoolCatalog(), BattleRewardCatalog()
    relic_scorer = RelicScorer(relic_scores_path, catalog=pools)
    contexts = (
        "node_battle_elite_scrap", "node_battle_boss_scrap", "node_final_scrap",
        "node_evacuate_scrap", "pool_scrap_3", "node_duel_left", "node_duel_center",
        "node_battle_savage_scrap_left", "node_battle_savage_scrap_right",
        "node_wandering_resident_scrap", "node_wandering_resident_convergence_scrap",
        "node_battle_recruit", "node_battle_boss_recruit", "node_battle_savage_recruit",
        "node_wandering_resident_recruit", "node_wandering_resident_convergence_recruit",
    )
    probes = {key: pool_probe(pools, key, relic_scorer=relic_scorer) for key in contexts}

    def action_value(gain: int) -> float:
        return 200 * gain if opportunity_scores is None else action_opportunity_score(
            opportunity_scores, action_points=action_points, gain=gain, pursuit=pursuit)["points"]

    for count in (painted_agor, painted_perro, processed_count, life):
        if type(count) is not int or count < 0:
            raise ValueError("Inventory quantities and life must be nonnegative integers")
    if life == 0:
        raise ValueError("A live run needs positive life")
    if type(arrives_by_processing) is not bool:
        raise ValueError("Arrival mode must be boolean")
    action_opportunity_score(opportunity_scores or [], action_points=action_points, gain=0, pursuit=pursuit)
    aid_score = emergency_aid_score(corn_count)
    safe_corner = {
        key: safe_corner_score(two_action_points_value=action_value(2),
                               hope_points=min(3, hope_deficit) * 50 if below else 0,
                               has_elite1_six_star=has_elite1_six_star)
        for key, below in (("met", False), ("unmet", True))
    }

    def value(context_id: str, below: bool = False) -> float:
        return pool_probe(pools, context_id, below=below, relic_scorer=relic_scorer)["expectedBest"] if below else probes[context_id]["expectedBest"]

    def xp_points(xp: int, below: bool) -> float:
        return experience_reward_score(level=level, experience=experience, reward=xp,
                                       below_threshold=below, hope_deficit=hope_deficit)["points"]

    def battle_total(reward: dict, below: bool, ticket: str, components: tuple[str, ...], relics: int,
                     relic_context: str | None = None) -> dict:
        cash = reward["originiumIngot"]
        if cash["kind"] != "fixed":
            raise ValueError("Variable cash requires explicit outcome probabilities")
        parts = {"experience": xp_points(reward["experienceAward"], below),
                 "cash": cash["value"] * 8, "tickets": value(ticket, below),
                 "components": sum(value(key) for key in components),
                 "relics": relics * relic_scorer.pool_score(relic_context) if relics else 0}
        return {"parts": parts, "total": sum(parts.values()), "experienceAward": reward["experienceAward"],
                "relicContextId": relic_context}

    combat_rows = []
    for floor, area in enumerate(ROMAN, 1):
        for mode, name, ticket, components, relics, relic_context in (
            ("normal", "作战", "node_battle_recruit", (), 0, None),
            ("emergency", "紧急作战", "node_battle_recruit", ("node_battle_elite_scrap",), 1, "node_battle_elite"),
            ("boss", "险路恶敌", "node_battle_boss_recruit", ("node_battle_boss_scrap",), 1, "pool_boss"),
        ):
            if mode == "boss" and floor not in (3, 5):
                continue
            reward = battles.resolve(area_key=area, mode=mode)
            met = battle_total(reward, False, ticket, components, relics, relic_context)
            unmet = battle_total(reward, True, ticket, components, relics, relic_context) if floor > 1 else None
            combat_rows.append({"floor": floor, "name": name, "met": met, "unmet": unmet})

    special_rows = []
    for stage, ticket, component_groups, relic_context in (
        ("枯枝", "node_battle_savage_recruit", ("node_battle_savage_scrap_left", "node_battle_savage_scrap_right"), "node_battle_savage"),
        ("败叶", "node_battle_savage_recruit", ("node_battle_savage_scrap_left", "node_battle_savage_scrap_right"), "node_battle_savage"),
        ("强买强卖", "node_wandering_resident_recruit", ("node_wandering_resident_scrap",), "node_wandering_resident_relic"),
        ("进退趋同", "node_wandering_resident_convergence_recruit", ("node_wandering_resident_convergence_scrap",), "node_wandering_resident_convergence_relic"),
        ("无效验尸", "node_battle_boss_recruit", ("node_battle_boss_scrap",), "node_battle_normal_invalid_autopsy"),
    ):
        reward = battles.resolve(area_key="III", mode="specialNormal", stage_name=stage)
        special_rows.append({"name": stage, "met": battle_total(reward, False, ticket, component_groups, 1, relic_context),
                             "unmet": battle_total(reward, True, ticket, component_groups, 1, relic_context)})

    normal = next(row for row in combat_rows if row["floor"] == 3 and row["name"] == "作战")
    emergency = next(row for row in combat_rows if row["floor"] == 3 and row["name"] == "紧急作战")
    boss = next(row for row in combat_rows if row["floor"] == 3 and row["name"] == "险路恶敌")
    dispatch = value("pool_scrap_3")
    hope_two = min(2, hope_deficit) * 50
    dispatch_scores = {
        key: {branch: dispatch_reference_score(
            processed_points=dispatch, hope_points=hope_two if below else 0,
            grants_promotion=branch == "ordinary",
        ) for branch in ("ordinary", "ending3")}
        for key, below in (("met", False), ("unmet", True))
    }
    duel_low = value("node_duel_left") + 2 * value("node_battle_recruit")
    duel_mid = value("node_duel_center") + 2 * value("node_battle_recruit")
    duel_high = relic_scorer.pool_score("node_duel_right") + value("node_battle_recruit") + 75
    duel_unmet = {"low": value("node_duel_left") + 2 * value("node_battle_recruit", True),
                  "middle": value("node_duel_center") + 2 * value("node_battle_recruit", True),
                  "high": relic_scorer.pool_score("node_duel_right") + value("node_battle_recruit", True) + 75 * 1.25}
    encounters = {key: encounter_probe(
        pools, battles, below=below, level=level, experience=experience, hope_deficit=hope_deficit,
        cash=cash, life=life, action_value=action_value, completed_events=completed_events,
        relic_scorer=relic_scorer, corn_count=corn_count,
    ) for key, below in (("met", False), ("unmet", True))}
    eligible_events = [row["id"] for row in encounters["met"]["events"]]

    def shop(category_id: str, *, below: bool = False, squad: str | None = None, yellow_visited: bool = True) -> dict:
        return merchant_reference_score(
            category_id=category_id, floor=3, cash=cash, estimated_value=estimated_value,
            box_capacity=8, box_count=2 + processed_count + painted_agor + painted_perro + corn_count,
            yellow_visited=yellow_visited, eligible_event_ids=eligible_events,
            below_threshold=below, squad_id=squad,
        )

    merchants = {"yellow": shop("node_type_013", yellow_visited=False),
                 "greenMet": shop("node_type_004"), "greenUnmet": shop("node_type_004", below=True),
                 "greenBeforeYellowMet": shop("node_type_004", yellow_visited=False),
                 "greenBeforeYellowUnmet": shop("node_type_004", below=True, yellow_visited=False),
                 "dualGreenMet": shop("node_type_004", squad="squad_005"),
                 "dualGreenUnmet": shop("node_type_004", squad="squad_005", below=True)}
    prefix_examples = {
        "earnedCash": merchant_prefix_score(
            category_id="node_type_013", floor=3, cash=10, estimated_value=0,
            box_capacity=8, box_count=3, yellow_visited=False, eligible_event_ids=[],
            below_threshold=False, prefix_cash_outcomes=[(13, 1)], path_steps=4),
        "additiveReserve": merchant_reference_score(
            category_id="node_type_004", floor=3, cash=100, estimated_value=0,
            box_capacity=8, box_count=3, yellow_visited=False, eligible_event_ids=[],
            below_threshold=False, reserve_entries={"yellow_shop": 30, "partner_meeting": 50, "lake_fairy": 3}),
    }
    painted = {key: painted_component_relic_bonus(
        category, painted_agor=painted_agor, painted_perro=painted_perro,
        arrives_by_processing=arrives_by_processing,
    ) for key, category in (("wish", "node_type_007"), ("exchange", "node_type_008"))}
    treehole = {"points": action_value(3) if processed_count else 0, "actionGainProxy": 3,
                "canEnter": processed_count > 0, "deductSacrificedComponentUtility": False,
                "usesMapQueue": opportunity_scores is not None}
    wish_reward = relic_scorer.wish_score(cash)
    exchange, wish = EXCHANGE_OPPORTUNITY_POINTS + painted["exchange"]["points"], wish_reward["points"] + painted["wish"]["points"]
    def event_formula(row: dict) -> str:
        parts = [f"{row['knownContribution']:.2f}"]
        parts.extend(f"{term['probabilityCoefficient']:.5f}×{term['label']}" for term in row["missingTerms"])
        return "＋".join(parts)

    node_rows = [
        ("node_type_001", "作战", f"{normal['met']['total']:.2f} / {normal['unmet']['total']:.2f}", "达标/缺口；仅经验、钱、券；未定触发率的普通零件不算"),
        ("node_type_002", "紧急作战", f"{emergency['met']['total']:.2f} / {emergency['unmet']['total']:.2f}", "达标/缺口；含1藏、1组零件二选一；额外箱不算"),
        ("node_type_003", "险路恶敌", f"{boss['met']['total']:.2f} / {boss['unmet']['total']:.2f}", "III领袖；不含结局/终止附加；V见逐层表，VI附加奖励待适配"),
        ("node_type_004", "诡意行商（绿/蓝店）", f"{merchants['greenMet']['points']:.2f} / {merchants['greenUnmet']['points']:.2f}", "总经济减勾选留钱后的对数基础分＋两张单券；重复0.2倍，不代表真实购买"),
        ("node_type_005", "安全的角落", f"{safe_corner['met']['points']:.2f} / {safe_corner['unmet']['points']:.2f}", "1固定＋5随机中等概率选2，10组合择优；高级物资券按有精一六星150/否则75"),
        ("node_type_006", "不期而遇", f"达标：{event_formula(encounters['met'])}；缺口：{event_formula(encounters['unmet'])}", "原事件概率保留缺项，不把已算事件再次归一化；详细概率/分支见下表"),
        ("node_type_007", "得偿所愿", f"{wish:.2f}（{wish_reward['relicPoints']:g}−{wish_reward['cashCostPoints']:g}＋{painted['wish']['points']}）", "现金≥4使用高级池并扣4钱，否则普通池；加工品抵达涂装佩洛额外奖励另算"),
        ("node_type_008", "失与得", f"{exchange:.2f}（200＋{painted['exchange']['points']}）", "默认交换机会直接计2藏价值200；非严格增减净值；加工品抵达每件阿戈尔另得2藏"),
        ("node_type_009", "先行一步", f"普通{dispatch_scores['met']['ordinary']['points']:.2f}/{dispatch_scores['unmet']['ordinary']['points']:.2f}；三结局{dispatch_scores['met']['ending3']['points']:.2f}/{dispatch_scores['unmet']['ending3']['points']:.2f}＋前置", "达标/缺口；延迟希望/加工品×0.7，普通进阶固定93.75；三结局无进阶、不重复给普通分"),
        ("node_type_010", "误入奇境", (f"{treehole['points']:.2f} = A(3)" if opportunity_scores is not None else f"{treehole['points']:.2f}（3×200校准参照）") if processed_count else "0：无加工品不能进入", "暂估为获得3点本层行动力；不扣献出1加工品的估值，但入口资格/实际损失保留"),
        ("node_type_011", "狭路相逢", f"低{duel_low:.2f}/{duel_unmet['low']:.2f}；中{duel_mid:.2f}/{duel_unmet['middle']:.2f}；高{duel_high:.2f}/{duel_unmet['high']:.2f}", "每档达标/缺口；保留中档高于高档的当前估值，无胜率折扣"),
        ("node_type_012", "命运所指", f"假节点{relic_scorer.pool_score('node_story_curiosity_and_death'):g}；真节点退出0＋信息/目标", "标记需实际扣50钱；真结局战斗另算，互斥选择依目标"),
        ("node_type_013", "秘境行商（黄店）", f"{merchants['yellow']['points']:.2f}", "min(1000,30×现金与估价之和)；重复0.2倍，不自动加购买/培育奖励"),
        ("node_type_014", "曲折密道", "0.00", "只含直接收益；仍有移动/揭示效果"),
        ("node_type_015", "险路尽头", f"{value('node_final_scrap'):.2f}＋留存券＋剩余希望价值", "该数字仅离层加工品；经过只用一次留存券/揭示，不能再发出口物品"),
        ("node_type_016", "险路小径", f"{value('node_evacuate_scrap'):.2f}＋200rG", "I/II/IV才生成；例如r=2,G=0.6时加240；不使用留存券"),
        ("node_type_017", "应急助力", f"{aid_score['points']:.2f}（96×{corn_count}玉米）", "3名免费干员×每玉米4估价×每钱8分；估价非现金，不另计短期战力"),
        ("node_type_018", "羽瞰点", "A(1)＋首次新揭示", "不耗行动力且+1；首次后为空地，不用固定200替换实际A(1)"),
        ("node_type_019", "居民据点", f"{special_rows[0]['met']['total']:.2f} / {special_rows[0]['unmet']['total']:.2f}", "枯枝达标/缺口；两个不同零件池各二选一，败叶见专项表"),
        ("node_type_020", "林间空地", "0.00", "不含首次新揭示；有居民标记时不能用本行覆盖居民收益"),
        ("node_type_021", "流窜居民", f"{special_rows[2]['met']['total']:.2f} / {special_rows[2]['unmet']['total']:.2f}", "强买强卖达标/缺口；另一个关卡见专项表，覆盖/叠加按标记规则"),
        ("node_type_022", "追猎", f"I/II/IV仅券{value('node_battle_recruit'):.2f}", "非视觉节点；III/V按领袖奖励，VI其他奖励待适配"),
    ]
    return {"parameters": {"level": level, "experience": experience, "hopeDeficit": hope_deficit,
                           "referenceSixStarHopeCost": 10, "componentActionReference": 200,
                           "componentSmallMovementReference": 20, "seedPoints": 250,
                           "cash": cash, "life": life, "paintedAgor": painted_agor,
                           "paintedPerro": painted_perro, "arrivesByProcessing": arrives_by_processing,
                           "processedCount": processed_count, "opportunityScores": opportunity_scores,
                           "actionPoints": action_points, "pursuit": pursuit,
                           "completedEvents": list(completed_events), "cornCount": corn_count,
                           "hasElite1SixStar": has_elite1_six_star, "estimatedValue": estimated_value},
            "thresholds": [{"floor": floor, "normal": team_threshold(floor),
                            "dual": team_threshold(floor, "squad_005")} for floor in range(1, 7)],
            "pools": list(probes.values()), "combat": combat_rows, "specialBattles": special_rows,
            "merchants": merchants, "encounters": encounters, "paintedBonuses": painted,
            "safeCorner": safe_corner, "emergencyAid": aid_score, "merchantPrefixExamples": prefix_examples,
            "dispatch": dispatch_scores, "exchangeOpportunityPoints": EXCHANGE_OPPORTUNITY_POINTS,
            "relicScores": relic_scorer.data, "wishReward": wish_reward,
            "treehole": treehole, "duel": {"met": {"low": duel_low, "middle": duel_mid, "high": duel_high}, "unmet": duel_unmet},
            "nodes": [dict(zip(("id", "name", "score", "notes"), row)) for row in node_rows]}


def markdown(report: dict) -> str:
    p = report["parameters"]
    lines = ["# 节点基础收益校准：扩展版", "",
             "这是独立测试报告，不是当前路线搜索的运行分，也不是所有状态共用的固定节点分。", "",
             "## 测试口径", "",
             f"- N15/满经验科技、非四双职业队；指挥等级{p['level']}，当前经验{p['experience']}。层级只决定战斗奖励，不自动猜该层实际等级。",
             f"- 对照两种状态：队伍达标（希望缺口价值关闭）；队伍未达且尚缺{p['hopeDeficit']}希望（六星完整费用10希望=500分，经验/券×1.25）。I层无门槛，不构造未达状态。",
             f"- 机械师已精二，无需求重装券×3；现金{p['cash']}，生命/上限{p['life']}/{p['life']}；可献出加工品{p['processedCount']}件。这些是测试状态，不从真实Playtime自动猜出。",
             f"- 当前涂装阿戈尔{p['paintedAgor']}件、涂装佩洛{p['paintedPerro']}件；抵达方式为{'加工品' if p['arrivesByProcessing'] else '徒步'}。获取零件时的+0.05库存修正不再乘到节点实际触发的藏品数。",
             "- 加工品估值专用参照：每行动力200、小八界移动20；种子250。真实地图仍用A(x)及小八界落点估值，不将这个参照灌入当局。",
             ("- 本报告未输入具体地图价值队列：行动力选项暂用每点200参照，误入奇境为600；这是展示用近似，不宣称当前地图A(3)恒等于600。" if p['opportunityScores'] is None else
              f"- 已输入冻结的地图底分队列{p['opportunityScores']}；行动力{p['actionPoints']}，{'追猎' if p['pursuit'] else '非追猎'}，多点奖励逐项计算A(x)，不递归加入树洞/契约自身。"),
             "- 误入奇境暂按+3本层行动力估价，不扣献出加工品的机会成本；真实进入仍需并失去一件加工品，不能把代理分当实际在旧地图获得3行动力。",
             "- 揭示、结局、顺序偏好暂关闭用于隔离基础收益，真实支出照扣；未定项显示公式，不伪装为0。",
             "- 失与得普通交换使用200分机会代理（2藏价值），不是严格库存增减净值；先行一步延迟加工品/希望×0.7，普通进阶固定50×1.25×1.5=93.75，达标也保留。三结局分支没有进阶奖励。",
             "- 黄店min(1000,30×总经济)；绿店301.873547×ln(1+x/21.283575)＋两单券机会（四职业队随机单券＋本家单券）。x为总经济减勾选留钱的非负余量，重复机会整体×0.2，不视为已经买入券。",
             "- 默认只给未去过且尚可能存在的黄店留20；黄店后/明确无黄店不扣这项。事件留钱改为用户勾选数额相加，不自动以事件池取最大门槛。各表是独立到达状态对照。",
             "- 使用当前本地奖励池的条件频次，不合并各来源列；未观察成员不宣称不可能。各池的样本范围见末表；N6/I层或III领袖统计跨层使用只是校准代理，未证明各层/N15一致。",
             "- 零件/券二选一来自同池的不同物品，暂按经验权重依次不放回抽取；候选组合真实联合频次未知。所列上下界为粗略评分范围。藏品使用每实际领取一件的池分，不再次求择优或乘2。",
             "- 不包含普通/紧急局内额外箱奖励。普通作战未明确触发率的零件不算入本版确认部分。概率与偏好数值不混改。", "",
             "## 各类节点", "", "| ID | 类别 | 测试分/公式 | 说明 |", "| --- | --- | --- | --- |"]
    lines.extend(f"| `{r['id']}` | {r['name']} | {r['score']} | {r['notes']} |" for r in report["nodes"])
    lines.extend(["", "## 藏品池评分", "", "| 共用池ID | 每件领取分 |", "| --- | --- |"])
    lines.extend(f"| `{key}` | {points:g} |" for key, points in report["relicScores"]["poolPoints"].items())
    lines.extend(["", "## 两类商店条件对照", "", "| 状态 | 首次机会分 | 分解 |", "| --- | --- | --- |"])
    for key, label in (("yellow", "黄店：首次总经济评分"),
                       ("greenMet", "绿店：黄店后、队伍达标"), ("greenUnmet", "绿店：黄店后、队伍缺口"),
                       ("greenBeforeYellowMet", "绿店：黄店前、队伍达标"),
                       ("greenBeforeYellowUnmet", "绿店：黄店前、队伍缺口"),
                       ("dualGreenMet", "四职业队绿店：达标"), ("dualGreenUnmet", "四职业队绿店：缺口")):
        row = report["merchants"][key]
        lines.append(f"| {label} | {row['points']:.2f} | 进店{row['parts']['entry']:.2f}＋券机会{row['parts']['tickets']:.2f} |")
    green = report["merchants"]["greenMet"]["preferences"]
    lines.extend(["", f"本测试绿店保留额{green['cashReserve']:.2f}，可评分经济{green['unreservedEconomy']:.2f}。零入参无券机会；正入参叠券机会。重复为对应原始机会分0.2倍，不自动获取新券。", "",
                  "## 安全角落与应急助力", "",
                  "安全角落固定生命上限选项，本阶段生命/携带位分0；另五项无放回等概率抽两项，三选一取最高。不是五个40%独立出现。", "",
                  "| 状态 | 希望选项 | 高级物资券 | +2行动力 | 箱容量 | 节点期望分 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for key, label in (("met", "达标"), ("unmet", "缺口")):
        safe = report["safeCorner"][key]
        options = safe["options"]
        lines.append(f"| {label} | {options['hope']:g} | {options['advanced_supply_ticket']:g} | {options['action_points']:g} | 100 | {safe['points']:.2f} |")
    aid = report["emergencyAid"]
    lines.extend(["", f"应急助力：玉米{aid['cornCount']}件，3×4×数量增加估价{aid['estimatedValueIncrease']}，计{aid['points']}分，现金不实际增加。", "",
                  "## 商店前缀补偿", "",
                  f"初始10钱、前序净得13钱、第4步商店：再加4步各1钱代理，到达评分现金27，黄店{report['merchantPrefixExamples']['earnedCash']['points']:.2f}分。该代理不写资源，不重复另加每钱8分。",
                  f"现金100，勾选黄店30/合伙人50/仙女3，合计留83，绿店入参17，机会分{report['merchantPrefixExamples']['additiveReserve']['points']:.2f}。", "",
                  "## 涂装零件触发对照", "", "| 抵达 | 对应涂装件数 | 得偿所愿 | 失与得：默认交换机会200 |", "| --- | --- | --- | --- |"])
    for processing in (False, True):
        for count in (0, 1, 2):
            wish = painted_component_relic_bonus("node_type_007", painted_perro=count, arrives_by_processing=processing)
            exchange = painted_component_relic_bonus("node_type_008", painted_agor=count, arrives_by_processing=processing)
            lines.append(f"| {'加工品' if processing else '徒步'} | {count} | {report['wishReward']['points'] + wish['points']:g} | {EXCHANGE_OPPORTUNITY_POINTS + exchange['points']} |")
    lines.extend(["", "各自只触发对应种类的概念体；交换一次/两次不让同一次抵达的阿戈尔收益再触发。默认200是完整交换机会代理，不再叠一份交换净值；特殊物品/结局上贡后续单列。", "",
                  "## 先行一步分解", "", "| 状态/分支 | 延迟加工品 | 延迟希望 | 进阶 | 已算合计 |", "| --- | --- | --- | --- | --- |"])
    for key, label in (("met", "达标"), ("unmet", "缺口")):
        for branch, branch_name in (("ordinary", "普通派遣"), ("ending3", "三结局派遣")):
            row = report["dispatch"][key][branch]
            scores = " | ".join(f"{row['parts'][part]:.2f}" for part in ("delayedProcessing", "delayedHope", "promotion"))
            lines.append(f"| {label}·{branch_name} | {scores} | {row['points']:.2f} |")
    lines.extend(["", "只对延迟希望/加工品打0.7折扣，不再将93.75进阶分打折或随当前门槛开关；三结局藏品/前置价值另加，不能把普通进阶收益复制过去。", "",
                  "## 本层不期而遇加权", "",
                  f"使用本地选择器检查材料，抓取时间{report['encounters']['met']['sourceCheckedAt']}；III主层普通随机池，不混入标记确认的线人/泪之聚落。不是本轮重新抓取网站。",
                  "测试未取得过笼控器、本层无应急助力，按条件排除红苔/独活；已走事件再按重复规则排除、重算全池概率。已算事件不另行归一化，未知项保留原概率。",
                  "伴生战斗券暂按一张普通单券代理；湖中魇零件暂用一般紧急二选一池，临时中介所按单券2倍。划算买卖/鸭托邦按隐藏藏品池；湖中仙女各分支藏品225。影子逐轮递推实际血量/回血，不以平均血量放行；指定藏品暂同100，护盾/生命/携带位本阶段资源分0。", "",
                  "| 事件 | 当前概率 | 达标：已算分 | 缺口：已算分 | 未算项/默认分支 |", "| --- | --- | --- | --- | --- |"])
    unmet_events = {row["id"]: row for row in report["encounters"]["unmet"]["events"]}
    for row in report["encounters"]["met"]["events"]:
        unmet = unmet_events[row["id"]]
        met_points = "待定" if row["knownPoints"] is None else f"{row['knownPoints']:.2f}"
        unmet_points = "待定" if unmet["knownPoints"] is None else f"{unmet['knownPoints']:.2f}"
        missing = "；".join(term["label"] for term in row["missingTerms"])
        lines.append(f"| {row['name']} | {row['probability']:.5%} | {met_points} | {unmet_points} | {missing + '；' if missing else ''}{row['notes']} |")
    lines.extend(["", "当前测试的合资格事件均有临时估值，汇总可给数值；其他状态若仍有未定项则保留公式，不自动用0补齐或将剩余事件压成100%。藏品池评分已替换通用100，固定藏品暂保留原估值。", "",
                  "## Boss与紧急作战分解", "",
                  "| III节点/状态 | 经验 | 钱 | 券 | 藏品 | 零件 | 合计 |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for name in ("紧急作战", "险路恶敌"):
        battle = next(row for row in report["combat"] if row["floor"] == 3 and row["name"] == name)
        for key, label in (("met", "达标"), ("unmet", "缺口")):
            row = battle[key]
            scores = " | ".join(f"{row['parts'][part]:.2f}" for part in ("experience", "cash", "tickets", "relics", "components"))
            lines.append(f"| {name}·{label} | {scores} | {row['total']:.2f} |")
    lines.extend(["", "两者都只领一件二选一；Boss藏品池200、紧急125。Boss零件为轮子/假肢/引擎/底座/外骨骼，当前移动分较低；紧急还可能获得高分自然物/概念体及带行动力的加工品。差异同时包含藏品和零件池，未加结局/离层终止分。"])
    lines.extend(["", "## 逐层战斗", "", "同样的等级/希望状态下，仅改变战斗所属区域；达标/未达不是同一局同时成立的状态。", "",
                  "| 区域 | 节点 | 经验 | 达标分 | 未达分 | 达标：钱/券/藏/零件 | 未达：经验分 |",
                  "| --- | --- | --- | --- | --- | --- | --- |"])
    for r in report["combat"]:
        met, unmet = r["met"], r["unmet"]
        parts = met["parts"]
        unmet_total = f"{unmet['total']:.2f}" if unmet else "不适用"
        unmet_xp = f"{unmet['parts']['experience']:.2f}" if unmet else "0"
        lines.append(f"| {ROMAN[r['floor'] - 1]} | {r['name']} | {met['experienceAward']} | {met['total']:.2f} | "
                     f"{unmet_total} | "
                     f"{parts['cash']:.2f}/{parts['tickets']:.2f}/{parts['relics']:.2f}/{parts['components']:.2f} | "
                     f"{unmet_xp} |")
    lines.extend(["", "## 居民与特殊战斗", "", "| 关卡 | 达标分 | 未达分 | 经验 | 零件分 |", "| --- | --- | --- | --- | --- |"])
    lines.extend(f"| {r['name']} | {r['met']['total']:.2f} | {r['unmet']['total']:.2f} | "
                 f"{r['met']['experienceAward']} | {r['met']['parts']['components']:.2f} |" for r in report["specialBattles"])
    lines.extend(["", "## 奖励池取值", "", "范围仅为按当前抽取权重估计的均值至最高物品分，不包含来源跨层偏差，不是实际游戏置信区间。", "",
                  "| 条件池 | 候选记录数 | 单候选均值 | 不重复择优值 | 评分下界/上界 | 样本范围 |",
                  "| --- | --- | --- | --- | --- | --- |"])
    for r in report["pools"]:
        scope = r["scope"] or r["observationSource"] or "见本地源数据条件"
        lines.append(f"| `{r['contextId']}` | {r['recordCount']} | {r['mean']:.2f} | {r['expectedBest']:.2f} | "
                     f"{r['lowerBound']:.2f}/{r['upperBound']:.2f} | {scope} |")
    lines.extend(["", "## 下一步校准", "",
                  "狭路相逢中档高于高档的当前排序保留；黄/绿店首次机会已有试用分。继续校准结局前置、揭示系数及实际顺序幅度。条件规则虽已有设计，不代表每个系数已填。",
                  "节点分随当前等级/希望缺口/干员/库存/地图变化；奖励期望不能作为实际到账资源。按路线模拟状态与去重后再接入搜索。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--level", type=int, default=4)
    parser.add_argument("--experience", type=int, default=0)
    parser.add_argument("--hope-deficit", type=float, default=20)
    parser.add_argument("--cash", type=float, default=50)
    parser.add_argument("--life", type=int, default=12)
    parser.add_argument("--corn-count", type=int, default=0)
    parser.add_argument("--has-elite1-six-star", action="store_true")
    parser.add_argument("--estimated-value", type=float, default=0)
    parser.add_argument("--painted-agor", type=int, default=0)
    parser.add_argument("--painted-perro", type=int, default=0)
    parser.add_argument("--walk", action="store_true", help="Disable processed-movement painted relic bonuses")
    parser.add_argument("--processed-count", type=int, default=1)
    parser.add_argument("--opportunity-scores", type=float, nargs="*", default=None,
                        help="Frozen unvisited intrinsic node scores; empty list means no valuable nodes")
    parser.add_argument("--action-points", type=int, default=6)
    parser.add_argument("--pursuit", action="store_true")
    parser.add_argument("--completed-event", action="append", default=[], help="Already visited main-layer encounter ID")
    parser.add_argument("--relic-scores", type=Path, default=RELIC_CONFIG_PATH)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "scoring_calibration")
    args = parser.parse_args()
    report = build_report(
        level=args.level, experience=args.experience, hope_deficit=args.hope_deficit,
        cash=args.cash, life=args.life, painted_agor=args.painted_agor, painted_perro=args.painted_perro,
        arrives_by_processing=not args.walk, processed_count=args.processed_count,
        opportunity_scores=args.opportunity_scores, action_points=args.action_points, pursuit=args.pursuit,
        completed_events=tuple(args.completed_event), relic_scores_path=args.relic_scores,
        corn_count=args.corn_count, has_elite1_six_star=args.has_elite1_six_star,
        estimated_value=args.estimated_value,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "node_scores.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path = args.output_dir / "node_scores.md"
    path.write_text(markdown(report), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
