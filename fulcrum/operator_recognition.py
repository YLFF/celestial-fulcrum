"""Reviewed screenshot synchronization, without acquisition costs or rewards."""

from copy import deepcopy

from .operator_catalog import find_operator
from .operators import add_operator
from .playtime_state import rebuild_derived


def operator_changes(result, state):
    changes = []
    for slot in result.get("slots", []):
        if not slot.get("operatorId"):
            continue
        matches = [row for row in state["operators"] if row.get("operatorId") == slot["operatorId"] or row["name"] == slot["name"]]
        permanent = [row for row in matches if not row.get("remainingBattles")]
        targets = permanent or matches
        target = targets[0] if len(targets) == 1 else None
        same_stage = target is not None and target.get("elite") is not None and (target["elite"] == 2) == (slot["elite"] == 2)
        kind = "ambiguous" if len(targets) > 1 else "add" if target is None else (
            "unchanged" if same_stage else "promote" if slot["elite"] == 2 else "downgrade" if target.get("elite") == 2 else "update")
        changes.append({**slot, "change": kind, "instanceId": target["instanceId"] if target else None,
                        "previousElite": target.get("elite") if target else None,
                        "selected": slot["status"] == "accepted" and kind in {"add", "promote", "update"},
                        "targets": [{"instanceId": row["instanceId"], "source": row.get("source"), "elite": row.get("elite")} for row in targets]})
    return changes


def apply_operator_choices(state, result, choices):
    by_slot = {row["slot"]: row for row in operator_changes(result, state)}
    draft = deepcopy(state)
    seen, names = set(), set()
    for choice in choices:
        slot = by_slot.get(choice["slot"])
        if not slot or not find_operator(slot["operatorId"]):
            raise ValueError("所选干员不在本次识别候选中")
        if choice["slot"] in seen or slot["name"] in names:
            raise ValueError("同一干员不能重复确认")
        seen.add(choice["slot"])
        names.add(slot["name"])
        target_id = choice.get("instanceId") or slot["instanceId"]
        if slot["targets"]:
            if target_id not in {row["instanceId"] for row in slot["targets"]}:
                raise ValueError("请选择本次候选对应的干员记录")
            target = next(row for row in draft["operators"] if row["instanceId"] == target_id)
            # A black/obscured badge must never silently downgrade an existing operator.
            if slot["elite"] != 2 and target.get("elite") == 2:
                raise ValueError("截图与已进阶状态冲突，请在干员编辑页面手动核对")
            if slot["change"] != "unchanged":
                target["elite"] = slot["elite"]
        else:
            if target_id:
                raise ValueError("新增干员不能指定其他干员记录")
            add_operator(draft, slot["name"], elite=slot["elite"], record_only=True, settle_rewards=False)
    rebuild_derived(draft)
    state.clear()
    state.update(draft)
