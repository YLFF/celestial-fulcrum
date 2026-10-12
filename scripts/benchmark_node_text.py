"""Compare node-label OCR with icon-only recognition on archived screenshots."""

import argparse
import json
from pathlib import Path
import sys
from statistics import median
from time import perf_counter

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.vision_pipeline import MapRecognizer
from fulcrum.vision_geometry import working_image
from fulcrum.vision_node_text import label_crop, make_label_sheet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*")
    parser.add_argument("--out", type=Path, default=ROOT / "work/node_text_benchmark")
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    args.out.mkdir(parents=True, exist_ok=True)
    samples = json.loads((ROOT / "samples/maps/manifest.json").read_text(encoding="utf-8"))["samples"]
    if args.files:
        samples = [row for row in samples if row["file"] in args.files]
    recognizer = MapRecognizer(use_node_text=False)
    hybrid = MapRecognizer(catalog=recognizer.catalog, icons=recognizer.icons)
    reports = []
    for sample in samples:
        image = cv2.imread(str(ROOT / "samples/maps" / sample["file"]))
        times, results = {"icon": [], "hybrid": []}, {}
        for repeat in range(args.repeats):
            order = ("icon", "hybrid") if repeat % 2 == 0 else ("hybrid", "icon")
            for mode in order:
                started = perf_counter()
                results[mode] = (recognizer if mode == "icon" else hybrid).recognize_image(image, screenshot=sample["file"])
                times[mode].append(round((perf_counter() - started) * 1000, 1))
        result, updated = results["icon"], results["hybrid"]
        report = {"file": sample["file"], "baselineMs": median(times["icon"]), "runsMs": times,
                  "timingScope": "map recognition; resource HUD OCR excluded",
                  "templateId": result.template_id, "success": result.success, "expectedSuccess": sample["expectMap"]}
        report["hybridMs"] = median(times["hybrid"])
        report["hybridTemplateId"] = updated.template_id
        report["hybridSuccess"] = updated.success
        report["nodeText"] = updated.node_text_observation
        if result.success:
            _, scale = working_image(image)
            step = result.template_candidates[0]["lattice"]["step"]
            step = min(value for value in step if value > 0) / scale
            positions = {node.coord.key: node.pixel for node in result.nodes if node.category_id != "start"}
            by_id = {node.coord.key: node for node in result.nodes}
            report["textNodes"] = sum(node.category_source in {"text", "text_and_icon"} for node in updated.nodes)
            report["differences"] = [{"id": node.coord.key, "icon": by_id[node.coord.key].category_id,
                                      "hybrid": node.category_id, "source": node.category_source}
                                     for node in updated.nodes if by_id[node.coord.key].category_id != node.category_id]
            crops = {node_id: crop for node_id, pixel in positions.items()
                     if (crop := label_crop(image, pixel, step, result.map_viewport)) is not None}
            if crops:
                sheet, _ = make_label_sheet(crops)
                cv2.imwrite(str(args.out / (Path(sample["file"]).stem + "-labels.png")), sheet)
        (args.out / (Path(sample["file"]).stem + "-result.json")).write_text(
            json.dumps({"iconOnly": result.to_dict(), "hybrid": updated.to_dict()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        reports.append(report)
        print(json.dumps({key: value for key, value in report.items() if key != "nodeText"}, ensure_ascii=False), flush=True)
    (args.out / "report.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
