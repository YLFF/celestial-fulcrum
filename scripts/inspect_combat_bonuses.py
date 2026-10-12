"""Export a read-only combat bonus report from a Playtime or state/context sample."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.combat_bonuses import render_combat_bonuses, summarize_combat_bonuses


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--operator", help="Stable operator instance ID")
    args = parser.parse_args()
    document = json.loads(args.input.read_text(encoding="utf-8-sig"))
    report = summarize_combat_bonuses(document.get("state", document), context=document.get("context"),
                                      operator_instance_id=args.operator)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.format == "json" else render_combat_bonuses(report)
    if args.output:
        if args.output.resolve() == args.input.resolve():
            parser.error("报告不能覆盖输入存档")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text, end="")


if __name__ == "__main__":
    main()
