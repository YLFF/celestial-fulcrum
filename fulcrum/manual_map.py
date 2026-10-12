"""Create an editable map from trusted offline geometry, without OCR guesses."""

from .map_catalog import TemplateCatalog
from .playtime_state import AREA_SPECS, FIXED_TEMPLATE_CATEGORIES, merge_map_observation, rebuild_derived


def templates_for_area(area_key):
    if area_key not in AREA_SPECS:
        raise ValueError("请选择有效的地图层数")
    return TemplateCatalog().candidates(*AREA_SPECS[area_key])


def template_observation(template, area_key):
    area, floor = AREA_SPECS[area_key]
    nodes = []
    for slot in template.occupied_slots:
        coord = template.coord(slot)
        hint = template.terminal_type if slot in template.terminal_slots else None
        category = "start" if slot == template.start_slot else FIXED_TEMPLATE_CATEGORIES.get(hint)
        nodes.append({"id": coord.key, "coord": [coord.x, coord.y], "slot": list(slot),
                      "categoryId": category, "templateHint": hint,
                      "visibility": "revealed" if category else "unknown", "marks": []})
    return {"success": True, "area": area, "floor": floor, "templateId": template.id,
            "templateSourceRegionId": template.region_id, "nodes": nodes,
            "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges]}


def template_options(area_key):
    rows = []
    for index, template in enumerate(templates_for_area(area_key), 1):
        observation = template_observation(template, area_key)
        nodes = {row["id"]: {**row, "observedCategoryId": row["categoryId"],
                 "resolvedCategoryId": row["categoryId"], "confirmedMarkIds": [],
                 "completion": "completed" if row["id"] == "0,0" else "pending"}
                 for row in observation["nodes"]}
        rows.append({"id": template.id, "number": index, "gridShape": list(template.grid_shape),
                     "nodeCount": len(nodes), "terminalCount": len(template.terminal_slots),
                     "preview": {"instanceId": f"manual-preview-{template.id}", "templateId": template.id,
                                 "areaKey": area_key, "playerPosition": "0,0", "nodes": nodes,
                                 "edges": observation["edges"], "prediction": {}}})
    return rows


def create_manual_map(state, area_key, template_id, *, replace_existing=False, action_points=None):
    templates = templates_for_area(area_key)
    template = next((row for row in templates if row.id == template_id), None)
    if template is None:
        raise ValueError("所选模板不属于当前层，请重新选择")
    slot = state["areas"][area_key]
    if slot["activeInstanceId"] and not replace_existing:
        raise ValueError("本层已有地图，请确认重新建立；旧地图实例会保留")
    if action_points is not None and (type(action_points) is not int or action_points < 0):
        raise ValueError("行动力须为不小于0的整数")
    fresh_opening = area_key == "I" and not slot["instances"] and state["currentAreaKey"] is None
    instance = merge_map_observation(state, area_key, template_observation(template, area_key),
                                    new_instance=True, player_position="0,0", initial_area_entry=fresh_opening)
    instance["mapOrigin"] = "manual"
    for node in instance["nodes"].values():
        node["completion"] = "completed" if node["id"] == "0,0" else "pending"
    if action_points is not None:
        instance["actionPoints"] = action_points
    rebuild_derived(state)
    return instance
