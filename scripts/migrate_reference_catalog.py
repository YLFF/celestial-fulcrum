"""One-time migration to stable file-safe IDs and one entry per display name."""

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from reference_catalog import CATEGORY_ORDER, normalized_name


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "lubiao_reference_catalog.json"
BACKUP = ROOT / "data" / "lubiao_reference_catalog.v1.json"
ASSETS = ROOT / "assets" / "lubiao"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    original = CATALOG.read_bytes()
    catalog = json.loads(original)
    if catalog.get("schemaVersion") == 2:
        print("Catalog already uses stable IDs")
        return
    if catalog.get("schemaVersion") != 1 or BACKUP.exists():
        raise RuntimeError("Unexpected catalog version or existing v1 backup")

    entries = []
    moves = []
    categories = {}
    for category in CATEGORY_ORDER:
        old_rows = [row for row in catalog["entries"] if row["category"] == category]
        groups = defaultdict(list)
        for row in old_rows:
            groups[normalized_name(row["name"])].append(row)
        categories[category] = {
            "label": catalog["categories"][category]["label"],
            "minimumSourceCardCount": catalog["categories"][category]["expectedCount"],
            "sourceCardCount": len(old_rows),
            "entryCount": len(groups),
        }
        for number, group in enumerate(groups.values(), 1):
            if len({row.get("effect") for row in group}) > 1:
                raise RuntimeError(f"Same-name cards have different effects: {category} {group[0]['name']}")
            item_id = f"{category}_{number:03d}"
            primary = dict(group[0])
            primary["id"] = item_id
            primary["legacyIds"] = [row["id"] for row in group]
            primary["sourceAliases"] = [row["sourceId"] for row in group[1:]]
            primary["imageVariants"] = []
            for variant_number, row in enumerate(group, 1):
                image_path = row.get("imagePath")
                if not image_path:
                    if variant_number > 1:
                        raise RuntimeError(f"Missing duplicate image: {row['id']}")
                    primary["imagePath"] = None
                    continue
                suffix = "" if variant_number == 1 else f"__{variant_number:02d}"
                destination = ASSETS / category / f"{item_id}{suffix}.png"
                source = ROOT / image_path
                moves.append((source, destination))
                new_path = destination.relative_to(ROOT).as_posix()
                if variant_number == 1:
                    primary["imagePath"] = new_path
                else:
                    primary["imageVariants"].append({
                        "sourceId": row["sourceId"],
                        "assetUrl": row.get("assetUrl"),
                        "imageKind": row.get("imageKind"),
                        "imagePath": new_path,
                        "imageStatus": row["imageStatus"],
                    })
            entries.append(primary)

    if len(entries) != 339 or len(moves) != 347:
        raise RuntimeError(f"Unexpected migration size: {len(entries)} entries, {len(moves)} images")
    asset_root = ASSETS.resolve()
    sources = [source.resolve() for source, _ in moves]
    targets = [target.resolve() for _, target in moves]
    if len(set(sources)) != len(sources) or len(set(targets)) != len(targets):
        raise RuntimeError("Duplicate image source or destination")
    for source, target in moves:
        if not source.resolve().is_relative_to(asset_root) or not target.resolve().is_relative_to(asset_root):
            raise RuntimeError(f"Image move escapes asset directory: {source} -> {target}")
        if source != target and source.exists() and target.exists():
            raise RuntimeError(f"Destination already exists: {target}")
        if not source.exists() and not target.exists():
            raise RuntimeError(f"Missing image: {source}")

    BACKUP.write_bytes(original)
    for source, target in moves:
        if source.exists() and source != target:
            source.rename(target)
    catalog.update({
        "schemaVersion": 2,
        "migratedAt": datetime.now(timezone.utc).isoformat(),
        "categories": categories,
        "entries": entries,
    })
    temporary = CATALOG.with_suffix(".new.json")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CATALOG)
    print(f"Migrated {len(entries)} entries and {len(moves)} images; v1 backup: {BACKUP}")


if __name__ == "__main__":
    main()
