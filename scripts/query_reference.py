"""Query the local Blackflow text-and-image catalog by category or ID."""

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "lubiao_reference_catalog.json"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", help="relic, component, dystopia, utopia, squad, node_type, node_mark")
    parser.add_argument("--id", help="Exact category ID, such as relic_001")
    parser.add_argument("--name", help="Substring match on the Chinese display name")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
    if args.category and args.category not in catalog["categories"]:
        parser.error(f"Unknown category: {args.category}")
    rows = [
        row for row in catalog["entries"]
        if (not args.category or row["category"] == args.category)
        and (not args.id or row["id"] == args.id)
        and (not args.name or args.name in row["name"])
    ]
    for row in rows[: args.limit]:
        print(f"{row['id']}  {row['name']}")
        if args.id or args.name:
            for key in ("effect", "condition", "nodeBehavior", "notes", "subtype", "rarity"):
                if row.get(key):
                    print(f"  {key}: {row[key]}")
            print(f"  image: {row['imagePath'] or row['imageStatus']}")
            print(f"  source: {row['sourceUrl']}")
    print(f"Matched {len(rows)}; shown {min(len(rows), args.limit)}")


if __name__ == "__main__":
    main()
