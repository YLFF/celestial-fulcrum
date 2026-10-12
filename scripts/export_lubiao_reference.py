"""Refresh Blackflow catalog text and rendered icons without renumbering IDs."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import sync_playwright

from playwright_browser import chromium_executable
from reference_catalog import CATEGORY_ORDER, deduplicate_cards, merge_category


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "lubiao_reference_catalog.json"
ARCHIVE_URL = "https://www.lubiao.wiki/archives/blackstream"
NODES_URL = "https://www.lubiao.wiki/nodes/rogue_6"
MARKS_URL = "https://www.lubiao.wiki/mechanisms/rogue_6"
PRTS_URL = "https://prts.wiki/w/沉沦者的黑流树海"
CATEGORIES = {
    "relic": ("收藏品", 243),
    "component": ("零件", 30),
    "dystopia": ("实托邦", 14),
    "utopia": ("乌托邦", 9),
    "squad": ("分队", 15),
    "node_type": ("节点类别", 21),
    "node_mark": ("节点标记", 7),
}


def close_changelog(page) -> None:
    page.wait_for_timeout(800)
    close = page.get_by_role("button", name="关闭更新日志")
    if close.count():
        close.click()


def save_icon(
    locator,
    item: dict,
    previous: dict | None,
    asset_dir: Path,
    refresh: bool,
    filename: str | None = None,
    container=None,
) -> None:
    path = asset_dir / item["category"] / (filename or f"{item['id']}.png")
    path.parent.mkdir(parents=True, exist_ok=True)
    item["imagePath"] = None
    if (
        not refresh
        and previous
        and previous.get("assetUrl") == item.get("assetUrl")
        and path.is_file()
    ):
        item["imagePath"] = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        item["imageStatus"] = "saved"
        return
    if container is not None:
        container.scroll_into_view_if_needed()
    if not locator.count():
        item["imageStatus"] = "missing_on_source"
        return
    temporary = path.with_suffix(".new.png")
    try:
        target = locator.first
        if target.evaluate("element => element.tagName === 'IMG'"):
            target.scroll_into_view_if_needed()
            target.evaluate(
                """async image => {
                  image.loading = 'eager';
                  await image.decode();
                  if (!image.naturalWidth || !image.naturalHeight) throw new Error('Image did not load');
                }"""
            )
        target.screenshot(path=str(temporary), animations="disabled", timeout=15000)
        if temporary.stat().st_size < 200:
            raise RuntimeError("PNG appears empty")
        temporary.replace(path)
        item["imagePath"] = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
        item["imageStatus"] = "saved"
    except Exception as error:
        temporary.unlink(missing_ok=True)
        item["imageStatus"] = "failed"
        item["imageError"] = str(error).splitlines()[0]


def archive_items(page, category: str, limit: int | None) -> list[dict]:
    label, minimum = CATEGORIES[category]
    page.get_by_role("button", name=re.compile(rf"^{re.escape(label)}\s+\d+$")).click()
    cards = page.locator("a.jieyuan-card")
    actual = cards.count()
    if actual < minimum:
        raise RuntimeError(f"{label}: expected at least {minimum} cards, got {actual}")
    rows = []
    for index in range(min(actual, limit or actual)):
        card = cards.nth(index)
        data = card.evaluate(
            """card => {
              const icon = card.querySelector('.item-card-image .asset-sprite, .item-card-image .asset-picture');
              return {
                href: card.getAttribute('href'),
                name: card.querySelector('h2')?.innerText.trim(),
                effect: card.querySelector('.archive-effect-summary p')?.innerText.trim(),
                subtype: card.querySelector('.archive-type')?.innerText.trim() ?? null,
                rarity: card.querySelector('.archive-card-rarity')?.innerText.trim() ?? null,
                assetUrl: icon?.querySelector('image')?.getAttribute('href')
                  ?? icon?.querySelector('img')?.getAttribute('src') ?? null,
                imageKind: icon?.classList.contains('asset-sprite') ? 'sprite' :
                  icon?.classList.contains('asset-picture') ? 'picture' : null
              };
            }"""
        )
        source_id = unquote(urlparse(data["href"]).path.rsplit("/", 1)[-1])
        item = {
            "category": category,
            "categoryLabel": label,
            "sourceId": source_id,
            "name": data["name"],
            "effect": data["effect"],
            "subtype": data["subtype"],
            "rarity": data["rarity"],
            "sourceUrl": urljoin(ARCHIVE_URL, data["href"]),
            "assetUrl": data["assetUrl"],
            "imageKind": data["imageKind"],
            "_sourceIndex": index,
        }
        if not item["name"] or not item["effect"]:
            raise RuntimeError(f"{label} card {index + 1} has missing text")
        rows.append(item)
    return rows


def node_types(page, limit: int | None) -> list[dict]:
    page.goto(NODES_URL, wait_until="domcontentloaded", timeout=30000)
    close_changelog(page)
    entries = page.locator(".compact-node-entry")
    actual = entries.count()
    if actual < CATEGORIES["node_type"][1]:
        raise RuntimeError(f"Node directory: expected at least 21 entries, got {actual}")
    rows = []
    for index in range(min(actual, limit or actual)):
        entry = entries.nth(index)
        data = entry.evaluate(
            """entry => ({
              href: entry.getAttribute('href'),
              name: entry.innerText.trim(),
              assetUrl: entry.querySelector('.directory-node-icon image')?.getAttribute('href')
                ?? entry.querySelector('.directory-node-icon img')?.getAttribute('src') ?? null
            })"""
        )
        item = {
            "category": "node_type",
            "categoryLabel": "节点类别",
            "sourceId": data["name"],
            "name": data["name"],
            "sourceUrl": urljoin(NODES_URL, data["href"]) if data["href"] else NODES_URL,
            "assetUrl": data["assetUrl"],
            "imageKind": "sprite" if data["assetUrl"] else None,
            "_sourceIndex": index,
        }
        rows.append(item)
    return rows


def node_marks(page, limit: int | None) -> list[dict]:
    page.goto(MARKS_URL, wait_until="domcontentloaded", timeout=30000)
    close_changelog(page)
    page.get_by_role("button", name="标记绘图集录", exact=False).first.click()
    source = page.locator(".imported-reference-source").first.get_attribute("href")
    entries = page.locator("table.imported-reference-table tbody tr")
    actual = entries.count()
    if actual < CATEGORIES["node_mark"][1]:
        raise RuntimeError(f"Mark table: expected at least 7 rows, got {actual}")
    rows = []
    for index in range(min(actual, limit or actual)):
        entry = entries.nth(index)
        data = entry.evaluate(
            """row => ({
              cells: [...row.querySelectorAll('th,td')].map(x => x.innerText.trim()),
              assetUrl: row.querySelector('.quick-reference-mark-image image')?.getAttribute('href') ?? null
            })"""
        )
        columns = [cell for cell in data["cells"] if cell]
        if len(columns) != 5:
            raise RuntimeError(f"Mark row {index + 1}: expected 5 text cells, got {columns}")
        name, condition, behavior, effect, notes = columns
        item = {
            "category": "node_mark",
            "categoryLabel": "节点标记",
            "sourceId": name,
            "name": name,
            "condition": condition,
            "nodeBehavior": behavior,
            "effect": effect,
            "notes": notes,
            "sourceUrl": MARKS_URL,
            "originalSourceUrl": source,
            "assetUrl": data["assetUrl"],
            "imageKind": "sprite" if data["assetUrl"] else None,
            "_sourceIndex": index,
        }
        rows.append(item)
    return rows


def capture_images(page, category: str, rows: list[dict], previous: list[dict], asset_dir: Path, refresh: bool) -> None:
    old_by_id = {row["id"]: row for row in previous}
    if category in ("node_type", "node_mark"):
        selector = ".compact-node-entry" if category == "node_type" else "table.imported-reference-table tbody tr"
        icon_selector = (
            ".directory-node-icon .asset-sprite, .directory-node-icon .asset-picture img"
            if category == "node_type" else ".quick-reference-mark-image"
        )
    else:
        selector = "a.jieyuan-card"
        icon_selector = ".item-card-image .asset-sprite, .item-card-image .asset-picture img"
    cards = page.locator(selector)
    for row in rows:
        old = old_by_id.get(row["id"])
        if category not in ("node_type", "node_mark"):
            variants = row.pop("_variants")
            row.pop("_sourceIndex", None)
            primary = variants[0]
            prior_primary = old if old and old["sourceId"] == primary["sourceId"] else None
            card = cards.nth(primary["_sourceIndex"])
            save_icon(card.locator(icon_selector), row, prior_primary, asset_dir, refresh, container=card)
            old_variants = {}
            if old:
                for index, item in enumerate(old.get("imageVariants", []), 2):
                    prior = dict(item)
                    prior["imagePath"] = prior.get("imagePath") or str(asset_dir / category / f"{row['id']}__{index:02d}.png")
                    old_variants[item["sourceId"]] = prior
            suffixes = [
                int(match.group(1))
                for item in old_variants.values()
                if (match := re.fullmatch(rf"{re.escape(row['id'])}__(\d+)\.png", Path(item["imagePath"]).name))
            ]
            next_suffix = max(suffixes, default=1) + 1
            image_variants = []
            for variant in variants[1:]:
                prior = old_variants.get(variant["sourceId"])
                if prior:
                    filename = Path(prior["imagePath"]).name
                else:
                    filename = f"{row['id']}__{next_suffix:02d}.png"
                    next_suffix += 1
                image = {key: variant[key] for key in ("sourceId", "assetUrl", "imageKind")}
                image.update({"id": row["id"], "category": category})
                card = cards.nth(variant["_sourceIndex"])
                save_icon(card.locator(icon_selector), image, prior, asset_dir, refresh, filename, card)
                image_variants.append({key: image[key] for key in ("sourceId", "assetUrl", "imageKind", "imagePath", "imageStatus")})
            row["imageVariants"] = image_variants
        else:
            index = row.pop("_sourceIndex")
            row.pop("_variants", None)
            card = cards.nth(index)
            save_icon(card.locator(icon_selector), row, old, asset_dir, refresh, container=card)
            if row["name"] == "林间空地" and row["imageStatus"] == "missing_on_source":
                row["imageStatus"] = "no_standalone_icon"
                row["imageNote"] = "Lubiao has no standalone icon; PRTS labels this node as blank."
                row["alternateSourceUrl"] = PRTS_URL


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--categories", nargs="+", choices=CATEGORIES, default=list(CATEGORIES))
    parser.add_argument("--limit", type=int, help="Capture at most this many entries per category")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--asset-dir", type=Path, default=ROOT / "assets" / "lubiao")
    parser.add_argument("--refresh-images", action="store_true", help="Recapture icons even if the source URL is unchanged")
    parser.add_argument("--executable")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.output.resolve() == DEFAULT_OUTPUT.resolve() and (
        args.limit is not None or set(args.categories) != set(CATEGORIES)
    ):
        parser.error("Partial exports require a separate --output to protect the full catalog")

    if not DEFAULT_OUTPUT.is_file():
        raise RuntimeError("Missing local catalog; initial ID registry is required")
    previous_catalog = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    if previous_catalog.get("schemaVersion") != 2:
        raise RuntimeError("Run scripts/migrate_reference_catalog.py before refreshing")
    previous_by_category = {
        category: [row for row in previous_catalog["entries"] if row["category"] == category]
        for category in CATEGORY_ORDER
    }
    complete = args.limit is None
    entries = []
    source_card_counts = {}

    def record_category(page, category: str, fetched: list[dict]) -> None:
        prior = previous_by_category[category]
        source_card_counts[category] = len(fetched)
        unique = deduplicate_cards(category, fetched, prior)
        rows, additions = merge_category(category, prior, unique, require_complete=complete)
        capture_images(page, category, rows, prior, args.asset_dir, args.refresh_images)
        entries.extend(rows)
        saved = sum(row["imageStatus"] == "saved" for row in rows)
        print(f"{category}: {len(fetched)} source cards -> {len(rows)} entries, {saved} primary images, {len(additions)} new IDs")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            page = browser.new_page(viewport={"width": 1400, "height": 1000}, device_scale_factor=2)
            if any(category in CATEGORIES and category not in ("node_type", "node_mark") for category in args.categories):
                response = page.goto(ARCHIVE_URL, wait_until="domcontentloaded", timeout=30000)
                if not response or response.status != 200:
                    raise RuntimeError("Could not open Lubiao archive")
                close_changelog(page)
                for category in args.categories:
                    if category in ("node_type", "node_mark"):
                        continue
                    record_category(page, category, archive_items(page, category, args.limit))
            if "node_type" in args.categories:
                record_category(page, "node_type", node_types(page, args.limit))
            if "node_mark" in args.categories:
                record_category(page, "node_mark", node_marks(page, args.limit))
        finally:
            browser.close()

    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate category IDs in export")
    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": {"archive": ARCHIVE_URL, "nodes": NODES_URL, "marks": MARKS_URL},
        "categories": {
            key: {
                "label": CATEGORIES[key][0],
                "minimumSourceCardCount": CATEGORIES[key][1],
                "sourceCardCount": source_card_counts.get(key),
                "entryCount": sum(row["category"] == key for row in entries),
            }
            for key in CATEGORY_ORDER
        },
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".new.json")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    failures = [item["id"] for item in entries if item["imageStatus"] != "saved"]
    print(f"Saved {args.output}: {len(entries)} records, {len(failures)} missing images")
    if failures:
        print("Missing:", failures)


if __name__ == "__main__":
    main()
