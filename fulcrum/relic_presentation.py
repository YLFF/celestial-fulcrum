"""Display metadata and confirmed single-operator relic assignments."""

from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def presentation():
    return json.loads((ROOT / "data/relic_presentation.json").read_text(encoding="utf-8"))


def display_metadata(entry):
    config = presentation()
    item_id = entry["id"]
    overrides = config["orderOverrides"]
    return {"displayCategory": config["categoryOverrides"].get(item_id, "未分类"),
            "displayOrder": overrides.index(item_id) if item_id in overrides else len(overrides),
            "enchantmentProfession": config["enchantments"].get(item_id, {}).get("profession")}


def relic_active(row):
    return row.get("state") in ("active", "已生效") or row.get("enchantment") is not None


def validate_binding(row):
    binding = row.get("enchantment")
    if binding is None:
        return
    profession = presentation()["enchantments"].get(row["id"], {}).get("profession")
    if not profession or not isinstance(binding, dict) or set(binding) != {"operatorInstanceId", "operatorName", "profession"}:
        raise ValueError("附魔记录格式不正确或该藏品不支持附魔")
    if not all(isinstance(value, str) and value.strip() for value in binding.values()) or binding["profession"] != profession:
        raise ValueError("附魔记录的职业或受益干员不正确")
    if row.get("state") not in ("active", "已生效"):
        raise ValueError("已附魔藏品必须保持已生效状态")


def enchant_relic(state, relic_id, operator_id):
    profession = presentation()["enchantments"].get(relic_id, {}).get("profession")
    relic = next((row for row in state["relics"] if row["id"] == relic_id), None)
    operator = next((row for row in state["operators"] if row["instanceId"] == operator_id), None)
    if not profession or relic is None:
        raise ValueError("请先持有可附魔的“新典训”藏品")
    if relic_active(relic):
        raise ValueError("该藏品已生效，不能再次附魔")
    if operator is None or operator.get("profession") != profession:
        raise ValueError(f"该藏品只能附魔给当前干员列表中的{profession}干员")
    if operator.get("elite") not in (1, 2) or (operator.get("rarity") or 0) < 4:
        raise ValueError("请选择可进阶或已经进阶的干员")
    relic["state"] = "active"
    relic["enchantment"] = {"operatorInstanceId": operator_id, "operatorName": operator["name"], "profession": profession}


def preserve_bindings(old_rows, new_rows):
    """Inventory edits cannot silently reset a used enchantment."""
    old = {row["id"]: row for row in old_rows}
    rows = deepcopy(new_rows)
    for row in rows:
        previous = old.get(row["id"], {})
        if row.get("enchantment") != previous.get("enchantment"):
            raise ValueError("请通过附魔操作绑定干员；已使用的附魔不能重新绑定")
        if row["id"] in presentation()["enchantments"] and relic_active(previous) and not relic_active(row):
            raise ValueError("已生效的附魔藏品不能改回未生效")
        if previous.get("enchantment"):
            row["state"] = "active"
    return rows
