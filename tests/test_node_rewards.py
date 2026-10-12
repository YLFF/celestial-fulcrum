"""Offline reward frequencies, item bindings, and manual-document protection."""

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

from fulcrum.node_rewards import NodeRewardPoolCatalog, compact_pools, expanded_pools, normalize_pools, validate_rendered_pools
from scripts.extract_lubiao_node_rewards import PROTECTED, markdown_draft, normalize_battle_observations, write_json


ROOT = Path(__file__).resolve().parents[1]


def fixture(distribution=None):
    catalog = {"schemaVersion": 2, "entries": [
        {"id": "relic_001", "name": "结构藏品", "category": "relic"},
        {"id": "component_001", "name": "测试零件", "category": "component"},
    ]}
    archive = {"schemaVersion": 2, "classifier": {"items": [
        {"itemId": "a", "name": "结构藏品-α", "dataType": "藏品"},
        {"itemId": "b", "name": "结构藏品-β", "dataType": "藏品"},
        {"itemId": "c", "name": "测试零件", "dataType": "零件"},
    ]}, "pools": {"pools": [{
        "id": "source:pool", "officialCode": "test_pool", "name": "测试池", "displayCategory": "node",
        "collectibles": ["a", "b", "c"], "observedDistribution": distribution,
    }]}}
    return archive, catalog


def observation(item_id, count, total=10):
    return {"itemId": item_id, "occurrenceCount": count, "totalOccurrenceCount": total}


class RewardNormalizationTests(unittest.TestCase):
    def test_stable_local_ids_and_variant_counts_merge(self):
        archive, catalog = fixture({"interpretation": "observedFrequencyOnly", "members": [
            observation("a", 2), observation("b", 3), observation("c", 5),
        ]})
        before = deepcopy(archive)
        pool = normalize_pools(archive, catalog)[0]
        self.assertEqual(pool["id"], "test_pool")
        self.assertEqual(len(pool["members"]), 2)
        relic = pool["members"][0]
        self.assertEqual((relic["itemId"], relic["name"], relic["sourceItemIds"]),
                         ("relic_001", "结构藏品", ["a", "b"]))
        self.assertEqual((relic["occurrenceCount"], relic["probability"]), (5, 0.5))
        self.assertEqual(archive, before)

    def test_membership_only_does_not_invent_probabilities(self):
        archive, catalog = fixture()
        pool = normalize_pools(archive, catalog)[0]
        self.assertTrue(all(row["probability"] is None for row in pool["members"]))
        self.assertTrue(all(row["occurrenceCount"] is None for row in pool["members"]))

    def test_explicit_zero_and_unobserved_are_different(self):
        archive, catalog = fixture({"interpretation": "observedFrequencyOnly", "members": [
            observation("a", 0), observation("c", 10),
        ]})
        archive["pools"]["pools"][0]["collectibles"] = ["a", "c", "unknown"]
        rows = normalize_pools(archive, catalog)[0]["members"]
        self.assertEqual((rows[0]["occurrenceCount"], rows[0]["probability"]), (0, 0))
        self.assertIsNone(rows[2]["probability"])
        self.assertEqual(rows[2]["metadataStatus"], "missing")

    def test_occurrence_rate_is_not_normalized_to_one(self):
        archive, catalog = fixture({"interpretation": "observedOccurrenceRate", "members": [observation("c", 2)]})
        self.assertEqual(normalize_pools(archive, catalog)[0]["members"][-1]["probability"], 0.2)

    def test_subpool_membership_and_scopes_remain_separate(self):
        archive, catalog = fixture({"interpretation": "hierarchicalObservedFrequency", "subpools": [
            {"id": "members", "name": "候选集合", "interpretation": "membershipOnly", "itemIds": ["c"]},
            {"id": "floor1", "name": "I", "interpretation": "observedFrequencyOnly", "members": [observation("c", 9)]},
            {"id": "floor2", "name": "II", "interpretation": "observedFrequencyOnly", "members": [observation("a", 8), observation("c", 2)]},
        ]})
        groups = normalize_pools(archive, catalog)[0]["subpools"]
        self.assertEqual(groups[0]["members"][0]["itemId"], "component_001")
        self.assertIsNone(groups[0]["members"][0]["probability"])
        self.assertEqual(groups[1]["members"][0]["probability"], 1)
        self.assertEqual(groups[2]["members"][-1]["probability"], 0.2)

    def test_duplicates_and_invalid_counts_fail_closed(self):
        for members in ([observation("c", 1), observation("c", 1)], [observation("c", -1)],
                        [observation("c", 1, 0)], [observation("c", 11, 10)]):
            archive, catalog = fixture({"interpretation": "observedFrequencyOnly", "members": members})
            with self.assertRaises(ValueError):
                normalize_pools(archive, catalog)

    def test_visible_subset_probability_does_not_replace_full_scope(self):
        archive, catalog = fixture({"interpretation": "observedFrequencyOnly", "members": [
            observation("a", 3), observation("c", 7),
        ]})
        pools = normalize_pools(archive, catalog)
        pages = [{"panels": [{"pools": [{"sourcePoolId": "source:pool", "groups": [{"name": None,
            "members": [{"name": "结构藏品", "probabilityText": "100.00%"}],
        }]}]}]}]
        checked, differences = validate_rendered_pools(pools, pages)
        self.assertEqual(checked, 1)
        self.assertEqual(differences[0]["fullSubpoolFrequency"], 0.3)
        self.assertEqual(pools[0]["members"][0]["probability"], 0.3)
        pages[0]["panels"][0]["pools"][0]["groups"][0]["members"][0]["probabilityText"] = "99.00%"
        with self.assertRaises(ValueError):
            validate_rendered_pools(pools, pages)


class LocalRewardPoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = NodeRewardPoolCatalog()
        cls.local = json.loads((ROOT / "data/lubiao_reference_catalog.json").read_text(encoding="utf-8"))

    def test_unique_pools_and_existing_item_bindings(self):
        pools = expanded_pools(self.catalog.data)
        self.assertGreaterEqual(len(pools), 65)
        self.assertEqual(len(pools), len({row["id"] for row in pools}))
        self.assertEqual(len(self.catalog.data["nodes"]), 21)
        local = {row["id"]: row for row in self.local["entries"]}
        for pool in pools:
            for group in [pool] + pool["subpools"]:
                for item in group["members"]:
                    if item["dataType"] in {"藏品", "零件"}:
                        self.assertEqual(local[item["itemId"]]["name"], item["name"])

    def test_all_displayed_members_are_checked_again(self):
        checked, differences = validate_rendered_pools(expanded_pools(self.catalog.data), self.catalog.data["nodes"])
        self.assertEqual(checked, self.catalog.data["renderedMembersChecked"])
        self.assertGreater(checked, 1000)
        self.assertEqual(differences, self.catalog.data["renderedProbabilityDifferences"])
        self.assertEqual({row["poolId"] for row in differences}, {"node_battle_shop_merchant"})

    def test_exit_pools_and_unrounded_probabilities(self):
        expected = {
            "node_final_scrap": {"报废轮子", "报废假肢", "标准引擎", "气垫底座", "试作外骨骼"},
            "node_evacuate_scrap": {"一次性喷气背包", "老妈妈的融雪", "坎诺特的触须", "结构性原理", "“简易遥控器”"},
        }
        for pool_id, names in expected.items():
            rows = self.catalog.get(pool_id)["members"]
            self.assertEqual({row["name"] for row in rows}, names)
            self.assertAlmostEqual(sum(row["probability"] for row in rows), 1)
            for row in rows:
                self.assertEqual(row["probability"], row["occurrenceCount"] / row["totalOccurrenceCount"])

    def test_encounter_exchange_options_and_query_are_independent(self):
        self.assertEqual(len(self.catalog.for_node("node_type_006")), 12)
        self.assertEqual(len(self.catalog.for_node("node_type_008")), 12)
        self.assertEqual(self.catalog.for_node("node_type_009")[0]["id"], "pool_scrap_3")
        queried = self.catalog.get("node_final_scrap")
        queried["members"].clear()
        self.assertEqual(len(self.catalog.get("node_final_scrap")["members"]), 5)

    def test_shop_filters_and_per_table_denominators(self):
        nodes = {row["nodeCategoryId"]: row for row in self.catalog.data["nodes"]}
        self.assertGreaterEqual(len(nodes["node_type_004"]["statisticsPanels"]), 32)
        panels = nodes["node_type_013"]["statisticsPanels"]
        self.assertGreaterEqual(len(panels), 8)
        tables = {row["title"]: row for row in panels[0]["tables"]}
        def sample(title):
            return int(re.search(r"样本数：([\d,]+)", tables[title]["metadata"]).group(1).replace(",", ""))
        self.assertEqual(sample("加工品型 · 零件类别占比"), 6 * sample("货架配额频次"))
        self.assertGreater(sample("零件频次"), 0)
        self.assertLess(sample("零件频次"), sample("加工品型 · 零件类别占比"))
        self.assertGreater(sample("各层店型频次"), 0)

    def test_handbook_draft_keeps_data_not_editorial_metadata(self):
        draft = markdown_draft(self.catalog.data)
        for text in ("用户已批准", "人工核对", "rogue_6_recruit_ticket_caster_candle"):
            self.assertNotIn(text, draft)
        self.assertIn("统计范围：N6三层", draft)
        self.assertIn("未列独立物品池；见节点效果", draft)
        self.assertIn("不是这两项占完整IV层藏品池的比例", draft)
        self.assertIn("| `component_013` | 报废轮子 |", draft)
        handbook = (ROOT / "BLACKFLOW_REFERENCE.md").read_text(encoding="utf-8")
        reward_section = handbook.split("## 12. 节点奖励候选池与统计分布", 1)[1]
        ids = re.findall(r"(?m)^#### ([a-z_0-9]+) ", reward_section)
        self.assertEqual(len(ids), len(set(ids)))
        expected = {pool["rewardPoolId"] for pool in self.catalog.data["observationContexts"]
                    if pool["displayCategory"] == "node" or any(pool["id"] in node["observationContextIds"] for node in self.catalog.data["nodes"])}
        self.assertEqual(set(ids), expected)

    def test_shared_definitions_and_node_selection_count(self):
        self.assertTrue(all("members" not in context for context in self.catalog.data["observationContexts"]))
        definitions = self.catalog.data["rewardPools"]
        self.assertEqual(len(definitions), len({row["id"] for row in definitions}))
        boss = self.catalog.get("node_battle_boss_scrap")
        final = self.catalog.get("node_final_scrap")
        self.assertEqual(boss["rewardPoolId"], final["rewardPoolId"])
        self.assertEqual(boss["selection"]["candidateCount"], 2)
        self.assertEqual(final["selection"]["takeCount"], 1)
        self.assertEqual(final["selection"]["when"], "leaveLayer")
        self.assertNotEqual(boss["statistics"]["sampleCount"], final["statistics"]["sampleCount"])
        left = self.catalog.get("node_battle_savage_scrap_left")
        right = self.catalog.get("node_battle_savage_scrap_right")
        self.assertNotEqual(left["rewardPoolId"], right["rewardPoolId"])
        shared = self.catalog.get_pool(left["rewardPoolId"])
        expected_items = {row["itemId"] for row in left["members"]}
        self.assertEqual({row["itemId"] for row in shared["members"]}, expected_items)
        selections = self.catalog.selections_for_node("node_type_019")
        self.assertEqual(len(selections), 2)
        self.assertEqual({row["rewardPoolId"] for row in selections}, {left["rewardPoolId"], right["rewardPoolId"]})
        self.assertTrue(all((row["groupCount"], row["candidateCount"], row["takeCountPerGroup"]) == (1, 2, 1)
                            for row in selections))
        self.assertEqual(len(self.catalog.shared_for_node("node_type_019")), 4)
        self.assertEqual(len(self.catalog.shared_for_node("node_type_006")), 9)

    def test_manual_documents_cannot_be_update_targets(self):
        for path in PROTECTED:
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                write_json(path, {})
            self.assertEqual(path.read_bytes(), before)
        result = subprocess.run([sys.executable, str(ROOT / "scripts/extract_lubiao_node_rewards.py"),
                                 "--markdown-draft", str(ROOT / "BLACKFLOW_REFERENCE.md")],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Manually maintained Markdown cannot be overwritten", result.stderr)


class SharedPoolTests(unittest.TestCase):
    def test_identical_members_share_definition_not_statistics(self):
        archive, catalog = fixture({"interpretation": "observedFrequencyOnly", "members": [
            observation("a", 2), observation("b", 3), observation("c", 5),
        ]})
        first = normalize_pools(archive, catalog)[0]
        first["id"] = "node_final_scrap"
        second = deepcopy(first)
        second["id"] = "node_battle_boss_scrap"
        second["members"][0]["probability"] = 0.7
        definitions, contexts = compact_pools([first, second])
        self.assertEqual(len(definitions), 1)
        self.assertEqual(definitions[0]["id"], "node_final_scrap")
        expanded = expanded_pools({"schemaVersion": 2, "rewardPools": definitions, "observationContexts": contexts})
        self.assertEqual(expanded[0]["members"], first["members"])
        self.assertEqual(expanded[1]["members"], second["members"])
        reversed_definitions, _ = compact_pools([second, first])
        self.assertEqual(reversed_definitions, definitions)

    def test_settlement_keeps_two_distinct_pools(self):
        archive, catalog = fixture()
        source = normalize_pools(archive, catalog)[0]
        left, right = deepcopy(source), deepcopy(source)
        left["id"] = "node_battle_savage_scrap_left"
        right["id"] = "node_battle_savage_scrap_right"
        left["members"] = source["members"][:1]
        right["members"] = source["members"][1:]
        definitions, contexts = compact_pools([left, right])
        self.assertEqual(len(definitions), 2)
        self.assertNotEqual(contexts[0]["rewardPoolId"], contexts[1]["rewardPoolId"])
        expanded = expanded_pools({"schemaVersion": 2, "rewardPools": definitions, "observationContexts": contexts})
        self.assertEqual(expanded[0]["members"], left["members"])
        self.assertEqual(expanded[1]["members"], right["members"])

    def test_rendered_occurrence_rates_keep_exact_denominators(self):
        rows = [{"rewardGroups": [{"description": "11场中5场直接掉落", "probability": 0.4545}]}]
        parsed = normalize_battle_observations(rows)
        self.assertEqual(parsed[0]["rewardGroups"][0]["probability"], 5 / 11)
        self.assertEqual(rows[0]["rewardGroups"][0]["probability"], 0.4545)
        with self.assertRaises(ValueError):
            normalize_battle_observations([{"rewardGroups": [{"description": "12/11 场"}]}])

    def test_different_members_and_unobserved_rows_are_not_forced_equal(self):
        archive, catalog = fixture()
        first = normalize_pools(archive, catalog)[0]
        second = deepcopy(first)
        second["id"] = "other_pool"
        second["members"] = second["members"][1:]
        definitions, contexts = compact_pools([first, second])
        self.assertEqual(len(definitions), 2)
        self.assertNotEqual(contexts[0]["rewardPoolId"], contexts[1]["rewardPoolId"])
        expanded = expanded_pools({"schemaVersion": 2, "rewardPools": definitions, "observationContexts": contexts})
        self.assertTrue(all(row["probability"] is None for row in expanded[0]["members"]))

    def test_legacy_reading_does_not_modify_legacy_file(self):
        archive, catalog = fixture()
        pool = normalize_pools(archive, catalog)[0]
        legacy = {"schemaVersion": 1, "pools": [pool], "nodes": [
            {"nodeCategoryId": "node_type_test", "poolIds": [pool["id"]]},
        ]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            loaded = NodeRewardPoolCatalog(path)
            self.assertEqual(loaded.get(pool["id"])["members"], pool["members"])
            self.assertEqual(len(loaded.shared_for_node("node_type_test")), 1)
            self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
