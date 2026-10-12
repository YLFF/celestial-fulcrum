"""Confirmed effect definitions, independent of acquisition scoring and settlement."""

from copy import deepcopy
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path


DEFINITIONS_PATH = Path(__file__).resolve().parents[1] / "data/relic_effects/calibration_10.json"
RULES_PATH = DEFINITIONS_PATH.parent / "numeric_rules.json"
CATEGORIES = {"immediate_resource", "development", "combat"}
COMBAT_CATEGORIES = {"cost", "skill_cycle", "survival", "damage", "control", "support", "mechanism"}


def management_for(relic_id):
    """Return confirmed policy; unknown management is not silently ordinary."""
    path = DEFINITIONS_PATH.parent / "management.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    if relic_id in policy["oneShotOperatorRelics"]:
        return {"kind": "one_shot", "bindOperator": True,
                "maxRecipients": policy["recipientOverrides"].get(relic_id, policy["defaultMaxRecipients"]),
                "promotionEffect": relic_id in policy["promotionEffectRelics"], "autoPromote": False}
    if relic_id in policy["oneShotOtherRelics"]:
        return {"kind": "one_shot", "bindOperator": False}
    if relic_id in policy["confirmedStacking"]:
        return {"kind": "stacking", "bindOperator": False, **policy["confirmedStacking"][relic_id]}
    definition = load_definitions().get(relic_id)
    return definition["management"] if definition else None


def validate_definition(definition):
    management = definition["management"]
    if management["kind"] not in {"ordinary", "one_shot", "stacking"}:
        raise ValueError("藏品维护类型不正确")
    if type(definition["endingRelic"]) is not bool:
        raise ValueError("结局藏品标记必须为布尔值")
    ids = set()
    for clause in definition["effects"]:
        if clause["id"] in ids:
            raise ValueError("词条 ID 重复")
        ids.add(clause["id"])
        if clause["category"] not in CATEGORIES:
            raise ValueError("词条效果类别不正确")
        if clause["category"] == "combat" and clause["combatCategory"] not in COMBAT_CATEGORIES:
            raise ValueError("战斗词条类别不正确")
        if clause["domain"] not in {"outside_battle", "inside_battle", "not_applicable"}:
            raise ValueError("计算域不正确")
        if clause["operation"] not in {"flat_delta", "base_ratio_delta", "factor", "grant", "mechanism"}:
            raise ValueError("词条运算不正确")
        if clause["operation"] in {"flat_delta", "base_ratio_delta", "factor"}:
            value = clause["value"]
            if not isinstance(value, (int, float, str)) or isinstance(value, bool) or not Decimal(str(value)).is_finite():
                raise ValueError("数值词条需要有限数值")
            if clause["operation"] == "factor" and Decimal(str(value)) < 0:
                raise ValueError("乘算因子不能为负数")
            if not clause.get("stackingGroup"):
                raise ValueError("数值词条需要乘区标识")
        for field in ("target", "conditions", "trigger", "lifetime", "reviewStatus"):
            if field not in clause:
                raise ValueError(f"词条缺少字段：{field}")


def load_definitions(path=None):
    paths = [Path(path)] if path is not None else [
        DEFINITIONS_PATH.parent / item["file"] for item in
        json.loads((DEFINITIONS_PATH.parent / "catalog.json").read_text(encoding="utf-8"))["batches"]]
    result = {}
    for batch_path in paths:
        data = json.loads(batch_path.read_text(encoding="utf-8"))
        if data["schemaVersion"] != 1:
            raise ValueError("藏品词条版本不支持")
        for definition in data["relics"]:
            validate_definition(definition)
            if definition["id"] in result:
                raise ValueError("藏品 ID 重复")
            result[definition["id"]] = definition
    return result


def validate_runtime_state(definition, state):
    """Validate the new state separately; do not migrate legacy runs implicitly."""
    kind = definition["management"]["kind"]
    value = state["value"]
    valid = (kind == "ordinary" and value is None
             or kind == "one_shot" and type(value) is bool
             or kind == "stacking" and type(value) is int and value >= 0)
    if not valid:
        raise ValueError("普通/一次性/层数藏品状态应分别为 null/bool/非负整数")
    bindings = state.get("operatorInstanceIds", [])
    if not isinstance(bindings, list) or any(not isinstance(item, str) or not item.strip() for item in bindings):
        raise ValueError("受益干员需要实例 ID 列表")
    if len(bindings) != len(set(bindings)):
        raise ValueError("同一藏品不能重复绑定同一干员")
    if bindings and (kind != "one_shot" or not definition["management"].get("bindOperator")
                     or value is not True or len(bindings) > definition["management"].get("maxRecipients", 1)):
        raise ValueError("干员绑定需要可绑定且已使用的一次性藏品")


def clause_enabled(definition, clause, state):
    validate_runtime_state(definition, state)
    if definition["management"]["kind"] == "stacking":
        expiry = definition["management"].get("ineffectiveAt")
        if expiry is not None and state["value"] >= expiry:
            return False
    if definition["management"]["kind"] != "one_shot":
        return True
    if clause["lifetime"] == "granted_operator_buff":
        return state["value"] is True and bool(state.get("operatorInstanceIds"))
    return state["value"] is False


def evaluate_numeric(base, *, flat_deltas=(), base_ratio_deltas=(), factors=()):
    """Apply additive terms, independent factors, then floor the result once."""
    convert = lambda value: Decimal(str(value))
    result = convert(base)
    result += sum((convert(value) for value in flat_deltas), Decimal(0))
    result *= 1 + sum((convert(value) for value in base_ratio_deltas), Decimal(0))
    for factor in factors:
        result *= convert(factor)
    if not result.is_finite():
        raise ValueError("计算结果必须为有限数值")
    return int(result.to_integral_value(rounding=ROUND_FLOOR))


def summarize_numeric(clauses):
    """Keep different targets, conditions and domains distinct, without rounding buffs."""
    groups = {}
    separate = []
    for clause in clauses:
        if clause["operation"] not in {"flat_delta", "base_ratio_delta", "factor"}:
            continue
        if clause.get("aggregation") == "separate" or clause.get("valueRule"):
            separate.append({**deepcopy(clause), "aggregation": "separate", "sources": [clause["id"]]})
            continue
        key = json.dumps({field: clause[field] for field in
                          ("domain", "target", "conditions", "trigger", "lifetime", "stackingGroup")},
                         sort_keys=True, ensure_ascii=False)
        row = groups.setdefault(key, {"domain": clause["domain"], "target": clause["target"],
                                     "conditions": clause["conditions"], "trigger": clause["trigger"],
                                     "lifetime": clause["lifetime"], "stackingGroup": clause["stackingGroup"],
                                     "flatDelta": Decimal(0), "baseRatioDelta": Decimal(0),
                                     "factor": Decimal(1), "sources": []})
        field = {"flat_delta": "flatDelta", "base_ratio_delta": "baseRatioDelta", "factor": "factor"}[clause["operation"]]
        value = Decimal(str(clause["value"]))
        row[field] = row[field] * value if field == "factor" else row[field] + value
        row["sources"].append(clause["id"])
    return [{key: str(value) if isinstance(value, Decimal) else value for key, value in row.items()}
            for row in groups.values()] + separate


def structural_stage(difficulty):
    if type(difficulty) is not int or difficulty < 0:
        raise ValueError("难度必须为非负整数")
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    for tier in rules["structuralStages"]:
        if tier["maximumDifficulty"] is None or difficulty <= tier["maximumDifficulty"]:
            return tier["stage"]
    raise ValueError("未配置该难度的多元奇物效果")


def deployment_capacity(base, upgrade_delta, held_definitions):
    """No permanent ledger for held deployment-slot bonuses; do not clamp to 13."""
    if any(type(value) is not int or value < 0 for value in (base, upgrade_delta)):
        raise ValueError("初始部署位与升级增量必须为非负整数")
    result = base + upgrade_delta
    for definition in held_definitions:
        for clause in definition["effects"]:
            if clause["target"]["metric"] != "deployment_capacity":
                continue
            if (clause["category"] != "development" or clause["operation"] != "flat_delta"
                    or clause["conditions"] or type(clause["value"]) is not int):
                raise ValueError("条件型部署位词条需要另行校准，不能当作常驻整数增量")
            result += clause["value"]
    return result
