from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin


BASE = "https://arkrog.com"
MANIFEST_URL = "https://arkrog.com/assets-v2/manifest-7983d98b.js"
OUT_DIR = Path("data/arkrog_blackflowmap")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8")


def safe_snippet(text: str, needle: str) -> str:
    idx = text.find(needle)
    if idx < 0:
        return ""
    return text[max(0, idx - 500) : idx + 1500].replace("\n", " ")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest_js = fetch(MANIFEST_URL)
    manifest_json = manifest_js.split("=", 1)[1].rsplit(";", 1)[0]
    manifest = json.loads(manifest_json)
    route = manifest["routes"]["modules/Tool/BlackFlowMap/index"]
    urls = [route["module"], *route["imports"]]
    urls = [urljoin(BASE, url) for url in urls]
    print("route", route["id"], "path", route["path"])
    print("hasLoader", route["hasLoader"], "hasClientLoader", route["hasClientLoader"])
    print("assets", len(urls))

    interesting = [
        "blackflowmap",
        "BlackFlow",
        "黑流",
        "树海",
        "fetch(",
        "axios",
        "/api",
        "localStorage",
        "sessionStorage",
        "FileReader",
        "canvas",
        "screenshot",
        "recogn",
        "stage",
        "node",
        "map",
        "route",
    ]

    for url in urls:
        try:
            code = fetch(url)
        except Exception as exc:
            print("FETCH_FAIL", url, exc)
            continue
        filename = OUT_DIR / url.rsplit("/", 1)[-1]
        filename.write_text(code, encoding="utf-8")
        hits = [needle for needle in interesting if needle in code]
        if hits:
            print("\nHIT", url, "len", len(code), hits)
            for needle in hits:
                print("---", needle)
                print(safe_snippet(code, needle)[:2000])

    print("\nsaved", OUT_DIR)


if __name__ == "__main__":
    main()
