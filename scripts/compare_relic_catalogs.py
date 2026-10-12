"""Compare PRTS and Lubiao relic names and effect text."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import unicodedata

from playwright.sync_api import sync_playwright

from playwright_browser import chromium_executable


ROOT = Path(__file__).resolve().parents[1]
PRTS_DATA = ROOT / "data" / "prts_relic_effects.json"
DEFAULT_OUTPUT = ROOT / "work/relic_catalog_comparison/report.md"
DEFAULT_DATA_OUTPUT = ROOT / "data" / "blackflow_relic_texts.json"
LUBIAO_URL = "https://www.lubiao.wiki/archives/blackstream"


def name_key(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", value))


def effect_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", value)
    return re.sub(r"[\s;；]+", "", text)


def effect_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def render_effect(value: str) -> str:
    return "<br>".join(effect_lines(value))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", help="Path to an existing Chromium executable")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--data-output", type=Path, default=DEFAULT_DATA_OUTPUT)
    args = parser.parse_args()

    prts_data = json.loads(PRTS_DATA.read_text(encoding="utf-8"))
    prts_rows = prts_data["relics"]
    if len(prts_rows) < 239:
        raise RuntimeError(f"Expected at least 239 PRTS relics, got {len(prts_rows)}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, executable_path=chromium_executable(args.executable)
        )
        try:
            page = browser.new_page()
            response = page.goto(LUBIAO_URL, wait_until="domcontentloaded", timeout=30000)
            if not response or response.status != 200:
                raise RuntimeError(f"Lubiao returned {response.status if response else 'no response'}")
            page.locator("h2:has(+ .archive-effect-summary)").first.wait_for()
            lubiao_rows = page.evaluate(
                """() => Array.from(document.querySelectorAll('h2'))
                  .filter(heading => heading.nextElementSibling?.matches('.archive-effect-summary'))
                  .map(heading => ({
                    name: heading.textContent.trim(),
                    effect: heading.nextElementSibling.querySelector('p')?.innerText.trim() ?? ''
                  }))"""
            )
        finally:
            browser.close()

    if len(lubiao_rows) < 243:
        raise RuntimeError(f"Expected at least 243 Lubiao cards, got {len(lubiao_rows)}")
    if any(not row["name"] or not row["effect"] for row in lubiao_rows):
        raise RuntimeError("Lubiao has cards with missing names or effects")

    prts_by_name = {name_key(row["name"]): row for row in prts_rows}
    if len(prts_by_name) != len(prts_rows):
        raise RuntimeError("Duplicate normalized PRTS relic names")
    lubiao_by_name = defaultdict(list)
    for row in lubiao_rows:
        lubiao_by_name[name_key(row["name"])].append(row)

    all_keys = list(prts_by_name) + [
        key for key in lubiao_by_name if key not in prts_by_name
    ]
    records = []
    for key in all_keys:
        prts_row = prts_by_name.get(key)
        lubiao_group = lubiao_by_name.get(key, [])
        name = prts_row["name"] if prts_row else lubiao_group[0]["name"]
        coverage = "both" if prts_row and lubiao_group else (
            "prts_only" if prts_row else "lubiao_only"
        )
        if name.startswith("襁褓"):
            status = "deferred_inherited"
        elif not prts_row:
            status = "lubiao_only"
        elif not lubiao_group:
            status = "prts_only"
        elif effect_key(prts_row["effect"]) in {
            effect_key(row["effect"]) for row in lubiao_group
        }:
            status = "agreed_text"
        else:
            status = "different_text"
        records.append(
            {
                "name": name,
                "status": status,
                "coverage": coverage,
                "prts_number": prts_row["number"] if prts_row else None,
                "prts_category": prts_row["category"] if prts_row else None,
                "prts_effect": prts_row["effect"] if prts_row else None,
                "lubiao_effects": [row["effect"] for row in lubiao_group],
            }
        )

    args.data_output.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "sources": {"prts": prts_data["source"], "lubiao": LUBIAO_URL},
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "relics": records,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    prts_only_records = [row for row in records if row["status"] == "prts_only"]
    lubiao_only_records = [row for row in records if row["status"] == "lubiao_only"]
    different_records = [row for row in records if row["status"] == "different_text"]
    agreed_records = [row for row in records if row["status"] == "agreed_text"]
    inherited_records = [row for row in records if row["status"] == "deferred_inherited"]
    inherited_both = [row for row in inherited_records if row["coverage"] == "both"]
    inherited_lubiao_only = [
        row for row in inherited_records if row["coverage"] == "lubiao_only"
    ]

    lines = [
        "# 黑流树海藏品：PRTS 与路标文本差异",
        "",
        f"生成时间：{datetime.now(timezone.utc).isoformat()}。",
        f"来源：[PRTS 拟造物质编目]({prts_data['source']})、[路标档案馆]({LUBIAO_URL})。",
        "比较方式：名称按 Unicode NFC 并去除空白后匹配；效果比较时另去除空白和分号。下面保留原始效果文字，不裁定哪站正确。",
        f"计数：PRTS {len(prts_rows)} 个名称，路标 {len(lubiao_rows)} 张卡片/{len(lubiao_by_name)} 个名称。普通藏品一致 {len(agreed_records)}，仅 PRTS {len(prts_only_records)}，仅路标 {len(lubiao_only_records)}，同名效果不同 {len(different_records)}。襁褓特殊藏品 {len(inherited_records)} 个名称，其中双方都有 {len(inherited_both)} 个、仅路标有 {len(inherited_lubiao_only)} 个。",
        "襁褓系列暂保留各站各版本文本与路标同名卡片数，不参与一般藏品一致性判定。全部原始效果文字已存入 data/blackflow_relic_texts.json。",
        "",
        f"## 仅 PRTS 有（{len(prts_only_records)}）",
        "",
    ]
    for row in prts_only_records:
        lines.extend(
            [
                f"### No.{row['prts_number']:03d} {row['name']}",
                f"分类：{row['prts_category']}",
                f"效果：{render_effect(row['prts_effect'])}",
                "",
            ]
        )
    lines.extend([f"## 仅路标有（{len(lubiao_only_records)}）", ""])
    for row in lubiao_only_records:
        lines.append(f"### {row['name']}")
        for index, effect in enumerate(row["lubiao_effects"], 1):
            lines.append(f"效果 {index}：{render_effect(effect)}")
        lines.append("")
    lines.extend([f"## 同名但效果文本不同（{len(different_records)}）", ""])
    for row in different_records:
        lines.extend(
            [
                f"### No.{row['prts_number']:03d} {row['name']}",
                f"PRTS：{render_effect(row['prts_effect'])}",
            ]
        )
        for index, effect in enumerate(row["lubiao_effects"], 1):
            lines.append(f"路标 {index}：{render_effect(effect)}")
        lines.append("")

    lines.extend([f"## 双方都有的襁褓，暂保留描述（{len(inherited_both)}）", ""])
    for row in inherited_both:
        lines.append(f"### {row['name']}")
        lines.append(f"PRTS：{render_effect(row['prts_effect'])}")
        lines.append(f"路标：{render_effect(row['lubiao_effects'][0])}")
        lines.append("")

    lines.extend([f"## 仅路标有的襁褓，暂保留描述（{len(inherited_lubiao_only)}）", ""])
    for row in inherited_lubiao_only:
        lines.append(f"### {row['name']}")
        effects = list(dict.fromkeys(row["lubiao_effects"]))
        lines.append(f"路标卡片：{len(row['lubiao_effects'])} 张；不同效果文本：{len(effects)} 条。")
        for index, effect in enumerate(effects, 1):
            lines.append(f"路标效果 {index}：{render_effect(effect)}")
        lines.append("")

    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"PRTS={len(prts_rows)} Lubiao-cards={len(lubiao_rows)} "
        f"Lubiao-names={len(lubiao_by_name)} agreed={len(agreed_records)} "
        f"PRTS-only={len(prts_only_records)} Lubiao-only={len(lubiao_only_records)} "
        f"different-effects={len(different_records)} inherited={len(inherited_records)} "
        f"inherited-both={len(inherited_both)} inherited-Lubiao-only={len(inherited_lubiao_only)}"
    )
    print(f"Saved {args.output} and {args.data_output}")
    print("PRTS-only:", [row["name"] for row in prts_only_records])
    print("Lubiao-only:", [row["name"] for row in lubiao_only_records])
    print("Inherited Lubiao-only:", [row["name"] for row in inherited_lubiao_only])


if __name__ == "__main__":
    main()
