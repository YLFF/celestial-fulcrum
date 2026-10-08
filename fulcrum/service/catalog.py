"""Offline IDs/names/images for editor option sets, not a new scoring source."""

from functools import lru_cache
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def entries():
    data = json.loads((ROOT / "data/lubiao_reference_catalog.json").read_text(encoding="utf-8"))
    icon_file = ROOT / "data/node_ui_icons.json"
    icons = json.loads(icon_file.read_text(encoding="utf-8"))["icons"] if icon_file.is_file() else {}
    return {row["id"]: {**row, **({"imagePath": icons[row["id"]]["imagePath"]} if row["id"] in icons else {})}
            for row in data["entries"]}


def editor_catalog():
    from ..product import PROJECT
    from ..goals import GOAL_DEFINITIONS
    from ..opening import SQUAD_NAMES, COCOON_NAMES, INITIAL_SUPPORTS
    result = {}
    for row in entries().values():
        result.setdefault(row["category"], []).append({"id": row["id"], "name": row["name"],
            "imageUrl": f"/api/catalog/{row['id']}/image" if row.get("imagePath") else None})
    result["encounters"] = json.loads((ROOT / "data/blackstream_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
    result["squads"] = SQUAD_NAMES
    result["cocoons"] = COCOON_NAMES
    result["initialSupports"] = INITIAL_SUPPORTS
    from ..operator_catalog import operators
    result["operators"] = list(operators())
    result["goals"] = GOAL_DEFINITIONS
    from ..component_box import INITIAL_USES, INITIAL_VALUES, APPRAISAL_EVENTS, component_kind
    result["componentInitialUses"] = INITIAL_USES
    result["componentAppraisalEvents"] = APPRAISAL_EVENTS
    for row in result["component"]:
        row.update(kind=component_kind(row["id"]), initialEstimatedValue=INITIAL_VALUES.get(row["id"]))
    from ..scoring_calibration import TICKET_WEIGHTS
    result["ticketNames"] = list(TICKET_WEIGHTS)
    result["labels"] = json.loads((ROOT / "data/vision_labels.json").read_text(encoding="utf-8"))
    result["nodeIcons"] = [{"id": kind, "name": result["labels"]["nodeTypes"][kind],
                            "imageUrl": f"/api/vision-icons/{kind}"}
                           for kind in ("unknown_mystery", "unknown_ferocity")]
    result["project"] = dict(PROJECT)
    return result


def image_path(entry_id):
    row = entries().get(entry_id)
    if not row or not row.get("imagePath"):
        raise FileNotFoundError("catalog image not available")
    path = (ROOT / row["imagePath"]).resolve()
    if not path.is_relative_to((ROOT / "assets").resolve()) or not path.is_file():
        raise FileNotFoundError("catalog image not available")
    return path
