"""Confirmed recruitment, promotion and one-battle support in the shared roster."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .component_box import acquire_component, new_component_box, set_capacity, validate_component_box


SOURCE_LABELS = {
    "normal": "普通招募", "temporary": "临时招募",
    "assistance": "临时助力", "emergency": "应急助力雇佣",
}
SUPPORT_SOURCES = {"assistance", "emergency"}
PERMANENT_SOURCES = {"normal", "temporary", "squad_002-temporary"}


def validate_operator_pool(operators: list[dict[str, Any]]) -> None:
    if not isinstance(operators, list):
        raise ValueError("invalid operator list")
    ids = set()
    for operator in operators:
        if not isinstance(operator, dict):
            raise ValueError("invalid operator record")
        instance_id = operator.get("instanceId")
        if not isinstance(instance_id, str) or not instance_id or instance_id in ids:
            raise ValueError("operator instance IDs must be distinct nonempty strings")
        ids.add(instance_id)
        if not isinstance(operator.get("name"), str) or not operator["name"].strip():
            raise ValueError("operator name is required")
        elite = operator.get("elite")
        if elite is not None and (type(elite) is not int or elite not in (0, 1, 2)):
            raise ValueError("invalid operator elite stage")
        rarity = operator.get("rarity")
        if rarity is not None and (type(rarity) is not int or not 1 <= rarity <= 6):
            raise ValueError("operator rarity must be 1..6 or null")
        for field in ("source", "profession"):
            value = operator.get(field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"invalid operator {field}")
        if "initialRecruitment" in operator and type(operator["initialRecruitment"]) is not bool:
            raise ValueError("initialRecruitment must be boolean")
        remaining = operator.get("remainingBattles")
        if remaining is not None and (type(remaining) is not int or remaining < 1):
            raise ValueError("remainingBattles must be a positive integer or null")
        if operator.get("source") in SUPPORT_SOURCES and remaining is None:
            raise ValueError("support operators require remainingBattles")


def _draft(state: dict[str, Any]) -> dict[str, Any]:
    draft = {"operators": deepcopy(state.get("operators", [])),
             "resources": deepcopy(state.get("resources", {})),
             "componentBox": deepcopy(state.get("componentBox", new_component_box()))}
    validate_operator_pool(draft["operators"])
    validate_component_box(draft["componentBox"])
    return draft


def _pay(draft: dict[str, Any], field: str, cost: int) -> None:
    if type(cost) is not int or cost < 0:
        raise ValueError("recruitment costs must be nonnegative integers")
    if not cost:
        return
    available = draft["resources"].get(field)
    if type(available) is not int or available < cost:
        raise ValueError(f"insufficient or unknown {field}")
    draft["resources"][field] -= cost


def mechanist_hope_cost(state: dict[str, Any], *, initial: bool = False, promotion: bool = False) -> int:
    difficulty = state.get("opening", {}).get("difficulty")
    if type(difficulty) is not int or difficulty < 15:
        raise ValueError("provide a confirmed hope cost outside the N15+ full-mastery preset")
    return 1 if promotion else (2 if initial else 3)


def add_operator(
    state: dict[str, Any], name: str, *, source: str = "normal", elite: int = 1,
    profession: str | None = None, rarity: int | None = None,
    instance_id: str | None = None, initial: bool = False,
    hope_cost: int | None = None, ingot_cost: int = 0, record_only: bool = False,
    settle_rewards: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(source, str) or source not in SOURCE_LABELS or type(initial) is not bool:
        raise ValueError("invalid recruitment source or initial flag")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("operator name is required")
    from .operator_catalog import find_operator
    entry = find_operator(name)
    if entry:
        profession = profession if entry.get("professionEditable") else entry["profession"]
        rarity = rarity if entry.get("rarityEditable") and rarity is not None else entry["rarity"]
        entry = {**entry, "profession": profession, "rarity": rarity}
    if instance_id is not None and (not isinstance(instance_id, str) or not instance_id):
        raise ValueError("operator instance ID must be a nonempty string")
    if type(record_only) is not bool or (record_only and (hope_cost not in (None, 0) or ingot_cost != 0)):
        raise ValueError("record-only updates cannot settle costs")
    if settle_rewards is not None and type(settle_rewards) is not bool:
        raise ValueError("settle_rewards must be boolean or null")
    draft = _draft(state)
    existing_ids = {row["instanceId"] for row in draft["operators"]}
    # Departed operators may still own a saved enchantment or granted effect.
    from .relic_presentation import binding_recipients
    reserved_ids = existing_ids | set(state.get("squad", []))
    for relic in state.get("relics", []):
        reserved_ids.update(row["operatorInstanceId"] for row in binding_recipients(relic))
    for grant in state.get("grantedEffects", []):
        reserved_ids.update(grant["operatorInstanceIds"])
    if instance_id is None:
        number = 1
        while f"operator-{number}" in reserved_ids:
            number += 1
        instance_id = f"operator-{number}"
    if instance_id in reserved_ids:
        raise ValueError(f"operator instance already exists or has saved references: {instance_id}")
    matching = [row for row in draft["operators"] if row["name"] == name]
    repeatable = bool(entry and entry.get("repeatable"))
    if not repeatable and any(row.get("remainingBattles") is None for row in matching):
        raise ValueError("operator already recruited; use promotion instead")
    if not repeatable and matching and source in SUPPORT_SOURCES:
        raise ValueError("support operator already present")
    # A permanent recruit replaces a same-name one-battle support, not a second copy.
    if not repeatable:
        draft["operators"] = [row for row in draft["operators"] if row["name"] != name]
    operator = {
        "instanceId": instance_id, "name": name, "profession": profession,
        "elite": elite, "source": source, "initialRecruitment": initial,
        "remainingBattles": 1 if source in SUPPORT_SOURCES else None,
    }
    if rarity is not None:
        operator["rarity"] = rarity
    if entry:
        operator["operatorId"] = entry["id"]
    draft["operators"].append(operator)
    validate_operator_pool(draft["operators"])
    if hope_cost is None:
        if entry and not record_only:
            from .recruitment import hope_price
            opening = state.get("opening", {})
            hope_cost = hope_price(entry, squad_id=opening.get("squadId"), difficulty=opening.get("difficulty", 15), initial=initial, source=source)
        else:
            hope_cost = mechanist_hope_cost(state, initial=initial) if name == "机械师" and source == "normal" and not record_only else 0
    _pay(draft, "hope", hope_cost)
    _pay(draft, "originiumIngot", ingot_cost)
    if name == "机械师" and source in PERMANENT_SOURCES and (settle_rewards if settle_rewards is not None else not record_only):
        set_capacity(draft["componentBox"], draft["componentBox"]["capacity"] + 2)
        if elite == 2:
            acquire_component(draft["componentBox"], "component_023")
    state.update(draft)
    return operator


def promote_operator(
    state: dict[str, Any], instance_id: str, *, hope_cost: int | None = None, record_only: bool = False,
    settle_rewards: bool | None = None,
) -> dict[str, Any]:
    if type(record_only) is not bool or (record_only and hope_cost not in (None, 0)):
        raise ValueError("record-only updates cannot settle costs")
    if settle_rewards is not None and type(settle_rewards) is not bool:
        raise ValueError("settle_rewards must be boolean or null")
    draft = _draft(state)
    operator = next((row for row in draft["operators"] if row["instanceId"] == instance_id), None)
    if operator is None:
        raise ValueError(f"unknown operator instance {instance_id}")
    if operator.get("remainingBattles") is not None:
        raise ValueError("one-battle support cannot be promoted")
    if operator.get("elite") == 2:
        return next(row for row in state["operators"] if row["instanceId"] == instance_id)
    if operator.get("elite") != 1:
        raise ValueError("confirm elite 1 before promotion")
    if hope_cost is None:
        from .operator_catalog import find_operator
        from .recruitment import hope_price
        entry = find_operator(operator["name"])
        if entry and entry.get("professionEditable"):
            entry = {**entry, "profession": operator.get("profession")}
        if entry and entry.get("rarityEditable"):
            entry = {**entry, "rarity": operator.get("rarity")}
        opening = state.get("opening", {})
        hope_cost = hope_price(entry, squad_id=opening.get("squadId"), promotion=True, source=operator.get("source")) if entry and not record_only else 0
    _pay(draft, "hope", hope_cost)
    operator["elite"] = 2
    if operator["name"] == "机械师" and operator.get("source") in PERMANENT_SOURCES and (settle_rewards if settle_rewards is not None else not record_only):
        acquire_component(draft["componentBox"], "component_023")
    state.update(draft)
    return operator


def remove_operator(state: dict[str, Any], instance_id: str) -> None:
    draft = _draft(state)
    if not any(row["instanceId"] == instance_id for row in draft["operators"]):
        raise ValueError(f"unknown operator instance {instance_id}")
    draft["operators"] = [row for row in draft["operators"] if row["instanceId"] != instance_id]
    state.update(draft)


def complete_operator_battle(state: dict[str, Any], deployed_ids: list[str]) -> list[str]:
    draft = _draft(state)
    if not isinstance(deployed_ids, list) or any(not isinstance(value, str) for value in deployed_ids):
        raise ValueError("provide the actually deployed operator instance IDs")
    known_ids = {row["instanceId"] for row in draft["operators"]}
    if len(deployed_ids) != len(set(deployed_ids)) or not set(deployed_ids) <= known_ids:
        raise ValueError("duplicate or unknown deployed operator instance")
    removed = []
    for operator in draft["operators"]:
        remaining = operator.get("remainingBattles")
        if operator["instanceId"] in deployed_ids and remaining is not None:
            operator["remainingBattles"] -= 1
            if operator["remainingBattles"] == 0:
                removed.append(operator["instanceId"])
    draft["operators"] = [row for row in draft["operators"] if row["instanceId"] not in removed]
    validate_operator_pool(draft["operators"])
    state.update(draft)
    return removed
