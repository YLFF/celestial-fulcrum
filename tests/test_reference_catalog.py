"""Offline checks for stable catalog IDs and local image bindings."""

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from scripts.reference_catalog import CATEGORY_ORDER, deduplicate_cards, id_number, merge_category


ROOT = Path(__file__).resolve().parents[1]


def card(item_id: str | None, source_id: str, name: str, effect: str = "effect") -> dict:
    row = {"category": "relic", "sourceId": source_id, "name": name, "effect": effect}
    if item_id:
        row["id"] = item_id
    return row


class CatalogMergeTests(unittest.TestCase):
    def test_reordered_source_and_new_card_keep_existing_ids(self) -> None:
        old = [card("relic_001", "a", "甲"), card("relic_002", "b", "乙")]
        fetched = [card(None, "c", "丙"), card(None, "b", "乙"), card(None, "a", "甲")]
        merged, additions = merge_category("relic", old, deduplicate_cards("relic", fetched, old))
        self.assertEqual([row["id"] for row in merged], ["relic_001", "relic_002", "relic_003"])
        self.assertEqual([row["name"] for row in merged], ["甲", "乙", "丙"])
        self.assertEqual(additions, ["relic_003"])

    def test_name_matches_when_source_id_changes(self) -> None:
        old = [card("relic_001", "old-url", "甲", "old effect")]
        fresh = [card(None, "new-url", "甲", "new effect")]
        merged, additions = merge_category("relic", old, deduplicate_cards("relic", fresh, old))
        self.assertEqual((merged[0]["id"], merged[0]["effect"], additions), ("relic_001", "new effect", []))

    def test_same_name_cards_collapse_but_keep_variants(self) -> None:
        old = [card("relic_240", "cat-a", "襁褓中的猫")]
        fresh = [card(None, "cat-c", "襁褓中的猫"), card(None, "cat-a", "襁褓中的猫")]
        deduped = deduplicate_cards("relic", fresh, old)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["sourceId"], "cat-a")
        self.assertEqual(deduped[0]["sourceAliases"], ["cat-c"])
        self.assertEqual(len(deduped[0]["_variants"]), 2)
        merged, additions = merge_category("relic", old, deduped)
        self.assertEqual((merged[0]["id"], additions), ("relic_240", []))

    def test_same_name_different_effect_is_rejected(self) -> None:
        fresh = [card(None, "a", "甲", "effect 1"), card(None, "b", "甲", "effect 2")]
        with self.assertRaisesRegex(ValueError, "different effects"):
            deduplicate_cards("relic", fresh, [])

    def test_missing_old_card_is_rejected(self) -> None:
        old = [card("relic_001", "a", "甲"), card("relic_002", "b", "乙")]
        with self.assertRaisesRegex(ValueError, "missing existing IDs"):
            merge_category("relic", old, [card(None, "a", "甲")])


class LocalCatalogTests(unittest.TestCase):
    def test_handbook_fields_match_category_policy(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        components = handbook.split("## 1. 零件", 1)[1].split("## 2. 实托邦完整效果", 1)[0]
        relics = handbook.split("## 8. 藏品池", 1)[1].split("## 9.额外支援选项：", 1)[0]
        component_ids = re.findall(r"(?m)^\| `(component_\d+)` \|", components)
        self.assertEqual(len(component_ids), 30)
        self.assertEqual(len(component_ids), len(set(component_ids)))
        self.assertIn("| ID | 类别 | 名称 | 稀有度 | 效果 |", components)
        self.assertIn("| `component_019` | 加工品 | 小八界 | NORMAL |", components)
        self.assertIn("极小概率传送到安眠一隅", components)
        self.assertIn("每次移动后估价-2", components)
        self.assertIn("初始估价32，无特殊效果", components)
        self.assertIn("否则须丢弃多余零件后才能继续移动", components)
        self.assertNotIn("## 7. 零件完整效果", handbook)
        self.assertNotIn("- 稀有度：", relics)
        self.assertNotIn("- 类型：", handbook)
        self.assertNotIn("- 注：", relics)
        self.assertEqual(len(re.findall(r"(?m)^### relic_\d+\b", relics)), 243)
        self.assertIn("### relic_243 襁褓羽蛇", relics)
        mistake_notes = handbook.split("## 10. 错题本", 1)[1].split("## 11.", 1)[0]
        self.assertIn("特定战斗关卡、藏品与干员组合", mistake_notes)
        self.assertNotRegex(mistake_notes, r"(?m)^### ")

    def test_handbook_dystopia_and_encounter_rules(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        rulebook = (ROOT / "BLACKFLOW_RULEBOOK.md").read_text(encoding="utf-8")
        dystopias = handbook.split("## 2. 实托邦完整效果", 1)[1].split("## 3. 乌托邦完整效果", 1)[0]
        encounters = handbook.split("## 7. 不期而遇事件表", 1)[1].split("## 8. 藏品池", 1)[0]
        pool = json.loads((ROOT / "data" / "blackflow_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
        self.assertIn("**理念（001-010）**", dystopias)
        self.assertIn("**方针（011-014）**", dystopias)
        self.assertIn("下一层才固定生成", dystopias)
        self.assertIn("其他情况下两者都不进入常规刷新池", dystopias)
        self.assertIn("| 事件名 | 出现层数 | 能否重复出现 | 事件效果 |", encounters)
        event_names = re.findall(r"(?m)^\| ([^|]+) \|", encounters)[2:]
        self.assertEqual(event_names, [event["name"] for event in pool])
        self.assertIn("具体职业组合未知", encounters)
        self.assertNotIn("??", encounters)
        self.assertIn("和平守卫者只有本层存在「居民」据点", rulebook)
        self.assertIn("独活只有本层存在应急助力节点", rulebook)
        self.assertNotIn("## 7. 不期而遇事件池", rulebook)
        self.assertNotIn("### encounter_", rulebook)
        self.assertIn("5 星 3/1", rulebook)
        self.assertNotIn("??", rulebook)
        alone = next(event for event in pool if event["name"] == "独活")
        self.assertEqual(alone["appearanceConditions"][0]["condition"], "当前层存在应急助力节点")
        peace = next(event for event in pool if event["name"] == "和平守卫者")
        self.assertEqual(peace["appearanceConditions"][0]["condition"], "当前层存在居民据点节点")
        self.assertIn("| 林间空地 | 0–3 | 0–7 | 5–11 | 3–13 | 10–17 |", rulebook)
        rules = json.loads((ROOT / "data" / "blackflow_node_generation_rules.json").read_text(encoding="utf-8"))
        clearing = next(row for row in rules["countRanges"] if row["label"] == "林间空地")
        self.assertEqual(clearing["values"]["V"]["maximum"], 17)
        for document in (handbook, rulebook):
            self.assertNotIn("[来源", document)
            self.assertNotIn("用户补充", document)
            self.assertNotIn("<!-- BEGIN GENERATED", document)

    def test_document_audits_are_read_only(self) -> None:
        paths = [ROOT / name for name in ("BLACKFLOW_REFERENCE.md", "BLACKFLOW_RULEBOOK.md", "BLACKFLOW_PLAYTIME_TEMPLATE.md")]
        before = {path: path.read_bytes() for path in paths}
        for script in ("build_reference_markdown.py", "build_rules_markdown.py"):
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script)],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("no Markdown files written", result.stdout)
        for path in paths:
            self.assertEqual(path.read_bytes(), before[path])

    def test_node_mark_roles_distinguish_stacking_override_and_fixed_identity(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        marks = handbook.split("## 6. 节点标记与规则", 1)[1].split("## 7.", 1)[0]
        self.assertIn("藏果地完整叠加所在节点的效果", marks)
        self.assertIn("流窜“居民”部分叠加", marks)
        self.assertIn("不影响羽瞰点首次获得行动力", marks)
        self.assertIn("完成居民战斗不等于完成原事件", marks)
        self.assertIn("光明之末对应无效验尸战斗", marks)
        self.assertIn("神明之殇对应泪之聚落", marks)
        self.assertIn("不与普通失与得的交换收益叠加", marks)
        self.assertNotIn("已确认标记的额外收益另叠", handbook)

    def test_route_scoring_draft_covers_catalogs(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        draft = handbook.split("## 11. 路线评分数值草稿", 1)[1]
        nodes = draft.split("### 11.4", 1)[1].split("### 11.5", 1)[0]
        options = draft.split("### 11.6", 1)[1].split("### 11.7", 1)[0]
        definitions = handbook.split("## 5. 节点类别与效果", 1)[1].split("## 6.", 1)[0]
        pool = json.loads((ROOT / "data" / "blackflow_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
        node_ids = re.findall(r"(?m)^\| `(node_type_\d+)` \|", nodes)
        self.assertEqual(len(node_ids), len(set(node_ids)))
        self.assertEqual(set(node_ids), set(re.findall(r"(?m)^### (node_type_\d+)\b", definitions)))
        self.assertEqual(set(re.findall(r"`(encounter_\d+)`", options)), {event["id"] for event in pool})
        for label in ("单位资源价值", "战斗基础奖励", "事件分布与候选资格", "揭示信息与未知节点", "到达与揭示顺序", "库存与其他状态修正", "终止结算、风险与结果比较"):
            self.assertIn(label, draft)
        self.assertIn("待填", draft)
        self.assertIn("统一标尺与目标偏好", draft)
        self.assertIn("10 级后普通升级价值为 0", draft)
        self.assertIn("按实际关卡所属层/特殊战斗", draft)
        self.assertIn("10 → 13", draft)
        rulebook = (ROOT / "BLACKFLOW_RULEBOOK.md").read_text(encoding="utf-8")
        self.assertIn("## 7. 路线收益与决策评分", rulebook)
        self.assertTrue((ROOT / "data/scoring/blackflow/default.json").is_file())

    def test_encounter_scoring_defaults_and_shadow_rounds_are_saved(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        scoring = handbook.split("### 11.6", 1)[1].split("### 11.7", 1)[0]
        for text in (
            "计分最高的合法选项", "所有伴生作战默认完美完成", "现金门槛只看当前源石锭",
            "本局经历沉寂之屋并成功取得笼控器", "卖出后仍保留",
            "和平守卫者的据点已清理时仍有1藏品", "直接资源收益为 0",
            "紧急合伙人会议经验/钱及隐藏池4藏品", "当前现金≥50，估价不算",
            "实际生命支出为当前生命的一半向下取整", "计分忽略此次失血负效用",
            "当前生命必须严格大于支出", "第8轮获得 `relic_215` 犬植浆",
            "现金机会成本", "当前路线结果不读取这些数值",
        ):
            self.assertIn(text, scoring)
        rounds = scoring.split("#### 被歌颂的影子", 1)[1].split("#### 默认分支", 1)[0]
        rows = re.findall(r"(?m)^\| (\d+) \| (\d+) \| ([^|]+) \| ([^|]+) \|", rounds)
        self.assertEqual([int(row[0]) for row in rows], list(range(1, 9)))
        self.assertEqual([int(row[1]) for row in rows], [1, 1, 2, 2, 2, 3, 3, 3])
        self.assertEqual([row[3].strip() for row in rows], ["1/2", "1/2", "1/2", "1/3", "1/2", "1/3", "1", "1"])
        for _, _, candidates, probability in rows:
            numerator, _, denominator = probability.strip().partition("/")
            self.assertAlmostEqual(len(candidates.split(" / ")) * int(numerator) / int(denominator or 1), 1)
        self.assertNotIn("据点已清理时触发 | 无效果", scoring)
        pool = json.loads((ROOT / "data" / "blackflow_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
        red_moss = next(event for event in pool if event["id"] == "encounter_010")
        self.assertIn("取得过笼控器", red_moss["appearanceConditions"][0]["condition"])
        self.assertIn("卖掉笼控器不影响", red_moss["appearanceConditions"][0]["condition"])

    def test_confirmed_event_repetition_and_reward_corrections_are_preserved(self) -> None:
        pool = json.loads((ROOT / "data" / "blackflow_encounter_pool.json").read_text(encoding="utf-8"))["eventPool"]
        by_name = {event["name"]: event for event in pool}
        self.assertEqual({event["name"] for event in pool if event["repeatability"] == "same_run_possible"},
                         {"色味不同源", "敲动杠杆", "货从口出"})
        self.assertEqual(by_name["洞中宝"]["repeatability"], "inside_and_outside_once")
        self.assertEqual(sum(event["repeatability"] == "once_per_run" for event in pool), 19)
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        event_table = handbook.split("## 7. 不期而遇事件表", 1)[1].split("## 8.", 1)[0]
        scoring = handbook.split("### 11.6", 1)[1].split("### 11.7", 1)[0]
        for section in (event_table, scoring):
            self.assertIn("猎印", section)
            self.assertIn("3源石锭", section)
            self.assertIn("普通作战并终止", section)
        self.assertIn("`relic_209`", scoring)
        self.assertNotIn("待核例外", handbook)
        corrections = {
            "黑诞": ("固定为猎印",),
            "湖中仙女": ("消耗3源石锭",),
            "洞中宝": ("普通作战并终止",),
        }
        for name, terms in corrections.items():
            effects = " ".join(choice["effect"] for choice in by_name[name]["openingChoices"])
            for term in terms:
                self.assertIn(term, effects)

    def test_slot_reward_upper_bounds_and_remaining_reward_gaps_are_documented(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        bounds = handbook.split("#### 编队位与部署位的收益上界", 1)[1].split("#### 统一标尺", 1)[0]
        for text in (
            "| 编队位 | C<13 | 1 |", "| 编队位 | C≥13 | 0 |",
            "| 部署位 | D<13 且 D<C | 1 |", "| 部署位 | D<13 且 D≥C | 0.5 |",
            "| 部署位 | D≥13 | 0 | 仍照常增加，不截断为13 |", "逐位累加",
        ):
            self.assertIn(text, bounds)
        gaps = handbook.split("### 11.12 奖励内容仍待补齐的部分", 1)[1]
        for text in ("先行一步", "险路尽头 / 险路小径", "无效验尸", "洞中宝", "升级"):
            self.assertIn(text, gaps)

    def test_latest_node_rewards_and_dispatch_branches_are_preserved(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        nodes = handbook.split("## 5. 节点类别与效果", 1)[1].split("## 6.", 1)[0]
        for text in (
            "连续两次各1换1，总计失去2件、获得2件", "不能先交换零件再交换藏品",
            "本局尚未完成失与得上贡", "进入新一层时归队但不进阶", "进入新一层时以进阶状态归队",
            "获得1件加工品、2希望及怦然信标", "即时获得2希望", "剩余行动力按1:1转为希望",
            "默认策略只招募免费干员", "1件藏品、2件零件", "1件藏品、1件零件", "3/5层不论是否追猎",
        ):
            self.assertIn(text, nodes)
        self.assertIn("| 无效验尸 | 特殊挑战 | 36 → 47 | 暂按III领袖5 |", handbook)

    def test_opening_technology_and_mechanist_rules(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        opening_rules = handbook.split("### 账号解锁与开局修正", 1)[1].split("### 11.2", 1)[0]
        for text in (
            "初始未招募机械师时", "只能出战一场，随后离队", "希望费用少 4", "进阶费用少 2",
            "初始招募为 2 希望", "非初始招募为 3 希望", "进阶为 1 希望",
            "普通招募或临时招募机械师时，零件箱容量 +2", "进阶时获得 1 件【结构性原理】",
            "这两项与临时助力无关", "不因初始精一状态先发进阶奖励",
        ):
            self.assertIn(text, opening_rules)
        scoring = handbook.split("### 11.2", 1)[1].split("### 11.3", 1)[0]
        for text in (
            "第一顺位：结局前置", "第二顺位：队伍门槛", "第三顺位：经济与发育",
            "达标后补齐偏好为 0", "不是“够打某关”的判定", "一场后离队的临时助力",
            "事件与商店共用资源标尺", "不是固定事件分", "不能再加一份事件总分",
        ):
            self.assertIn(text, scoring)
        event_scoring = handbook.split("### 11.6", 1)[1].split("### 11.7", 1)[0]
        self.assertIn("额外加分（默认 0）", event_scoring)
        self.assertIn("可填正分或负分", event_scoring)
        self.assertIn("当前路线结果不读取这些数值", event_scoring)

    def test_catalog_images_and_ids(self) -> None:
        data = json.loads((ROOT / "data" / "lubiao_reference_catalog.json").read_text(encoding="utf-8"))
        self.assertEqual(data["schemaVersion"], 2)
        rows = data["entries"]
        self.assertEqual(len(rows), 339)
        self.assertEqual(len({row["id"] for row in rows}), len(rows))
        image_paths = []
        for category in CATEGORY_ORDER:
            selected = [row for row in rows if row["category"] == category]
            self.assertEqual([id_number(category, row["id"]) for row in selected], list(range(1, len(selected) + 1)))
            self.assertEqual(len({row["name"] for row in selected}), len(selected))
        for row in rows:
            image_paths.extend([row["imagePath"]] if row.get("imagePath") else [])
            image_paths.extend(variant["imagePath"] for variant in row.get("imageVariants", []))
        self.assertEqual(len(image_paths), 347)
        self.assertEqual(len(set(image_paths)), len(image_paths))
        for image_path in image_paths:
            self.assertTrue((ROOT / image_path).is_file(), image_path)

    def test_route_corrections_are_consistent_in_documents(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        mistake_notes = handbook.split("## 10. 错题本", 1)[1].split("## 11.", 1)[0]
        for term in ("沉重的契约", "5 行动力", "全知者盲区", "未亡者遗怨", "惩罚性减分"):
            self.assertIn(term, mistake_notes)
        self.assertIn("事件估值默认按这个选项处理", mistake_notes)
        self.assertIn("尽量避免触发该事件", mistake_notes)
        for name in ("BLACKFLOW_RULEBOOK.md", "BLACKFLOW_REFERENCE.md", "docs/ROADMAP.md"):
            document = (ROOT / name).read_text(encoding="utf-8")
            self.assertIn("不能重复进入", document)
            self.assertNotIn("两类行商与应急助力可", document)
            self.assertNotIn("应急助力已补入可重复", document)
        self.assertTrue((ROOT / "packaging/README.md").is_file())
        dependencies = (ROOT / "requirements-vision.txt").read_text(encoding="utf-8")
        self.assertIn("opencv-python-headless", dependencies)
        self.assertNotRegex(dependencies, r"(?m)^opencv-python[<>=]")

    def test_playtime_template_has_requested_sections(self) -> None:
        template = (ROOT / "BLACKFLOW_PLAYTIME_TEMPLATE.md").read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(r"(?m)^## \d+\. (.+)$", template),
            [
                "基础信息",
                "全局策略、结局目标与进度",
                "地图、节点与本层策略",
                "干员池（当前 0 人）",
                "藏品（当前 0 件）",
                "零件箱（当前 2 件，上限 8 件）",
                "实时资源",
                "随手记录",
            ],
        )
        for row in (
            "| 难度 | 15 |",
            "| 指挥等级 |  1| - |",
            "| 经验 | 0 |",
            "| 希望 | 6 |",
            "| 源石锭 | 20 |",
            "| 目标生命 | 4 |",
            "| 护盾 |  2| - |",
            "| 干员携带位 |  7| 上限13  |",
            "| 招募券留存 | 0 | 上限 3 |",
        ):
            self.assertIn(row, template)
        self.assertIn("| 当前追猎次数 | 0 |", template)
        self.assertIn("| 局外科技预设 | 全部解锁；可在初始化时调整 |", template)
        for row in (
            "| 局外科技攻击力加成 | +20% |",
            "| 局外科技防御力加成 | +20% |",
            "| 局外科技生命值加成 | +25% |",
        ):
            self.assertIn(row, template)
        self.assertIn("机械师精通预设", template)
        self.assertLess(template.index("| 源石锭 | 20 |"), template.index("| 总估价 |  4| - |"))
        self.assertEqual(template.count("| `component_001` | 种子 | 自然物 | 2 | - | 否 |"), 2)
        self.assertIn("| 招募券类别 | 数量 |", template)
        self.assertIn("| 藏品 ID | 名称 | 状态值（数量 / 层数 / 生效） |", template)
        for heading in (
            "3.1 I 层", "3.2 II 层", "3.3 III 层", "3.4 III 层树洞",
            "3.5 IV 层", "3.6 IV 层（追忆）", "3.7 IV 层树洞",
            "3.8 V 层", "3.9 V 层树洞", "3.10 VI 层", "3.11 全局不期而遇池",
        ):
            self.assertIn(f"### {heading}", template)
        self.assertIn("| 当前地图图片（含节点预测 mask） | 待生成 |", template)
        self.assertIn("| 地图实例 ID / 模板 / 节点连线 | 待导入 |", template)
        self.assertIn("| 节点快照（探明、原始/当前类别、完成、标记、事件） | 待导入 |", template)
        self.assertIn("| 本层节点池（总数范围、已知、已完成、剩余） | 待计算 |", template)
        self.assertIn("| 事件 ID / 名称 | 可能出现层 | 能否重复 | 本局完成次数 | 已确认节点与结果 |", template)
        self.assertIn("第三章已由经校验的结构化地图快照生成", template)
        self.assertIn("不直接编辑本页", template)
        self.assertNotIn("获得节点与时间", template)
        self.assertNotIn("确认状态", template)
        self.assertNotIn("来源/确认", template)
        self.assertNotIn("| 怦然信标 |", template)
        self.assertNotIn("| 六层进入资格 |", template)
        for prerequisite in ("失与得上贡", "不期而遇上贡", "无效验尸战斗"):
            self.assertEqual(template.count(f"| {prerequisite} | 未知 |"), 1)
        with tempfile.TemporaryDirectory() as directory:
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "new_run.py"), "--run-id", "sample", "--output-dir", directory],
                check=True,
                capture_output=True,
                text=True,
            )
            generated = (Path(directory) / "sample.md").read_text(encoding="utf-8")
            self.assertNotIn("{{", generated)
            self.assertIn("# 黑流树海（Black Flow）：本局记录（Playtime）", generated)
            self.assertIn("## 3. 地图、节点与本层策略", generated)
            self.assertIn("## 4. 干员池（当前 1 人）", generated)
            self.assertIn("## 5. 藏品（当前 0 件）", generated)
            self.assertIn("| 局外科技预设 |", generated)
            self.assertIn("| 机械师精通预设 |", generated)
            state = json.loads((Path(directory) / "sample.json").read_text(encoding="utf-8"))
            self.assertEqual(len(state["areas"]), 10)
            self.assertIn("IV-remembrance", state["areas"])

    def test_roadmap_records_current_state_and_llm_boundary(self) -> None:
        design = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
        for module in ("Playtime", "节点预测", "路线规划", "藏品", "资源"):
            self.assertIn(module, design)
        self.assertIn("runs/<run_id>/playtime.json", design)
        self.assertIn("不要求玩家逐项标注来源或可靠性", design)
        self.assertIn("模板不需要为 LLM 保留专用命名空间", design)
        self.assertIn("不解析手改 Markdown 作为存档恢复依据", design)
        self.assertIn("客观功能输出", design)
        self.assertIn("大模型交互输出", design)

    def test_component_scoring_covers_all_thirty_catalog_items(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        section = handbook.split("### 11.15", 1)[1].split("### 11.16", 1)[0]
        ids = re.findall(r"(?m)^\| `(component_\d+)` \|", section)
        self.assertEqual(len(ids), 30)
        self.assertEqual(set(ids), {f"component_{index:03}" for index in range(1, 31)})
        self.assertNotIn("| 待填 |", section)
        for text in ("| 100 | 3 | 0 | 300 |", "| 10 | 1 | 4 | 10 |", "125（霜晶树的一半）",
                     "250（同光彩松露）", "当前未知诡秘访问分+预计新揭示分的平均",
                     "B×(1+0.05k)", "已有2个玉米再获得1个为550分", "襁褓三头犬"):
            self.assertIn(text, section)

    def test_level_table_has_nine_steps_and_preserves_experience_remainder(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        section = handbook.split("### 11.16", 1)[1].split("### 11.17", 1)[0]
        rows = re.findall(r"(?m)^\| (\d+)→(\d+) \| (\d+) \| (\d+) \| (\d+) \|", section)
        values = [tuple(map(int, row)) for row in rows]
        self.assertEqual([(row[0], row[1]) for row in values], [(level, level + 1) for level in range(1, 10)])
        self.assertEqual([row[2] for row in values], [10, 24, 36, 40, 55, 65, 75, 90, 95])
        self.assertEqual([row[3] for row in values], [4, 4, 5, 5, 6, 6, 6, 6, 8])
        self.assertEqual(sum(row[2] for row in values), 490)
        self.assertEqual(sum(row[3] for row in values), 50)
        self.assertEqual([row[1] for row in values if row[4]], [4, 6, 9])
        self.assertIn("当前经验3，实际希望+4", section)
        self.assertIn("4+4×3/24=4.5", section)

    def test_ticket_table_has_eighteen_entries_and_state_dependent_mechanist_weights(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        section = handbook.split("### 11.17", 1)[1].split("### 11.18", 1)[0]
        rows = re.findall(r"(?m)^\| ([^|]+) \| ([\d.]+) \| ([\d.]+) \|$", section)
        self.assertEqual(len(rows), 18)
        for name, weight, points in rows:
            with self.subTest(name=name):
                self.assertEqual(Decimal(weight) * 50, Decimal(points))
        elite_rows = re.findall(r"(?m)^\| (精英[^|]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|$", section)
        self.assertEqual(len(elite_rows), 4)
        for _, base, multiplier, points in elite_rows:
            self.assertEqual(Decimal(base) * Decimal(multiplier), Decimal(points))
        for text in ("不含地面、高台和本源队", "未招募时前2张重装券×3", "已招募未进阶时前1张×3",
                     "已进阶时全部回归正常", "门槛未达为1.25", "精英突击/堡垒/远程/破坏"):
            self.assertIn(text, section)

    def test_seed_fixed_reference_uses_exact_frequencies_and_half_up_rounding(self) -> None:
        from fulcrum.node_rewards import NodeRewardPoolCatalog

        rows = NodeRewardPoolCatalog().get("node_scrap_shop_seed_cultivation")["members"]
        counts = {row["itemId"]: row["occurrenceCount"] for row in rows}
        fixed = {
            "component_003": 150, "component_004": 500, "component_005": 150,
            "component_006": 250, "component_009": 2000, "component_010": 200,
            "component_019": 220, "component_020": 300, "component_021": 50,
            "component_022": 80, "component_023": 300, "component_024": 810,
            "relic_240": 100, "relic_241": 100, "relic_242": 200, "relic_243": 100,
        }
        self.assertEqual(len(counts), 16)
        self.assertEqual(set(counts), set(fixed))
        self.assertEqual(sum(counts.values()), 1292)
        numerator = sum(counts[key] * points for key, points in fixed.items())
        self.assertEqual(numerator, 370110)
        self.assertEqual(counts["component_019"] + counts["component_020"], 105)
        self.assertEqual(counts["component_024"], 6)
        result = Decimal(numerator) / sum(counts.values())
        self.assertEqual(result.quantize(Decimal("1"), rounding=ROUND_HALF_UP), 286)
        section = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8").split("### 11.15", 1)[1].split("### 11.16", 1)[0]
        self.assertIn("每单位行动力200分，小八界自身移动能力20分", section)
        self.assertIn("固定默认250分", section)
        self.assertIn("四舍五入为286分", section)
        self.assertIn("多生苔藓200分已含获得时的3个枯苔藓球", section)
        self.assertIn("融雪的2希望、触须每次4现金已包含", section)
        self.assertNotIn("343910 + 20M_小八界", section)

    def test_action_option_and_exit_formulas_remain_distinct_from_actual_budget(self) -> None:
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        section = handbook.split("### 11.18", 1)[1].split("## 12.", 1)[0]
        for text in ("已经持有的行动力只是当前预算输入", "不维护行动力价值账本",
                     "不取m倍同一个首项分", "不另外模拟特殊移动以修正n",
                     "同一个位置只计一次", "G=max(0,1-0.2d)", "相等按差额0也取1",
                     "出口加工品期望分+200r×G", "抵达、结算移动后实际携带"):
            self.assertIn(text, section)
        for core_count, actions, expected_factor in ((5, 8, 1), (5, 5, 1), (5, 3, 0.6), (5, 0, 0), (0, 0, 1)):
            factor = max(0, 1 - 0.2 * max(0, core_count - actions))
            self.assertAlmostEqual(factor, expected_factor)
        self.assertAlmostEqual(200 * 2 * max(0, 1 - 0.2 * (5 - 3)), 240)
        values = [400, 200, 100, 60, 20]
        self.assertEqual(sum(values[2:4]), 160)

    def test_roadmap_phases_and_numeric_scope(self) -> None:
        roadmap = (ROOT / "docs/ROADMAP.md").read_text(encoding="utf-8")
        phases = (
            "## 第一阶段：结构化状态与客观功能",
            "## 第二阶段：应用化与前端测试",
            "## 第三阶段：智能化交互",
        )
        self.assertEqual([roadmap.index(phase) for phase in phases], sorted(roadmap.index(phase) for phase in phases))
        self.assertIn("将现有藏品表的效果格式化为可计算条目", roadmap)
        self.assertIn("合并所有适用加成", roadmap)
        self.assertIn("截图到地图/资源候选、确认入局和离线节点预测", roadmap)
        self.assertFalse((ROOT / "STAGE1_MAP_AND_RESOURCES.md").exists())
        self.assertIn("不计算具体干员的生存、输出", roadmap)
        self.assertIn("节点预测", roadmap)
        self.assertIn("路线规划", roadmap)
        self.assertFalse((ROOT / "NEXT_STEPS.md").exists())


if __name__ == "__main__":
    unittest.main()
