"""Inspect rendered Lubiao catalog cards and category navigation."""

import argparse
import json
import sys

from playwright.sync_api import sync_playwright

from playwright_browser import chromium_executable


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://www.lubiao.wiki/archives/blackstream")
    parser.add_argument("--category")
    parser.add_argument("--click")
    parser.add_argument("--executable")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            page = browser.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
            page.locator("body").wait_for()
            page.wait_for_timeout(800)
            changelog_close = page.get_by_role("button", name="关闭更新日志")
            if changelog_close.count():
                changelog_close.click()
            if args.category:
                page.get_by_role("button", name=args.category, exact=False).first.click()
            if args.click:
                page.get_by_role("button", name=args.click, exact=False).first.click()
                page.wait_for_timeout(700)
            result = page.evaluate(
                """() => {
                  const card = document.querySelector('a.jieyuan-card');
                  const specialHeading = [...document.querySelectorAll('h2,h3')].find(x => x.innerText.includes('标记绘图集录'));
                  const links = [...document.querySelectorAll('a[href]')].map(a => ({
                    text: a.innerText.trim().slice(0, 80), href: a.href
                  }));
                  const buttons = [...document.querySelectorAll('button')].map(b => ({
                    text: b.innerText.trim().slice(0, 80), html: b.outerHTML.slice(0, 400)
                  }));
                  return {
                    url: location.href,
                    card: card?.outerHTML.slice(0, 10000),
                    special: specialHeading?.parentElement?.parentElement?.outerHTML.slice(0, 4000),
                    cardCount: document.querySelectorAll('a.jieyuan-card').length,
                    nodeEntry: document.querySelector('.directory-base-icon')?.parentElement?.parentElement?.outerHTML.slice(0, 5000),
                    nodeIconCount: document.querySelectorAll('.directory-base-icon').length,
                    headings: [...document.querySelectorAll('h1,h2,h3')].map(x => x.innerText.trim()).slice(0, 25),
                    links: links.filter(x => /标记绘图集录|节点|机制速查/.test(x.text)).slice(0, 15),
                    buttons: buttons.filter(x => x.text).slice(0, 40),
                    pictures: [...document.querySelectorAll('picture')].slice(0, 4).map(x => x.outerHTML.slice(0, 1500)),
                    tables: [...document.querySelectorAll('table')].slice(0, 2).map(x => x.outerHTML.slice(0, 10000)),
                    visuals: [...document.querySelectorAll('.asset-sprite, .asset-picture')].slice(0, 4).map(x => x.outerHTML.slice(0, 2500)),
                    bodyEnd: document.body.innerText.slice(-5000)
                  };
                }"""
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            browser.close()


if __name__ == "__main__":
    main()
