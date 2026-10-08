"""Check or replace the single local Lubiao prediction dataset."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.playwright_browser import chromium_executable


URL = "https://www.lubiao.wiki/tools/blackstream-route"
OUTPUT = ROOT / "data" / "lubiao_prediction_data.json"
HEADERS = ["节点", "I", "II", "III", "IV", "IV追忆", "V"]
NAME_TO_TYPE = {
    "起点": "start", "误入奇境": "wrong-turn", "狭路相逢": "narrow-meet",
    "诡意行商": "rogue-trader", "秘境行商": "secret-trader",
    "林间空地": "forest-clearing", "作战": "combat", "紧急作战": "emergency-combat",
    "险路恶敌": "danger-enemy", "居民据点": "settlement", "“居民”据点": "settlement",
    "安全的角落": "safe-corner", "不期而遇": "encounter", "得偿所愿": "wish",
    "失与得": "gain-loss", "先行一步": "first-step", "命运所指": "fate-choice",
    "应急助力": "emergency-aid", "曲折密道": "winding-path", "羽瞰点": "overlook",
    "险路小径": "danger-path", "险路尽头": "danger-end",
    "未知的诡秘": "unknown-mystery", "未知的凶戾": "unknown-ferocity",
    "流窜“居民”": "roving-resident", "地图节点总数": "total-nodes",
}
DISTANCE_TYPES = {
    "start", "wrong-turn", "narrow-meet", "rogue-trader", "secret-trader", "forest-clearing",
    "combat", "emergency-combat", "danger-enemy", "settlement", "safe-corner", "encounter",
    "wish", "gain-loss", "first-step", "fate-choice", "emergency-aid", "winding-path",
    "overlook", "danger-path", "danger-end", "unknown-mystery", "unknown-ferocity",
    "roving-resident",
}
COUNT_TYPES = {
    "wrong-turn", "narrow-meet", "rogue-trader", "secret-trader", "forest-clearing",
    "combat", "emergency-combat", "settlement", "safe-corner", "encounter", "wish",
    "gain-loss", "first-step", "fate-choice", "emergency-aid", "winding-path",
    "overlook", "danger-path", "total-nodes",
}
REQUIRED_SAMPLE_TYPES = (COUNT_TYPES - {"total-nodes"}) | {"start", "danger-enemy", "danger-end"}


def _normalize_range(raw: str, *, count: bool) -> str:
    value = raw.strip().replace("–", "-").replace("—", "-").replace(" ", "")
    pattern = r"(?:\d+|\d+-\d+)" if count else r"(?:\d+|\d+-\d+)(?:,(?:\d+|\d+-\d+))*"
    if value and not re.fullmatch(pattern, value):
        raise ValueError(f"unrecognized {'count' if count else 'distance'} range: {raw!r}")
    return value


def _table(rows: list[list[str]], *, count: bool) -> dict[str, list[str]]:
    if not rows or rows[0] != HEADERS:
        raise ValueError("Lubiao table headers changed; inspect the page before updating")
    result = {}
    for row in rows[1:]:
        if len(row) != len(HEADERS):
            raise ValueError(f"Lubiao table has {len(row)} columns, expected {len(HEADERS)}: {row}")
        label = row[0].strip()
        if label not in NAME_TO_TYPE:
            raise ValueError(f"new or renamed Lubiao node type: {label}")
        node_type = NAME_TO_TYPE[label]
        if node_type in result:
            raise ValueError(f"duplicate Lubiao node type: {label}")
        result[node_type] = [_normalize_range(cell, count=count) for cell in row[1:]]
    expected = COUNT_TYPES if count else DISTANCE_TYPES
    if set(result) != expected:
        raise ValueError(f"Lubiao table types changed: missing={sorted(expected - result.keys())}, extra={sorted(result.keys() - expected)}")
    return result


def build_rules(snapshot: dict[str, Any]) -> dict[str, Any]:
    if snapshot.get("source") != URL:
        raise ValueError("snapshot source is not the Lubiao route tool")
    version = snapshot.get("ruleVersion")
    if not isinstance(version, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", version):
        raise ValueError("invalid or missing rule version")
    sample_count = snapshot.get("sampleCount")
    if not isinstance(sample_count, int) or sample_count <= 0:
        raise ValueError("invalid or missing sample count")
    sample_updated = snapshot.get("sampleUpdatedAt")
    if not isinstance(sample_updated, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\+8", sample_updated):
        raise ValueError("invalid or missing sample update time")
    distance = _table(snapshot["distance"], count=False)
    counts = _table(snapshot["count"], count=True)
    labels_by_floor = snapshot["types"]
    if set(labels_by_floor) != {"I", "II", "III", "IV", "V"}:
        raise ValueError("Lubiao floor-type list changed")
    allowed_types = {}
    for floor, labels in labels_by_floor.items():
        if not isinstance(labels, list) or not labels:
            raise ValueError(f"empty floor-type list for {floor}")
        unknown = set(labels) - NAME_TO_TYPE.keys()
        if unknown:
            raise ValueError(f"new Lubiao floor types: {sorted(unknown)}")
        mapped = [NAME_TO_TYPE[label] for label in labels]
        if len(mapped) != len(set(mapped)):
            raise ValueError(f"duplicate floor type in {floor}")
        if "start" not in mapped:
            raise ValueError(f"start is missing from {floor}")
        allowed_types[floor] = mapped
    allowed_types["IV追忆"] = list(allowed_types["IV"])
    return {
        "schemaVersion": 1,
        "source": URL,
        "ruleVersion": version,
        "sampleCount": sample_count,
        "sampleUpdatedAt": sample_updated,
        "floors": HEADERS[1:],
        "distanceRanges": distance,
        "countRanges": counts,
        "allowedTypes": allowed_types,
    }


def _object_literal(source: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}=\{{", source)
    if match is None:
        raise ValueError(f"cannot find {name} sample object in route script")
    start = match.end() - 1
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise ValueError(f"unterminated {name} sample object")


def extract_samples(source: str) -> tuple[str, dict[str, dict[str, dict[str, int]]]]:
    sample_match = re.search(r'\b([A-Za-z_$][\w$]*)=\{combat:\{0:\{', source)
    timestamps = list(re.finditer(r'\bupdatedAt:"([^"\n]+)"', source[:sample_match.start()])) if sample_match else []
    timestamp_match = timestamps[-1] if timestamps else None
    if sample_match is None or timestamp_match is None:
        raise ValueError("route script lacks dated distance samples")
    try:
        updated_at = datetime.fromisoformat(timestamp_match[1])
        literal = _object_literal(source, sample_match[1])
        normalized = re.sub(r'(?<=[{,])([A-Za-z_][\w-]*|\d+)(?=:)', r'"\1"', literal)
        samples = json.loads(normalized)
    except (ValueError, TypeError) as error:
        raise ValueError("route distance samples could not be parsed") from error
    if updated_at.tzinfo is None or not isinstance(samples, dict):
        raise ValueError("route samples need a timezone and an object")
    missing = REQUIRED_SAMPLE_TYPES - samples.keys()
    if missing:
        raise ValueError(f"route samples are missing node types: {', '.join(sorted(missing))}")
    for required in REQUIRED_SAMPLE_TYPES:
        if not isinstance(samples[required], dict) or "remembrance" not in samples[required]:
            raise ValueError(f"route samples are missing {required} remembrance counts")
    for node_type, floors in samples.items():
        if not isinstance(floors, dict):
            raise ValueError(f"invalid sample floors for {node_type}")
        for floor, counts in floors.items():
            if floor not in {"0", "1", "2", "3", "4", "remembrance"} or not isinstance(counts, dict):
                raise ValueError(f"invalid sample floor {node_type}/{floor}")
            if any(not str(distance).isdigit() or type(count) is not int or count < 0 for distance, count in counts.items()):
                raise ValueError(f"invalid distance counts for {node_type}/{floor}")
    return updated_at.isoformat(), samples


def build_data(snapshot: dict[str, Any], chunk: str, chunk_url: str) -> dict[str, Any]:
    parsed = urlparse(chunk_url)
    if parsed.scheme != "https" or parsed.netloc != "www.lubiao.wiki" or not re.fullmatch(r"/_nuxt/[\w-]+\.js", parsed.path):
        raise ValueError("sample script URL is not a Lubiao Nuxt route chunk")
    rules = build_rules(snapshot)
    updated_at, samples = extract_samples(chunk)
    return {
        **rules,
        "schemaVersion": 2,
        "sourceChunk": chunk_url,
        "statisticsUpdatedAt": updated_at,
        "distanceSamples": samples,
    }


def extract_live_sources(executable: str | None = None) -> tuple[dict[str, Any], str, str]:
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise RuntimeError("Python Playwright is required for live sync; use --snapshot and --chunk offline") from error
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable(executable))
            try:
                page = browser.new_page()
                page.goto(URL, wait_until="domcontentloaded", timeout=30000)
                rules_button = page.get_by_role("button", name="查看节点预测功能说明")
                rules_button.wait_for(state="visible")
                changelog_dismiss = page.get_by_text("知道了", exact=True)
                if changelog_dismiss.count() and changelog_dismiss.is_visible():
                    changelog_dismiss.click()
                rules_button.click()
                page.locator("#prediction-distance-table-title").wait_for()
                rows = {}
                for key, title in (("distance", "prediction-distance-table-title"), ("count", "prediction-count-table-title")):
                    rows[key] = page.locator(f'section[aria-labelledby="{title}"] table tr').evaluate_all(
                        "rows => rows.map(row => [...row.querySelectorAll('th,td')].map(cell => cell.textContent.trim()))"
                    )
                rows["types"] = page.locator('section[aria-labelledby="prediction-layer-types-table-title"] tbody tr').evaluate_all(
                    "rows => Object.fromEntries(rows.map(row => [row.querySelector('th').textContent.trim(), [...row.querySelectorAll('.table-node-list > .node-label')].map(node => node.textContent.trim())]))"
                )
                modal_text = page.locator('[aria-labelledby="prediction-rules-title"]').inner_text()
                version = re.search(r"规则版本[:：]\s*(\d{4}-\d{2}-\d{2})", modal_text)
                sample = re.search(
                    r"样本数[:：]\s*([\d,]+)\s*最近更新时间[:：]\s*(\d{4})\.(\d{2})\.(\d{2})\s+(\d{2}:\d{2}:\d{2})\s*（UTC\+8）",
                    modal_text,
                )
                if version is None or sample is None:
                    raise ValueError("Lubiao version or sample metadata is missing")
                snapshot = {
                    "source": URL,
                    "ruleVersion": version[1],
                    "sampleCount": int(sample[1].replace(",", "")),
                    "sampleUpdatedAt": f"{sample[2]}-{sample[3]}-{sample[4]} {sample[5]} UTC+8",
                    **rows,
                }
                scripts = page.evaluate("""() => [...new Set([
                    ...performance.getEntriesByType('resource').map(item => item.name),
                    ...[...document.querySelectorAll('script[src]')].map(item => item.src)
                ])]""")
                for script_url in scripts:
                    parsed = urlparse(script_url)
                    if parsed.scheme != "https" or parsed.netloc != "www.lubiao.wiki" or not re.fullmatch(r"/_nuxt/[\w-]+\.js", parsed.path):
                        continue
                    response = page.request.get(script_url, timeout=30000)
                    if not response.ok:
                        continue
                    chunk = response.text()
                    try:
                        extract_samples(chunk)
                    except ValueError:
                        continue
                    return snapshot, chunk, script_url
                raise ValueError("no dated Lubiao prediction sample script was loaded")
            finally:
                browser.close()
    except PlaywrightError as error:
        reason = str(error).splitlines()[0]
        raise RuntimeError(f"live Lubiao access failed ({reason}); use --snapshot and --chunk when network is restricted") from error


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, help="saved rendered-table JSON for offline checking")
    parser.add_argument("--chunk", type=Path, help="saved route script for offline checking")
    parser.add_argument("--executable", help="existing Chromium executable for Playwright")
    parser.add_argument("--apply", action="store_true", help="atomically replace the one local prediction dataset")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args(argv)
    if bool(args.snapshot) != bool(args.chunk):
        parser.error("--snapshot and --chunk must be supplied together")
    try:
        if args.snapshot:
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
            chunk = args.chunk.read_text(encoding="utf-8")
            chunk_url = f"https://www.lubiao.wiki/_nuxt/{args.chunk.name}"
        else:
            snapshot, chunk, chunk_url = extract_live_sources(args.executable)
        data = build_data(snapshot, chunk, chunk_url)
        current = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else None
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.exit(2, f"sync failed: {error}\n")
    if current is not None and (
        data["ruleVersion"] < current["ruleVersion"]
        or data["statisticsUpdatedAt"] < current["statisticsUpdatedAt"]
    ):
        parser.exit(2, "sync failed: source is older than the installed prediction dataset\n")
    if current == data:
        print(f"up to date: {args.output}")
        return 0
    changed = [key for key in data if current is None or current.get(key) != data[key]]
    print(f"prediction data drift: {args.output} ({', '.join(changed)})")
    if not args.apply:
        print("review the source, then rerun with --apply")
        return 1
    _write_json(args.output, data)
    print(f"updated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
