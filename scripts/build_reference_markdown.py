"""Read-only audit of catalog IDs against the manually maintained reference."""

import json
from pathlib import Path
import re

from reference_catalog import CATEGORY_ORDER, id_number, normalized_name


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "lubiao_reference_catalog.json"
ENCOUNTERS = ROOT / "data" / "blackstream_encounter_pool.json"
DOCUMENT = ROOT / "BLACKSTREAM_REFERENCE.md"


def main() -> None:
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    rows = data["entries"]
    if data.get("schemaVersion") != 2 or len(rows) != len({row["id"] for row in rows}):
        raise RuntimeError("Expected a v2 catalog with unique IDs")
    by_category = {}
    for category in CATEGORY_ORDER:
        selected = [row for row in rows if row["category"] == category]
        if not selected or [id_number(category, row["id"]) for row in selected] != list(range(1, len(selected) + 1)):
            raise RuntimeError(f"Non-sequential IDs in {category}")
        if len({normalized_name(row["name"]) for row in selected}) != len(selected):
            raise RuntimeError(f"Duplicate display name in {category}")
        by_category[category] = selected
    events = json.loads(ENCOUNTERS.read_text(encoding="utf-8"))["eventPool"]
    if len(events) < 23 or len({event["name"] for event in events}) != len(events):
        raise RuntimeError("Encounter pool is incomplete or has duplicate names")

    content = DOCUMENT.read_text(encoding="utf-8")
    missing = []
    for category in CATEGORY_ORDER:
        pattern = rf"(?m)^\| `({category}_\d+)` \|" if category == "component" else rf"(?m)^### ({category}_\d+)\b"
        body = content
        if category == "component":
            heading = re.search(r"(?m)^## \d+\. 零件[^\n]*\n", content)
            if not heading:
                raise RuntimeError("Missing component definitions")
            body = content[heading.end():]
            next_heading = re.search(r"(?m)^## \d+\. ", body)
            if next_heading:
                body = body[:next_heading.start()]
        present = re.findall(pattern, body)
        expected = {row["id"]: row["name"] for row in by_category[category]}
        if len(present) != len(set(present)):
            raise RuntimeError(f"Duplicate IDs in {category}")
        missing.extend(f"{item_id} {name}" for item_id, name in expected.items() if item_id not in present)
    event_heading = re.search(r"(?m)^## \d+\. 不期而遇事件表[^\n]*\n", content)
    if not event_heading:
        raise RuntimeError("Missing encounter table")
    event_body = content[event_heading.end():]
    next_heading = re.search(r"(?m)^## \d+\. ", event_body)
    if next_heading:
        event_body = event_body[:next_heading.start()]
    present_events = re.findall(r"(?m)^\| ([^|]+) \|", event_body)[2:]
    expected_events = [event["name"] for event in events]
    if len(present_events) != len(set(present_events)):
        raise RuntimeError("Duplicate encounter names")
    missing.extend(name for name in expected_events if name not in present_events)
    print(f"Read-only audit: {len(rows)} catalog entries, {len(events)} encounters; no Markdown files written.")
    if missing:
        raise RuntimeError("Manually add these entries to the reference:\n" + "\n".join(missing))


if __name__ == "__main__":
    main()
