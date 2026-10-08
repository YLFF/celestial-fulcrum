"""Inspect rendered Lubiao pages with a local Playwright browser."""

import argparse
import json
import sys

from playwright.sync_api import sync_playwright

from playwright_browser import chromium_executable


DEFAULT_URLS = (
    "https://www.lubiao.wiki/archives/blackstream",
    "https://www.lubiao.wiki/nodes/rogue_6",
    "https://www.lubiao.wiki/mechanisms/rogue_6",
)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", default=DEFAULT_URLS)
    parser.add_argument("--max-chars", type=int, default=5000)
    parser.add_argument("--executable", help="Path to an existing Chromium executable")
    parser.add_argument("--selector", help="Include a sample matching element's HTML")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            for url in args.urls:
                page = browser.new_page()
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    page.locator("body").wait_for()
                    page.wait_for_timeout(1500)
                    body = page.locator("body").inner_text()
                    headings = page.locator("h1, h2, h3").all_inner_texts()
                    matched = page.locator(args.selector) if args.selector else None
                    print(
                        json.dumps(
                            {
                                "url": page.url,
                                "status": response.status if response else None,
                                "title": page.title(),
                                "headingCount": len(headings),
                                "headings": headings[:30],
                                "bodyLength": len(body),
                                "bodyExcerpt": body[: args.max_chars],
                                "selectorCount": matched.count() if matched else None,
                                "selectorHtml": (
                                    matched.first.evaluate("element => { const output = []; for (let next = element, i = 0; next && i < 5; next = next.nextElementSibling, i++) output.push(next.outerHTML.slice(0, 900)); return output; }")
                                    if matched and matched.count()
                                    else None
                                ),
                            },
                            ensure_ascii=False,
                        )
                    )
                except Exception as error:
                    print(json.dumps({"url": url, "error": str(error)}, ensure_ascii=False))
                finally:
                    page.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
