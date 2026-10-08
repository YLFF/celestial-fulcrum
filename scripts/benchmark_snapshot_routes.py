"""Replay archived geometry with synthetic resources; never edit live runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.component_box import add_component
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime
from fulcrum.route_planner import RoutePlanner


def run_case(name, game_map, state, out):
    started = perf_counter()
    result = RoutePlanner(game_map).plan(state)
    elapsed = perf_counter() - started
    (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"case": name, "seconds": round(elapsed, 4), "expanded": result["expandedStates"],
            "generated": result["generatedStates"], "complete": result["searchComplete"],
            "routes": len(result["routes"]), "best": result["routes"][0]["metrics"]["weightedValue"] if result["routes"] else None,
            "items": len(state["items"]), "actionPoints": state["actionPoints"]}


def third_floor_inputs(*, with_items=True):
    observation = json.loads((ROOT / "work/map_floor3.json").read_text(encoding="utf-8"))
    playtime = new_playtime("synthetic-third-floor")
    playtime["resources"].update(level=4, experience={"current": 0, "max": 40}, hope=10,
                               originiumIngot=16, life={"current": 8, "max": 8})
    instance = merge_map_observation(playtime, "III", observation)
    instance["playerPosition"], instance["actionPoints"] = "0,0", 2
    instance["strategy"]["scoringOptions"] = {"teamCounts": {"totalOperators": 6, "sixStars": 4, "elite2SixStars": 2}}
    if with_items:
        for component in ("component_018", "component_015", "component_021", "component_019", "component_013", "component_016"):
            add_component(playtime["componentBox"], component, estimated_value=10)
    return route_inputs(playtime)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "work/snapshot_scoring")
    parser.add_argument("--max-states", type=int, default=50000)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    opening = json.loads((ROOT / "work/opening_shop_verified/opening-shop-two-cats-pegasus.json").read_text(encoding="utf-8"))
    game_map, inputs = route_inputs(opening)
    rows = [run_case("archived_opening", game_map, {**inputs, "maxStates": args.max_states}, args.out)]
    game_map, inputs = third_floor_inputs(with_items=False)
    rows.append(run_case("third_two_ap_no_items", game_map, {**inputs, "maxStates": args.max_states}, args.out))
    game_map, inputs = third_floor_inputs()
    for mode in ("target", "reference"):
        rows.append(run_case(f"third_two_ap_six_items_{mode}", game_map,
                             {**inputs, "maxStates": args.max_states, "searchMode": mode}, args.out))
    report = {"cases": rows, "scope": "archived opening plus artificial third-floor resources/items; not a new live-game test",
              "budget": args.max_states, "optimality": "only complete searches establish the best score under this approximate scoring model"}
    (args.out / "benchmark.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Snapshot Route Benchmark", "", report["scope"], "", f"State budget: {args.max_states}.", "",
             "| Case | Seconds | Expanded | Generated | Complete | Best score |", "| --- | ---: | ---: | ---: | --- | ---: |"]
    lines += [f"| {r['case']} | {r['seconds']} | {r['expanded']} | {r['generated']} | {r['complete']} | {r['best']} |" for r in rows]
    lines += ["", report["optimality"], "", "Random small-teleport items remain excluded from guaranteed routes; they are retained as inventory/entry sacrifices."]
    (args.out / "benchmark.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
