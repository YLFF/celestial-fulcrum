"""Create a structured Playtime map state and its Markdown reading view."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.playtime_state import new_playtime
from fulcrum.playtime_view import render_standalone, replace_runtime_sections
from fulcrum.opening import SQUAD_NAMES


TEMPLATE = ROOT / "BLACKFLOW_PLAYTIME_TEMPLATE.md"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="ASCII letters, digits, hyphens and underscores only")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "runs")
    parser.add_argument("--difficulty", type=int, default=15)
    parser.add_argument("--investment-balance", type=int, default=99, help="confirmed investment withdrawal budget")
    parser.add_argument("--squad", choices=sorted(SQUAD_NAMES))
    parser.add_argument("--cocoon", action="append", default=[], help="cocoon name or ID, optionally =count; repeatable")
    parser.add_argument("--tech-attack-percent", type=float, default=20, help="account technology attack bonus in percent")
    parser.add_argument("--tech-defense-percent", type=float, default=20, help="account technology defense bonus in percent")
    parser.add_argument("--tech-hp-percent", type=float, default=25, help="account technology unit HP bonus in percent")
    parser.add_argument("--no-lookout-split", action="store_true", help="account lookout Split technology is not unlocked")
    parser.add_argument("--initial-mechanist", choices=("normal", "temporary"),
                        help="confirm Mechanist in initial recruitment; otherwise add one-battle support")
    args = parser.parse_args()
    now = datetime.now().astimezone()
    run_id = args.run_id or now.strftime("run-%Y%m%d-%H%M%S")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        parser.error("--run-id must contain only ASCII letters, digits, hyphens and underscores")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{run_id}.md"
    state_output = output_dir / f"{run_id}.json"
    if output.exists() or state_output.exists():
        parser.error("run ID already exists in the output directory")
    timestamp = now.isoformat(timespec="seconds")
    cocoons = {}
    for raw in args.cocoon:
        name, separator, count_text = raw.partition("=")
        try:
            count = int(count_text) if separator else 1
        except ValueError:
            parser.error(f"invalid cocoon count: {raw}")
        cocoons[name] = cocoons.get(name, 0) + count
    try:
        state = new_playtime(
            run_id, difficulty=args.difficulty, squad_id=args.squad, cocoons=cocoons,
            technology_combat_bonuses={"attackPercent": args.tech_attack_percent,
                                       "defensePercent": args.tech_defense_percent,
                                       "maxHpPercent": args.tech_hp_percent},
            initial_operators=[{"name": "机械师", "source": args.initial_mechanist}] if args.initial_mechanist else None,
            investment_balance=args.investment_balance,
            lookout_split_unlocked=not args.no_lookout_split,
        )
    except ValueError as error:
        parser.error(str(error))
    state["createdAt"] = timestamp
    state["updatedAt"] = timestamp
    content = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("{{RUN_ID}}", run_id)
        .replace("{{CREATED_AT}}", timestamp)
        .replace("{{UPDATED_AT}}", timestamp)
        .replace(
            "(BLACKSTREAM_REFERENCE.md)",
            f"({os.path.relpath(ROOT / 'BLACKSTREAM_REFERENCE.md', output_dir).replace(os.sep, '/')})",
        )
    ) if TEMPLATE.is_file() else render_standalone(state)
    content = replace_runtime_sections(content, state)
    with state_output.open("x", encoding="utf-8", newline="\n") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)
        file.write("\n")
    with output.open("x", encoding="utf-8", newline="\n") as file:
        file.write(content)
    print(output)
    print(state_output)


if __name__ == "__main__":
    main()
