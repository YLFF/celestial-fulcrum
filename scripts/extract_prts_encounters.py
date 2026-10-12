"""Extract Blackflow encounter floors, choices, and repeat notes from PRTS."""

from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
import re
import sys

from playwright_browser import chromium_executable


ROOT = Path(__file__).resolve().parents[1]
URL = "https://prts.wiki/w/沉沦者的黑流树海/事件一览"
OUTPUT = ROOT / "data" / "blackflow_encounter_pool.json"
CATALOG = ROOT / "data" / "lubiao_reference_catalog.json"


def repeat_status(name: str) -> str:
    if name in {"色味不同源", "敲动杠杆", "货从口出"}:
        return "same_run_possible"
    if name == "洞中宝":
        return "inside_and_outside_once"
    return "once_per_run"


CHOICE_EFFECT_OVERRIDES = {
    "黑诞": {
        "和猎狗战斗到底": "遭遇一场艰难的特殊作战；胜利后的藏品固定为猎印",
        "掏出笼控器控制猎狗": "持有笼控器即可获得猎印，不消耗笼控器",
    },
    "呼吸的红苔": {
        "尝试驱赶猎狗": "持有笼控器即可获得30源石锭，并在下一区域生成希望的沃土；不消耗笼控器",
    },
    "愈创之心": {
        "检测此地有无危险": "持有笼控器即可获得5行动力，不消耗笼控器",
    },
    "鸭托邦": {
        "呛一句": "普通开业剪彩，完美胜利获取对应经验/钱及2藏品",
        "故意挑事": "暂定现金≥0可选，紧急开业剪彩经验/钱及3藏品，不额外叠加通用紧急藏品；真实门槛待校准",
    },
    "传奇团伙": {
        "凭什么？": "原地坐下触发普通合伙人会议，经验/钱及3藏品",
        "扎穿货车车胎": "现金≥50（不计估价，不消耗50钱）可选，紧急合伙人会议经验/钱及4藏品，不额外叠加通用紧急藏品",
    },
    "湖中仙女": {
        "上前看看": "连续三次各支付1钱，共消耗3源石锭，80%紧急湖中魇、20%不作战直接获得同池1藏品；普通战斗也可能获得同池1藏品，出现率见战斗统计",
    },
    "洞中宝": {
        "树洞里肯定有好东西": "每轮随机获得5源石锭、无奖励、获得1藏品并终止、或触发下一层普通作战并终止；5钱与无奖励后可以继续；本阶段四种结果暂各25%，不是实测概率",
    },
    "独活": {
        "去看看小狗": "获得同行者后可免费前往本层未完成的应急助力；已经完成并消失的助力不能再前往，但仍获得同行者",
    },
}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--correct-local", action="store_true", help="apply confirmed choice corrections without fetching PRTS")
    args = parser.parse_args()
    if args.correct_local:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        for event in payload["eventPool"]:
            for choice in event["openingChoices"]:
                choice["effect"] = CHOICE_EFFECT_OVERRIDES.get(event["name"], {}).get(choice["label"], choice["effect"])
        OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Applied confirmed choice corrections; retained event IDs and other fields")
        return
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=chromium_executable(None))
        try:
            page = browser.new_page()
            response = page.goto(URL, wait_until="domcontentloaded", timeout=30000)
            if not response or response.status != 200:
                raise RuntimeError("Could not open PRTS event list")
            rows = page.evaluate(
                """async () => {
                  const html = await fetch(location.href).then(response => response.text());
                  const document = new DOMParser().parseFromString(html, 'text/html');
                  let currentType = null;
                  const result = [];
                  for (const group of document.querySelectorAll('#IS-event-data-root > .IS-event-data')) {
                    const start = group.querySelector('.scene[data-nav="开始"]');
                    if (!start) continue;
                    currentType = start.getAttribute('data-etype') || currentType;
                    if (currentType !== '不期而遇') continue;
                    const repeatText = start.querySelector('.edesc')?.textContent.trim() ?? '';
                    result.push({
                      name: start.getAttribute('data-name'),
                      floors: (start.getAttribute('data-efloor') || '').split(',').filter(Boolean),
                      repeatNote: repeatText.replace(/\\s+/g, ' ').trim(),
                      sceneCount: group.querySelectorAll('.scene').length,
                      openingChoices: [...start.querySelectorAll(':scope > .choose')].map(choice => ({
                        label: choice.getAttribute('data-title')?.trim() ?? '',
                        effect: choice.querySelector('.desc1')?.textContent.replace(/\\s+/g, ' ').trim() ?? ''
                      }))
                    });
                  }
                  return result;
                }"""
            )
        finally:
            browser.close()

    if len(rows) != 23 or len({row["name"] for row in rows}) != len(rows):
        raise RuntimeError(f"Expected 23 distinct encounters, got {len(rows)}")
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    mark_ids = {row["name"]: row["id"] for row in catalog["entries"] if row["category"] == "node_mark"}
    events = []
    for index, row in enumerate(rows, 1):
        repeat_note = row["repeatNote"]
        repeat_note = re.sub(r"^(.+。) \1$", r"\1", repeat_note)
        event = {
            "id": f"encounter_{index:03d}",
            "name": row["name"],
            "floors": row["floors"],
            "openingChoices": [
                {
                    "label": choice["label"],
                    "effect": CHOICE_EFFECT_OVERRIDES.get(row["name"], {}).get(
                        choice["label"], re.sub(r"^\d+(?=获得)", "", choice["effect"])
                    ),
                }
                for choice in row["openingChoices"]
            ],
            "sceneCount": row["sceneCount"],
            "repeatability": repeat_status(row["name"]),
            "repeatNote": repeat_note or None,
            "appearanceConditions": [],
            "specialMarkId": None,
            "detailStatus": "opening_choices_only",
        }
        if event["name"] == "和平守卫者":
            event["appearanceConditions"].append({
                "source": "user",
                "condition": "当前层存在居民据点节点",
            })
        elif event["name"] == "独活":
            event["appearanceConditions"].append({
                "source": "user",
                "condition": "当前层存在应急助力节点",
            })
        elif event["name"] == "呼吸的红苔":
            event["appearanceConditions"].append({
                "source": "user",
                "condition": "本局经历沉寂之屋并取得过笼控器，之后卖掉笼控器不影响出现资格",
            })
        elif event["name"] == "线人":
            event["specialMarkId"] = mark_ids["线人与线索"]
            event["appearanceConditions"].append({
                "source": "user",
                "condition": "若上一层未进入该事件，下一层仍可出现",
            })
        elif event["name"] == "泪之聚落":
            event["specialMarkId"] = mark_ids["神明之殇"]
        if event["repeatability"] == "once_per_run":
            event["repeatNote"] = (
                "未实际经历时可跨层再现；本局实际经历后不再出现。"
                if event["name"] in {"线人", "泪之聚落"} else "本局最多实际经历一次。"
            )
        events.append(event)

    payload = {
        "schemaVersion": 2,
        "source": {
            "name": "PRTS 沉沦者的黑流树海/事件一览",
            "url": URL,
            "extractedAt": datetime.now(timezone.utc).isoformat(),
            "qqDocsStatus": "未能读取事件页签单元格；本版以 PRTS 结构化事件页为准",
        },
        "notes": [
            "openingChoices 仅表示事件起始场景的选项和简述；多阶段后续分支未完全整理。",
            "常规可重复经历事件只有色味不同源、敲动杠杆、货从口出；洞中宝在同一局主层/树洞内各可经历一次。",
            "树洞内不期而遇按进入的母层刷新；此规则来自用户补充。",
            "特殊标记与节点类型分别记录；探明标记后可识别线人或泪之聚落。",
        ],
        "eventPool": events,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(events)} encounters to {OUTPUT}")
    for event in events:
        print(event["id"], event["name"], ",".join(event["floors"]), event["repeatability"])


if __name__ == "__main__":
    main()
