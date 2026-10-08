from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NODE = Path(
    r"C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
)
DEFAULT_NODE_PATH = Path(
    r"C:/Users/Lean/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
)


NODE_TYPE_BY_TEXT = {
    "作战": "combat",
    "紧急作战": "emergency-combat",
    "不期而遇": "encounter",
    "未知的诡秘": "unknown-mystery",
    "未知的凶戾": "unknown-ferocity",
    "曲折密道": "winding-path",
    "险路恶敌": "danger-enemy",
    "险路恶敌·中型 II": "danger-enemy-shsgzd",
    "羽瞰点": "overlook",
    "得偿所愿": "wish",
}

MOJIBAKE_NODE_TEXT = {
    "鏈煡鐨勮绉?": "未知的诡秘",
    "鏈煡鐨勮绉?": "未知的诡秘",
    "鏈煡鐨勫嚩鎴?": "未知的凶戾",
    "涓嶆湡鑰岄亣": "不期而遇",
    "闄╄矾鎭舵晫路涓瀷 II": "险路恶敌·中型 II",
    "鏇叉姌瀵嗛亾": "曲折密道",
    "绱ф€ヤ綔鎴?": "紧急作战",
    "浣滄垬": "作战",
    "缇界灠鐐?": "羽瞰点",
    "寰楀伩鎵€鎰?": "得偿所愿",
}


@dataclass(frozen=True)
class ResourceRegion:
    name: str
    box_2048: tuple[int, int, int, int]
    parser: str = "int"


RESOURCE_REGIONS = [
    ResourceRegion("life", (275, 48, 395, 92), "fraction"),
    ResourceRegion("shield", (405, 42, 465, 82), "int"),
    ResourceRegion("level", (500, 20, 560, 88), "int"),
    ResourceRegion("exp", (570, 48, 660, 92), "fraction"),
    ResourceRegion("yellow_top", (1535, 35, 1715, 82), "fraction"),
    ResourceRegion("money", (1890, 35, 2010, 82), "int"),
    ResourceRegion("action", (1790, 185, 1875, 265), "int"),
    ResourceRegion("estimated_value", (885, 1060, 935, 1130), "int"),
    ResourceRegion("parts_box", (1188, 1080, 1310, 1135), "fraction"),
    ResourceRegion("human_resource", (1368, 1082, 1412, 1128), "int"),
    ResourceRegion("squad_size", (1618, 1068, 1665, 1130), "int"),
]


def scale_box(box: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    sx = width / 2048
    sy = height / 1152
    return tuple(round(v * (sx if index % 2 == 0 else sy)) for index, v in enumerate(box))  # type: ignore[return-value]


def enhance_digit_crop(crop: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(crop)
    gray = ImageOps.autocontrast(gray)
    # Upscale before OCR; tesseract behaves much better on these thin UI digits.
    return gray.resize((gray.width * 3, gray.height * 3), Image.Resampling.LANCZOS)


def parse_ocr_value(text: str, parser: str) -> dict[str, Any]:
    cleaned = re.sub(r"[^0-9/]", "", text)
    if parser == "fraction":
        match = re.search(r"(\d+)\s*/\s*(\d+)", cleaned)
        if match:
            return {"current": int(match.group(1)), "max": int(match.group(2)), "raw": cleaned}
        if re.fullmatch(r"\d{4}", cleaned):
            return {"current": int(cleaned[:2]), "max": int(cleaned[2:]), "raw": cleaned}
        digits = re.findall(r"\d+", cleaned)
        if len(digits) >= 2:
            return {"current": int(digits[0]), "max": int(digits[1]), "raw": cleaned}
        return {"current": None, "max": None, "raw": cleaned}
    match = re.search(r"\d+", cleaned)
    return {"value": int(match.group(0)) if match else None, "raw": cleaned}


def run_digit_ocr(image_path: Path, node: Path = DEFAULT_NODE) -> dict[str, Any]:
    env = os.environ.copy()
    env["NODE_PATH"] = str(DEFAULT_NODE_PATH)
    completed = subprocess.run(
        [str(node), str(ROOT / "scripts" / "ocr_resources_tesseract.mjs"), str(image_path)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        return {"text": "", "confidence": None, "error": completed.stderr.strip() or completed.stdout.strip()}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"text": completed.stdout.strip(), "confidence": None, "error": "invalid_tesseract_json"}


def extract_resources(screenshot: Path, debug_dir: Path | None = None) -> dict[str, Any]:
    image = Image.open(screenshot).convert("RGB")
    resources: dict[str, Any] = {}
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
    for region in RESOURCE_REGIONS:
        crop = image.crop(scale_box(region.box_2048, image.width, image.height))
        prepared = enhance_digit_crop(crop)
        crop_path = (debug_dir or (ROOT / "work")) / f"resource_{region.name}.png"
        prepared.save(crop_path)
        ocr = run_digit_ocr(crop_path)
        parsed = parse_ocr_value(str(ocr.get("text", "")), region.parser)
        confidence = ocr.get("confidence")
        if (
            region.name != "yellow_top"
            and isinstance(confidence, (int, float))
            and confidence < 40
            and "value" in parsed
        ):
            parsed["value"] = None
        resources[region.name] = {
            **parsed,
            "ocr_text": ocr.get("text", ""),
            "confidence": confidence,
            "crop": str(crop_path) if debug_dir else None,
            **({"error": ocr["error"]} if "error" in ocr else {}),
        }
    return resources


def normalize_node_text(text: str) -> str:
    text = (text or "").strip()
    if text in MOJIBAKE_NODE_TEXT:
        return MOJIBAKE_NODE_TEXT[text]
    if text.startswith("闄╄矾鎭舵晫"):
        return "险路恶敌"
    return text


def node_type_for(node: dict[str, Any]) -> str:
    cls = node.get("nodeClass", "")
    if "has-start" in cls:
        return "start"
    text = normalize_node_text(str(node.get("text", "")))
    if "has-prediction" in cls:
        if "凶戾" in text or "嚩" in text:
            return "unknown-ferocity"
        return "unknown-mystery"
    return NODE_TYPE_BY_TEXT.get(text, text or "unknown")


def parse_prediction_tooltip(tooltip: str | None) -> list[dict[str, Any]]:
    if not tooltip:
        return []
    lines = [line.strip() for line in tooltip.splitlines() if line.strip()]
    entries = []
    index = 0
    while index + 1 < len(lines):
        name = normalize_node_text(lines[index])
        percent_match = re.fullmatch(r"(\d+(?:\.\d+)?)%", lines[index + 1])
        if percent_match:
            entries.append({"name": name, "percent": float(percent_match.group(1))})
            index += 2
        else:
            index += 1
    return entries


def load_prediction_overrides(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if not path:
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("predictionNodes", raw.get("predictions", []))
    return {
        item.get("cellKey"): parse_prediction_tooltip(item.get("tooltip"))
        for item in items
        if item.get("cellKey")
    }


def load_lubiao_map(path: Path, prediction_json: Path | None = None) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    start_cell = next(
        (node.get("cellKey") for node in raw.get("nodes", []) if "has-start" in node.get("nodeClass", "")),
        None,
    )
    start_row = start_col = None
    if start_cell:
        start_row, start_col = [int(part) for part in start_cell.split(":")]
    prediction_by_cell = {
        item.get("cellKey"): parse_prediction_tooltip(item.get("tooltip"))
        for item in raw.get("predictionNodes", raw.get("predictions", []))
    }
    prediction_by_cell.update(load_prediction_overrides(prediction_json))
    nodes = []
    for node in raw.get("nodes", []):
        row, col = [int(part) for part in node["cellKey"].split(":")]
        nodes.append(
            {
                "cell": node["cellKey"],
                "relative": {
                    "x": None if start_col is None else col - start_col,
                    "y": None if start_row is None else start_row - row,
                },
                "nodeType": node_type_for(node),
                "name": normalize_node_text(str(node.get("text", ""))) or ("起点" if "has-start" in node.get("nodeClass", "") else ""),
                "hasPrediction": "has-prediction" in node.get("nodeClass", ""),
                "prediction": prediction_by_cell.get(node["cellKey"], []),
                "source": {"cellClass": node.get("cellClass"), "nodeClass": node.get("nodeClass")},
            }
        )
    return {
        "recognizer": "lubiao-local-or-compatible",
        "nodeCount": raw.get("nodeCount", len(nodes)),
        "predictionCount": raw.get("predictionCount", raw.get("predictionNodeCount")),
        "previewImage": raw.get("image") or raw.get("previewPath"),
        "startCell": start_cell,
        "nodes": nodes,
    }


def build_state(
    screenshot: Path,
    lubiao_json: Path,
    debug_crops: Path | None,
    prediction_json: Path | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "screenshot": str(screenshot),
        "map": load_lubiao_map(lubiao_json, prediction_json),
        "resources": extract_resources(screenshot, debug_crops),
        "notes": [
            "resources are OCR estimates; fields with low confidence or null values should be treated as uncertain",
            "map predictions use lubiao tooltip semantics: distribution by node type at walking distance, not normalized per-node posterior",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge lubiao map recognition and resource OCR into one game-state JSON.")
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("--lubiao-json", type=Path, required=True, help="JSON exported from lubiao local/cloud recognition adapter.")
    parser.add_argument("--prediction-json", type=Path, default=None, help="Optional JSON with lubiao prediction tooltip text.")
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "game_state.json")
    parser.add_argument("--debug-crops", type=Path, default=None)
    args = parser.parse_args()

    state = build_state(args.screenshot, args.lubiao_json, args.debug_crops, args.prediction_json)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
