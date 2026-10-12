"""Read-only combat bonus calculation and presentation, without battle simulation."""

from copy import deepcopy
from decimal import Decimal
from functools import lru_cache
import json

from .operator_catalog import find_operator
from .relic_effects import DEFINITIONS_PATH, load_definitions, structural_stage, validate_runtime_state


CATEGORY_LABELS = {
    "survival": "生存", "damage": "伤害", "cost": "费用", "skill_cycle": "回转",
    "control": "控制", "mechanism": "机制", "support": "支援道具",
}
DOMAIN_LABELS = {"outside_battle": "局外", "inside_battle": "局内"}
METRIC_LABELS = {
    "attack": "攻击力", "max_hp": "最大生命", "defense": "防御力", "resistance": "法术抗性",
    "attack_speed": "攻击速度", "redeployment_time": "再部署时间", "deployment_cost": "部署费用",
    "initial_dp": "初始费用", "dp_recovery": "费用自然回复", "initial_sp": "初始技力",
    "skill_sp_cost": "技能技力需求", "sp_recovery_per_second": "技力自然回复速度",
    "sp_recovery_per_attack": "攻击回复技力", "sp_recovery_per_hit": "受击回复技力",
    "direct_sp_grant": "直接获得技力", "damage_taken": "受到伤害", "damage_dealt": "造成伤害",
    "physical_damage_taken": "受到物理伤害", "arts_damage_taken": "受到法术伤害",
    "dodge_probability": "闪避概率", "vulnerability": "脆弱", "camouflage": "迷彩",
    "barrier": "屏障", "damage_blocking_shield": "伤害抵挡护盾", "block_count": "阻挡数",
    "healing_received": "接受治疗", "hp_recovery_received": "生命回复效果",
    "hp_recovery_per_second": "每秒生命回复", "hp_recovery": "生命回复", "hp_loss": "生命流失",
    "extra_damage": "额外伤害", "status_duration": "异常持续时间", "weight": "重量",
    "status_immunity": "异常免疫", "stun": "晕眩", "levitate": "浮空",
    "disable_special_abilities": "特殊能力失效", "allowed_deployment_tiles": "部署地形",
    "uses_deployment_capacity": "占用部署位", "ammo_restore": "补充弹药", "summon": "召唤物",
    "elemental_buildup_received": "受到元素损伤", "elemental_burst_enhancement": "元素爆发增强",
    "remove_elemental_self_dot": "移除自身元素持续伤害", "random_enemy_max_hp": "随机敌人生命",
    "enemy_resistance_reduction": "降低目标法抗", "enemy_defense_ignore": "无视目标防御",
    "skill_activation_forbidden": "禁止开启技能", "skill_auto_activation": "技能自动开启",
    "support_item": "支援道具", "boss_ability_modifier": "指定Boss机制", "additional_enemies": "额外敌人",
    "current_hp": "当前生命", "damage_block_layers": "抵挡伤害次数", "dp_grant": "获得费用",
    "hp_regeneration_per_second": "每秒生命回复", "remaining_redeployment_time": "剩余再部署时间",
    "deployment_cost_shuffle": "部署费用重排", "sluggish": "停顿",
}
SIDE_LABELS = {"friendly_unit": "我方全体单位", "friendly_operator": "我方全体干员",
               "operator": "该干员", "bound_operator": "附魔受益干员", "enemy": "敌方", "battle": "战场"}
SCOPE_LABELS = {
    "damageType": "伤害类型", "skillRecoveryType": "技力回复类型", "skillRecoveryTypes": "技力回复类型",
    "flightState": "起飞状态", "deploymentTile": "部署地形", "faction": "阵营", "enemyRank": "敌人类别",
    "enemyId": "指定敌人", "unitType": "单位类型", "selection": "选择对象", "statuses": "异常类型",
    "statusApplication": "异常施加方式", "provider": "提供者", "providerProfession": "提供者职业",
    "providerPosition": "提供者部署位", "providerSubprofessions": "提供者子职业", "receiver": "接收者",
    "receiverDeploymentTile": "接收者部署地形", "position": "部署位", "profession": "职业",
    "subprofessions": "子职业", "operatorSource": "招募来源",
    "explicitStatuses": "明确列出的异常", "item": "支援道具", "boundProviderIds": "附魔提供者",
}
TOKEN_LABELS = {
    "physical": "物理", "arts": "法术", "true": "真实", "elemental_damage": "元素伤害",
    "bound": "束缚", "ammo": "弹药技能",
    "natural": "自然恢复", "attack": "攻击回复", "being_hit": "受击回复",
    "melee": "近战", "ranged": "远程", "airborne": "起飞", "summon": "召唤物",
    "elite": "精英", "boss": "领袖", "elite_and_boss": "精英与领袖", "normal": "普通",
    "high_ground": "高台", "low_ground": "地面", "stunned": "晕眩", "cold": "寒冷", "frozen": "冻结",
    "discrete": "一次性施加", "temporary": "临时招募", "emergency": "应急助力",
    "one_random_in_squad_operator_at_battle_start": "本场从编队随机1名",
    "first_deployed_operator": "首次部署干员", "bound_operator": "附魔受益干员",
    "any_friendly_operator": "任意我方干员", "attacked_enemy": "被攻击目标", "healing_target": "治疗目标",
    "healing_receiver": "治疗目标", "all_enemies": "全体敌人",
    "enemies_in_provider_attack_range": "提供者攻击范围内敌人",
    "enemies_in_operator_attack_range": "干员攻击范围内敌人",
    "friendly_units_in_provider_attack_range": "提供者攻击范围内我方单位",
    "friendly_operators_in_provider_attack_range": "提供者攻击范围内干员",
    "operators_in_provider_attack_range": "提供者攻击范围内干员",
    "other_operators_in_provider_attack_range": "提供者攻击范围内其他干员",
    "other_friendly_operators_on_field": "场上其他干员", "enemy_entering_attack_range": "进入攻击范围的敌人",
    "enemies_in_4_surrounding_tiles": "周围4格敌人",
    "one_random_enemy_and_surrounding_8_tiles": "随机敌人及其周围8格",
}
IDENTITY_FIELDS = {"profession", "subprofessions", "position", "operatorSource", "faction"}
TAG_FIELDS = {"damageType", "skillRecoveryType", "skillRecoveryTypes", "statuses", "explicitStatuses", "statusApplication", "item"}
NUMERIC_OPERATIONS = {"flat_delta", "base_ratio_delta", "factor"}


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("加成数值必须为有限数")
    return result


def decimal_text(value):
    return format(number(value).normalize(), "f")


@lru_cache(maxsize=1)
def constants():
    return json.loads((DEFINITIONS_PATH.parent / "constant_sources.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def layer_environments():
    return json.loads((DEFINITIONS_PATH.parent / "layer_environments.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def original_texts():
    data = json.loads((DEFINITIONS_PATH.parents[1] / "blackflow_relic_texts.json").read_text(encoding="utf-8"))
    return {row["prts_number"]: row.get("prts_effect", "") for row in data["relics"]}


def fresh_relic_state(relic_id, definitions=None):
    """A new acquisition does not inherit counters from an earlier lost copy."""
    definition = (definitions or load_definitions())[relic_id]
    kind = definition["management"]["kind"]
    value = definition["management"].get("initial", 0) if kind == "stacking" else False if kind == "one_shot" else None
    return {"id": relic_id, "value": value}


def _relic_state(row, definition):
    kind = definition["management"]["kind"]
    raw = row.get("value", row.get("state"))
    if kind == "ordinary":
        if "value" in row and raw is not None:
            raise ValueError("普通藏品的维护值必须为null")
        value = None
    elif kind == "one_shot":
        if "value" in row and type(raw) is not bool:
            raise ValueError("一次性藏品的维护值必须为布尔值")
        value = raw if type(raw) is bool else raw in ("active", "已生效")
    else:
        value = raw
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("藏品层数必须为非负整数")
    binding = row.get("enchantment")
    ids = row.get("operatorInstanceIds", [binding["operatorInstanceId"]] if binding else [])
    state = {"value": value, "operatorInstanceIds": ids}
    if value is not None or kind != "stacking":
        validate_runtime_state(definition, state)
    maximum = definition["management"].get("maximum")
    minimum = definition["management"].get("minimum", 0)
    if kind == "stacking" and value is not None and (value < minimum or maximum is not None and value > maximum):
        raise ValueError(f"{definition['name']}层数超出已确认范围")
    return state


def _operators(state):
    result = []
    squad = set(state.get("squad", []))
    for raw in state.get("operators", []):
        entry = find_operator(raw.get("operatorId") or raw.get("name")) or {}
        operator = {**entry, **deepcopy(raw)}
        operator["instanceId"] = raw["instanceId"]
        operator["position"] = {"近战位": "melee", "远程位": "ranged"}.get(operator.get("position"), operator.get("position"))
        operator["inSquad"] = operator["instanceId"] in squad
        result.append(operator)
    if len({row["instanceId"] for row in result}) != len(result):
        raise ValueError("干员实例ID重复")
    return result


def _scope(clause, operator, include_scoped=False):
    scope = clause["target"]["scope"]
    bindings = clause.get("operatorInstanceIds", [])
    direct_bound = clause["target"]["side"] == "bound_operator"
    bound_action = scope.get("provider") == "bound_operator" and scope.get("receiver") in {"attacked_enemy", "enemy_entering_attack_range"}
    pending = []
    if direct_bound or bound_action:
        if not bindings:
            pending.append("附魔受益干员未确认")
        elif (operator is None and not include_scoped) or (operator is not None and operator["instanceId"] not in bindings):
            return None
    for key in IDENTITY_FIELDS:
        if key not in scope:
            continue
        if operator is None:
            if include_scoped:
                continue
            return None
        attribute = {"subprofessions": "subprofession", "operatorSource": "source"}.get(key, key)
        actual = operator.get(attribute)
        expected = scope[key] if isinstance(scope[key], list) else [scope[key]]
        if not actual:
            pending.append(f"{SCOPE_LABELS[key]}未确认")
        elif actual not in expected:
            return None
    if operator is not None and scope.get("selection") == "one_random_in_squad_operator_at_battle_start" and not operator["inSquad"]:
        return None
    if scope.get("unitType") == "summon":
        return "related", pending
    for key in scope.keys() - SCOPE_LABELS.keys():
        pending.append(f"作用范围字段尚未支持：{key}")
    return "applicable", pending


def _resolve(clause, relic_state, context, states, difficulty):
    item = deepcopy(clause)
    pending, conditions = [], []
    for condition in item["conditions"]:
        if condition.get("field") == "relic_variant" and condition.get("operator") == "eq":
            if structural_stage(difficulty) != condition["value"]:
                return None
        else:
            conditions.append(condition)
    item["conditions"] = conditions
    rule = item.get("valueRule", {})
    count = None
    if rule.get("kind") == "persistent_counter":
        count = relic_state["value"]
    elif rule.get("kind") == "external_relic_counter":
        count = states.get(rule["relicId"], {}).get("value")
    elif rule.get("kind") in {"snapshot_count", "battle_count"}:
        count = context.get(rule.get("field"))
    if rule.get("kind") in {"persistent_counter", "external_relic_counter", "snapshot_count", "battle_count"}:
        if count is None:
            pending.append("当前计数未确认")
        else:
            if type(count) is not int or count < 0:
                raise ValueError("条件计数必须为非负整数")
            unit_size = rule.get("unitSize", 1)
            if type(unit_size) is not int or unit_size <= 0:
                raise ValueError("计数单位必须为正整数")
            count //= unit_size
            count = min(count, rule.get("maximumStacks", count))
            value = number(rule.get("initial", 0)) + number(rule.get("perStack", rule.get("perUnit", 0))) * count
            value = min(value, number(rule.get("maximum", value)))
            item["value"] = decimal_text(value)
            item["resolvedCount"] = count
            item["resolvedFrom"] = rule["kind"]
            if rule.get("kind") in {"persistent_counter", "external_relic_counter"} or item["domain"] == "outside_battle":
                if rule.get("kind") == "snapshot_count":
                    item["resolvedConditions"] = item["conditions"]
                    item["conditions"] = []
                item.pop("aggregation", None)
                item.pop("valueRule", None)
            else:
                item["snapshotConditional"] = True
                item.pop("aggregation", None)
                item.pop("valueRule", None)
    for relic_id in item.get("requiresRelicIds", []):
        if relic_id not in states:
            return None
    item["pending"] = pending
    return item


def _external_clause(source_id, name, metric, value, group, scope=None, operation="factor", description=None):
    side, metric = metric.split("_", 1)
    side = {"friendly": "friendly_unit", "enemy": "enemy", "battle": "battle"}[side]
    category = "survival" if (side == "enemy" and metric == "attack") or (side != "enemy" and metric in {"max_hp", "defense"}) else "damage"
    return {"id": source_id + "." + metric, "category": "combat", "combatCategory": category,
            "domain": "outside_battle", "target": {"side": side, "metric": metric, "scope": scope or {}},
            "operation": operation, "value": decimal_text(value) if operation in NUMERIC_OPERATIONS else value, "stackingGroup": group,
            "conditions": [], "sourceId": source_id, "sourceName": name, "sourceType": "environment",
            "pending": [], "description": description}


def _external(state, context, difficulty, notices):
    config, result = constants(), []
    bonuses = state.get("opening", {}).get("technologyCombatBonuses")
    if bonuses is None:
        bonuses = {field: (number(config["technology"]["defaults"]["friendly_" + metric]) - 1) * 100
                   for field, metric in (("attackPercent", "attack"), ("defensePercent", "defense"), ("maxHpPercent", "max_hp"))}
        notices.append("局外科技未提供，暂用满科技默认值")
    for field, metric in (("attackPercent", "attack"), ("defensePercent", "defense"), ("maxHpPercent", "max_hp")):
        if field not in bonuses:
            notices.append("局外科技字段缺失：" + field)
            continue
        if isinstance(bonuses[field], bool) or number(bonuses[field]) < 0:
            raise ValueError("局外科技百分比必须为非负有限数")
        result.append(_external_clause("technology", "局外科技", "friendly_" + metric,
                                      number(bonuses[field]) / 100, config["technology"]["stackingGroup"],
                                      operation="base_ratio_delta"))
    for metric, value in config["difficultyOnly"].get(str(difficulty), {}).items():
        result.append(_external_clause("difficulty_only", f"N{difficulty}专属修正", metric, value, "difficulty_only"))
    for row in config["difficultyCumulative"]:
        if difficulty >= row["minimumDifficulty"]:
            scope = {} if row["scope"] == "all_enemies" else {"enemyRank": "elite_and_boss" if row["scope"] == "elite_and_boss_enemies" else "boss"}
            result.append(_external_clause("difficulty_" + str(row["minimumDifficulty"]), f"N{row['minimumDifficulty']}追加条件", "enemy_" + row["metric"], row["factor"], row["stackingGroup"], scope))
    count = context.get("enemyRegionCount")
    scaling = config["floorScaling"]
    if difficulty >= len(scaling["difficultyPercentByN"]):
        raise ValueError("该难度的敌人区域增长尚未配置")
    factor = 1 + number(scaling["difficultyPercentByN"][difficulty]) / 100
    for metric in scaling["metrics"]:
        row = _external_clause("enemy_region_growth", "敌人逐区域增长", metric, factor ** count if count is not None else factor, scaling["stackingGroup"])
        if count is None:
            row["pending"].append("实际计入敌人难度的区域数未确认，不以当前主层编号代替")
        result.append(row)
    dystopia_id = context.get("dystopiaId")
    if dystopia_id:
        entry = config.get("dystopias", {}).get(dystopia_id)
        if entry is None:
            notices.append("该实托邦的战斗词条尚未结构化：" + dystopia_id)
        elif context.get("dystopiaAffected") is not False:
            tier = next((row for row in reversed(entry["tiers"]) if difficulty >= row["minimumDifficulty"]), None)
            if tier:
                for metric in entry["metrics"]:
                    row = _external_clause(dystopia_id, entry["name"], metric, tier["factor"], entry["stackingGroup"])
                    if context.get("dystopiaAffected") is not True:
                        row["conditions"] = [{"description": "战斗节点在实托邦覆盖范围内", "resolution": "display_only"}]
                    result.append(row)
                extra = _external_clause(dystopia_id, entry["name"], "battle_additional_enemies", {"description": entry["additionalEffect"]}, entry["stackingGroup"], operation="mechanism")
                extra["conditions"] = [{"description": "实托邦覆盖范围内", "resolution": "display_only"}]
                result.append(extra)
    return result


def _row(clause, operator, include_scoped=False):
    match = _scope(clause, operator, include_scoped)
    if match is None:
        return None
    relationship, pending = match
    pending = [*clause.get("pending", []), *pending]
    scope = deepcopy(clause["target"]["scope"])
    conditions = deepcopy(clause["conditions"])
    if clause.get("operatorInstanceIds") and scope.get("provider") == "bound_operator":
        scope["boundProviderIds"] = clause["operatorInstanceIds"]
    dynamic = {key: value for key, value in scope.items() if key not in IDENTITY_FIELDS | TAG_FIELDS}
    if dynamic:
        conditions.append({"scope": dynamic})
    conditional = bool(conditions or clause.get("snapshotConditional"))
    numeric = clause["operation"] in NUMERIC_OPERATIONS and not clause.get("valueRule") and clause.get("resolution") != "description_only"
    strategy = "numeric" if numeric else "describe"
    if clause["target"]["metric"] == "dodge_probability":
        strategy = "evasion"
    elif clause["target"]["metric"] == "vulnerability":
        strategy = "vulnerability"
    if pending:
        strategy = "describe"
    bucket = "related" if relationship == "related" else "unresolved" if pending else "conditional" if conditional or strategy == "describe" else "constant"
    side = clause["target"]["side"]
    if operator is not None and side in {"friendly_unit", "friendly_operator", "bound_operator"} and relationship != "related":
        side = "operator"
    source = {"id": clause["sourceId"], "name": clause["sourceName"], "type": clause["sourceType"],
              "clauseId": clause["id"], "operation": clause["operation"], "value": clause["value"],
              "scope": deepcopy(clause["target"]["scope"]), "conditions": deepcopy(clause["conditions"]),
              "stackingGroup": clause.get("stackingGroup"), "lifetime": clause.get("lifetime"),
              "originalText": clause.get("originalText"), "trigger": clause.get("trigger"),
              "resolvedConditions": clause.get("resolvedConditions", []),
              "operatorInstanceIds": clause.get("operatorInstanceIds", [])}
    if "resolvedCount" in clause:
        source["resolvedCount"] = clause["resolvedCount"]
        source["resolvedFrom"] = clause["resolvedFrom"]
    if clause.get("acquisitionId"):
        source["acquisitionId"] = clause["acquisitionId"]
    row = {"category": clause["combatCategory"], "domain": clause["domain"], "side": side,
           "metric": clause["target"]["metric"], "bucket": bucket, "strategy": strategy,
           "conditions": conditions, "tags": {key: scope[key] for key in TAG_FIELDS if key in scope},
           "pending": pending, "sources": [source], "value": deepcopy(clause["value"]),
           "description": clause.get("description"), "valueRule": clause.get("valueRule"),
           "conditionGroup": clause.get("conditionGroup"), "selectionGroup": clause.get("selectionGroup")}
    if include_scoped:
        # Overview scopes remain separate; a selected operator can merge applicable scopes.
        row["displayScope"] = deepcopy(scope)
        if clause["target"]["side"] == "bound_operator":
            row["displayScope"]["operatorInstanceIds"] = clause.get("operatorInstanceIds", [])
        row["boundOperatorNames"] = clause.get("boundOperatorNames", [])
    if strategy == "numeric":
        row.update(flatDelta="0", baseRatioDelta="0", factor="1")
        field = {"flat_delta": "flatDelta", "base_ratio_delta": "baseRatioDelta", "factor": "factor"}[clause["operation"]]
        row[field] = decimal_text(clause["value"])
    elif strategy in {"evasion", "vulnerability"}:
        row["ratio"] = decimal_text(clause["value"]["chance" if strategy == "evasion" else "ratio"])
        if number(row["ratio"]) < 0 or strategy == "evasion" and number(row["ratio"]) > 1:
            raise ValueError("闪避概率必须在0到1之间，脆弱比例不能为负数")
        row["strategyParameters"] = {key: value for key, value in clause["value"].items()
                                     if key not in {"chance", "ratio"}}
    return row


def _numeric_zones(sources):
    """Sum percentages within a zone, and multiply independent zone results."""
    zones = {}
    for source in sources:
        group = source["stackingGroup"]
        zone = zones.setdefault(group, {"id": group, "flatDelta": Decimal(0),
                                       "baseRatioDelta": Decimal(0), "factor": Decimal(1), "clauseIds": []})
        field = {"flat_delta": "flatDelta", "base_ratio_delta": "baseRatioDelta", "factor": "factor"}[source["operation"]]
        value = number(source["value"])
        zone[field] = zone[field] * value if field == "factor" else zone[field] + value
        zone["clauseIds"].append(source["clauseId"])
    percentage_factor, factor = Decimal(1), Decimal(1)
    for zone in zones.values():
        percentage_factor *= 1 + zone["baseRatioDelta"]
        factor *= zone["factor"]
    return {"flatDelta": decimal_text(sum((zone["flatDelta"] for zone in zones.values()), Decimal(0))),
            "baseRatioDelta": decimal_text(percentage_factor - 1), "factor": decimal_text(factor),
            "relativeFactor": decimal_text(percentage_factor * factor),
            "relativePercent": decimal_text((percentage_factor * factor - 1) * 100),
            "multiplicationZones": [{key: decimal_text(value) if isinstance(value, Decimal) else value
                                     for key, value in zone.items()} for zone in zones.values()]}


def _merge(rows):
    groups, output = {}, []
    for row in rows:
        identity = {field: row[field] for field in ("category", "domain", "side", "metric", "bucket", "strategy", "conditions", "tags")}
        identity["strategyParameters"] = row.get("strategyParameters")
        identity["conditionGroup"] = row.get("conditionGroup")
        identity["selectionGroup"] = row.get("selectionGroup")
        identity["displayScope"] = row.get("displayScope")
        key = json.dumps(identity, sort_keys=True, ensure_ascii=False)
        if row["strategy"] == "describe":
            output.append(row)
            continue
        if key not in groups:
            groups[key] = row
            output.append(row)
            continue
        current = groups[key]
        current["sources"].extend(row["sources"])
        if row["strategy"] == "evasion":
            current["ratio"] = decimal_text(1 - (1 - number(current["ratio"])) * (1 - number(row["ratio"])))
        elif row["strategy"] == "vulnerability":
            current["ratio"] = decimal_text(number(current["ratio"]) + number(row["ratio"]))
    for row in output:
        if row["strategy"] == "numeric":
            row.update(_numeric_zones(row["sources"]))
        elif row["strategy"] == "vulnerability":
            row["factor"] = decimal_text(1 + number(row["ratio"]))
        row["metricLabel"] = METRIC_LABELS.get(row["metric"], row["metric"])
    return output


def _display_scope(row):
    scope = row.get("displayScope", {})
    labels = []
    for key in ("position", "profession", "subprofessions", "operatorSource", "faction",
                "enemyRank", "enemyId", "unitType", "selection", "flightState", "deploymentTile", "receiver"):
        if key in scope:
            labels.append(f"{SCOPE_LABELS[key]}：{_token(scope[key])}")
    if row["side"] == "bound_operator":
        labels = row.get("boundOperatorNames") or ["附魔受益干员"]
    text = "；".join(labels) or SIDE_LABELS.get(row["side"], row["side"])
    breadth = 0 if row["side"] in {"friendly_unit", "enemy", "battle", "operator"} else 1
    for key, rank in (("position", 10), ("enemyRank", 10), ("operatorSource", 15),
                      ("faction", 20), ("profession", 20), ("subprofessions", 30),
                      ("flightState", 30), ("deploymentTile", 30), ("receiver", 35),
                      ("unitType", 35), ("enemyId", 40), ("selection", 45), ("operatorInstanceIds", 50)):
        if key in scope:
            value = scope[key]
            count = len(value) if isinstance(value, list) else 1
            breadth = max(breadth, rank - min(max(count - 1, 0), 5))
    return text, breadth


def _view(clauses, operator=None, include_scoped=False):
    rows = _merge([row for clause in clauses if (row := _row(clause, operator, include_scoped)) is not None])
    priority = {"constant": 0, "conditional": 1, "unresolved": 2, "related": 3}
    rows.sort(key=lambda row: (priority[row["bucket"]], row["side"] == "enemy", row["domain"]))
    for row in rows:
        scope_label, breadth = _display_scope(row)
        row.update(valueText=_value_text(row), conditionText=_condition_text(row),
                   scopeLabel=scope_label, scopeBreadth=breadth,
                   sideLabel=SIDE_LABELS.get(row["side"], row["side"]),
                   domainLabel=DOMAIN_LABELS.get(row["domain"], row["domain"]),
                   tagText="；".join(f"{SCOPE_LABELS.get(key, key)}：{_token(value)}"
                                      for key, value in sorted(row["tags"].items())))
        for source in row["sources"]:
            source["scopeText"] = "；".join(f"{SCOPE_LABELS.get(key, key)}：{_token(value)}"
                                             for key, value in source["scope"].items())
            if source["operation"] in NUMERIC_OPERATIONS:
                source["valueText"] = _value_text({"strategy": "numeric", **_numeric_zones([source])})
    return {"operator": {key: operator.get(key) for key in ("instanceId", "name", "profession", "subprofession", "position", "inSquad")} if operator else None,
            "attributeSummary": _attribute_summary(rows, operator),
            "categories": [{"id": category, "name": name, "rows": [row for row in rows if row["category"] == category]}
                           for category, name in CATEGORY_LABELS.items()]}


def _attribute_summary(rows, operator):
    cells = []
    for metric in ("max_hp", "attack", "attack_speed"):
        for domain in DOMAIN_LABELS:
            sources, pending = {}, 0
            for row in rows:
                if row["metric"] != metric or row["domain"] != domain or row["side"] not in {"friendly_unit", "friendly_operator", "operator", "bound_operator"}:
                    continue
                for source in row["sources"]:
                    scope = source["scope"]
                    if row["tags"] or any(key not in IDENTITY_FIELDS for key in scope):
                        continue
                    if operator is None and any(key in IDENTITY_FIELDS for key in scope):
                        continue
                    # A resolved inventory snapshot is current, not a skill-time peak.
                    current = row["bucket"] == "constant" or source.get("resolvedFrom") == "snapshot_count"
                    if row["strategy"] != "numeric" or row["pending"]:
                        if row["pending"]:
                            pending += 1
                        continue
                    if not current:
                        continue
                    key = (source["clauseId"], source.get("acquisitionId"))
                    sources[key] = source
            values = _numeric_zones(sources.values())
            cells.append({"metric": metric, "domain": domain, **values,
                          "status": "partial" if pending else "known", "pendingCount": pending,
                          "sources": list(sources.values())})
    return cells


def describe_layer_environment(instance, difficulty, entries):
    """Display the recorded layer environment without applying its combat modifiers."""
    if not instance:
        return None
    dystopia = instance.get("dystopia") or {}
    utopia_id = instance.get("utopiaId") if "treehole" in instance.get("areaKey", "") else None
    entry_id = utopia_id or (dystopia.get("ideologyId") if dystopia.get("active") else None)
    if not entry_id and not dystopia.get("active"):
        return None
    entry = entries.get(entry_id, {})
    effect = entry.get("effect") or "本层理念待确认"
    config = layer_environments()
    configured = config["utopias" if utopia_id else "dystopias"].get(entry_id)
    tier_index = next(index for index in reversed(range(len(config["tierMinimumDifficulties"])))
                      if difficulty >= config["tierMinimumDifficulties"][index])
    if configured:
        effect = configured["tiers"][tier_index] if "tiers" in configured else configured["effect"]
    policy = entries.get(dystopia.get("policyId"), {}) if not utopia_id else {}
    return {"id": entry_id, "name": entry.get("name", "理念待确认").strip('“”'),
            "kind": "乌托邦" if utopia_id else "实托邦", "effect": effect,
            "tier": tier_index + 1 if configured and not utopia_id else None,
            "tierLabel": config["tierLabels"][tier_index] if configured and not utopia_id else None,
            "scope": "本树洞层生效" if utopia_id else "仅覆盖范围内生效",
            "policy": {"name": policy["name"], "effect": policy.get("effect", "")} if policy else None}


def summarize_combat_bonuses(state, *, context=None, operator_instance_id=None, definitions=None,
                             include_operator_views=True):
    """Calculate global and operator views without modifying any supplied state."""
    definitions = definitions or load_definitions()
    context = deepcopy(context or {})
    difficulty = state.get("opening", {}).get("difficulty", 15)
    if type(difficulty) is not int or difficulty < 0:
        raise ValueError("难度必须为非负整数")
    for field in ("enemyRegionCount", "componentCount", "airborneCount", "cash"):
        if field in context and (type(context[field]) is not int or context[field] < 0):
            raise ValueError(f"{field}必须为非负整数")
    if "dystopiaAffected" in context and context["dystopiaAffected"] is not None and type(context["dystopiaAffected"]) is not bool:
        raise ValueError("实托邦覆盖情况必须为布尔值")
    if "componentCount" not in context and "componentBox" in state:
        context["componentCount"] = len(state["componentBox"].get("items", []))
    if "cash" not in context and state.get("resources", {}).get("originiumIngot") is not None:
        context["cash"] = state["resources"]["originiumIngot"]
    operators = _operators(state)
    if operator_instance_id is not None and operator_instance_id not in {row["instanceId"] for row in operators}:
        raise ValueError("找不到指定干员实例")
    states, clauses, notices, acquisitions = {}, [], [], {}
    for raw in state.get("relics", []):
        relic_id = raw["id"]
        if relic_id in states:
            raise ValueError("持有藏品ID重复，不能重复叠加")
        if relic_id not in definitions:
            notices.append("藏品词条尚未定义：" + relic_id)
            continue
        states[relic_id] = _relic_state(raw, definitions[relic_id])
        acquisitions[relic_id] = raw.get("acquisitionId")
    effect_states = [(key, status, acquisitions[key], False) for key, status in states.items()]
    # Already granted operator buffs can outlive the held relic, without settling again.
    granted_seen = {}
    for raw in state.get("grantedEffects", []):
        relic_id = raw["relicId"]
        definition = definitions.get(relic_id)
        if not definition or not definition["management"].get("bindOperator"):
            raise ValueError("已授予效果必须来自可附魔的一次性藏品")
        granted = _relic_state({"value": True, "operatorInstanceIds": raw["operatorInstanceIds"]}, definition)
        acquisition = raw.get("acquisitionId")
        recipients = frozenset(granted["operatorInstanceIds"])
        identity = (relic_id, acquisition or recipients)
        if identity in granted_seen:
            if granted_seen[identity] != recipients:
                raise ValueError("同次获取的附魔记录存在不同受益者")
            continue
        granted_seen[identity] = recipients
        current = states.get(relic_id)
        same_acquisition = acquisition and acquisition == acquisitions.get(relic_id)
        same_legacy = not acquisition and not acquisitions.get(relic_id) and current and current["value"] is True and recipients == frozenset(current["operatorInstanceIds"])
        if same_acquisition or same_legacy:
            if current["value"] is not True or recipients != frozenset(current["operatorInstanceIds"]):
                raise ValueError("已授予效果与持有藏品的绑定记录冲突")
        else:
            effect_states.append((relic_id, granted, acquisition, True))
    for relic_id, status, acquisition, granted_only in effect_states:
        definition = definitions[relic_id]
        kind, expiry = definition["management"]["kind"], definition["management"].get("ineffectiveAt")
        if expiry is not None and status["value"] is not None and status["value"] >= expiry:
            continue
        if kind == "one_shot" and status["value"] is not True:
            notices.append(definition["name"] + "尚未使用，不计入已生效加成")
            continue
        for instance_id in status["operatorInstanceIds"]:
            recipient = next((row for row in operators if row["instanceId"] == instance_id), None)
            if recipient is None:
                notices.append(definition["name"] + "的受益干员已不在当前列表：" + instance_id)
            elif definition["management"].get("profession") and recipient.get("profession") != definition["management"]["profession"]:
                raise ValueError(definition["name"] + "与受益干员职业不匹配")
        for effect in definition["effects"]:
            if effect["category"] != "combat" or granted_only and effect["lifetime"] != "granted_operator_buff":
                continue
            clause = _resolve(effect, status, context, states, difficulty)
            if clause is not None:
                clause.update(sourceId=relic_id, sourceName=definition["name"], sourceType="relic",
                              operatorInstanceIds=status["operatorInstanceIds"], acquisitionId=acquisition,
                              boundOperatorNames=[row["name"] for row in operators if row["instanceId"] in status["operatorInstanceIds"]],
                              originalText=definition["source"].get("originalText")
                              or original_texts().get(definition["source"].get("prtsNumber")))
                clauses.append(clause)
    clauses.extend(_external(state, context, difficulty, notices))
    global_view = _view(clauses)
    global_view["detailCategories"] = _view(clauses, include_scoped=True)["categories"]
    return {"schemaVersion": 1, "difficulty": difficulty, "context": context,
            "global": global_view, "operators": [_view(clauses, operator) for operator in operators
                  if include_operator_views and (operator_instance_id is None or operator["instanceId"] == operator_instance_id)],
            "notices": notices, "assumptions": ["只汇总藏品、科技及已配置难度/环境；不含干员技能、天赋、模组或关卡普通/紧急额外强化",
                "条件项不等于常驻效果；百分比不取整，不据此判断战力够不够",
                constants()["specificEnemyModifiers"]]}


def _token(value):
    if isinstance(value, list):
        return "、".join(_token(item) for item in value)
    return TOKEN_LABELS.get(str(value), str(value))


def _condition_text(row):
    texts = []
    for condition in row["conditions"]:
        if "description" in condition:
            texts.append(condition["description"])
        elif "scope" in condition:
            texts.extend(f"{SCOPE_LABELS.get(key, key)}：{_token(value)}" for key, value in condition["scope"].items())
        else:
            texts.append(_condition_label(condition))
    texts.extend(row["pending"])
    texts.extend(f"{SCOPE_LABELS.get(key, key)}：{_token(value)}" for key, value in sorted(row["tags"].items()))
    return "；".join(texts) or "无额外条件"


def _condition_label(condition):
    for key, conjunction in (("any", "或"), ("all", "且")):
        if key in condition:
            return conjunction.join(_condition_label(item) for item in condition[key])
    field = {"enemy_status": "敌人状态", "touches_operator_link": "触碰干员连线",
             "active_skill_type": "当前技能类型"}.get(condition.get("field"), condition.get("field", "条件"))
    relation = {"eq": "为", "contains": "包含"}.get(condition.get("operator"), "：")
    value = condition.get("value")
    return field + relation + ("是" if value is True else "否" if value is False else _token(value))


def _value_text(row):
    if row["strategy"] == "numeric":
        parts = []
        if number(row["flatDelta"]):
            parts.append("固定增量" + ("+" if number(row["flatDelta"]) > 0 else "") + row["flatDelta"])
        if number(row["relativePercent"]) or not parts:
            percent = number(row["relativePercent"])
            parts.append(("+" if percent > 0 else "") + decimal_text(percent) + "%（×" + row["relativeFactor"] + "）")
        if number(row["flatDelta"]) and number(row["relativeFactor"]) != 1:
            delta = ("+" if number(row["flatDelta"]) > 0 else "") + row["flatDelta"]
            parts.append("（基础值" + delta + "）×" + row["relativeFactor"] + "；基础值未代入")
        return "；".join(parts)
    if row["strategy"] in {"evasion", "vulnerability"}:
        return decimal_text(number(row["ratio"]) * 100) + "%"
    rule = row.get("valueRule") or {}
    if rule.get("kind") == "battle_count":
        return "每个符合条件的单位+" + decimal_text(number(rule.get("perUnit", rule.get("perStack", 0))) * 100) + "%；当前单位数未确认"
    if row.get("description"):
        return row["description"]
    value = row["value"]
    if isinstance(value, dict) and value.get("description"):
        return value["description"]
    if rule:
        return rule.get("description") or row["sources"][0].get("originalText") or "条件数值，详见来源；不计常驻峰值"
    if isinstance(value, dict):
        return row["sources"][0].get("originalText") or json.dumps(value, ensure_ascii=False)
    if row["sources"][0]["operation"] == "factor":
        return "×" + decimal_text(value) + "（范围确认后生效）"
    if row["sources"][0]["operation"] in {"flat_delta", "base_ratio_delta"}:
        ratio = row["sources"][0]["operation"] == "base_ratio_delta"
        return ("+" if number(value) > 0 else "") + decimal_text(number(value) * (100 if ratio else 1)) + ("%" if ratio else "") + "（范围确认后生效）"
    return str(value)


def render_combat_bonuses(report):
    """Chinese Markdown presentation of the same structured calculation result."""
    lines = ["# 战斗加成汇总", "", "只展示当前加成，不计算胜率或战力门槛。", ""]
    context = report["context"]
    inputs = ["难度：N" + str(report["difficulty"])]
    for field, label in (("componentCount", "当前零件数量"), ("enemyRegionCount", "计入敌人难度的区域数量")):
        if field in context:
            inputs.append(label + "：" + str(context[field]))
    if context.get("dystopiaId"):
        name = constants().get("dystopias", {}).get(context["dystopiaId"], {}).get("name", context["dystopiaId"])
        coverage = "范围内战斗" if context.get("dystopiaAffected") is True else "范围外战斗" if context.get("dystopiaAffected") is False else "覆盖情况未确认"
        inputs.append("实托邦：" + name + "（" + coverage + "）")
    lines.extend(["；".join(inputs) + "。", ""])
    for view in [report["global"], *report["operators"]]:
        operator = view["operator"]
        lines.extend(["## " + (operator["name"] + "（" + (operator["profession"] or "职业未确认") + "）" if operator else "全局加成"), ""])
        for category in view.get("detailCategories", view["categories"]):
            if not category["rows"]:
                continue
            lines.extend(["### " + category["name"], "", "| 对象与指标 | 域 | 类型 | 加成 | 条件 | 来源 |",
                          "| --- | --- | --- | --- | --- | --- |"])
            for row in category["rows"]:
                sources = "、".join(dict.fromkeys(source["name"] for source in row["sources"]))
                bucket = {"constant": "常驻", "conditional": "条件项", "unresolved": "待确认", "related": "关联单位"}[row["bucket"]]
                cells = [row["scopeLabel"] + "：" + row["metricLabel"], DOMAIN_LABELS[row["domain"]],
                         bucket, _value_text(row), _condition_text(row), sources]
                lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
            lines.append("")
    if report["notices"]:
        lines.extend(["## 状态提示", "", *["- " + text for text in report["notices"]], ""])
    lines.extend(["## 计算边界", "", *["- " + text for text in report["assumptions"]], ""])
    return "\n".join(lines)
