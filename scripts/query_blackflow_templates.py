from __future__ import annotations

import argparse
import json
from collections import deque
from pathlib import Path


DEFAULT_DATA_PATH = Path("data/blackflow_map_templates.json")


def load_data(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slot_key(slot: list[int]) -> str:
    return f"{slot[0]}:{slot[1]}"


def validate_template(template: dict) -> list[str]:
    errors: list[str] = []
    occupied = {slot_key(slot) for slot in template["occupiedSlots"]}

    if slot_key(template["startSlot"]) not in occupied:
        errors.append("startSlot is not occupied")

    for slot in template.get("terminalSlots", []):
        if slot_key(slot) not in occupied:
            errors.append(f"terminalSlot {slot} is not occupied")

    for edge in template.get("edges", []):
        if len(edge) != 2:
            errors.append(f"edge {edge} does not have two endpoints")
            continue
        a, b = edge
        if slot_key(a) not in occupied or slot_key(b) not in occupied:
            errors.append(f"edge {edge} endpoint is not occupied")
        if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            errors.append(f"edge {edge} is not orthogonally adjacent")

    if occupied:
        adjacency = {key: set() for key in occupied}
        for a, b in template.get("edges", []):
            ak, bk = slot_key(a), slot_key(b)
            if ak in adjacency and bk in adjacency:
                adjacency[ak].add(bk)
                adjacency[bk].add(ak)
        start = slot_key(template["startSlot"])
        seen = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        if seen != occupied:
            errors.append(f"graph is disconnected: {len(seen)}/{len(occupied)} reachable from start")

    return errors


def print_regions(data: dict) -> None:
    for region in data["regions"]:
        shapes = ", ".join(data["summary"][region["id"]]["gridShapes"])
        print(f'{region["id"]:30} {region["name"]}  templates={len(region["templates"]):2d}  shapes={shapes}')


def print_region(data: dict, region_id: str) -> None:
    region = next((region for region in data["regions"] if region["id"] == region_id), None)
    if region is None:
        raise SystemExit(f"unknown region: {region_id}")
    print(f'{region["name"]} ({region["id"]})')
    for template in region["templates"]:
        shape = f'{template["gridShape"][0]}x{template["gridShape"][1]}'
        start = template["startSlot"]
        terminals = template.get("terminalSlots", [])
        fixed = ", ".join(f'{node["type"]}@{node["slot"]}' for node in template.get("fixedNodes", [])) or "-"
        shared = " shared" if template.get("sharedAcrossTreeholeFloors") else ""
        print(
            f'  {template["id"]:32} source={template["sourceId"]:<28} '
            f'shape={shape:<5} slots={template["slotCount"]:2d} edges={template["edgeCount"]:2d} '
            f'start={start} terminals={terminals} fixed={fixed}{shared}'
        )


def print_template(data: dict, template_id: str) -> None:
    for region in data["regions"]:
        for template in region["templates"]:
            if template["id"] == template_id:
                print(json.dumps({"region": region["id"], **template}, ensure_ascii=False, indent=2))
                return
    raise SystemExit(f"unknown template: {template_id}")


def validate_all(data: dict) -> int:
    problem_count = 0
    checked_ids: set[str] = set()
    for region in data["regions"]:
        for template in region["templates"]:
            key = template["id"]
            if key in checked_ids:
                continue
            checked_ids.add(key)
            errors = validate_template(template)
            if errors:
                problem_count += 1
                print(f'{template["id"]}: FAIL')
                for error in errors:
                    print(f"  - {error}")
    print(f"validated {len(checked_ids)} unique templates; problems={problem_count}")
    return 1 if problem_count else 0


def interactive_shell(data: dict) -> None:
    print("Blackflow template shell. Commands: regions, region <id>, template <id>, validate, quit")
    while True:
        try:
            command = input("> ").strip()
        except EOFError:
            print()
            return
        if not command:
            continue
        if command in {"q", "quit", "exit"}:
            return
        if command == "regions":
            print_regions(data)
        elif command.startswith("region "):
            print_region(data, command.split(maxsplit=1)[1])
        elif command.startswith("template "):
            print_template(data, command.split(maxsplit=1)[1])
        elif command == "validate":
            validate_all(data)
        else:
            print("unknown command")


def main() -> int:
    parser = argparse.ArgumentParser(description="Query blackflow map template rules.")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument("--list-regions", action="store_true")
    parser.add_argument("--region")
    parser.add_argument("--template")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    data = load_data(args.data)
    if args.list_regions:
        print_regions(data)
    if args.region:
        print_region(data, args.region)
    if args.template:
        print_template(data, args.template)
    exit_code = 0
    if args.validate:
        exit_code = validate_all(data)
    if args.interactive:
        interactive_shell(data)
    if not any([args.list_regions, args.region, args.template, args.validate, args.interactive]):
        parser.print_help()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
