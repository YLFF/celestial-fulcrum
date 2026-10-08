"""Compare queue orders against a fully explored small deterministic state graph."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.component_box import INITIAL_USES
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.route_planner import RoutePlanner


class TracedPlanner(RoutePlanner):
    def __init__(self, game_map: dict) -> None:
        super().__init__(game_map)
        self.records: dict[int, dict] = {}
        self.terminals: list[dict] = []

    def observe(self, record: dict) -> None:
        self.records[record["labelId"]] = record

    def _offer(self, pool: list, candidate: object, limit_equal: int) -> None:
        if candidate.treehole_item_index is None and candidate.label_index in self.records:
            record = self.records[candidate.label_index]
            self.terminals.append({"labelId": candidate.label_index,
                                   "score": candidate.metrics[0] / 20,
                                   "expansion": record["expansion"],
                                   "rewardNodeMask": record["rewardNodeMask"]})
        super()._offer(pool, candidate, limit_equal)

    def path(self, label_id: int) -> list[dict]:
        result = []
        while self.records[label_id]["parentLabelId"] is not None:
            record = self.records[label_id]
            result.append(record)
            label_id = record["parentLabelId"]
        return list(reversed(result))


class LegacyPlanner(TracedPlanner):
    def _queue_priority(self, metrics: tuple, exit_distance: float,
                        action_points: int, serial: int) -> tuple:
        return (-metrics[0], -metrics[1],
                int(exit_distance) if exit_distance != float("inf") else 9999,
                -metrics[4], -action_points, serial)


class FifoPlanner(TracedPlanner):
    def _queue_priority(self, metrics: tuple, exit_distance: float,
                        action_points: int, serial: int) -> tuple:
        return (serial,)


def inputs(action_points: int = 2) -> tuple[dict, dict]:
    template = min(TemplateCatalog().candidates("main", 3), key=lambda item: len(item.occupied_slots))
    ids = {slot: template.coord(slot).key for slot in template.occupied_slots}
    edges = [[ids[a], ids[b]] for a, b in template.edges]
    adjacent = {key: [] for key in ids.values()}
    for a, b in edges:
        adjacent[a].append(b)
        adjacent[b].append(a)
    distance = {"0,0": 0}
    pending = deque(distance)
    while pending:
        source = pending.popleft()
        for target in adjacent[source]:
            if target not in distance:
                distance[target] = distance[source] + 1
                pending.append(target)
    terminals = {ids[slot] for slot in template.terminal_slots}
    remote = sorted((key for key in ids.values() if key not in terminals and distance[key] > 1),
                    key=lambda key: (distance[key], key))
    hidden = {key: "unknown_mystery" if index % 3 else "unknown_ferocity"
              for index, key in enumerate(remote[:12])}
    known = dict(zip(remote[12:], ("node_type_006", "node_type_007", "node_type_013",
                                   "node_type_008", "node_type_001", "node_type_004")))
    nodes = []
    for slot in template.occupied_slots:
        key = ids[slot]
        category = ("start" if key == "0,0" else "node_type_003" if key in terminals else
                    "node_type_001" if distance[key] == 1 else hidden.get(key, known.get(key, "node_type_020")))
        coord = template.coord(slot)
        nodes.append({"id": key, "coord": [coord.x, coord.y], "categoryId": category,
                      "visibility": "hidden" if key in hidden else "revealed"})
    components = ["component_017", "component_015", "component_021", "component_019",
                  "component_013", "component_016"]
    state = {"position": "0,0", "completedNodes": ["0,0"], "actionPoints": action_points,
             "searchMode": "reference",
             "componentBoxFreeSlots": 2, "topN": 10,
             "items": [{"instanceId": component, "componentId": component,
                        "remainingUses": INITIAL_USES[component]} for component in components]}
    return {"success": True, "templateId": template.id, "nodes": nodes, "edges": edges}, state


def summarize(planner: TracedPlanner, result: dict, seconds: float) -> dict:
    best = max((terminal["score"] for terminal in planner.terminals), default=None)
    summary = {"searchComplete": result["searchComplete"], "generatedStates": result["generatedStates"],
               "expandedStates": result["expandedStates"], "seconds": round(seconds, 4),
               "bestScore": best, "randomMovement": result["randomMovement"]}
    if best is None:
        return summary
    first_per_set = {}
    for terminal in planner.terminals:
        if terminal["score"] >= 0.95 * best:
            first_per_set.setdefault(terminal["rewardNodeMask"], terminal)
    latest = max(first_per_set.values(), key=lambda terminal: terminal["expansion"])
    path = planner.path(latest["labelId"])
    root_children = sorted((record for record in planner.records.values() if record["parentLabelId"] == 0),
                           key=lambda record: record["queuePriority"])
    first_rank = next(index + 1 for index, record in enumerate(root_children)
                      if record["labelId"] == path[0]["labelId"])
    first_terminal_at = min(terminal["expansion"] for terminal in planner.terminals)
    frontier = sorted((record for record in planner.records.values()
                       if record["parentLabelId"] is not None and record["expansion"] > first_terminal_at
                       and planner.records[record["parentLabelId"]]["expansion"] <= first_terminal_at),
                      key=lambda record: record["queuePriority"])
    next_prefix = next((record for record in path if record["expansion"] > first_terminal_at), None)
    prefix_rank = next((index + 1 for index, record in enumerate(frontier)
                        if next_prefix is not None and record["labelId"] == next_prefix["labelId"]), None)
    summary.update({
        "firstBestExpansion": min(terminal["expansion"] for terminal in planner.terminals if terminal["score"] == best),
        "topTierDefinition": "score >= 95% of exhaustive best; not resource utility",
        "topTierRewardSets": len(first_per_set),
        "latestFirstTopTierRewardSet": {
            "score": latest["score"], "expansion": latest["expansion"],
            "fractionOfFullExpansion": round(latest["expansion"] / result["expandedStates"], 4),
            "initialActionQueueRank": first_rank, "initialActionCount": len(root_children),
            "firstGoalCheckpoint": first_terminal_at,
            "prefixQueueRankAtFirstGoal": prefix_rank, "frontierSizeAtFirstGoal": len(frontier),
            "firstPrefixScore": path[0]["weightedValue"],
            "steps": [record["step"] for record in path],
        },
    })
    return summary


def audit(action_points: int, cap: int, budgets: list[int]) -> dict:
    game_map, state = inputs(action_points)
    report = {"synthetic": True, "map": game_map, "state": state, "policies": {},
              "limitations": ["Full deterministic state graph, not every distinct path permutation",
                              "Random component_019 is held but excluded from movement, not exhaustively modeled",
                              "Synthetic node assignment, not a validated in-game generation",
                              "Fixed heuristic score, no event/resource/order weights or future item gains"]}
    for name, planner_type in (("legacy", LegacyPlanner), ("current", TracedPlanner), ("fifo", FifoPlanner)):
        planner = planner_type(game_map)
        started = perf_counter()
        result = planner.plan({**state, "maxStates": cap}, on_expand=planner.observe)
        summary = summarize(planner, result, perf_counter() - started)
        if not result["searchComplete"]:
            raise RuntimeError(f"{name} hit {cap} states; this case is not an exhaustive reference")
        summary["budgetComparisons"] = []
        for budget in budgets:
            bounded = planner_type(game_map).plan({**state, "maxStates": budget})
            summary["budgetComparisons"].append({
                "maxStates": budget, "generatedStates": bounded["generatedStates"],
                "searchComplete": bounded["searchComplete"],
                "bestScore": max((route["metrics"]["weightedValue"] for route in bounded["routes"]), default=None),
            })
        report["policies"][name] = summary
    scores = [case["bestScore"] for case in report["policies"].values()]
    if len(set(scores)) != 1:
        raise RuntimeError(f"Fully explored queue orders disagree: {scores}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-points", type=int, default=2)
    parser.add_argument("--max-states", type=int, default=500000)
    parser.add_argument("--budgets", type=int, nargs="+", default=[100, 500, 1000, 5000, 50000])
    parser.add_argument("--out", type=Path, default=ROOT / "work" / "route_search_audit.json")
    args = parser.parse_args()
    report = audit(args.action_points, args.max_states, args.budgets)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"templateId": report["map"]["templateId"], "policies": report["policies"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
