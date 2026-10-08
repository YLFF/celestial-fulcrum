"""Compare target/inventory compression with the uncompressed reference search."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.route_planner import RoutePlanner
from scripts.audit_route_search import TracedPlanner, inputs


def summarize(result: dict) -> dict:
    return {
        "generatedStates": result["generatedStates"], "expandedStates": result["expandedStates"],
        "searchComplete": result["searchComplete"],
        "bestScore": max((r["metrics"]["weightedValue"] for r in result["routes"]), default=None),
        "diagnostics": result["searchDiagnostics"],
    }


def small_case(ap: int, repeats: int) -> dict:
    game_map, state = inputs(ap)
    cases = {}
    tier_sets = {}
    for mode in ("reference", "target"):
        samples = []
        planner = RoutePlanner(game_map)
        for _ in range(repeats):
            gc.collect()
            started = perf_counter()
            result = planner.plan({**state, "searchMode": mode, "maxStates": 500000})
            samples.append(perf_counter() - started)
        if not result["searchComplete"]:
            raise RuntimeError("Small-case comparison must be exhaustive")
        cases[mode] = {**summarize(result), "secondsMedian": round(statistics.median(samples), 4),
                       "secondsSamples": [round(s, 4) for s in samples]}
        traced = TracedPlanner(game_map)
        trace_result = traced.plan({**state, "searchMode": mode, "maxStates": 500000}, on_expand=traced.observe)
        if not trace_result["searchComplete"]:
            raise RuntimeError("Trace did not finish")
        best = cases[mode]["bestScore"]
        tier_sets[mode] = {t["rewardNodeMask"] for t in traced.terminals if t["score"] >= 0.95 * best}
        cases[mode]["topTierRewardSets"] = len(tier_sets[mode])
        del traced, trace_result
    missing = tier_sets["reference"] - tier_sets["target"]
    if cases["reference"]["bestScore"] != cases["target"]["bestScore"] or missing:
        raise RuntimeError(f"Optimal score or high-value node sets lost: {sorted(missing)}")
    return {"templateId": game_map["templateId"], "nodes": len(game_map["nodes"]),
            "actionPoints": ap, "items": len(state["items"]), "cases": cases,
            "highValueRewardSetsLost": len(missing),
            "highValueDefinition": ">=95% of exhaustive reference best score; distinct reward-node sets"}


def large_case(profile: str, cap: int, repeats: int) -> dict:
    cases = {}
    for mode in ("reference", "target"):
        samples = []
        for _ in range(repeats):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts/benchmark_route_planner.py"), "--case", profile,
                 "--max-states", str(cap), "--search-mode", mode],
                check=True, capture_output=True, text=True,
            )
            record = json.loads(completed.stdout)
            samples.append(record["seconds"])
        cases[mode] = {**record, "secondsMedian": round(statistics.median(samples), 4), "secondsSamples": samples}
    return {"profile": profile, "maxStates": cap, "cases": cases,
            "notAnOptimalityProof": not all(case["searchComplete"] for case in cases.values())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--max-states", type=int, default=50000)
    parser.add_argument("--out", type=Path, default=ROOT / "work/route_optimization_comparison.json")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    report = {"python": sys.version, "platform": platform.platform(), "small": [], "large": [],
              "limitations": ["Synthetic node assignments; current fixed heuristic score only",
                              "Random component_019 excluded from guaranteed movement",
                              "Reference and target share corrected end/pass and visibility rules",
                              "Budget-limited fifth-floor scores do not prove global optimality",
                              "Order/resource-dependent scoring needs additional state before dominance is reused"]}
    for ap in (2, 3):
        case = small_case(ap, args.repeats)
        report["small"].append(case)
        print(json.dumps({"floor3": ap, "results": {k: {f: v[f] for f in (
            "generatedStates", "expandedStates", "secondsMedian", "bestScore", "topTierRewardSets")}
            for k, v in case["cases"].items()}, "highValueRewardSetsLost": case["highValueRewardSetsLost"]}), flush=True)
    for profile in ("none", "engines", "mixed"):
        case = large_case(profile, args.max_states, args.repeats)
        report["large"].append(case)
        print(json.dumps({"floor5": profile, "results": {k: {f: v[f] for f in (
            "generatedStates", "expandedStates", "secondsMedian", "topRouteScores", "searchComplete")}
            for k, v in case["cases"].items()}}), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
