from __future__ import annotations

from dataclasses import dataclass


COMBAT_CATEGORIES = {
    "node_type_001", "node_type_002", "node_type_003", "node_type_011",
    "node_type_019", "node_type_021", "unknown_ferocity",
}
MERCHANT_CATEGORIES = {"node_type_004", "node_type_013"}


@dataclass(frozen=True)
class MovementRule:
    component_id: str
    shape: str
    range: int | None = None
    target: str = "any"
    action_cost: int = 1
    action_gain: int = 0
    hope_gain: int = 0
    ingot_gain: int = 0
    expires_on_exit: bool = False
    deterministic: bool = True

    def reaches(
        self,
        source: tuple[int, int],
        destination: tuple[int, int],
        category_id: str | None,
        revealed: bool,
    ) -> bool:
        if not self.deterministic or source == destination:
            return False
        dx = abs(destination[0] - source[0])
        dy = abs(destination[1] - source[1])
        if self.shape == "line" and not ((dx == 0 or dy == 0) and dx + dy <= self.range):
            return False
        if self.shape == "square" and max(dx, dy) > self.range:
            return False
        if self.shape == "diamond" and dx + dy > self.range:
            return False
        if self.target == "noncombat" and (category_id is None or category_id in COMBAT_CATEGORIES):
            return False
        if self.target == "revealed_merchant" and (category_id not in MERCHANT_CATEGORIES or not revealed):
            return False
        return True


MOVEMENT_RULES = {
    "component_013": MovementRule("component_013", "line", 2),
    "component_014": MovementRule("component_014", "square", 1),
    "component_015": MovementRule("component_015", "square", 1),
    "component_016": MovementRule("component_016", "diamond", 2, action_cost=0, expires_on_exit=True),
    "component_017": MovementRule("component_017", "diamond", 2),
    "component_018": MovementRule("component_018", "line", 3),
    "component_019": MovementRule("component_019", "any", target="noncombat", action_cost=0,
                                   expires_on_exit=True, deterministic=False),
    "component_020": MovementRule("component_020", "any", action_cost=0),
    "component_021": MovementRule("component_021", "any", target="noncombat", hope_gain=2),
    "component_022": MovementRule("component_022", "any", target="revealed_merchant", ingot_gain=4),
    "component_023": MovementRule("component_023", "any"),
    "component_024": MovementRule("component_024", "square", 1, action_cost=0, action_gain=3),
}
