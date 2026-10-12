"""Stable IDs and reconciliation for the local Blackflow catalog."""

from collections import defaultdict
import re


CATEGORY_ORDER = (
    "relic",
    "component",
    "dystopia",
    "utopia",
    "squad",
    "node_type",
    "node_mark",
)


def normalized_name(name: str) -> str:
    return " ".join(name.split())


def id_number(category: str, item_id: str) -> int:
    match = re.fullmatch(rf"{re.escape(category)}_(\d+)", item_id)
    if not match:
        raise ValueError(f"Invalid {category} ID: {item_id}; migrate the catalog first")
    return int(match.group(1))


def deduplicate_cards(category: str, fetched: list[dict], previous: list[dict]) -> list[dict]:
    """Collapse duplicate page cards by name, retaining their icon variants."""
    groups = defaultdict(list)
    for row in fetched:
        if row["category"] != category:
            raise ValueError(f"Unexpected category in fetched card: {row}")
        groups[normalized_name(row["name"])].append(row)
    old_by_name = {normalized_name(row["name"]): row for row in previous}
    result = []
    for name, group in groups.items():
        if len({row.get("effect") for row in group}) > 1:
            raise ValueError(f"Same-name {category} cards have different effects: {name}")
        old = old_by_name.get(name)
        preferred = old["sourceId"] if old else None
        group.sort(key=lambda row: (row["sourceId"] != preferred, row["sourceId"]))
        main = dict(group[0])
        main["sourceAliases"] = [row["sourceId"] for row in group[1:]]
        main["_variants"] = group
        result.append(main)
    return result


def merge_category(
    category: str,
    previous: list[dict],
    fetched: list[dict],
    *,
    require_complete: bool = True,
) -> tuple[list[dict], list[str]]:
    """Keep existing IDs through source reordering; append only genuinely new cards."""
    old_by_source = {}
    old_by_name = defaultdict(list)
    old_by_id = {}
    next_number = 1
    for row in previous:
        if row["category"] != category:
            raise ValueError(f"Unexpected category in previous catalog: {row['id']}")
        number = id_number(category, row["id"])
        next_number = max(next_number, number + 1)
        if row["id"] in old_by_id or row["sourceId"] in old_by_source:
            raise ValueError(f"Duplicate old ID or source ID in {category}")
        old_by_id[row["id"]] = row
        old_by_source[row["sourceId"]] = row
        old_by_name[normalized_name(row["name"])].append(row)

    fetched_sources = [row["sourceId"] for row in fetched]
    if len(fetched_sources) != len(set(fetched_sources)):
        raise ValueError(f"Duplicate source ID in fetched {category} cards")
    if len({normalized_name(row["name"]) for row in fetched}) != len(fetched):
        raise ValueError(f"Fetched {category} cards must be deduplicated by name first")
    updated_by_id = {}
    additions = []
    for row in fetched:
        if row["category"] != category or not row.get("name") or not row.get("sourceId"):
            raise ValueError(f"Incomplete fetched {category} card: {row}")
        source_match = old_by_source.get(row["sourceId"])
        name_matches = old_by_name[normalized_name(row["name"])]
        unique_name_match = name_matches[0] if len(name_matches) == 1 else None
        if source_match and unique_name_match and source_match["id"] != unique_name_match["id"]:
            raise ValueError(f"Conflicting name and source ID for {category}: {row['name']}")
        if source_match:
            match = source_match
        elif unique_name_match:
            match = unique_name_match
        elif name_matches:
            raise ValueError(f"Previous {category} catalog has duplicate name: {row['name']}")
        else:
            match = None

        if match:
            item_id = match["id"]
            if item_id in updated_by_id:
                raise ValueError(f"Two fetched cards matched {item_id}")
            updated_by_id[item_id] = {**match, **row, "id": item_id}
        else:
            item_id = f"{category}_{next_number:03d}"
            next_number += 1
            updated_by_id[item_id] = {**row, "id": item_id}
            additions.append(item_id)

    missing = set(old_by_id) - set(updated_by_id)
    if require_complete and missing:
        raise ValueError(f"Fetched {category} snapshot is missing existing IDs: {sorted(missing)}")
    if require_complete:
        ordered = [updated_by_id[row["id"]] for row in previous]
        ordered.extend(updated_by_id[item_id] for item_id in additions)
    else:
        ordered = list(updated_by_id.values())
    return ordered, additions
