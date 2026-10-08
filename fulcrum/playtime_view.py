"""Render the ten mutable map-area snapshots in the Playtime reading view."""

from __future__ import annotations

import json
from typing import Any

from .playtime_state import AREA_SPECS, active_instance
from .component_box import catalog, component_kind
from .opening import COCOON_NAMES, SQUAD_NAMES, DEFAULT_TECHNOLOGY_COMBAT_BONUSES, opening_action_points
from .goals import goal_summary
from .operators import SOURCE_LABELS
from .merchant_state import DEFAULT_INVESTMENT_BALANCE, SHOP_CATEGORIES, snapshot_shelves, shelf_fraction


AREA_TITLES = {
    "I": "I 层", "II": "II 层", "III": "III 层",
    "III-treehole": "III 层树洞（未萌生摇篮）", "IV": "IV 层",
    "IV-remembrance": "IV 层（追忆）",
    "IV-treehole": "IV 层树洞（未萌生摇篮）", "V": "V 层",
    "V-treehole": "V 层树洞（未萌生摇篮）", "VI": "VI 层（源流交汇处）",
}
START_MARKER = "<!-- PLAYTIME_MAPS_START -->"
END_MARKER = "<!-- PLAYTIME_MAPS_END -->"
COMPONENTS_START = "<!-- PLAYTIME_COMPONENTS_START -->"
COMPONENTS_END = "<!-- PLAYTIME_COMPONENTS_END -->"
RESOURCES_START = "<!-- PLAYTIME_RESOURCES_START -->"
RESOURCES_END = "<!-- PLAYTIME_RESOURCES_END -->"
BASIC_START = "<!-- PLAYTIME_BASIC_START -->"
BASIC_END = "<!-- PLAYTIME_BASIC_END -->"
OPERATORS_START = "<!-- PLAYTIME_OPERATORS_START -->"
OPERATORS_END = "<!-- PLAYTIME_OPERATORS_END -->"
RELICS_START = "<!-- PLAYTIME_RELICS_START -->"
RELICS_END = "<!-- PLAYTIME_RELICS_END -->"
INITIAL_RELIC_NAMES = {"relic_134": "河谷祭祈", "relic_211": "黑流树海笔记"}


def _cell(value: Any) -> str:
    return str(value if value is not None else "待确认").replace("|", "\\|").replace("\n", " ")


def _frequency(value: float | None) -> str:
    if value is None:
        return "无对应样本"
    if value == 0:
        return "0%（该距离无样本）"
    percent = value * 100
    if percent < 1:
        return "<1%"
    return f"{percent:.1f}%".replace(".0%", "%")


def _area_view(state: dict[str, Any], key: str, index: int) -> list[str]:
    slot = state["areas"][key]
    lines = [f"### 3.{index} {AREA_TITLES[key]}", ""]
    lines += ["| 项目 | 当前实例 |", "| --- | --- |"]
    if slot["activeInstanceId"] is None:
        lines += [
            "| 地图实例 ID / 模板 / 节点连线 | 待导入 |",
            "| 玩家位置 / 行动力 | 待确认 |",
            "| 当前乌托邦 | 待确认 |",
            "| 节点快照（探明、原始/当前类别、完成、标记、事件） | 待导入 |",
            "| 本层节点池（总数范围、已知、已完成、剩余） | 待计算 |",
            "| 本层不期而遇池（候选、已完成） | 待计算 |",
            "| 本层策略（节点权重、目标） | 待设置 |",
            "| 当前地图图片（含节点预测 mask） | 待生成 |",
        ]
    else:
        instance = active_instance(state, key)
        lines += [
            f"| 地图实例 ID / 模板 / 节点连线 | `{_cell(instance['instanceId'])}` / `{_cell(instance['templateId'])}` / {len(instance['nodes'])} 节点、{len(instance['edges'])} 连线 |",
            f"| 玩家位置 / 行动力 | `{_cell(instance['playerPosition'])}` / {_cell(instance['actionPoints'])} |",
            f"| 当前乌托邦 | {_cell(instance.get('utopiaId'))} |",
            f"| 实托邦（理念、方针、覆盖节点、理想源） | {_cell(instance.get('dystopia'))} |",
            f"| 节点快照（探明、原始/当前类别、完成、标记、事件） | {len(instance['nodes'])} 节点；见下表 |",
            f"| 本层节点池（总数范围、已知、已完成、剩余） | {len(instance['nodePool'])} 类；见下表 |",
            f"| 本层不期而遇池（候选、已完成） | {len(slot['encounterPool'])} 项；见下表 |",
            f"| 本层策略（节点权重、目标） | {_cell(instance['strategy']['goal'])}；覆盖 {len(instance['strategy']['nodeWeights'])} 个节点 |",
            f"| 当前地图图片（含节点预测 mask） | {_cell(instance['mapImage'])} |",
        ]
        if instance["prediction"].get("warnings"):
            lines.append(f"| 预测校验 | {_cell('; '.join(instance['prediction']['warnings']))} |")
        if key == "V":
            entry = instance.get("ending2Entry", {})
            lines.append(f"| 入层沙盘快照 / 二结局生成 | {_cell(instance.get('entrySandboxRelicIds'))} / {_cell(entry)} |")
        lines += ["", "#### 节点快照", "", "| 坐标 | 原始/探明类别 | 当前画面类别 | 可见 | 完成 | 实际完成类别 | 标记 | 不期事件身份 | 未知候选：分类估算概率 |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for node_id, node in sorted(instance["nodes"].items(), key=lambda pair: tuple(map(int, pair[0].split(",")))):
            category_label = node["resolvedCategoryId"] or node["observedCategoryId"]
            if category_label == "node_type_012" and node.get("fateRole") in {"true", "fake"}:
                category_label += "（真）" if node["fateRole"] == "true" else "（假）"
            prediction = instance["prediction"].get("unknownNodes", {}).get(node_id, {})
            posterior = prediction.get("categoryProbabilities")
            candidates = ", ".join(f"{category} {_frequency(probability)}"
                                    for category, probability in posterior.items()) if posterior is not None else ", ".join(
                f"{candidate['nodeType']} 距离频次 {_frequency(candidate['distanceFrequency'])}"
                f"{'（数量规则冲突）' if candidate.get('countRuleConflict') else ''}"
                for candidate in prediction.get("candidates", []))
            lines.append(
                f"| `{node_id}` | {_cell(category_label)} | {_cell(node['observedCategoryId'])} | {node['visibility']} | {node['completion']} | {_cell(node.get('completedCategoryId'))} | {_cell(', '.join(node['confirmedMarkIds']))} | {_cell(node['encounterId'])} | {_cell(candidates)} |"
            )
        if instance["nodePool"]:
            lines += ["", "#### 节点池", "", "| 类别 | 总数范围 | 已知数 | 已完成数 | 尚可能数 |", "| --- | --- | ---: | ---: | --- |"]
            for node_type, row in instance["nodePool"].items():
                maximum = row["maximum"] if row["maximum"] is not None else "无上限"
                remaining = "待核" if row.get("countRuleConflict") else (
                    row["maximumRemaining"] if row["maximumRemaining"] is not None else "无上限"
                )
                lines.append(f"| {node_type} | {row['minimum']}–{maximum} | {row['knownCount']} | {row['completedCount']} | {row['minimumRemaining']}–{remaining} |")
        else:
            lines += ["", "该区域没有可套用的 I–V 主层节点数量/距离统计表。"]
        shops = [(key, node) for key, node in instance["nodes"].items()
                 if (node.get("resolvedCategoryId") or node.get("observedCategoryId")) in SHOP_CATEGORIES]
        if shops:
            lines += ["", "#### 商店货柜状态", "", "| 节点 | 已查看面数（含初始面） | 剩余比例 |", "| --- | ---: | ---: |"]
            for key, node in shops:
                viewed = snapshot_shelves(node)
                lines.append(f"| `{key}` | {viewed}/5 | {shelf_fraction(viewed):.0%} |")
    lines += ["", "#### 本层不期而遇池", "", "| 事件 | 状态 | 本层完成 / 本局完成 | 条件 |", "| --- | --- | --- | --- |"]
    for event in slot["encounterPool"]:
        lines.append(f"| {event['id']} {event['name']} | {event['eligibility']} | {event['completedHere']} / {event['completedRun']} | {_cell(', '.join(event['requirements']))} |")
    lines.append("")
    return lines


def render_map_sections(state: dict[str, Any]) -> str:
    current = state.get("currentAreaKey")
    lines = [START_MARKER, f"当前区域：{AREA_TITLES.get(current, '待确认')}。", ""]
    for index, key in enumerate(AREA_SPECS, 1):
        lines.extend(_area_view(state, key, index))
    lines += ["### 3.11 全局不期而遇池", "", "| 事件 ID / 名称 | 可能出现层 | 能否重复 | 本局完成次数 | 已确认节点 |", "| --- | --- | --- | ---: | --- |"]
    for event in state["globalEncounterPool"]:
        nodes_with_outcomes = ", ".join(
            f"{location}（{event['outcomes'][location]}）" if location in event.get("outcomes", {}) else location
            for location in event["completedAt"]
        )
        lines.append(
            f"| {event['id']} {event['name']} | {', '.join(event['floors'])} | {event['repeatability']} | {event['completedCount']} | {_cell(nodes_with_outcomes)} |"
        )
    lines += [END_MARKER]
    return "\n".join(lines)


def replace_map_sections(markdown: str, state: dict[str, Any]) -> str:
    start = markdown.find(START_MARKER)
    end = markdown.find(END_MARKER)
    if start < 0 or end < start:
        raise ValueError("Playtime Markdown map-section markers are missing")
    return markdown[:start] + render_map_sections(state) + markdown[end + len(END_MARKER):]


def _replace_section(markdown: str, start_marker: str, end_marker: str, content: str) -> str:
    start = markdown.find(start_marker)
    end = markdown.find(end_marker)
    if start < 0 or end < start:
        raise ValueError(f"Playtime Markdown markers are missing: {start_marker}")
    return markdown[:start] + content + markdown[end + len(end_marker):]


def render_basic_section(state: dict[str, Any]) -> str:
    opening = state.get("opening", {})
    squad_id = opening.get("squadId")
    squad = f"`{squad_id}` {SQUAD_NAMES[squad_id]}" if squad_id else "未知"
    cocoons = opening.get("cocoons", {})
    cocoon_text = "、".join(f"{COCOON_NAMES[relic_id]} ×{count}" for relic_id, count in cocoons.items()) or "无"
    pending = state.get("pendingOpeningRewards", [])
    area = state.get("currentAreaKey")
    bonuses = opening.get("technologyCombatBonuses")
    bonus_rows = [
        f"| 局外科技{name}加成 | +{bonuses[field]:g}% |" if bonuses is not None
        else f"| 局外科技{name}加成 | 未记录 |"
        for name, field in (("攻击力", "attackPercent"), ("防御力", "defensePercent"), ("生命值", "maxHpPercent"))
    ]
    if bonuses is None:
        technology_preset = "三项属性未记录；其余科技逐项配置待接入"
    elif bonuses == DEFAULT_TECHNOLOGY_COMBAT_BONUSES:
        technology_preset = "三项属性为满解锁默认；其余科技逐项配置待接入"
    else:
        technology_preset = "三项属性自定义；其余科技逐项配置待接入"
    return "\n".join([
        BASIC_START, "## 1. 基础信息", "", "| 字段 | 当前值 |", "| --- | --- |",
        f"| 本局 ID | `{_cell(state['runId'])}` |",
        "| 状态 | 进行中 |",
        f"| 更新时间 | {_cell(state.get('updatedAt'))} |",
        f"| 难度 | {opening.get('difficulty', 15)} |",
        f"| 分队 ID / 名称 | {squad} |",
        f"| 本局启用的襁褓 | {cocoon_text} |",
        f"| 待确认的随机开局奖励 | {_cell('、'.join(pending)) if pending else '无'} |",
        f"| 局外科技预设 | {technology_preset} |",
        *bonus_rows,
        f"| 羽瞰点局外科技：分裂 | {'已解锁' if opening.get('lookoutSplitUnlocked', True) else '未解锁'}"
        f"{'（旧局按满科技默认）' if 'lookoutSplitUnlocked' not in opening else ''} |",
        "| 战斗经验科技倍率 | 默认 1.1 × 1.1 × 1.1；所有倍率最终统一取整 |",
        "| 局外科技开局加成 | 已预填默认资源，不重复叠加 |",
        "| 难度修正 | 账号/难度完整重算待接入，当前资源以确认值为准 |",
        "| 机械师精通预设 | 满解锁；助力、招募、进阶按确认操作结算 |" if opening.get("mechanistMasteryPreset") == "full"
        else "| 机械师精通预设 | 未记录；旧局不自动补发助力或奖励 |",
        "| 机械师后备 / 招募减费 / 招募箱容量与进阶奖励档位 | 一场助力；招募 -4 / 进阶 -2 希望；容量 +2；进阶结构性原理 |"
        if opening.get("mechanistMasteryPreset") == "full"
        else "| 机械师后备 / 招募减费 / 招募箱容量与进阶奖励档位 | 待确认；临时助力不等同于已招募 |",
        "| 其他开局条件 / 资源覆盖 | 当前资源以确认快照为准 |",
        f"| 当前区域 / 是否树洞 / 母层 | {AREA_TITLES.get(area, '未知')} |",
        f"| 当前追猎次数 | {state.get('pursuitCount', 0)} |",
        BASIC_END,
    ])


def render_operator_section(state: dict[str, Any]) -> str:
    operators = state.get("operators", [])
    lines = [
        OPERATORS_START, f"## 4. 干员池（当前 {len(operators)} 人）", "",
        "| 干员 | 职业 | 星级 | 精英阶段 | 招募来源 | 在队 / 暂离 / 临时期限 | 备注 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for operator in operators:
        elite = f"精{operator['elite']}" if operator.get("elite") is not None else "待确认"
        source = SOURCE_LABELS.get(operator.get("source"), operator.get("source"))
        remaining = operator.get("remainingBattles")
        availability = f"在队；可出战 {remaining} 场" if remaining is not None else (
            "在队" if "remainingBattles" in operator else "待确认"
        )
        lines.append(f"| {_cell(operator['name'])} | {_cell(operator.get('profession'))} | {_cell(operator.get('rarity'))} | {elite} | {_cell(source)} | {availability} | `{_cell(operator['instanceId'])}` |")
    return "\n".join([*lines, OPERATORS_END])


def render_relic_section(state: dict[str, Any]) -> str:
    relics = state.get("relics", [])
    lines = [
        RELICS_START, f"## 5. 藏品（当前 {sum(row['count'] for row in relics)} 件）", "",
        "| 藏品 ID | 名称 | 状态值（数量 / 层数 / 生效） |",
        "| --- | --- | --- |",
    ]
    for relic in relics:
        relic_id = relic["id"]
        name = COCOON_NAMES.get(relic_id, INITIAL_RELIC_NAMES.get(relic_id, relic_id))
        value = relic["count"] if relic["count"] > 1 else relic.get("state")
        lines.append(f"| `{relic_id}` | {name} | {'' if value is None else value} |")
    return "\n".join([*lines, RELICS_END])


def render_component_section(state: dict[str, Any]) -> str:
    box = state["componentBox"]
    items = box["items"]
    counts = {kind: sum(component_kind(item["componentId"]) == kind for item in items)
              for kind in ("加工品", "概念体", "自然物")}
    lines = [
        COMPONENTS_START,
        f"## 6. 零件箱（当前 {len(items)} 件，上限 {box['capacity']} 件）",
        "", "| 指标 | 当前值 |", "| --- | --- |",
        f"| 已占用格数 | {len(items)} |",
        f"| 加工品 / 概念体 / 自然物数量 | {counts['加工品']} / {counts['概念体']} / {counts['自然物']} |",
        "", "| 实例 ID | 零件 ID | 名称 | 类别 | 当前估价 | 剩余使用次数 | 参与路线规划 |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for item in items:
        component = catalog()[item["componentId"]]
        lines.append(
            f"| `{item['instanceId']}` | `{item['componentId']}` | {_cell(component['name'])} | "
            f"{component_kind(item['componentId'])} | {_cell(item['estimatedValue'])} | "
            f"{_cell(item['remainingUses']) if item['remainingUses'] is not None else '-'} | "
            f"{'是' if item['routeCandidate'] else '否'} |"
        )
    lines += [COMPONENTS_END]
    return "\n".join(lines)


def render_resource_section(state: dict[str, Any]) -> str:
    resources = state["resources"]
    current = state.get("currentAreaKey")
    action = None
    if current and state["areas"][current]["activeInstanceId"]:
        action = active_instance(state, current).get("actionPoints")
    elif current is None:
        action = opening_action_points(state.get("opening", {}), "I")
    life = resources["life"]
    experience = resources["experience"]
    values = [item["estimatedValue"] for item in state["componentBox"]["items"]]
    known_value = sum(value for value in values if value is not None)
    valuation = str(known_value) if all(value is not None for value in values) else f"已知 {known_value}，另有待估价"
    tickets = state.get("recruitmentTickets", [])
    lines = [
        RESOURCES_START, "## 7. 实时资源", "", "| 资源 | 当前值 | 上限 / 下一级 |", "| --- | --- | --- |",
        f"| 指挥等级 | {_cell(resources['level'])} | - |",
        f"| 经验 | {_cell(experience['current'])} | {('下一级需求 ' + str(experience['max'])) if experience['max'] is not None else '下一级需求未知'} |",
        f"| 希望 | {_cell(resources['hope'])} | - |",
        f"| 源石锭 | {_cell(resources['originiumIngot'])} | - |",
        f"| 投资余额（取钱预算） | {_cell(resources.get('investmentBalance', DEFAULT_INVESTMENT_BALANCE))} | 玩家可调整；不是当前现金 |",
        f"| 总估价 | {valuation} | - |",
        f"| 目标生命 | {_cell(life['current'])} | 上限 {_cell(life['max'])} |",
        f"| 护盾 | {_cell(resources['shield'])} | - |",
        f"| 行动力 | {_cell(action) if action is not None else '未知'} | - |",
        f"| 干员携带位 | {_cell(resources.get('carrySlots', 7))} | 上限 13 |",
        f"| 部署位 | {_cell(resources.get('deploymentSlots', 6))} | 无上限 |",
        f"| 招募券留存 | {len(tickets)} | 上限 {_cell(resources.get('recruitmentTicketCapacity', 3))} |",
        "", "| 招募券类别 | 数量 |", "| --- | ---: |",
    ]
    if tickets:
        for category in sorted(set(tickets)):
            lines.append(f"| {_cell(category)} | {tickets.count(category)} |")
    else:
        lines.append("| 暂无 | 0 |")
    lines.append(RESOURCES_END)
    return "\n".join(lines)


def replace_runtime_sections(markdown: str, state: dict[str, Any]) -> str:
    markdown = replace_map_sections(markdown, state)
    if "goals" in state:
        summary = goal_summary(state)
        lines = ["## 2. 全局策略、结局目标与进度", "",
                 f"五层目标：{_cell(summary['endingV'])}；六层目标：{_cell(summary['endingVI'])}。", "",
                 "| 事项 | 优先级 | 进度 | 备注 |", "| --- | --- | --- | --- |"]
        priorities = {"required": "必须完成", "preferred": "尽量获取", "ignored": "不需要"}
        statuses = {"unknown": "未知", "pending": "未完成", "completed": "已完成", "unavailable": "不可完成"}
        lines += [f"| {row['name']} | {priorities[row['priority']]} | {statuses[row['status']]} | {_cell(row['note'])} |"
                  for row in summary["milestones"]]
        lines += ["", _cell(summary["note"]), "", "目标进度用于提示；本次规划优先目标由玩家在规划时选择。", ""]
        start = markdown.find("## 2. 全局策略、结局目标与进度")
        end = markdown.find("## 3. 地图、节点与本层策略", start)
        if end < 0:
            end = markdown.find(START_MARKER, start)
        if start >= 0 and end >= start:
            markdown = markdown[:start] + "\n".join(lines) + "\n" + markdown[end:]
    for start, end, render in (
        (BASIC_START, BASIC_END, render_basic_section),
        (OPERATORS_START, OPERATORS_END, render_operator_section),
        (RELICS_START, RELICS_END, render_relic_section),
    ):
        if start in markdown:
            markdown = _replace_section(markdown, start, end, render(state))
    if COMPONENTS_START in markdown:
        markdown = _replace_section(markdown, COMPONENTS_START, COMPONENTS_END, render_component_section(state))
    if RESOURCES_START in markdown:
        markdown = _replace_section(markdown, RESOURCES_START, RESOURCES_END, render_resource_section(state))
    return markdown


def render_standalone(state: dict[str, Any]) -> str:
    """The desktop exporter must also work without the editable project manual."""
    template = "\n\n".join([
        "# Playtime", f"{BASIC_START}\n{BASIC_END}",
        "## 2. 全局策略、结局目标与进度", "## 3. 地图、节点与本层策略",
        f"{START_MARKER}\n{END_MARKER}", f"{OPERATORS_START}\n{OPERATORS_END}",
        f"{RELICS_START}\n{RELICS_END}", f"{COMPONENTS_START}\n{COMPONENTS_END}",
        f"{RESOURCES_START}\n{RESOURCES_END}",
    ])
    return replace_runtime_sections(template, state) + "\n"
