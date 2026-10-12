"""Normalize the saved Lubiao selector evidence into one runtime event-weight file."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def convert(source: dict, events: list[dict]) -> dict:
    by_name = {event["name"]: event["id"] for event in events}
    scenes = {}
    for response in source["json_responses"]:
        for floor in response.get("floor_encounters", []):
            for event in floor["events"]:
                if event.get("classification") != "不期而遇" or event["name"] not in by_name:
                    continue
                for scene in event["sceneIds"]:
                    if scene.endswith("_enter"):
                        scenes[scene.removesuffix("_enter")] = by_name[event["name"]]
    areas = {}
    for row in source["encounter_weight_rows"]:
        if type(row["floor"]) is not int or not 1 <= row["floor"] <= 6:
            raise ValueError("invalid floor in encounter evidence")
        weight = row["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0:
            raise ValueError("invalid event weight; refusing to publish")
        key = ("I", "II", "III", "IV", "V", "VI")[row["floor"] - 1]
        if row["treehole"]:
            key += "-treehole"
        event_id = scenes[row["id"]]
        if event_id in areas.get(key, {}):
            raise ValueError(f"duplicate encounter weight: {key}:{event_id}")
        areas.setdefault(key, {})[event_id] = {
            "weight": row["weight"], "observedCount": row.get("observedCount"),
            "sourceSceneId": row["id"], "status": row.get("status"),
        }
    return {"schemaVersion": 1, "source": source["url"], "checkedAt": source["checked_at"],
            "meaning": "relative statistical encounter weights; normalize after eligibility filtering",
            "areas": areas}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "work/lubiao_encounter_selector/report.json")
    parser.add_argument("--out", type=Path, default=ROOT / "data/blackflow_encounter_weights.json")
    args = parser.parse_args()
    source = json.loads(args.source.read_text(encoding="utf-8"))
    events = json.loads((ROOT / "data/blackflow_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
    result = convert(source, events)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pending = args.out.with_suffix(args.out.suffix + ".pending")
    pending.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending.replace(args.out)
    print(f"{args.out}: {len(result['areas'])} areas")


if __name__ == "__main__":
    main()
