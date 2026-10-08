from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from .vision_pipeline import MapRecognizer, render_overlay


def main() -> int:
    parser = argparse.ArgumentParser(description="Recognize a Black Flow map without node probability prediction.")
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("--area", choices=("main", "treehole", "source_confluence"), help="Override the detected area.")
    parser.add_argument("--floor", type=int, default=None, help="Override the detected floor, or set a treehole's entry floor.")
    parser.add_argument("--template", default=None, help="Explicit template ID after reviewing candidates.")
    parser.add_argument("--resources", action="store_true", help="Also read six OCR HUD fields and action points.")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, default=None)
    args = parser.parse_args()

    result = MapRecognizer().recognize(
        args.screenshot, area=args.area, floor=args.floor, template_override=args.template,
        include_resources=args.resources,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.overlay and result.success:
        image = cv2.imread(str(args.screenshot))
        args.overlay.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(str(args.overlay), render_overlay(image, result)):
            raise OSError(f"could not write overlay: {args.overlay}")
    print(f"layer={result.layer_observation['label']} template={result.template_id or 'unresolved'} nodes={len(result.nodes)} output={args.out}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    return 0 if result.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
