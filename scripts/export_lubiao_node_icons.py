"""Export page-declared atlas rectangles to UI-only PNGs; leave CV templates alone."""
import json
from pathlib import Path
import shutil
import cv2

ROOT = Path(__file__).resolve().parents[1]


def main():
    source_dir = ROOT / "work/lubiao_node_icons"
    source = json.loads((source_dir / "source.json").read_text(encoding="utf-8"))
    out = ROOT / "assets/ui/nodes"
    out.mkdir(parents=True, exist_ok=True)
    icons = {}
    for row in source["icons"]:
        source_path = source_dir / f"{row['id']}.png"
        image = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
        if image is None or image.shape[:2] != tuple(reversed(row["box"][2:])):
            raise ValueError("invalid rendered atlas crop")
        path = out / f"{row['id']}.png"
        shutil.copyfile(source_path, path)
        icons[row["id"]] = {**row, "imagePath": path.relative_to(ROOT).as_posix()}
    (ROOT / "data/node_ui_icons.json").write_text(json.dumps({"source": source["source"],
        "fetchedAt": source["fetchedAt"], "icons": icons}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"icons": len(icons), "output": "assets/ui/nodes"}))


if __name__ == "__main__":
    main()
