"""Read the hand-maintained handbook and export a review-only relic partition."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "BLACKSTREAM_REFERENCE.md"
GROUP_LABELS = {
    "combat": "战斗数值或条件效果",
    "combat_special": "战斗特殊效果",
    "mixed": "战斗与非战斗混合效果",
    "noncombat": "无直接战斗效果",
    "review": "描述待确认",
}
COMBAT_SIGNALS = {
    "attributes": r"攻击力|防御(?:力)?|法术抗性|法抗|攻击速度|生命",
    "damage": r"伤害|元素损伤|爆发效果|脆弱",
    "cost": r"部署费用|费用回复|回复.*部署费用|获得.*部署费用",
    "skill": r"技力|弹药|技能会自动开启|无法开启技能",
    "special": r"治疗|屏障|护盾|闪避|阻挡|重量|晕眩|寒冷|冻结|束缚|浮空|失重|迷彩|再部署|起飞|降落|召唤|免疫异常|在高台部署|在低地部署|便携式补给站|干扰地雷|轰隆隆先生|安全起重机|防暴桩|舞台雾机|战斗.*失败|灾厄之口",
}
NONCOMBAT_SIGNAL = re.compile(
    r"目标生命|护盾值|指挥经验|战斗经验|希望|可携带干员|可同时部署人数|"
    r"可同时部署人|可同时部署数量|招募(?:券|所需)|临时招募|立即进阶|零件箱容量|行动力|"
    r"源石锭[-+]|获得[^；。\n]*源石锭|购买道具.*源石锭|"
    r"获得(?:\d+|[一二三四五六七八九十]+|一个|随机)[^；。\n]*(?:收藏品|加工品|自然物|零件|小玩意)|"
    r"获得【[^】]+】|获得自然物|获得收藏品|得偿所愿节点.*可选项|战利品.*可选项|"
    r"让探索|下次探索|下一区域|特殊节点"
)


def parse_relics(text: str) -> list[dict]:
    section = re.search(r"(?m)^## 8\. 藏品池[^\n]*\n", text)
    if section is None:
        raise ValueError("handbook relic section is missing")
    tail = text[section.end():]
    end = re.search(r"(?m)^## ", tail)
    body = tail[:end.start()] if end else tail
    headings = list(re.finditer(r"(?m)^### (relic_\d+) ([^\n]+)\n", body))
    if not headings:
        raise ValueError("handbook relic section has no entries")
    rows = []
    for index, heading in enumerate(headings):
        block_end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        block = body[heading.end():block_end].strip()
        if not block.startswith("- 效果："):
            raise ValueError(f"missing effect: {heading.group(1)}")
        effect = block.removeprefix("- 效果：").strip()
        if not effect:
            raise ValueError(f"empty effect: {heading.group(1)}")
        line = text[:section.end() + heading.start()].count("\n") + 1
        rows.append({"id": heading.group(1), "name": heading.group(2).strip(),
                     "effect": effect, "sourceLine": line})
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate relic IDs")
    return rows


def screen_effect(effect: str) -> dict:
    # Exploration HP/shield and squad slots are not unit HP/barriers/deployment cost.
    combat_text = re.sub(r"目标生命(?:值|上限)?|护盾值|可携带干员|可同时部署(?:人数|人|数量)", "", effect)
    signals = [name for name, pattern in COMBAT_SIGNALS.items() if re.search(pattern, combat_text)]
    noncombat = bool(NONCOMBAT_SIGNAL.search(effect))
    incomplete = any(effect.count(left) != effect.count(right) for left, right in (("（", "）"), ("(", ")"), ("【", "】")))
    if incomplete:
        group, reason = "review", "原文括号不完整，保留原文待确认，不推测缺失内容。"
    elif signals and noncombat:
        group, reason = "mixed", "同时含直接战斗效果与探索/资源/招募等效果，后续按效果拆分。"
    elif signals:
        group = "combat_special" if signals == ["special"] else "combat"
        reason = "含直接战斗效果；本轮不判定乘区、生效数值或叠加公式。"
    elif noncombat:
        group, reason = "noncombat", "只描述探索、资源、招募或获得/转换物品，无直接单位属性或战斗效果。"
    else:
        group, reason = "review", "没有匹配到明确分类，需人工检查，不默认无战斗效果。"
    return {"group": group, "combatSignals": signals, "hasNoncombatEffect": noncombat,
            "reason": reason, "confirmed": False}


def build_review(text: str) -> dict:
    rows = [{**row, **screen_effect(row["effect"])} for row in parse_relics(text)]
    counts = Counter(row["group"] for row in rows)
    return {"schemaVersion": 1, "purpose": "review-only", "source": SOURCE.name,
            "sourceSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "counts": {group: counts[group] for group in GROUP_LABELS}, "entries": rows}


def render_review(review: dict) -> str:
    lines = ["# 藏品战斗相关性：确认草稿", "",
             "从当前手工数据手册读取名、ID与完整描述。下面是文本初筛，全部未确认；不参与战斗计算或路线评分。混合效果同时保留战斗与非战斗部分。", "",
             "确认分类后再拆分固定/条件、对象范围、伤害类型和叠加规则。本清单不修改藏品正文；重新导出到新文件，不覆盖玩家批注。", "",
             "| 分组 | 数量 |", "| --- | ---: |"]
    lines.extend(f"| {label} | {review['counts'][group]} |" for group, label in GROUP_LABELS.items())
    lines.extend([f"| 合计 | {len(review['entries'])} |", ""])
    for group, label in GROUP_LABELS.items():
        lines.extend([f"## {label}", ""])
        for row in review["entries"]:
            if row["group"] != group:
                continue
            lines.extend([f"### {row['id']} {row['name']}", "",
                          f"- 效果：{row['effect']}", f"- 初筛依据：{row['reason']}",
                          "- 确认或修订：待确认", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--json", type=Path, default=ROOT / "work/relic_effects/review.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "work/relic_effects_review/report.md")
    args = parser.parse_args()
    protected = {args.source.resolve(), *(ROOT / name for name in
                 ("BLACKSTREAM_REFERENCE.md", "BLACKSTREAM_RULEBOOK.md", "BLACKFLOW_PLAYTIME_TEMPLATE.md"))}
    outputs = [args.json.resolve(), args.markdown.resolve()]
    if len(set(outputs)) != len(outputs) or any(path in protected for path in outputs):
        parser.error("outputs must be distinct and must not overwrite source or maintained handbooks")
    if any(path.exists() for path in outputs):
        parser.error("output already exists; choose new filenames to preserve review edits")
    review = build_review(args.source.read_text(encoding="utf-8"))
    review["source"] = args.source.name
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    outputs[0].write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    outputs[1].write_text(render_review(review), encoding="utf-8")
    print(json.dumps({"total": len(review["entries"]), **review["counts"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
