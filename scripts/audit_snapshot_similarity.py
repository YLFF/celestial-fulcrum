"""Measure trajectory redundancy; hypothetical merges do not change the search."""

from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.playtime_route import route_inputs
from fulcrum.route_planner import RoutePlanner
from scripts.benchmark_snapshot_routes import third_floor_inputs


def future_key(row, *, inventory=True):
    return (row["position"], row["actionPoints"], row["doneMask"], row["visibleMask"],
            row["informationMask"], row["prefixCash"], row["prefixAppraisal"], row["movements"],
            row.get("economyMovements", row["movements"]), row.get("investmentBalance", 99),
            tuple(row.get("merchantShelves", ())), row.get("retainedAppraisalFraction", 1),
            tuple(row["canonicalUses"]) if inventory else None)


def pareto_labels(rows):
    frontier = []
    for row in sorted(rows, key=lambda value: value["score"], reverse=True):
        uses = row["canonicalUses"]
        if any(peer["score"] >= row["score"] and all(a >= b for a, b in zip(peer["canonicalUses"], uses))
               for peer in frontier):
            continue
        frontier = [peer for peer in frontier if not (row["score"] >= peer["score"]
                    and all(a >= b for a, b in zip(uses, peer["canonicalUses"])))]
        frontier.append(row)
    return frontier


def near_trajectory_clusters(paths):
    # One deletion from each equal-length path means at most one substituted step.
    parent = list(range(len(paths)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[b] = a

    buckets = defaultdict(list)
    exact = {path: index for index, path in enumerate(paths)}
    for index, (goal, steps) in enumerate(paths):
        for slot in range(len(steps)):
            shortened = steps[:slot] + steps[slot + 1:]
            buckets[(goal, len(steps), slot, shortened)].append(index)
            shorter = exact.get((goal, shortened))
            if shorter is not None:
                union(index, shorter)
    for values in buckets.values():
        for index in values[1:]:
            union(values[0], index)
    sizes = defaultdict(int)
    for index in range(len(paths)):
        sizes[find(index)] += 1
    return sorted(sizes.values(), reverse=True)


def summarize(records, result, coordinates, *, score_band=.01):
    trajectories = {}
    active = {}
    for row in records:
        step = row["step"]
        if step is None:
            path = ()
        else:
            source, entry, arrival = (coordinates[step[name]] for name in ("from", "entered", "arrived"))
            delta = (entry[0] - source[0], entry[1] - source[1], arrival[0] - entry[0], arrival[1] - entry[1])
            path = trajectories[row["parentLabelId"]] + (delta,)
        trajectories[row["labelId"]] = path
        active[future_key(row)] = row
    rows = list(active.values())
    same_path = defaultdict(list)
    future_groups = defaultdict(list)
    for row in rows:
        same_path[trajectories[row["labelId"]]].append(row)
        future_groups[future_key(row, inventory=False)].append(row)
    terminal = [row for row in rows if row["terminalScore"] is not None]
    terminal_signature = sorted((future_key(row), row["score"], row["terminalScore"]) for row in terminal)
    terminal_digest = sha256(json.dumps(terminal_signature, separators=(",", ":")).encode("utf-8")).hexdigest()
    best = max((row["terminalScore"] for row in terminal), default=None)
    margin = abs(best) * score_band if best is not None else 0
    near_best = [row for row in terminal if row["terminalScore"] >= best - margin] if best is not None else []
    paths = sorted({(row["position"], trajectories[row["labelId"]]) for row in near_best})
    reward_sets = {(row["position"], row["rewardNodeMask"]) for row in near_best}
    frontier_count = sum(len(pareto_labels(group)) for group in future_groups.values())
    close_path_excess = 0
    for group in same_path.values():
        scores = sorted(row["score"] for row in group)
        if scores and scores[-1] - scores[0] <= margin:
            close_path_excess += len(group) - 1
    examples = []
    for path, group in sorted(same_path.items(), key=lambda pair: len(pair[1]), reverse=True)[:3]:
        examples.append({"deltas": path, "labels": len(group),
                         "scoreRange": [min(row["score"] for row in group), max(row["score"] for row in group)],
                         "inventoryVariants": len({tuple(row["canonicalUses"]) for row in group}),
                         "apValues": sorted({row["actionPoints"] for row in group})})
    return {
        "generatedLabels": len(records), "activeFutureLabels": len(rows),
        "supersededLabels": len(records) - len(rows),
        "exactGeometricTrajectories": len(same_path),
        "sameTrajectoryExcessLabels": len(rows) - len(same_path),
        "sameTrajectoryCloseScoreExcessLabels": close_path_excess,
        "futureGroupsIgnoringInventory": len(future_groups),
        "hypotheticalInventoryScoreParetoLabels": frontier_count,
        "hypotheticalDominatedLabels": len(rows) - frontier_count,
        "terminalLabels": len(terminal), "bestTerminalScore": best,
        "terminalStateDigest": terminal_digest,
        "zeroAPDeadEndLabels": sum(row["actionPoints"] == 0 and row["terminalScore"] is None for row in rows),
        "nearBestBand": score_band, "nearBestScoreMargin": margin,
        "nearBestTerminalLabels": len(near_best), "nearBestDistinctTrajectories": len(paths),
        "nearBestRewardNodeSets": len(reward_sets),
        "nearBestOneEditClusterSizes": near_trajectory_clusters(paths),
        "sameTrajectoryExamples": examples,
        "diagnostics": result["searchDiagnostics"],
        "searchComplete": result["searchComplete"],
        "interpretation": "similarity is diagnostic only; removing different inventories or score-close paths is not proven safe",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--playtime", type=Path)
    parser.add_argument("--action-points", type=int, default=2)
    parser.add_argument("--max-states", type=int, default=50000)
    parser.add_argument("--search-mode", choices=("reference", "target"), default="reference")
    parser.add_argument("--score-band", type=float, default=.01)
    parser.add_argument("--out", type=Path, default=ROOT / "work/snapshot_similarity")
    args = parser.parse_args()
    if not 0 <= args.score_band <= 1:
        parser.error("score-band must be in [0,1]")
    if args.playtime:
        game_map, state = route_inputs(json.loads(args.playtime.read_text(encoding="utf-8")))
        scope = "confirmed playtime; read-only diagnostic"
    else:
        game_map, state = third_floor_inputs()
        state["actionPoints"] = args.action_points
        scope = "archived III geometry, synthetic resources and six processing items; random teleport excluded"
    state["maxStates"] = args.max_states
    state["searchMode"] = args.search_mode
    records = []
    started = perf_counter()
    result = RoutePlanner(game_map).plan(state, on_generate=records.append)
    search_seconds = perf_counter() - started
    started = perf_counter()
    report = summarize(records, result, {row["id"]: tuple(row["coord"]) for row in game_map["nodes"]},
                       score_band=args.score_band)
    report.update(scope=scope, actionPoints=state["actionPoints"], searchSeconds=round(search_seconds, 4),
                  analysisSeconds=round(perf_counter() - started, 4), budget=args.max_states,
                  searchMode=args.search_mode)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Snapshot Similarity Audit", "", scope, "",
             "| Metric | Value |", "| --- | ---: |"]
    for name, value in report.items():
        if isinstance(value, (bool, int, float)):
            lines.append(f"| {name} | {value} |")
    lines += ["", "Exact trajectories keep entry and portal-transfer deltas, but ignore item identity.",
              "One-edit clusters are connected neighborhoods, not pairwise-identical paths.",
              "Score proximity uses 1% of the best terminal score by default, not a gameplay probability.",
              "Hypothetical Pareto removes lower-score, componentwise-lower inventory in otherwise identical future groups.",
              "Dead-end and hypothetical Pareto counts overlap; they cannot be added as independent savings.",
              "This audit itself does not prune. Reference mode disables target-only dead-end pruning; terminal figures exclude treehole-entry branches."]
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items()
                     if key not in {"diagnostics", "sameTrajectoryExamples", "nearBestOneEditClusterSizes"}},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
