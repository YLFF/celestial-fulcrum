"""Structured component-box instances for a single Playtime run."""

from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
INITIAL_USES = {
    "component_013": 1, "component_014": 1, "component_015": 3,
    "component_016": 1, "component_017": 2, "component_018": 2,
    "component_019": 1, "component_020": 1, "component_021": 1,
    "component_022": 2, "component_023": 3, "component_024": 1,
}
INITIAL_VALUES = {f"component_{index:03d}": value for index, value in enumerate((2, 2, 2, 4, 3, 6, 5, 2, 8, 32, 32, 16), 1)}
INITIAL_VALUES.update({f"component_{index:03d}": 1 for index in range(13, 31)})
APPRAISAL_EVENTS = {
    "recruit": {"component_004": 3},
    "battle": {"component_002": 2, "component_006": 4},
    "acquire": {"component_007": 1, "component_009": 4},
    "soilMove": {f"component_{index:03d}": 2 for index in range(1, 13)},
}


@lru_cache(maxsize=1)
def catalog() -> dict[str, dict[str, Any]]:
    entries = json.loads((ROOT / "data" / "lubiao_reference_catalog.json").read_text(encoding="utf-8"))["entries"]
    return {entry["id"]: entry for entry in entries if entry["category"] == "component"}


def component_kind(component_id: str) -> str:
    if component_id not in catalog():
        raise ValueError(f"unknown component {component_id}")
    number = int(component_id.split("_")[1])
    return "加工品" if 13 <= number <= 24 else ("自然物" if number <= 12 else "概念体")


def new_component_box() -> dict[str, Any]:
    return {"capacity": 8, "items": []}


def validate_component_box(box: dict[str, Any]) -> None:
    capacity = box.get("capacity")
    items = box.get("items")
    if type(capacity) is not int or capacity < 0 or not isinstance(items, list):
        raise ValueError("invalid component-box capacity or contents")
    ids = set()
    for item in items:
        instance_id = item.get("instanceId")
        component_id = item.get("componentId")
        if not isinstance(instance_id, str) or not instance_id or instance_id in ids:
            raise ValueError("component instance IDs must be distinct nonempty strings")
        ids.add(instance_id)
        kind = component_kind(component_id)
        value, uses = item.get("estimatedValue"), item.get("remainingUses")
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("estimated value must be a nonnegative integer or null")
        if kind == "加工品":
            if type(uses) is not int or not 0 <= uses <= INITIAL_USES[component_id]:
                raise ValueError("invalid processing-item remaining uses")
        elif uses is not None:
            raise ValueError("only processing items have remaining uses")
        if type(item.get("routeCandidate")) is not bool:
            raise ValueError("routeCandidate must be boolean")


def add_component(
    box: dict[str, Any], component_id: str, *, instance_id: str | None = None,
    estimated_value: int | None = None, remaining_uses: int | None = None,
    route_candidate: bool = True,
) -> dict[str, Any]:
    kind = component_kind(component_id)
    if kind != "加工品" and remaining_uses is not None:
        raise ValueError("only processing items have remaining uses")
    existing = {item["instanceId"] for item in box["items"]}
    if instance_id is None:
        number = 1
        while f"part-{number}" in existing:
            number += 1
        instance_id = f"part-{number}"
    item = {
        "instanceId": instance_id,
        "componentId": component_id,
        "estimatedValue": estimated_value,
        "remainingUses": remaining_uses if kind == "加工品" else None,
        "routeCandidate": route_candidate if kind == "加工品" else False,
    }
    if kind == "加工品" and remaining_uses is None:
        item["remainingUses"] = INITIAL_USES[component_id]
    proposed = {**box, "items": [*box["items"], item]}
    validate_component_box(proposed)
    box["items"].append(item)
    return item


def update_component(box: dict[str, Any], instance_id: str, **changes: Any) -> dict[str, Any]:
    if not changes or not set(changes) <= {"estimatedValue", "remainingUses", "routeCandidate"}:
        raise ValueError("unsupported component update")
    item = next((item for item in box["items"] if item["instanceId"] == instance_id), None)
    if item is None:
        raise ValueError(f"unknown component instance {instance_id}")
    proposed = {**box, "items": [{**row, **changes} if row is item else row for row in box["items"]]}
    validate_component_box(proposed)
    item.update(changes)
    return item


def apply_appraisal_event(box: dict[str, Any], event: str, count: int = 1) -> None:
    """Explicit confirmed events; battle assumes a perfect victory."""
    if event not in APPRAISAL_EVENTS or type(count) is not int or not 1 <= count <= 1000:
        raise ValueError("invalid appraisal event or count")
    validate_component_box(box)
    increments = APPRAISAL_EVENTS[event]
    for item in box["items"]:
        if item["estimatedValue"] is not None:
            item["estimatedValue"] += increments.get(item["componentId"], 0) * count


def acquire_component(box: dict[str, Any], component_id: str, **kwargs: Any) -> dict[str, Any]:
    """Acquire atomically, including moss's three balls and existing growth."""
    draft = deepcopy(box)
    apply_appraisal_event(draft, "acquire")
    confirmed_value = kwargs.get("estimated_value")
    kwargs["estimated_value"] = 2 if component_id == "component_007" else (
        confirmed_value if confirmed_value is not None else INITIAL_VALUES.get(component_id))
    item = add_component(draft, component_id, **kwargs)
    if component_id == "component_007":
        for _ in range(3):
            apply_appraisal_event(draft, "acquire")
            add_component(draft, "component_008", estimated_value=INITIAL_VALUES["component_008"])
        if confirmed_value is not None:
            item["estimatedValue"] = confirmed_value
    validate_component_box(draft)
    box["items"] = draft["items"]
    return item


def remove_component(box: dict[str, Any], instance_id: str) -> None:
    if not any(item["instanceId"] == instance_id for item in box["items"]):
        raise ValueError(f"unknown component instance {instance_id}")
    box["items"] = [item for item in box["items"] if item["instanceId"] != instance_id]


def set_capacity(box: dict[str, Any], capacity: int) -> None:
    validate_component_box({**box, "capacity": capacity})
    box["capacity"] = capacity


def route_items(box: dict[str, Any]) -> list[dict[str, Any]]:
    validate_component_box(box)
    return [
        {"instanceId": item["instanceId"], "componentId": item["componentId"], "remainingUses": item["remainingUses"]}
        for item in box["items"] if component_kind(item["componentId"]) == "加工品" and item["routeCandidate"]
    ]
