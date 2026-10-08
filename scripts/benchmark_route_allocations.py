"""Compare allocation/terminal optimizations on archived geometry with synthetic resources."""

from copy import deepcopy
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.route_planner import RoutePlanner
from scripts.benchmark_snapshot_routes import third_floor_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action-points", type=int, default=2)
    parser.add_argument("--max-states", type=int, default=500000)
    parser.add_argument("--out", type=Path, default=ROOT / "work/route_allocations")
    args = parser.parse_args()
    game_map, initial = third_floor_inputs()
    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, mode, free, dominance in (
        ("tight_reference", "reference", 0, True), ("tight_target", "target", 0, True),
        ("spacious_reference", "reference", 8, True),
        ("spacious_cache_only", "target", 8, False), ("spacious_target", "target", 8, True),
    ):
        inputs = deepcopy(initial)
        inputs.update(actionPoints=args.action_points, pursuit=True, maxStates=args.max_states,
                      searchMode=mode, componentBoxFreeSlots=free, allocationDominance=dominance)
        inputs["scoringContext"]["componentBox"]["capacity"] = len(inputs["scoringContext"]["componentBox"]["items"]) + free
        started = perf_counter()
        result = RoutePlanner(game_map).plan(inputs)
        elapsed = perf_counter() - started
        diagnostics = result["searchDiagnostics"]
        row = {"case": name, "seconds": round(elapsed, 4), "generated": result["generatedStates"],
               "expanded": result["expandedStates"], "complete": result["searchComplete"],
               "best": result["routes"][0]["metrics"]["weightedValue"] if result["routes"] else None,
               "topScores": [route["metrics"]["weightedValue"] for route in result["routes"]],
               "inventoryDominance": diagnostics["inventoryDominanceEnabled"],
               "dominatedAllocations": diagnostics["dominatedInventoryStatesSkipped"],
               "pursuitTerminalsPruned": diagnostics["pursuitTerminalsPruned"],
               "pursuitTerminalsSettled": diagnostics["pursuitTerminalsSettledWithoutQueue"],
               "geometryReuse": diagnostics["targetEffectsReused"],
               "scoreReuse": diagnostics["sharedScoreTransitionsReused"]}
        rows.append(row)
        (args.out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    by_name = {row["case"]: row for row in rows}
    checks = {}
    for target, reference in (("tight_target", "tight_reference"),
                              ("spacious_cache_only", "spacious_reference"), ("spacious_target", "spacious_reference")):
        a, b = by_name[target], by_name[reference]
        checks[target] = {"bestScoreEqual": a["best"] == b["best"],
                          "bothComplete": a["complete"] and b["complete"],
                          "topScoreListEqual": a["topScores"] == b["topScores"]}
    report = {"scope": "III archived geometry; synthetic resources, six processing items, pursuit; random teleport excluded",
              "actionPoints": args.action_points, "budget": args.max_states, "cases": rows, "comparisons": checks}
    (args.out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Route Allocation Benchmark", "", report["scope"], "",
             "| Case | Generated | Expanded | Seconds | Complete | Best |", "| --- | ---: | ---: | ---: | --- | ---: |"]
    lines += [f"| {row['case']} | {row['generated']} | {row['expanded']} | {row['seconds']} | {row['complete']} | {row['best']} |" for row in rows]
    lines += ["", "Budget-limited comparisons only compare observed results, not certified global optima.",
              "Terminal pruning compares completed results, not low-scoring prefixes."]
    (args.out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
