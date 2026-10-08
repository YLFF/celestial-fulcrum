"""Export a one-time editable relic-pool score sheet from the local catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fulcrum.node_rewards import NodeRewardPoolCatalog
from fulcrum.relic_scoring import RelicScorer


POOL_USES = (
    ("node_battle_normal", "普通作战", "非固定奖励；本阶段普通作战主收益不自动加藏品", "单件"),
    ("node_battle_elite", "紧急作战", "固定领取1件，二选一", "二选一后领取一件"),
    ("pool_boss", "III/V险路恶敌与对应追猎", "默认领取1件，二选一；VI奖励不据此外推", "二选一后领取一件"),
    ("node_battle_savage", "居民据点：枯枝、败叶", "每战1件藏品；两个零件池不属于本表", "单件"),
    ("node_wandering_resident_relic", "流窜居民：强买强卖", "每战1件按当前规则；统计是记录子集，不修改领取数量", "单件"),
    ("node_wandering_resident_convergence_relic", "流窜居民：进退趋同", "只记录到1种藏品，不证明完整池仅1种或固定给它", "单件"),
    ("node_battle_normal_invalid_autopsy", "光明之末：无效验尸", "暂记1藏；专属藏品集合，不用Boss藏品池替代", "单件"),
    ("node_incident_lake_fairy", "湖中仙女：普通湖中魇、紧急湖中魇、直接得藏品", "三个结果共用成员集合；付3钱后80%紧急/20%直接1藏，普通战得藏概率另算", "单件"),
    ("node_duel_right", "狭路相逢高档", "1藏品；低/中档奖励为零件/券，不凭档位新增藏品", "单件"),
    ("node_incident_cave_treasure", "洞中宝：直接得藏品结果", "该结果1件并终止；不要把此池绑定给伴生下一层普通战", "单件"),
    ("node_wish_relic", "得偿所愿、敲动杠杆、被歌颂的影子随机藏品", "共用成员集合，抽取条件/频次独立；影子最终犬植浆另列", "按用途区分单件/二选一"),
    ("node_wish_relic_advanced", "得偿所愿：刷新为更高级", "消耗4钱换候选，仍只领取1件；刷新支出另算", "二选一后领取一件"),
    ("node_story_curiosity_and_death", "假命运所指：好奇心与死", "进入后领取1件并消耗节点；标记真节点的50钱另算", "单件"),
    ("node_hidden_collectible", "思乡心切、划算买卖、鸭托邦、传奇团伙", "共用隐藏藏品池：思乡心切1藏、划算买卖3藏、鸭托邦普通2/紧急3藏、传奇团伙普通3/紧急4藏；不再叠通用紧急藏品", "单件"),
)
PENDING_BINDINGS = (
    ("I/II/IV追猎", "当前只计招募券", "不套Boss藏品池"),
    ("VI结局战斗与VI追猎", "其他奖励待适配", "不将III/V奖励与池外推到VI"),
    ("诡意行商挑战 / 死箱、活木", "战斗经验/钱已知", "额外藏品数量/池未在本地绑定"),
)
FIXED_RELICS = (
    ("relic_209", "黑诞 / “闹乐”等对应事件战斗", "1件固定猎印"),
    ("relic_215", "被歌颂的影子最终轮", "1件固定犬植浆；非随机藏品池"),
    ("relic_208", "和平守卫者", "1件厄运火杆；免费据点战斗另算"),
    ("relic_207", "独活", "1件同行者；免费应急助力另算"),
    ("relic_123", "血衣之下：拽出衣服", "该选项1件他缚；与另外两个藏品选项互斥"),
    ("relic_112", "血衣之下：割怪花", "该选项1件“剑锤”；与另外两个藏品选项互斥"),
    ("relic_239", "血衣之下：砍藤蔓", "该选项1件一串钱伥；与另外两个藏品选项互斥"),
)


def build_index() -> dict:
    catalog = NodeRewardPoolCatalog()
    scorer = RelicScorer(catalog=catalog)
    entries = json.loads((ROOT / "data" / "lubiao_reference_catalog.json").read_text(encoding="utf-8"))["entries"]
    relics = {row["id"]: row for row in entries if row["category"] == "relic"}
    pools = []
    for context_id, usage, rule, unit in POOL_USES:
        context = catalog.get(context_id)
        definition = catalog.get_pool(context["rewardPoolId"])
        aliases = [catalog.get(alias) for alias in definition["contextIds"]]
        if any(member["dataType"] != "藏品" or member["itemId"] not in relics for member in definition["members"]):
            raise ValueError(f"Unbound or non-relic pool member: {context_id}")
        pools.append({
            "id": definition["id"], "usage": usage, "rewardRule": rule, "scoreUnit": unit,
            "expectedPointsPerReceivedRelic": scorer.pool_score(context_id),
            "members": sorted([{"id": row["itemId"], "name": row["name"]} for row in definition["members"]], key=lambda row: row["id"]),
            "contexts": [{"id": alias["id"], "name": alias["name"], "statistics": alias["statistics"],
                          "observations": [{"id": m["itemId"], "count": m["occurrenceCount"], "probability": m["probability"]}
                                           for m in alias["members"]]} for alias in aliases],
        })
    if len({row["id"] for row in pools}) != len(pools):
        raise ValueError("Duplicate shared pool in score sheet")
    fixed = [{"id": rid, "name": relics[rid]["name"], "usage": usage, "rewardRule": rule, "points": scorer.fixed_score(rid)}
             for rid, usage, rule in FIXED_RELICS]
    special_components = []
    for context_id in ("hopeful_fruits", "node_battle_savage_scrap_right"):
        context = catalog.get(context_id)
        special_components.append({"id": context_id, "name": context["name"],
                                   "rewardPoolId": context["rewardPoolId"], "statistics": context["statistics"],
                                   "selection": context.get("selection"), "sourceReferences": context.get("sourceReferences", []),
                                   "members": sorted(context["members"], key=lambda row: row["itemId"])})
    event_bindings = [{"id": eid, "relicContextId": scorer.event_pool(eid)}
                      for eid in ("encounter_013", "encounter_014", "encounter_015", "encounter_016")]
    return {"schemaVersion": 1, "sourceGeneratedAt": catalog.data["generatedAt"],
            "scoreMeaning": "per_received_relic_opportunity_not_whole_event_total",
            "pools": pools, "fixedRelics": fixed, "eventBindings": event_bindings,
            "specialComponentPools": special_components,
            "pendingBindings": [dict(zip(("usage", "rewardRule", "reason"), row)) for row in PENDING_BINDINGS]}


def cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def markdown(index: dict) -> str:
    lines = ["# 战斗与事件藏品池评分表", "",
             "## 评分口径", "",
             "本表供手动校准。池分填写每实际领取一件藏品的期望收益，不是整个事件总分；固定给多件时再乘件数，奖励概率、事件出现概率、钱/经验/券/零件仍另外计算。计算配置在data/blackflow_relic_scoring.json，手动改本表不会自动解析成代码配置。",
             "二选一的池分填写择优领取一件后的期望分，不能再乘2或再算一次择优。若后续改为逐藏品分数推导，则需候选分布/抽样假设，并替代本表的整体代理分，不能两份相加。共用池可在下方按场景覆盖单件分，不需要复制成员清单。",
             "同一成员集合只列一次，共用池的不同条件频次不合并。频次空白表示未记录，不是概率0；仅列成员的池不默认每件等概率。进退趋同目前只有一件已记录藏品，不视为已确认完整池。",
             "普通作战池保留供查询，但本阶段普通作战不自动加一件藏品。伴生战斗的额外藏品不因战斗标签而重复叠通用紧急奖励。",
             "本表独立于数据手册正文和原始概率数据；导出脚本拒绝覆盖已存在的评分表。池分已接入独立校准计算，尚未替换实时路线评分；不改游戏奖励或来源频次。得偿所愿现金≥4时使用高级池150并扣4钱（32分），净118；现金不足4时用普通池100。", "",
             "## 池分待校准", "", "| 池ID | 对应战斗/事件 | 成员数 | 每件领取期望分 |", "| --- | --- | --- | --- |"]
    for pool in index["pools"]:
        lines.append(f"| `{pool['id']}` | {cell(pool['usage'])} | {len(pool['members'])} | {pool['expectedPointsPerReceivedRelic']:g} |")
    lines.extend(["", "## 共用池的场景覆盖", "",
                  "默认沿用上表池分；希望区分条件频次或二选一/直接领取时，在这一列填写数值替代池分，而不是额外加分。成员仍只保留一份。", "",
                  "| 场景ID | 共用池ID | 单件期望分覆盖 |", "| --- | --- | --- |"])
    for pool in index["pools"]:
        if len(pool["contexts"]) > 1:
            for ctx in pool["contexts"]:
                lines.append(f"| `{ctx['id']}` | `{pool['id']}` | 沿用池分 |")
    lines.extend(["", "## 固定藏品", "",
                  "血衣之下的三个藏品选项取最高分的合法选项，不将三件分数相加。固定藏品只替代该次奖励原来的100，其他奖励另算。", "",
                  "| 藏品ID | 名称 | 对应事件 | 单件分 |", "| --- | --- | --- | --- |"])
    for row in index["fixedRelics"]:
        lines.append(f"| `{row['id']}` | {cell(row['name'])} | {cell(row['usage'])} | {row['points']:g} |")
    lines.extend(["", "## 尚未绑定的战斗结果", "", "这些结果暂保留原100×件数，不能声称已确定藏品池。", "",
                  "| 战斗/事件 | 已知奖励 | 缺口/边界 |", "| --- | --- | --- |"])
    for row in index["pendingBindings"]:
        lines.append(f"| {cell(row['usage'])} | {cell(row['rewardRule'])} | {cell(row['reason'])} |")
    lines.extend(["", "## 池成员与条件频次", "",
                  "统计来自本地已归档数据，未在本轮重新联网抓取；下表是池内成员/候选条件频次，不是奖励触发率。", ""])
    for pool in index["pools"]:
        lines.extend([f"### {pool['id']}", "", pool["usage"], "", pool["rewardRule"], ""])
        contexts = pool["contexts"]
        observations = {ctx["id"]: {row["id"]: row for row in ctx["observations"]} for ctx in contexts}
        for ctx in contexts:
            stats = ctx["statistics"]
            lines.append(f"- `{ctx['id']}`：{cell(stats.get('scopeLabel') or stats.get('observationSource') or stats.get('interpretation', '未记录'))}；更新{stats.get('updatedAt', '未记录')}；{cell(stats.get('notes', ''))}")
        headings = ["藏品ID", "名称"] + [f"`{ctx['id']}` 频次" for ctx in contexts]
        lines.extend(["", "| " + " | ".join(headings) + " |", "| " + " | ".join("---" for _ in headings) + " |"])
        for member in pool["members"]:
            values = [f"`{member['id']}`", cell(member["name"])]
            for ctx in contexts:
                obs = observations[ctx["id"]].get(member["id"])
                if obs is None or obs["count"] is None:
                    values.append("未记录")
                else:
                    probability = "" if obs["probability"] is None else f"；{obs['probability']:.2%}"
                    values.append(f"{obs['count']}{probability}")
            lines.append("| " + " | ".join(values) + " |")
        lines.append("")
    lines.extend(["## 红苔相关零件池（收益影响待接入）", "",
                  "这两个池已在同一份本地奖励数据源中保存。这里只保留成员、选择规则和各自统计，不提前叠加红苔带来的节点分。希望硕果的具体额外奖励次数/触发条件后续适配；丰饶树冢使用独立的居民据点频次，不套狭路相逢低档的频次。", ""])
    for pool in index["specialComponentPools"]:
        stats, selection = pool["statistics"], pool["selection"]
        lines.extend([f"### {pool['id']} {pool['name']}", "",
                      f"共用成员池：`{pool['rewardPoolId']}`；样本{stats.get('sampleCount', '未记录')}；成员{len(pool['members'])}种。",
                      f"候选数{selection['candidateCount']}、领取数{selection['takeCount']}。" if selection else "本池未记录候选/领取规则，不由成员概率推断奖励次数。", "",
                      "| 零件ID | 名称 | 候选/抽取记录 | 条件频次 |", "| --- | --- | --- | --- |"])
        for member in pool["members"]:
            probability = member["probability"]
            frequency = "未记录" if probability is None else f"{probability:.2%}"
            count = member["occurrenceCount"]
            lines.append(f"| `{member['itemId']}` | {cell(member['name'])} | {count if count is not None else '未记录'} | {frequency} |")
        lines.append("")
    return "\n".join(lines)


def export_sheet(sheet: Path, data_path: Path) -> None:
    if sheet.resolve() == data_path.resolve():
        raise ValueError("Score sheet and index paths must differ")
    for path in (sheet, data_path):
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite manual score sheet/index: {path}")
    index = build_index()
    sheet.parent.mkdir(parents=True, exist_ok=True)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open("x", encoding="utf-8") as stream:
        stream.write(markdown(index))
    with data_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(index, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, default=ROOT / "RELIC_POOL_SCORING.md")
    parser.add_argument("--index", type=Path, default=ROOT / "work" / "relic_pool_scoring" / "index.json")
    args = parser.parse_args()
    export_sheet(args.sheet, args.index)
    print(args.sheet)


if __name__ == "__main__":
    main()
