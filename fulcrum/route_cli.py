from __future__ import annotations

import argparse
import json
from pathlib import Path

from .route_planner import RoutePlanner
from .playtime_route import route_inputs


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan Black Flow routes from a confirmed map and run snapshot.")
    parser.add_argument("--map", type=Path, help="JSON emitted by fulcrum.cli for a matched map.")
    parser.add_argument("--state", type=Path, help="Current position, action points, and item instances.")
    parser.add_argument("--playtime", type=Path, help="Use a confirmed Playtime snapshot instead of --map and --state.")
    parser.add_argument("--area-key", help="Area instance within --playtime; defaults to the current area.")
    parser.add_argument("--pursuit", action="store_true", help="Find routes that exhaust action points.")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--scoring-mode", choices=("snapshot", "legacy"), default="snapshot",
                        help="Playtime defaults to snapshot utility; legacy is for comparison.")
    parser.add_argument("--max-states", type=int, help="Search budget; incomplete results remain explicitly marked.")
    parser.add_argument("--search-mode", choices=("target", "reference"),
                        help="Target/inventory compression (default), or uncompressed comparison mode.")
    parser.add_argument("--no-allocation-dominance", action="store_true",
                        help="Keep incomparable and dominated inventories for allocation diagnostics.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.playtime:
        if args.map or args.state:
            parser.error("--playtime cannot be combined with --map or --state")
        map_result, state = route_inputs(json.loads(args.playtime.read_text(encoding="utf-8")),
                                         args.area_key, pursuit=args.pursuit, top_n=args.top_n,
                                         scoring_mode=args.scoring_mode)
    else:
        if not args.map or not args.state or args.area_key:
            parser.error("supply --playtime or both --map and --state")
        map_result = json.loads(args.map.read_text(encoding="utf-8"))
        state = json.loads(args.state.read_text(encoding="utf-8"))
    if args.search_mode:
        state["searchMode"] = args.search_mode
    if args.no_allocation_dominance:
        state["allocationDominance"] = False
    if args.scoring_mode == "legacy":
        state.pop("scoringContext", None)
    if args.max_states is not None:
        state["maxStates"] = args.max_states
    result = RoutePlanner(map_result).plan(state)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"mode={result['mode']} routes={len(result['routes'])} "
        f"treeholeBranches={len(result['treeholeBranches'])} "
        f"searchComplete={result['searchComplete']} output={args.out}"
    )
    return 0 if result["routes"] or result["treeholeBranches"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
