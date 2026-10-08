from __future__ import annotations

import json
from pathlib import Path

from .map_model import MapTemplate


DEFAULT_TEMPLATES = Path(__file__).resolve().parents[1] / "data" / "blackstream_map_templates.json"


class TemplateCatalog:
    def __init__(self, path: Path = DEFAULT_TEMPLATES) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.templates: list[MapTemplate] = []
        seen: set[str] = set()
        for region in raw["regions"]:
            for item in region["templates"]:
                if item["id"] in seen:
                    continue
                seen.add(item["id"])
                self.templates.append(
                    MapTemplate(
                        id=item["id"],
                        region_id=region["id"],
                        kind=region["kind"],
                        grid_shape=tuple(item["gridShape"]),
                        start_slot=tuple(item["startSlot"]),
                        occupied_slots=tuple(tuple(slot) for slot in item["occupiedSlots"]),
                        terminal_slots=tuple(tuple(slot) for slot in item.get("terminalSlots", [])),
                        terminal_type=item.get("terminalType"),
                        edges=tuple((tuple(a), tuple(b)) for a, b in item["edges"]),
                        fixed_nodes={tuple(node["slot"]): node["type"] for node in item.get("fixedNodes", [])},
                    )
                )

    def candidates(self, area: str, floor: int | None = None) -> list[MapTemplate]:
        if area == "treehole":
            if floor is not None and floor not in (3, 4, 5):
                raise ValueError("treehole entry floor must be 3, 4, or 5")
            # Share one visual construction pool across entry floors. Occupancy
            # alone is insufficient: some constructions differ only in edges.
            unique: dict[tuple, MapTemplate] = {}
            for template in self.templates:
                if template.kind != "treehole":
                    continue
                edges = tuple(sorted(tuple(sorted(edge)) for edge in template.edges))
                signature = (
                    template.grid_shape,
                    tuple(sorted(template.occupied_slots)),
                    template.start_slot,
                    tuple(sorted(template.terminal_slots)),
                    edges,
                    tuple(sorted(template.fixed_nodes.items())),
                )
                unique.setdefault(signature, template)
            return list(unique.values())
        if area == "main":
            if floor not in (1, 2, 3, 4, 5):
                raise ValueError("main area requires floor 1..5")
            return [template for template in self.templates if template.region_id == f"floor_{floor}"]
        if area == "source_confluence":
            if floor not in (None, 6):
                raise ValueError("source confluence is floor 6")
            return [template for template in self.templates if template.region_id == "floor_6_source_confluence"]
        raise ValueError(f"unknown area: {area}")
