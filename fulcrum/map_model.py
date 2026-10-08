from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, order=True)
class Coord:
    """Map coordinate relative to the start: right/up are positive."""

    x: int
    y: int

    @classmethod
    def from_slot(cls, slot: tuple[int, int], start: tuple[int, int]) -> Coord:
        return cls(slot[0] - start[0], start[1] - slot[1])

    @property
    def key(self) -> str:
        return f"{self.x},{self.y}"


@dataclass(frozen=True)
class MapTemplate:
    id: str
    region_id: str
    kind: str
    grid_shape: tuple[int, int]
    start_slot: tuple[int, int]
    occupied_slots: tuple[tuple[int, int], ...]
    terminal_slots: tuple[tuple[int, int], ...]
    terminal_type: str | None
    edges: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    fixed_nodes: dict[tuple[int, int], str]

    def coord(self, slot: tuple[int, int]) -> Coord:
        return Coord.from_slot(slot, self.start_slot)


@dataclass(frozen=True)
class TemplateMatch:
    template: MapTemplate
    origin_x: float
    origin_y: float
    step_x: float
    step_y: float
    score: float
    coverage: float
    matched_slots: int
    extra_slots: int
    point_explanation: float
    edge_score: float | None = None
    ranking_score: float | None = None

    def pixel_at(self, slot: tuple[int, int]) -> tuple[float, float]:
        return self.origin_x + slot[0] * self.step_x, self.origin_y + slot[1] * self.step_y

    @property
    def grid_step(self) -> float:
        columns, rows = self.template.grid_shape
        steps = [self.step_x if columns > 1 else float("inf"), self.step_y if rows > 1 else float("inf")]
        return min(steps)

    def summary(self) -> dict[str, Any]:
        return {
            "templateId": self.template.id,
            "sourceRegionId": self.template.region_id,
            "score": round(self.score, 4),
            "rankingScore": round(self.ranking_score, 4) if self.ranking_score is not None else None,
            "coverage": round(self.coverage, 4),
            "matchedSlots": self.matched_slots,
            "extraSlots": self.extra_slots,
            "pointExplanation": round(self.point_explanation, 4),
            "edgeScore": round(self.edge_score, 4) if self.edge_score is not None else None,
            "lattice": {
                "origin": [round(self.origin_x, 2), round(self.origin_y, 2)],
                "step": [round(self.step_x, 2), round(self.step_y, 2)],
            },
        }


@dataclass
class MapNode:
    coord: Coord
    slot: tuple[int, int]
    pixel: tuple[float, float]
    category_id: str | None = None
    category_name: str | None = None
    category_score: float | None = None
    category_candidates: list[dict[str, Any]] = field(default_factory=list)
    template_hint: str | None = None
    visibility: str = "unknown"
    completion: str = "unknown"
    marks: list[dict[str, Any]] = field(default_factory=list)
    mark_review_required: bool = True
    review_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.coord.key,
            "coord": [self.coord.x, self.coord.y],
            "slot": list(self.slot),
            "pixel": [round(self.pixel[0], 1), round(self.pixel[1], 1)],
            "categoryId": self.category_id,
            "categoryName": self.category_name,
            "categoryScore": self.category_score,
            "categoryCandidates": self.category_candidates,
            "templateHint": self.template_hint,
            "visibility": self.visibility,
            "completion": self.completion,
            "marks": self.marks,
            "markReviewRequired": self.mark_review_required,
            "reviewReasons": self.review_reasons,
        }


@dataclass
class MapResult:
    screenshot: str
    image_size: tuple[int, int]
    area: str | None
    floor: int | None
    success: bool
    template_id: str | None = None
    region_id: str | None = None
    template_source_region_id: str | None = None
    layer_observation: dict[str, Any] | None = None
    resource_observation: dict[str, Any] | None = None
    player_position_observation: dict[str, Any] | None = None
    map_viewport: tuple[int, int, int, int] | None = None
    map_roi: tuple[int, int, int, int] | None = None
    template_candidates: list[dict[str, Any]] = field(default_factory=list)
    match_quality: dict[str, Any] | None = None
    dystopia_observation: dict[str, Any] | None = None
    nodes: list[MapNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": 3,
            "screenshot": self.screenshot,
            "imageSize": list(self.image_size),
            "area": self.area,
            "floor": self.floor,
            "success": self.success,
            "templateId": self.template_id,
            "regionId": self.region_id,
            "templateSourceRegionId": self.template_source_region_id,
            "layerObservation": self.layer_observation,
            "resourceObservation": self.resource_observation,
            "playerPositionObservation": self.player_position_observation,
            "mapViewport": list(self.map_viewport) if self.map_viewport else None,
            "mapRoi": list(self.map_roi) if self.map_roi else None,
            "templateCandidates": self.template_candidates,
            "matchQuality": self.match_quality,
            "dystopiaObservation": self.dystopia_observation,
            "coordinateSystem": "start=(0,0); +x right; +y up",
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [list(edge) for edge in self.edges],
            "warnings": self.warnings,
        }
