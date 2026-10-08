"""Inspect the live encounter selector in an isolated Playwright context."""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from playwright_browser import chromium_executable


URL = "https://www.lubiao.wiki/tools/blackstream-route"


def keyword_fields(value, prefix=""):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if any(word in key.lower() for word in ("probab", "frequen", "weight", "sample")):
                found.add(path)
            found.update(keyword_fields(child, path))
    elif isinstance(value, list):
        for child in value:
            found.update(keyword_fields(child, f"{prefix}[]"))
    return sorted(found)


def panel_state(panel):
    return {
        "text": panel.inner_text(),
        "buttons": panel.get_by_role("button").all_inner_texts(),
        "sections": panel.locator("section").all_inner_texts(),
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("work/lubiao_encounter_selector"))
    parser.add_argument("--executable")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"url": URL, "checked_at": datetime.now(timezone.utc).isoformat()}
    responses = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1080})
            page.on("response", lambda response: responses.append(response))
            navigation = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            report["status"] = navigation.status
            notice = page.get_by_role("button", name="知道了", exact=True)
            try:
                notice.wait_for(state="visible", timeout=5000)
                notice.click()
            except PlaywrightTimeoutError:
                if notice.is_visible():
                    raise
            page.get_by_role("button", name="选择已经历事件", exact=True).click()
            panel = page.get_by_role("dialog", name="选择已经历事件", exact=True)
            panel.wait_for(state="visible")
            entries = panel.locator(".blackstream-experienced-event")
            entries.first.wait_for(state="visible", timeout=20000)
            report["before"] = panel_state(panel)
            panel.screenshot(path=str(args.output / "before.png"))

            selectable = panel.locator(".blackstream-experienced-event:not(.is-selected)")
            event = selectable.first
            report["selected_for_probe"] = event.inner_text()
            event.click()
            report["after"] = panel_state(panel)
            panel.screenshot(path=str(args.output / "after.png"))

            panel.get_by_role("button", name="重置", exact=True).click()
            repeatable = panel.locator(".blackstream-experienced-event").filter(has_text="可重复").first
            if repeatable.count():
                report["repeatable_for_probe"] = repeatable.inner_text()
                repeatable.click()
                report["after_repeatable"] = panel_state(panel)
                panel.get_by_role("button", name="重置", exact=True).click()

            panel.get_by_role("button", name="关闭", exact=True).click()
            report["regions"] = []
            regions = page.locator(".blackstream-layer-tabs button")
            for index, name in enumerate(regions.all_inner_texts()):
                regions.nth(index).click()
                page.get_by_role("button", name="选择已经历事件", exact=True).click()
                report["regions"].append({"name": name, **panel_state(panel)})
                panel.get_by_role("button", name="关闭", exact=True).click()

            report["response_urls"] = sorted({response.url for response in responses})
            report["route_scripts"] = []
            report["encounter_scripts"] = []
            report["json_responses"] = []
            for response in list(responses):
                if "lubiao.wiki" not in response.url:
                    continue
                if response.url.endswith(".js"):
                    source = response.text()
                    if "blackstream-experienced-events-panel" in source:
                        filename = "route.js"
                        (args.output / filename).write_text(source, encoding="utf-8")
                        report["route_scripts"].append({"url": response.url, "file": filename})
                    if "zero_count_regularized" in source and "observedCount" in source:
                        matches = re.findall(r"JSON\.parse\('\s*(\[.*?\])\s*'\)", source)
                        tables = [json.loads(literal) for literal in matches]
                        weights = next(
                            rows for rows in tables
                            if rows and all(
                                isinstance(row, dict)
                                and {"floor", "treehole", "id", "weight", "status", "observedCount"} <= row.keys()
                                for row in rows
                            )
                        )
                        filename = "event_weights.js"
                        (args.output / filename).write_text(source, encoding="utf-8")
                        report["encounter_weight_rows"] = weights
                        report["encounter_scripts"].append({"url": response.url, "file": filename})
                    elif "prerequisiteNames" in source and "scene_ro6_res5" in source:
                        filename = "event_catalog.js"
                        (args.output / filename).write_text(source, encoding="utf-8")
                        report["encounter_scripts"].append({"url": response.url, "file": filename})
                if ".json" not in response.url:
                    continue
                try:
                    data = response.json()
                except Exception:
                    continue
                summary = {
                    "url": response.url,
                    "status": response.status,
                    "fields": list(data) if isinstance(data, dict) else None,
                    "probability_frequency_weight_fields": keyword_fields(data),
                }
                if "foundation-floors-rogue_6.json" in response.url:
                    summary["floor_encounters"] = [
                        {
                            "floor": floor.get("floor"),
                            "events": floor.get("eventsByNodeType", {}).get("INCIDENT", []),
                        }
                        for floor in data.get("floors", [])
                    ]
                report["json_responses"].append(summary)
            report["page_title"] = page.title()
            report["page_url"] = page.url
        finally:
            browser.close()

    output = args.output / "report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "report": str(output.resolve()),
        "before": report["before"]["sections"][0],
        "after": report["after"]["sections"][0],
        "regions": [region["name"] for region in report["regions"]],
        "route_scripts": report["route_scripts"],
        "encounter_scripts": report["encounter_scripts"],
        "weight_rows": len(report.get("encounter_weight_rows", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
