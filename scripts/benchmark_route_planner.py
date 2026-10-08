"""Synthetic large-floor route benchmark; does not change game or Playtime data."""

from __future__ import annotations

import argparse
import gc
import json
import platform
import subprocess
import sys
from collections import deque
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.route_planner import RoutePlanner


def peak_memory_mib() -> float | None:
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage",
            )
        ]

    get_process = ctypes.windll.kernel32.GetCurrentProcess
    get_process.restype = wintypes.HANDLE
    get_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    get_info.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not get_info(get_process(), ctypes.byref(counters), counters.cb):
        return None
    return round(counters.PeakWorkingSetSize / 1024**2, 2)


def inputs(profile: str) -> tuple[dict, dict]:
    template = max(TemplateCatalog().candidates("main", 5), key=lambda item: len(item.occupied_slots))
    ids = {slot: template.coord(slot).key for slot in template.occupied_slots}
    adjacent = {value: [] for value in ids.values()}
    edges = [[ids[a], ids[b]] for a, b in template.edges]
    for a, b in edges:
        adjacent[a].append(b)
        adjacent[b].append(a)
    distance = {"0,0": 0}
    queue = deque(distance)
    while queue:
        source = queue.popleft()
        for target in adjacent[source]:
            if target not in distance:
                distance[target] = distance[source] + 1
                queue.append(target)
    terminals = {ids[slot] for slot in template.terminal_slots}
    eligible = [key for key in ids.values() if key != "0,0" and key not in terminals and distance[key] > 1]
    hidden = {key: "unknown_mystery" if i < 12 else "unknown_ferocity" for i, key in enumerate(eligible[:16])}
    known_types = iter([
        "node_type_004", "node_type_013", "node_type_010", "node_type_011",
        "node_type_007", "node_type_007", "node_type_002", "node_type_002",
        "node_type_005", "node_type_008", "node_type_018",
    ])
    nodes = []
    for slot in template.occupied_slots:
        node_id = ids[slot]
        category = (
            "start" if node_id == "0,0" else "node_type_003" if node_id in terminals else
            hidden[node_id] if node_id in hidden else "node_type_001" if distance[node_id] == 1 else
            next(known_types, "node_type_020")
        )
        coord = template.coord(slot)
        nodes.append({"id": node_id, "coord": [coord.x, coord.y], "categoryId": category,
                      "visibility": "hidden" if node_id in hidden else "revealed"})
    item_types = {
        "none": [],
        "engines": [("component_015", 3)] * 10,
        "mixed": [("component_013", 3), ("component_014", 1), ("component_015", 3),
                  ("component_016", 2), ("component_017", 3), ("component_018", 2),
                  ("component_020", 1), ("component_021", 2), ("component_023", 1),
                  ("component_024", 1)],
    }[profile]
    state = {
        "position": "0,0", "completedNodes": ["0,0"], "actionPoints": 8, "topN": 5,
        "items": [{"instanceId": f"part-{i + 1}", "componentId": item_id, "remainingUses": uses}
                  for i, (item_id, uses) in enumerate(item_types)],
    }
    return {"success": True, "templateId": template.id, "nodes": nodes, "edges": edges}, state


def run_case(profile: str, cap: int, search_mode: str = "target") -> dict:
    game_map, state = inputs(profile)
    state["maxStates"] = cap
    state["searchMode"] = search_mode
    gc.collect()
    started = perf_counter()
    result = RoutePlanner(game_map).plan(state)
    elapsed = perf_counter() - started
    return {
        "profile": profile, "searchMode": search_mode, "synthetic": True, "templateId": game_map["templateId"],
        "nodes": len(game_map["nodes"]), "edges": len(game_map["edges"]),
        "unknownNodes": sum(node["categoryId"].startswith("unknown_") for node in game_map["nodes"]),
        "processingItems": len(state["items"]), "initialActionPoints": state["actionPoints"],
        "maxStates": cap, "seconds": round(elapsed, 4), "peakWorkingSetMiB": peak_memory_mib(),
        "expandedStates": result["expandedStates"], "generatedStates": result["generatedStates"],
        "searchComplete": result["searchComplete"], "routes": len(result["routes"]),
        "treeholeBranches": len(result["treeholeBranches"]),
        "diagnostics": result.get("searchDiagnostics", {}),
        "topRouteScores": [route["metrics"]["weightedValue"] for route in result["routes"]],
        "differentRewardSets": len({
            frozenset(node for step in route["steps"] for node in step["newNodes"])
            for route in result["routes"]
        }),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("none", "engines", "mixed"))
    parser.add_argument("--max-states", type=int, default=50000)
    parser.add_argument("--search-mode", choices=("target", "reference"), default="target")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.case:
        print(json.dumps(run_case(args.case, args.max_states, args.search_mode)))
        return
    results = []
    for profile in ("none", "engines", "mixed"):
        command = [sys.executable, str(Path(__file__).resolve()), "--case", profile,
                   "--max-states", str(args.max_states), "--search-mode", args.search_mode]
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
        record = json.loads(completed.stdout)
        results.append(record)
        print(json.dumps(record), flush=True)
    report = {"python": sys.version, "platform": platform.platform(), "cases": results,
              "limitations": ["Synthetic node assignments, not a real fifth-floor screenshot",
                              "Current fixed heuristic scorer, not the future resource scorer",
                              "Memory is peak process working set including Python runtime"]}
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
