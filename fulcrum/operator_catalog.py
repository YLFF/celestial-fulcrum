"""Offline PRTS operator identities and list-page reference stats."""

from functools import lru_cache
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unicodedata

PATH = Path(__file__).resolve().parents[1] / "data/prts_operators.json"
PROFESSIONS = ("先锋", "近卫", "重装", "狙击", "术师", "医疗", "辅助", "特种")
LOCAL_OPERATORS = [
    {"id": "local_rhodes_reserve", "name": "罗德岛预备干员", "rarity": 3},
    {"id": "local_rhodes_elite", "name": "罗德岛精英干员", "rarity": 5},
    {"id": "local_new_operator_placeholder", "name": "新干员临时占位", "rarity": 3, "rarityEditable": True},
]


def numeric(text):
    match = re.fullmatch(r"(-?\d+(?:\.\d+)?)(?:s)?", (text or "").strip())
    if not match:
        return None
    value = float(match[1])
    return int(value) if value.is_integer() else value


class OperatorPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = {}

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if not attrs.get("data-zh") or not attrs.get("data-char-id") or attrs.get("data-profession") not in PROFESSIONS:
            return
        rarity = numeric(attrs.get("data-rarity"))
        if not isinstance(rarity, int) or not 0 <= rarity <= 5:
            raise ValueError("PRTS rarity schema changed")
        fields = {"hp": "hp", "attack": "atk", "defense": "def", "resistance": "res",
                  "redeploySeconds": "re-deploy", "block": "block", "attackIntervalSeconds": "interval"}
        stats = {key: numeric(attrs.get(f"data-{source}")) for key, source in fields.items()}
        cost = attrs.get("data-cost", "")
        stats["deploymentCosts"] = [numeric(value) for value in cost.split("→")]
        row = {"id": attrs["data-char-id"], "name": attrs["data-zh"], "code": attrs.get("data-id", ""),
               "englishName": attrs.get("data-en", ""), "profession": attrs["data-profession"],
               "subprofession": attrs.get("data-subprofession", ""), "position": attrs.get("data-position", ""),
               "rarity": rarity + 1, "stats": stats,
               "rawStats": {source: attrs.get(f"data-{source}", "") for source in (*fields.values(), "cost")},
               "trustBonuses": [numeric(x) for x in attrs.get("data-trust", "").split(",")]}
        previous = self.rows.get(row["id"])
        if previous and previous != row:
            raise ValueError(f"conflicting PRTS operator data: {row['id']}")
        self.rows[row["id"]] = row


@lru_cache(maxsize=1)
def operators():
    rows = json.loads(PATH.read_text(encoding="utf-8"))["operators"]
    return [*rows, *[
        {**row, "code": "", "englishName": "", "profession": None,
         "subprofession": "", "position": "", "stats": {}, "repeatable": True,
         "professionEditable": True, "source": "local"}
        for row in LOCAL_OPERATORS
    ]]


def find_operator(value):
    return next((row for row in operators() if value in (row["id"], row["name"])), None)


def search_operators(query="", profession=None):
    query = unicodedata.normalize("NFKD", query).casefold()
    query = "".join(c for c in query if c.isalnum())
    result = []
    for row in operators():
        if profession and row["profession"] != profession:
            continue
        value = unicodedata.normalize("NFKD", " ".join(str(row[k]) for k in ("name", "code", "englishName", "id"))).casefold()
        value = "".join(c for c in value if c.isalnum())
        cursor = iter(value)
        if all(any(c == char for c in cursor) for char in query):
            result.append(row)
    return result
