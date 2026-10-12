"""Read the hand-maintained handbook and export a review-only relic partition."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "BLACKFLOW_REFERENCE.md"
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
SIGNAL_LABELS = {
    "attributes": "单位属性",
    "damage": "伤害／元素损伤",
    "cost": "部署费用／费用回复",
    "skill": "技力／技能",
    "special": "战术或特殊效果",
}
CALIBRATION_FIELDS = (
    "确认分类",
    "展示类型（普通型／层数型／生效型／附魔型，可多选）",
    "层数／阶段规则（初始值、上限、增减条件、各阶段差异）",
    "生效／失效规则（触发时机、持续范围、是否消耗）",
    "附魔规则（受益对象数量、选择方式、绑定及保留条件）",
    "效果文字修订（留空沿用原文）",
    "其他备注",
)
EFFECT_FIELDS = (
    "效果类别（我方／敌方／资源／战斗特殊／探索特殊）",
    "具体指标",
    "生效对象与范围（职业、子职业、近远程、指定干员等）",
    "伤害类型（物理／法术／真实／元素损伤／元素伤害／不适用）",
    "计算区（局外／局内／不适用／待确认）",
    "计算方式（固定值／百分比／动态表达式／特殊）",
    "数值、单位或表达式",
    "生效条件与触发时机",
    "持续时间、次数或上限",
    "同类叠加方式与例外（相加／相乘／覆盖／其他）",
)
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


def render_calibration(review: dict) -> str:
    lines = ["# 黑流树海藏品效果：人工校准表", "",
             "本表供玩家校准，不接入现有评分、战力门槛或加成汇总。以当前手工数据手册中的 ID、名称和完整效果为底稿，保留已有文本初筛；初筛分类不是已确认结论。", "",
             f"- 来源：`{review['source']}` 的第 8 章。",
             f"- 来源内容 SHA-256：`{review['sourceSha256']}`。",
             f"- 收录：{len(review['entries'])} 件藏品，每个基础 ID 一项；多阶段效果保留在同一项中。", "",
             "## 填写口径", "",
             "- 只校准本 Markdown 文件，不需要同时编辑生成时的初筛 JSON。现有数据手册、程序藏品表和评分配置保持不变；后续根据确认内容另行结构化。",
             "- 空白表示尚未填写，不代表 0、无效果、全体适用或已生效。可以先填展示类型和分类，再逐步补完效果。",
             "- 展示类型：普通型为不需额外状态的效果；层数型需维护层数或阶段；生效型需维护触发前后状态；附魔型需绑定受益干员。这些标签可以同时使用。",
             "- 层数或阶段请写明初始值、上限、增减条件及不同阶段效果；不要把多元奇物的品质变体默认当成可累计层数。",
             "- 一个藏品有多个指标、作用对象或乘区时，复制其“效果 1”表，改名为效果 2、效果 3，分别填写；混合效果中的探索或资源部分也要保留。",
             "- 生效范围逐效果填写，可包含全体／指定干员／我方或敌方／职业／子职业／近战或远程／精英化／召唤物等，并保留额外条件。",
             "- 局内／局外指你要确认的加成计算区；即时资源奖励等可填“不适用”。条件、动态表达式、百分比的叠加方式另行填写，不从初筛自动推定。",
             "- 具体指标可填：我方生命、防御、法抗、攻击、攻速；敌方生命、防御、法抗；部署费用、费用回复、再部署、技力、伤害、治疗、阻挡等；非战斗项如经验、希望、编队位、部署位、现金、零件箱或事件效果。",
             "- 附魔请写清受益人数、对象选择与触发时机、藏品是否保留，以及附魔后状态；本表不会自动执行干员进阶。",
             "- 完成一项后将“校准状态”改为“已确认”；可以只确认分类并写明仍待核实的字段。此导出工具拒绝覆盖已有文件，避免丢失你的校准。", "",
             "## 初筛概览", "", "| 初筛分类 | 数量 |", "| --- | ---: |"]
    lines.extend(f"| {label} | {review['counts'][group]} |" for group, label in GROUP_LABELS.items())
    lines.extend([f"| 合计 | {len(review['entries'])} |", ""])
    for group, label in GROUP_LABELS.items():
        lines.extend([f"## {label}", ""])
        for row in review["entries"]:
            if row["group"] != group:
                continue
            signals = "、".join(SIGNAL_LABELS[signal] for signal in row["combatSignals"]) or "未匹配直接战斗信号"
            lines.extend([f"### {row['id']} {row['name']}", "",
                          f"- 原始效果：{row['effect']}",
                          f"- 初筛分类：{GROUP_LABELS[row['group']]}；方向：{signals}。",
                          f"- 初筛依据：{row['reason']}",
                          f"- 来源位置：数据手册第 {row['sourceLine']} 行。", "",
                          "| 校准字段 | 填写内容 |", "| --- | --- |", "| 校准状态 | 待确认 |"])
            lines.extend(f"| {field} |  |" for field in CALIBRATION_FIELDS)
            lines.extend(["", "#### 效果 1（多个效果请复制此表）", "",
                          "| 效果字段 | 填写内容 |", "| --- | --- |"])
            lines.extend(f"| {field} |  |" for field in EFFECT_FIELDS)
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--json", type=Path, default=ROOT / "work/relic_effects/review.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "work/relic_effects_review/report.md")
    parser.add_argument("--calibration", action="store_true", help="Add editable calibration fields to Markdown")
    args = parser.parse_args()
    protected = {args.source.resolve(), *(ROOT / name for name in
                 ("BLACKFLOW_REFERENCE.md", "BLACKFLOW_RULEBOOK.md", "BLACKFLOW_PLAYTIME_TEMPLATE.md"))}
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
    renderer = render_calibration if args.calibration else render_review
    outputs[1].write_text(renderer(review), encoding="utf-8")
    print(json.dumps({"total": len(review["entries"]), **review["counts"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
