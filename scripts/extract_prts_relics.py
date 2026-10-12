"""Extract relic names and effects from the PRTS blackflow catalog."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from playwright_browser import chromium_executable


SOURCE_URL = "https://prts.wiki/w/沉沦者的黑流树海/拟造物质编目"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "prts_relic_effects.json"
CATEGORIES = (
    (1, 13, "多元奇物"),
    (14, 37, "生存助力"),
    (38, 142, "斗争之物"),
    (143, 188, "专业工具"),
    (189, 218, "巧用收藏"),
    (219, 224, "支援道具"),
    (225, 230, "叙事珍奇"),
    (231, 239, "泰拉之密"),
)


def category_for(number: int) -> str:
    return next((name for first, last, name in CATEGORIES if first <= number <= last), "待分类")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", help="Path to an existing Chromium executable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            page = browser.new_page()
            response = page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=30000)
            if not response or response.status != 200:
                raise RuntimeError(f"PRTS returned {response.status if response else 'no response'}")
            rows = page.evaluate(
                """() => Array.from(document.querySelectorAll('.mw-parser-output > p[id]'))
                  .filter(anchor => /^\\d{3}$/.test(anchor.id))
                  .map(anchor => {
                    const nameAnchor = anchor.nextElementSibling;
                    const table = nameAnchor?.nextElementSibling;
                    const header = table?.querySelector('tr:first-child th[colspan]');
                    const label = Array.from(table?.querySelectorAll('th') ?? [])
                      .find(cell => cell.textContent.trim() === '效果');
                    const effect = label?.closest('tr')?.nextElementSibling
                      ?.querySelector('td b');
                    return {
                      number: Number(anchor.id),
                      name: nameAnchor?.id ?? null,
                      headerName: header?.textContent.trim() ?? null,
                      effect: effect?.innerText.trim() ?? null,
                      validTable: table?.tagName === 'TABLE'
                    };
                  })"""
            )
        finally:
            browser.close()

    numbers = [row["number"] for row in rows]
    if len(numbers) < 239 or numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"Expected at least the legacy 001-239 consecutive IDs; got {len(numbers)}: {numbers}")
    bad = [
        row for row in rows
        if not row["validTable"] or not row["name"] or not row["effect"]
        or not row["headerName"].startswith(row["name"])
    ]
    if bad:
        raise RuntimeError(f"Could not reliably extract {len(bad)} entries: {bad[:5]}")

    data = {
        "schemaVersion": 1,
        "source": SOURCE_URL,
        "retrievedAt": datetime.now(timezone.utc).isoformat(),
        "note": "PRTS numbered catalog; not equivalent to Lubiao's deduplicated card count. New categories beyond the legacy 001-239 ranges require review.",
        "relics": [
            {
                "number": row["number"],
                "name": row["name"],
                "category": category_for(row["number"]),
                "effect": row["effect"],
            }
            for row in rows
        ],
    }
    args.output.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Extracted {len(rows)} relic effects to {args.output}")
    print(json.dumps(data["relics"][0], ensure_ascii=False))
    print(json.dumps(data["relics"][-1], ensure_ascii=False))


if __name__ == "__main__":
    main()
