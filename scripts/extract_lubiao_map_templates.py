from __future__ import annotations

import ast
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin


PAGE_URL = "https://www.lubiao.wiki/tools/blackstream-route"
OUT_PATH = Path("data/blackstream_map_templates.json")


REGION_BY_INTERNAL_LAYER = {
    0: ("floor_1", "I", "第 I 层"),
    1: ("floor_2", "II", "第 II 层"),
    2: ("floor_3", "III", "第 III 层"),
    3: ("floor_4", "IV", "第 IV 层"),
    4: ("floor_5", "V", "第 V 层"),
    5: ("floor_6_source_confluence", "VI", "第 VI 层 源流交汇处"),
}

TREEHOLE_REGIONS = [
    ("treehole_floor_3", "III_TREEHOLE", "第 III 层 未萌生摇篮（树洞）"),
    ("treehole_floor_4", "IV_TREEHOLE", "第 IV 层 未萌生摇篮（树洞）"),
    ("treehole_floor_5", "V_TREEHOLE", "第 V 层 未萌生摇篮（树洞）"),
]


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def find_route_chunk(page_html: str) -> tuple[str, str]:
    chunk_urls = [
        urljoin(PAGE_URL, match.group(1))
        for match in re.finditer(r'(?:href|src)="([^"]+\.js)"', page_html)
    ]
    for url in chunk_urls:
        code = fetch_text(url)
        if "floor-1-single-exit" in code and "treehole-01" in code and "节点预测功能说明" in code:
            return url, code
    raise RuntimeError("未找到包含黑流树海地图模板的前端 chunk")


def extract_assignment(source: str, marker: str) -> str:
    start = source.index(marker) + len(marker)
    i = start
    depth = 0
    in_string = False
    escape = False
    while i < len(source):
        ch = source[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "[{(":
                depth += 1
            elif ch in "]})":
                depth -= 1
            if i > start and depth == 0 and source[i + 1 : i + 2] in {",", ";"}:
                return source[start : i + 1]
        i += 1
    raise RuntimeError(f"无法截取赋值表达式：{marker}")


def quote_object_keys(js_expr: str) -> str:
    return re.sub(r'([,{]\s*)([A-Za-z_$][\w$]*)(\s*:)', r'\1"\2"\3', js_expr)


def js_literal_to_python(js_expr: str):
    py_expr = quote_object_keys(js_expr)
    py_expr = py_expr.replace("_e(", "auto_edges(")
    py_expr = re.sub(r"\bnull\b", "None", py_expr)
    py_expr = re.sub(r"\btrue\b", "True", py_expr)
    py_expr = re.sub(r"\bfalse\b", "False", py_expr)
    return eval(py_expr, {"__builtins__": {}}, {"auto_edges": auto_edges})


def slot_key(slot: list[int]) -> str:
    return f"{slot[0]}:{slot[1]}"


def edge_key(edge: list[list[int]]) -> str:
    return "|".join(sorted(slot_key(slot) for slot in edge))


def auto_edges(template: dict) -> dict:
    occupied = {slot_key(slot) for slot in template["occupiedSlots"]}
    excluded = {edge_key(edge) for edge in template.get("excludedEdges", [])}
    edges = []
    for slot in template["occupiedSlots"]:
        row, col = slot
        for neighbor in ([row + 1, col], [row, col + 1]):
            if slot_key(neighbor) in occupied and edge_key([slot, neighbor]) not in excluded:
                edges.append([slot, neighbor])
    template = dict(template)
    template["edges"] = edges
    return template


def infer_treehole_source_floor(template: dict) -> str | None:
    source_id = template.get("sourceId", "")
    portal = template.get("utopiaPortal")
    if "red-construction" in source_id:
        return "III"
    if portal in {5, 6}:
        return "III"
    if portal in {7, 8}:
        return "IV"
    if portal == 9:
        return "V"
    return None


def normalize_template(template: dict) -> dict:
    return {
        "id": template["id"],
        "sourceId": template.get("sourceId"),
        "internalLayerIndex": template["layerIndex"],
        "gridShape": template["gridShape"],
        "occupiedSlots": template["occupiedSlots"],
        "startSlot": template.get("startSlot"),
        "terminalSlots": template.get("terminalSlots", []),
        "terminalType": template.get("terminalType"),
        "fixedNodes": template.get("fixedNodes", []),
        "edges": template.get("edges", []),
        "excludedEdges": template.get("excludedEdges", []),
        "utopiaPortal": template.get("utopiaPortal"),
        "slotCount": len(template.get("occupiedSlots", [])),
        "edgeCount": len(template.get("edges", [])),
    }


def group_templates(templates: list[dict]) -> list[dict]:
    region_map: dict[str, dict] = {}

    for internal_layer, (region_id, floor, name) in REGION_BY_INTERNAL_LAYER.items():
        region_map[region_id] = {
            "id": region_id,
            "floor": floor,
            "name": name,
            "kind": "main" if internal_layer <= 4 else "source_confluence",
            "templates": [],
        }

    for region_id, floor, name in TREEHOLE_REGIONS:
        region_map[region_id] = {
            "id": region_id,
            "floor": floor,
            "name": name,
            "kind": "treehole",
            "templates": [],
        }

    shared_treehole_templates = []
    for template in templates:
        normalized = normalize_template(template)
        layer_index = template["layerIndex"]
        if layer_index <= 5:
            region_id = REGION_BY_INTERNAL_LAYER[layer_index][0]
            region_map[region_id]["templates"].append(normalized)
            continue

        source_floor = infer_treehole_source_floor(template)
        if source_floor == "III":
            region_map["treehole_floor_3"]["templates"].append(normalized)
        elif source_floor == "IV":
            region_map["treehole_floor_4"]["templates"].append(normalized)
        elif source_floor == "V":
            region_map["treehole_floor_5"]["templates"].append(normalized)
        else:
            shared_treehole_templates.append(normalized)

    for template in shared_treehole_templates:
        for region_id, *_ in TREEHOLE_REGIONS:
            copied = dict(template)
            copied["sharedAcrossTreeholeFloors"] = True
            region_map[region_id]["templates"].append(copied)

    order = [
        "floor_1",
        "floor_2",
        "floor_3",
        "floor_4",
        "floor_5",
        "treehole_floor_3",
        "treehole_floor_4",
        "treehole_floor_5",
        "floor_6_source_confluence",
    ]
    return [region_map[region_id] for region_id in order]


def summarize_regions(regions: list[dict]) -> dict:
    return {
        region["id"]: {
            "name": region["name"],
            "templateCount": len(region["templates"]),
            "gridShapes": sorted({f'{t["gridShape"][0]}x{t["gridShape"][1]}' for t in region["templates"]}),
            "templateIds": [t["id"] for t in region["templates"]],
        }
        for region in regions
    }


def main() -> None:
    page_html = fetch_text(PAGE_URL)
    route_chunk, code = find_route_chunk(page_html)
    expr = extract_assignment(code, "const _l=")
    templates = js_literal_to_python(expr)
    regions = group_templates(templates)

    output = {
        "schemaVersion": 1,
        "source": {
            "name": "路标档案馆 黑流树海地图规划 - 所有构造",
            "pageUrl": PAGE_URL,
            "routeChunk": route_chunk,
            "extractedAt": datetime.now(timezone.utc).isoformat(),
            "note": "模板来自网页“所有构造”背后的前端模板数据；树洞模板按 sourceId/utopiaPortal 归入 III/IV/V 未萌生摇篮，无法唯一归层的共享模板会复制到三个树洞区域并标记 sharedAcrossTreeholeFloors。",
        },
        "regions": regions,
        "summary": summarize_regions(regions),
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH}")
    for region in regions:
        shapes = ", ".join(output["summary"][region["id"]]["gridShapes"])
        print(f'{region["name"]}: {len(region["templates"])} templates ({shapes})')


if __name__ == "__main__":
    main()
