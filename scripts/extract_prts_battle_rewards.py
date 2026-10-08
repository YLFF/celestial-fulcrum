"""Read PRTS reward/stage tables without regenerating hand-maintained documents."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
URL = "https://prts.wiki/w/" + quote("沉沦者的黑流树海")


def tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class PageTables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict] = []
        self.stack: list[dict] = []
        self.links: list[dict] = []
        self.link: dict | None = None
        self.xp_variant: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            self.stack.append({"attrs": attributes, "rows": [], "row": None, "cell": None})
        elif tag == "tr" and self.stack:
            table = self.stack[-1]
            table["row"] = []
            table["rows"].append(table["row"])
        elif tag in ("th", "td") and self.stack and self.stack[-1]["row"] is not None:
            cell = {"tag": tag, "attrs": attributes, "parts": [], "links": [], "experience": {}}
            self.stack[-1]["cell"] = cell
            self.stack[-1]["row"].append(cell)
        elif tag == "br":
            self.handle_data(" ")
        if tag == "a":
            self.link = {"href": attributes.get("href"), "title": attributes.get("title"), "parts": []}
        if tag == "span" and self.stack and self.stack[-1]["cell"] is not None:
            classes = attributes.get("class", "").split()
            if "is6-exp" in classes:
                self.xp_variant = "fullTechnology" if "is-fulltech" in classes else "base"

    def handle_data(self, data: str) -> None:
        for table in self.stack:
            if table["cell"] is not None:
                table["cell"]["parts"].append(data)
        if self.link is not None:
            self.link["parts"].append(data)
        if self.xp_variant and self.stack and self.stack[-1]["cell"] is not None:
            value = tidy(data)
            if value:
                if not value.isdecimal():
                    raise ValueError(f"Unexpected experience value: {value}")
                self.stack[-1]["cell"]["experience"][self.xp_variant] = int(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self.stack:
            table = self.stack.pop()
            for row in table["rows"]:
                for cell in row:
                    cell["text"] = tidy(" ".join(cell.pop("parts")))
            self.tables.append({"attrs": table["attrs"], "rows": table["rows"]})
        elif tag in ("td", "th") and self.stack:
            self.stack[-1]["cell"] = None
        elif tag == "tr" and self.stack:
            self.stack[-1]["row"] = None
        if tag == "a" and self.link is not None:
            link = {"href": self.link["href"], "title": self.link["title"],
                    "text": tidy("".join(self.link["parts"]))}
            self.links.append(link)
            if self.stack and self.stack[-1]["cell"] is not None:
                self.stack[-1]["cell"]["links"].append(link)
            self.link = None
        if tag == "span":
            self.xp_variant = None


REGIONS = {"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "0": "VI"}


def expanded_rows(table: dict) -> list[list[dict | None]]:
    """Expand HTML spans so inherited region and special-stage cells remain aligned."""
    matrix: list[list[dict | None]] = []
    for y, source_row in enumerate(table["rows"]):
        while len(matrix) <= y:
            matrix.append([])
        x = 0
        for cell in source_row:
            while x < len(matrix[y]) and matrix[y][x] is not None:
                x += 1
            width = int(cell["attrs"].get("colspan", "1"))
            height = int(cell["attrs"].get("rowspan", "1"))
            for row_index in range(y, y + height):
                while len(matrix) <= row_index:
                    matrix.append([])
                matrix[row_index].extend([None] * max(0, x + width - len(matrix[row_index])))
                for col in range(x, x + width):
                    if matrix[row_index][col] is not None:
                        raise ValueError("Overlapping HTML table spans")
                    matrix[row_index][col] = cell
            x += width
    return matrix


def money_value(cell: dict) -> dict:
    text = cell["text"].split()[-1]
    if text.isdecimal():
        return {"kind": "fixed", "value": int(text)}
    if re.fullmatch(r"\d+~\d+", text):
        low, high = map(int, text.split("~"))
        return {"kind": "range", "min": low, "max": high, "probabilities": None}
    if text == "?":
        return {"kind": "unknown", "value": None}
    raise ValueError(f"Unexpected money value: {cell['text']}")


def reward(xp_cell: dict, money_cell: dict) -> dict | None:
    if not xp_cell["experience"]:
        if set(xp_cell["text"]) <= {"—"}:
            return None
        raise ValueError(f"Missing separate base/full experience spans: {xp_cell['text']}")
    xp = xp_cell["experience"]
    if set(xp) != {"base", "fullTechnology"}:
        raise ValueError(f"Incomplete experience variants: {xp}")
    return {"experience": xp, "originiumIngot": money_value(money_cell)}


def extract_data(html: str) -> dict:
    parser = PageTables()
    parser.feed(html)
    parser.close()
    reward_tables = [table for table in parser.tables
                     if table["rows"] and "作战指挥经验值及源石锭数量" in table["rows"][0][0]["text"]]
    if len(reward_tables) != 1:
        raise ValueError("Expected exactly one reward table; preserve the previous dataset")
    regions: dict[str, dict] = {}
    special = []
    for row in expanded_rows(reward_tables[0]):
        first = row[0]
        if first["text"] in REGIONS:
            regions[REGIONS[first["text"]]] = {
                mode: reward(row[index], row[index + 1])
                for mode, index in (("normal", 1), ("emergency", 3), ("boss", 5), ("bossPursuit", 7))
            }
        elif first["tag"] == "td" and first["text"] != "/":
            stages = [link["text"] for link in first["links"] if (link["title"] or "").startswith("ISW-")]
            if not stages:
                raise ValueError(f"Special battle has no stage link: {first['text']}")
            special.append({"stages": stages, "context": first["text"],
                            "variant": "emergency" if "紧急作战版本" in row[5]["text"] else "normal",
                            **reward(row[5], row[7])})
    stage_regions: dict[str, str] = {}
    stage_groups: dict[str, list[str]] = {}
    for table in parser.tables:
        if not table["rows"]:
            continue
        heading = table["rows"][0][0]["text"]
        if not heading.startswith("ISW-"):
            continue
        group = heading
        for row in expanded_rows(table):
            if row[0] and row[0]["tag"] == "th" and row[0]["text"].startswith("ISW-"):
                group = row[0]["text"]
                continue
            stages = sorted({link["text"] for cell in row if cell for link in cell["links"]
                             if (link["title"] or "").startswith("ISW-")})
            stage_groups.setdefault(group, []).extend(stages)
            if "一般作战" in group and row[0] and row[0]["text"] in REGIONS:
                for stage in stages:
                    region = REGIONS[row[0]["text"]]
                    if stage in stage_regions and stage_regions[stage] != region:
                        raise ValueError(f"Conflicting stage region: {stage}")
                    stage_regions[stage] = region
    stage_groups = {key: sorted(set(values)) for key, values in stage_groups.items() if values}
    if (set(regions) != set(REGIONS.values()) or set(stage_regions.values()) != set(REGIONS.values())
            or not special):
        raise ValueError("Incomplete reward/stage dataset; preserve the previous dataset")
    return {
        "schemaVersion": 1, "sourceUrl": URL,
        "regionRewards": regions, "specialBattles": special, "stageRegions": stage_regions,
        "stageGroups": stage_groups,
        "experienceCalculation": {"fullTechnologyMultipliers": ["1.1", "1.1", "1.1"],
                                  "rounding": "floor_after_all_multipliers"},
        "ordinaryPursuit": {"experience": {"base": 0, "fullTechnology": 0},
                            "originiumIngot": {"kind": "fixed", "value": 0}},
        "treeholeRewardPolicy": "resolve_actual_stage_region_or_special_battle_context",
        "remembranceRewardPolicy": "use_IV_unless_an_explicit_reward_override_is_supplied",
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", type=Path, help="Parse a previously saved main-page HTML snapshot")
    parser.add_argument("--out", type=Path, default=ROOT / "data/blackflow_battle_rewards.json")
    parser.add_argument("--save-html", type=Path)
    args = parser.parse_args()
    if args.offline:
        html = args.offline.read_text(encoding="utf-8")
    else:
        with urlopen(Request(URL, headers={"User-Agent": "Fulcrum-Reference/0.1"}), timeout=45) as response:
            html = response.read().decode("utf-8")
    result = extract_data(html)
    if args.save_html:
        args.save_html.parent.mkdir(parents=True, exist_ok=True)
        args.save_html.write_text(html, encoding="utf-8")
    payload = {**result, "extractedAt": datetime.now(timezone.utc).isoformat()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"regions": len(result["regionRewards"]), "stages": len(result["stageRegions"]),
                      "specialVariants": len(result["specialBattles"]), "output": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
