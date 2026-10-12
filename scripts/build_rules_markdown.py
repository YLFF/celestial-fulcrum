"""Read-only audit of node count and distance tables in the rulebook."""

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "data" / "blackflow_node_generation_rules.json"
DOCUMENT = ROOT / "BLACKFLOW_RULEBOOK.md"


def format_value(value: dict | None) -> str:
    if value is None:
        return "—"
    if value["kind"] == "unknown":
        return "未定"
    if value["kind"] == "oneOf":
        return "或".join(str(number) for number in value["values"])
    if value["kind"] == "range":
        low, high = value["minimum"], value["maximum"]
        return f"{low}+" if high is None else str(low) if low == high else f"{low}–{high}"
    raise ValueError(f"Unknown range kind: {value['kind']}")


def parse_table(content: str, number: int, columns: tuple[str, ...]) -> dict[str, list[str]]:
    heading = re.search(rf"(?m)^## {number}\. [^\n]*\n", content)
    if not heading:
        raise RuntimeError(f"Missing rulebook section {number}")
    following = re.search(r"(?m)^## \d+\. ", content[heading.end():])
    end = heading.end() + following.start() if following else len(content)
    lines = [line for line in content[heading.end():end].splitlines() if line.startswith("| ")]
    expected_header = ["节点", *columns]
    if len(lines) < 2 or [cell.strip() for cell in lines[0].strip("|").split("|")] != expected_header:
        raise RuntimeError(f"Unexpected table header in section {number}")
    rows = {}
    for line in lines[2:]:
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != len(expected_header) or cells[0] in rows:
            raise RuntimeError(f"Invalid or duplicate table row in section {number}: {line}")
        rows[cells[0]] = cells[1:]
    return rows


def main() -> None:
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    if not rules["countRanges"] or not rules["shortestDistanceFromStart"]:
        raise RuntimeError("Node generation rules are empty")
    content = DOCUMENT.read_text(encoding="utf-8")
    sections = (
        (5, "countRanges", ("I", "II", "III", "IV", "V")),
        (6, "shortestDistanceFromStart", ("I", "II", "III", "IV", "IV追忆", "V")),
    )
    differences = []
    for number, key, columns in sections:
        actual = parse_table(content, number, columns)
        expected = {
            row["label"]: [format_value(row["values"].get(column)) for column in columns]
            for row in rules[key]
        }
        for label in sorted(actual.keys() | expected.keys()):
            if actual.get(label) != expected.get(label):
                differences.append(f"section {number}, {label}: Markdown={actual.get(label)}, JSON={expected.get(label)}")
    print(f"Read-only audit: {len(rules['countRanges'])} count rows and {len(rules['shortestDistanceFromStart'])} distance rows; no Markdown files written.")
    if differences:
        raise RuntimeError("Rule tables differ from structured data:\n" + "\n".join(differences))


if __name__ == "__main__":
    main()
