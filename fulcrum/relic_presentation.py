"""Relic management, display metadata and confirmed operator assignments."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def presentation():
    return json.loads((ROOT / "data/relic_presentation.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def effect_metadata():
    from .relic_effects import load_definitions
    definitions = load_definitions()
    policy = json.loads((ROOT / "data/relic_effects/management.json").read_text(encoding="utf-8"))
    result = {}
    for relic_id, definition in definitions.items():
        management = deepcopy(definition["management"])
        if relic_id in policy["oneShotOperatorRelics"]:
            management.update(kind="one_shot", bindOperator=True,
                maxRecipients=policy["recipientOverrides"].get(relic_id, policy["defaultMaxRecipients"]),
                promotionEffect=relic_id in policy["promotionEffectRelics"],
                autoPromote=relic_id in policy["promotionEffectRelics"])
        snapshot = next((effect["valueRule"] for effect in definition["effects"]
                         if effect.get("valueRule", {}).get("kind") == "snapshot_count"
                         and effect["valueRule"].get("field") in {"cash", "componentCount"}), None)
        automatic = "snapshot" if snapshot else management.get("counter") if management.get("counter") in {
            "entered_map_layers", "entered_regions"} else None
        result[relic_id] = {"management": management, "automaticCounter": automatic,
                            "snapshotCounter": snapshot}
    return result


def display_metadata(entry):
    config = presentation()
    item_id = entry["id"]
    overrides = config["orderOverrides"]
    metadata = effect_metadata().get(item_id, {})
    return {"displayCategory": config["categoryOverrides"].get(item_id, "未分类"),
            "displayOrder": overrides.index(item_id) if item_id in overrides else len(overrides),
            **metadata,
            "enchantmentProfession": metadata.get("management", {}).get("profession")}


def binding_recipients(row):
    binding = row.get("enchantment")
    if not binding:
        return []
    return binding.get("recipients", [binding] if "operatorInstanceId" in binding else [])


def runtime_status(state, row):
    metadata = effect_metadata().get(row["id"], {})
    management = metadata.get("management", {})
    automatic = metadata.get("automaticCounter")
    value = row.get("state")
    if automatic == "snapshot":
        rule = metadata["snapshotCounter"]
        count = (len(state.get("componentBox", {}).get("items", [])) if rule["field"] == "componentCount"
                 else state.get("resources", {}).get("originiumIngot"))
        value = count // rule.get("unitSize", 1) if count is not None else None
    elif automatic in {"entered_map_layers", "entered_regions"}:
        from .playtime_state import AREA_SPECS
        current = state.get("currentAreaKey")
        floor = AREA_SPECS.get(current, (None, None))[1]
        visited = {key for key, slot in state.get("areas", {}).items()
                   if floor is not None and slot.get("activeInstanceId") and AREA_SPECS.get(key, (None, 99))[1] <= floor}
        visited.add(current)
        caves = sum(key is not None and key.endswith("-treehole") for key in visited)
        value = floor + (min(1, caves) if automatic == "entered_regions" else caves + int("IV-remembrance" in visited)) if floor is not None else None
    elif management.get("kind") == "one_shot":
        value = relic_active(row)
    elif management.get("kind") == "ordinary":
        value = None
    expiry = management.get("ineffectiveAt")
    return {"value": value, "automatic": bool(automatic) or bool(management.get("bindOperator")),
            "expired": expiry is not None and value is not None and value >= expiry}


def relic_active(row):
    return row.get("state") is True or row.get("state") in ("active", "已生效") or row.get("enchantment") is not None


def validate_binding(row):
    binding = row.get("enchantment")
    if binding is None:
        return
    management = effect_metadata().get(row["id"], {}).get("management", {})
    if not management.get("bindOperator") or not isinstance(binding, dict):
        raise ValueError("附魔记录格式不正确或该藏品不支持附魔")
    recipients = binding_recipients(row)
    if (set(binding) not in ({"operatorInstanceId", "operatorName", "profession"}, {"recipients"})
            or not isinstance(recipients, list) or not 1 <= len(recipients) <= management.get("maxRecipients", 1)
            or any(not isinstance(item, dict) or set(item) != {"operatorInstanceId", "operatorName", "profession"}
                   or not all(isinstance(value, str) and value.strip() for value in item.values())
                   or management.get("profession") and item["profession"] != management["profession"] for item in recipients)):
        raise ValueError("附魔记录的职业或受益干员不正确")
    if len({item["operatorInstanceId"] for item in recipients}) != len(recipients):
        raise ValueError("不能重复绑定同一干员")
    if row.get("state") not in ("active", "已生效"):
        raise ValueError("已附魔藏品必须保持已生效状态")


def enchant_relic(state, relic_id, operator_ids):
    management = effect_metadata().get(relic_id, {}).get("management", {})
    profession = management.get("profession")
    relic = next((row for row in state["relics"] if row["id"] == relic_id), None)
    if not management.get("bindOperator") or relic is None:
        raise ValueError("请先持有可绑定干员的一次性藏品")
    if relic_active(relic):
        raise ValueError("该藏品已生效，不能再次附魔")
    ids = [operator_ids] if isinstance(operator_ids, str) else operator_ids
    if (not isinstance(ids, list) or not 1 <= len(ids) <= management.get("maxRecipients", 1)
            or any(not isinstance(item, str) or not item for item in ids) or len(set(ids)) != len(ids)):
        raise ValueError("受益干员人数不正确或重复")
    recipients, promotions, identities = [], [], []
    for operator_id in ids:
        operator = next((row for row in state["operators"] if row["instanceId"] == operator_id), None)
        if operator is None:
            raise ValueError(f"请选择当前干员列表中的{profession or ''}干员")
        from .operator_catalog import find_operator
        entry = find_operator(operator.get("operatorId")) or find_operator(operator["name"])
        identity = {field: entry[field] for field in ("profession", "rarity")
                    if entry and operator.get(field) is None and not entry.get(f"{field}Editable")}
        resolved = {**operator, **identity}
        if profession and resolved.get("profession") != profession:
            raise ValueError(f"请选择当前干员列表中的{profession or ''}干员")
        if management.get("promotionEffect"):
            if (operator.get("elite") not in (1, 2) or (resolved.get("rarity") or 0) < 4
                    or operator.get("remainingBattles") is not None):
                raise ValueError("请选择可进阶或已经进阶的非应急助力干员")
            if operator["elite"] == 1:
                promotions.append(operator_id)
        identities.append((operator, identity))
        recipients.append({"operatorInstanceId": operator_id, "operatorName": operator["name"],
                           "profession": resolved.get("profession") or "未确认"})
    for operator, identity in identities:
        operator.update(identity)
    for operator_id in promotions:
        from .operators import promote_operator
        promote_operator(state, operator_id, hope_cost=0)
    relic = next(row for row in state["relics"] if row["id"] == relic_id)
    relic["state"] = "active"
    relic["enchantment"] = recipients[0] if len(recipients) == 1 else {"recipients": recipients}


def preserve_bindings(old_rows, new_rows):
    """Inventory edits cannot silently reset a used enchantment."""
    old = {row["id"]: row for row in old_rows}
    rows = deepcopy(new_rows)
    for row in rows:
        previous = old.get(row["id"], {})
        if row.get("enchantment") != previous.get("enchantment"):
            raise ValueError("请通过附魔操作绑定干员；已使用的附魔不能重新绑定")
        management = effect_metadata().get(row["id"], {}).get("management", {})
        if management.get("bindOperator") and relic_active(previous) and not relic_active(row):
            raise ValueError("已生效的附魔藏品不能改回未生效")
        if previous.get("enchantment"):
            row["state"] = "active"
        elif management.get("kind") == "ordinary":
            row["state"] = None
    return rows
