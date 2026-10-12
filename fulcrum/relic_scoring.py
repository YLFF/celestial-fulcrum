"""Player-calibrated values per received relic, separate from drop statistics."""

from __future__ import annotations

import json
from math import isfinite
from pathlib import Path

from .node_rewards import NodeRewardPoolCatalog
from .resource_scoring import DEFAULT_UNIT_VALUES, REFERENCE_POINTS


CONFIG_PATH = Path(__file__).resolve().parents[1] / "data/scoring/blackflow/relics.json"


def _points(value: float) -> float:
    if type(value) not in (int, float):
        raise ValueError("Relic points must be finite and nonnegative")
    try:
        result = float(value)
    except OverflowError as error:
        raise ValueError("Relic points must be finite and nonnegative") from error
    if not isfinite(result) or result < 0:
        raise ValueError("Relic points must be finite and nonnegative")
    return result


class RelicScorer:
    def __init__(self, path: Path = CONFIG_PATH, *, catalog: NodeRewardPoolCatalog | None = None):
        self.catalog = catalog if catalog is not None else NodeRewardPoolCatalog()
        self.data = json.loads(path.read_text(encoding="utf-8"))
        if self.data.get("schemaVersion") != 1:
            raise ValueError("Unsupported relic score schema")
        self.default_points = _points(self.data["defaultPoints"])
        maps = {}
        for field in ("poolPoints", "contextPoints", "fixedRelicPoints"):
            raw = self.data.get(field, {})
            if not isinstance(raw, dict) or any(not isinstance(key, str) or not key for key in raw):
                raise ValueError(f"Invalid relic score map: {field}")
            maps[field] = {key: _points(value) for key, value in raw.items()}
        self.pool_points, self.context_points, self.fixed_points = (
            maps[field] for field in ("poolPoints", "contextPoints", "fixedRelicPoints"))
        for key in self.pool_points:
            self._require_relics(self.catalog.get_pool(key))
        for key in self.context_points:
            self._require_relics(self.catalog.get(key))

    @staticmethod
    def _require_relics(pool: dict) -> None:
        if not pool["members"] or any(row["dataType"] != "藏品" for row in pool["members"]):
            raise ValueError("Relic scoring requires a relic-only pool")

    def pool_score(self, context_id: str) -> float:
        context = self.catalog.get(context_id)
        self._require_relics(context)
        return self.context_points.get(context_id,
                                       self.pool_points.get(context["rewardPoolId"], self.default_points))

    def fixed_score(self, relic_id: str) -> float:
        return self.fixed_points.get(relic_id, self.default_points)

    def event_pool(self, event_id: str) -> str:
        return self.catalog.rules_for("events", event_id)["relicContextId"]

    def wish_score(self, cash: float) -> dict:
        cash = _points(cash)
        advanced = cash >= 4
        context = "node_wish_relic_advanced" if advanced else "node_wish_relic"
        cost = 4 if advanced else 0
        reward = self.pool_score(context)
        cash_points = cost * REFERENCE_POINTS * DEFAULT_UNIT_VALUES["originiumIngot"]
        return {"points": reward - cash_points, "relicPoints": reward,
                "cashCostPoints": cash_points, "cashCost": cost, "cashAfter": cash - cost,
                "contextId": context, "usesAdvancedPool": advanced}
