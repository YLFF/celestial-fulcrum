"""Review extraction is read-only and does not assert combat stacking rules."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.screen_relic_effects import build_review, parse_relics, render_review, screen_effect


ROOT = Path(__file__).resolve().parents[1]


class RelicEffectsReviewTests(unittest.TestCase):
    def test_all_current_relics_have_one_review_entry_and_original_text(self):
        text = (ROOT / "BLACKSTREAM_REFERENCE.md").read_text(encoding="utf-8")
        parsed = parse_relics(text)
        review = build_review(text)
        self.assertEqual(len(review["entries"]), 243)
        self.assertEqual(sum(review["counts"].values()), 243)
        self.assertEqual([row["id"] for row in parsed], [row["id"] for row in review["entries"]])
        lines = text.splitlines()
        for source, row in zip(parsed, review["entries"]):
            self.assertEqual(row["effect"], source["effect"])
            self.assertIn(f"### {row['id']} {row['name']}", lines[row["sourceLine"] - 1])
            self.assertFalse(row["confirmed"])
        self.assertEqual(build_review(text), review)
        rendered = render_review(review)
        for row in parsed:
            self.assertEqual(rendered.count(f"### {row['id']} "), 1)

    def test_exploration_hp_shield_and_slots_are_not_combat_stats(self):
        for effect in ("目标生命上限+2，希望+2", "护盾值+4", "希望+2，可同时部署人数+1"):
            self.assertEqual(screen_effect(effect)["group"], "noncombat")
        self.assertEqual(screen_effect("所有我方单位在部署时获得2层护盾")["group"], "combat_special")

    def test_mixed_effects_preserve_both_domains(self):
        self.assertEqual(screen_effect("我方单位的攻击力+40%，指挥经验+20%")["group"], "mixed")
        self.assertEqual(screen_effect("立即进阶一个近卫干员，使其首次被击倒时回复100%生命")["group"], "mixed")
        self.assertEqual(screen_effect("精英敌人的生命+10%，战斗获得的钱和指挥经验+40%")["group"], "mixed")

    def test_conditions_and_binding_do_not_imply_resource_rewards(self):
        for effect in ("每有5源石锭，所有我方单位的攻击速度+7",
                       "零件箱中每有1个零件，所有干员的生命和攻击力+8%",
                       "下一个招募或进阶的干员攻击速度+50",
                       "获得此收藏品时，使随机2名干员的技力回复速度+0.8/秒"):
            self.assertEqual(screen_effect(effect)["group"], "combat")
        self.assertEqual(screen_effect("立即进阶一个狙击干员，攻击时无视目标50%的防御")["group"], "mixed")

    def test_delayed_conversion_is_separate_from_direct_effect(self):
        self.assertEqual(screen_effect("完成1场追猎作战后，获得【犬植浆】")["group"], "noncombat")
        self.assertEqual(screen_effect("战斗后掉落战利品时，增加一个可选项")["group"], "noncombat")
        self.assertEqual(screen_effect("每探索一种新节点叠加1层，每层使作战后获得收藏品的概率提升")["group"], "noncombat")
        self.assertEqual(screen_effect("可以在特殊节点中，使灾厄之口不摧毁危朽")["group"], "mixed")

    def test_damage_skill_cost_and_tactical_effects_are_not_discarded(self):
        for effect in ("所有敌人受到的元素损伤+75%", "初始技力+12", "所有干员部署费用-1",
                       "每次战斗中携带2个雪雉的安全起重机", "可以在高台部署近战位干员"):
            self.assertIn(screen_effect(effect)["group"], ("combat", "combat_special"))

    def test_incomplete_or_unrecognized_text_is_pending(self):
        self.assertEqual(screen_effect("下次探索增加支援（描述缺失")["group"], "review")
        self.assertEqual(screen_effect("尚未描述的机制")["group"], "review")

    def test_missing_or_duplicate_entries_fail_instead_of_silently_dropping(self):
        with self.assertRaises(ValueError):
            parse_relics("## 8. 藏品池\n### relic_001 名称\n")
        with self.assertRaises(ValueError):
            parse_relics("## 8. 藏品池\n### relic_001 名称\n- 效果：希望+2\n### relic_001 名称\n- 效果：希望+2\n")

    def test_export_never_changes_source_or_overwrites_existing_review(self):
        source = ROOT / "BLACKSTREAM_REFERENCE.md"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "review.json"
            md_path = Path(directory) / "review.md"
            command = [sys.executable, str(ROOT / "scripts/screen_relic_effects.py"),
                       "--json", str(json_path), "--markdown", str(md_path)]
            subprocess.run(command, check=True, capture_output=True)
            original = md_path.read_bytes()
            retry = subprocess.run(command, capture_output=True)
            self.assertNotEqual(retry.returncode, 0)
            self.assertEqual(md_path.read_bytes(), original)
            unsafe = subprocess.run([sys.executable, str(ROOT / "scripts/screen_relic_effects.py"),
                                     "--json", str(source), "--markdown", str(Path(directory) / "other.md")],
                                    capture_output=True)
            self.assertNotEqual(unsafe.returncode, 0)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
