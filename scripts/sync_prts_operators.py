"""Fetch structured public PRTS list attributes, never rewrite manual handbooks."""

import argparse
import json
from pathlib import Path
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fulcrum.operator_catalog import OperatorPageParser


def main():
    import httpx
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(ROOT / "data/prts_operators.json"))
    args = parser.parse_args()
    rows, sources = {}, []
    with httpx.Client(follow_redirects=True, timeout=45) as client:
        for title in ("干员一览",):
            url = "https://prts.wiki/w/" + quote(title)
            response = client.get(url)
            response.raise_for_status()
            page = OperatorPageParser()
            page.feed(response.text)
            if not page.rows:
                raise ValueError(f"no operator rows in {title}; keep existing catalog")
            rows.update(page.rows)
            sources.append({"url": url, "count": len(page.rows)})
    if len(rows) < 300 or not any(r["name"] == "机械师" for r in rows.values()):
        raise ValueError("incomplete operator catalog; keep existing file")
    payload = {"schemaVersion": 1, "sources": sources,
               "statsBasis": "PRTS干员一览展示的参考基础值，保留原始文本；不是本局当前精英化/等级/信赖/潜能/模组后的实际属性。",
               "operators": sorted(rows.values(), key=lambda r: r["id"])}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    output = Path(args.output)
    if output.exists() and output.read_text(encoding="utf-8") == text:
        print(f"up to date: {len(rows)} operators")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(output)
    print(f"saved: {len(rows)} operators; {len(sources)} pages")


if __name__ == "__main__":
    main()
