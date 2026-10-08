from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin


BASE = "https://arkrog.com"
PAGES = ["https://arkrog.com/tool", "https://arkrog.com/tool/blackflowmap"]
OUT_DIR = Path("data/arkrog_inspection")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    html = fetch(PAGES[0])
    assets = sorted(
        {
            urljoin(BASE, match.group(1))
            for match in re.finditer(r'(?:href|src)="([^"]+\.(?:js|css))"', html)
        }
    )
    print("initial assets", len(assets))
    all_assets = list(assets)
    seen = set()
    for url in list(all_assets):
        if url in seen or not url.endswith(".js"):
            continue
        seen.add(url)
        try:
            code = fetch(url)
        except Exception as exc:
            print("fetch failed", url, exc)
            continue
        filename = OUT_DIR / url.rsplit("/", 1)[-1]
        filename.write_text(code, encoding="utf-8")
        for match in re.finditer(r'["\'](/assets-v2/[^"\']+\.js)["\']', code):
            next_url = urljoin(BASE, match.group(1))
            if next_url not in all_assets:
                all_assets.append(next_url)
        hits = []
        for needle in ["blackflowmap", "黑流", "树海", "map", "route", "fetch(", "/api", "localStorage"]:
            if needle in code:
                hits.append(needle)
        if hits:
            print("HIT", url, hits, "len", len(code))
            for needle in hits:
                idx = code.find(needle)
                print("---", needle, idx)
                print(code[max(0, idx - 300) : idx + 900].replace("\n", " ")[:1400])

    print("js fetched", len(seen))
    print("saved to", OUT_DIR)


if __name__ == "__main__":
    main()
