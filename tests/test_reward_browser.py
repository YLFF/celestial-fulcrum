from copy import deepcopy
import json
import unittest

from fulcrum.node_rewards import DATA_PATH, NodeRewardPoolCatalog
from fulcrum.reward_browser import browser_catalog
from fulcrum.service.catalog import entries


class RewardBrowserTests(unittest.TestCase):
    def test_every_display_member_is_canonical_and_kind_matches(self):
        browser = browser_catalog()
        known = entries()
        for pool in browser["pools"].values():
            self.assertTrue(pool["itemIds"])
            self.assertNotIn("probability", pool)
            for item_id in pool["itemIds"]:
                self.assertEqual(known[item_id]["category"], pool["kind"])
        self.assertEqual(browser["nodes"]["node_type_006"], [])

    def test_different_options_and_resident_pools_stay_separate(self):
        browser = browser_catalog()
        keys = browser["nodes"]["node_type_007"]
        self.assertIn("node_wish_relic:relic", keys)
        self.assertIn("node_wish_relic_advanced:relic", keys)
        keys = browser["nodes"]["node_type_019"]
        left = browser["pools"]["node_battle_savage_scrap_left:component"]
        right = browser["pools"]["node_battle_savage_scrap_right:component"]
        self.assertIn(left["id"], keys)
        self.assertIn(right["id"], keys)
        self.assertNotEqual(set(left["itemIds"]), set(right["itemIds"]))

    def test_event_hidden_fixed_and_special_rewards_are_bound(self):
        browser = browser_catalog()
        for event_id in ("encounter_013", "encounter_014", "encounter_015", "encounter_016"):
            self.assertIn("node_hidden_collectible:relic", browser["events"][event_id])
        self.assertEqual(browser["pools"]["event_hunt_seal:relic"]["itemIds"], ["relic_209"])
        self.assertEqual(browser["pools"]["event_remembrance:relic"]["itemIds"], ["relic_216"])
        self.assertEqual(len(browser["events"]["encounter_006"]), 3)
        self.assertIn("node_battle_normal_invalid_autopsy:relic", browser["special"]["ending3_autopsy"])
        self.assertIn("hopeful_fruits:component", browser["events"]["encounter_010"])

    def test_exchange_inputs_not_presented_as_rewards(self):
        browser = browser_catalog()
        for key in browser["nodes"]["node_type_008"]:
            self.assertNotIn("_input", key)
            self.assertNotIn(key, {"node_sacrifice_normal_relic:relic", "node_sacrifice_rare_relic:relic"})

    def test_fruit_mark_uses_pool_seven_independently_of_node_category(self):
        browser = browser_catalog()
        self.assertEqual(browser["marks"]["node_mark_007"], ["pool_scrap_7:component"])
        self.assertEqual(set(browser["pools"]["pool_scrap_7:component"]["itemIds"]),
                         {"component_009", "component_010", "component_011"})
        self.assertEqual(browser["missing"], [])

    def test_secret_trader_shelves_merge_shop_types_but_keep_first_floor_scope(self):
        browser = browser_catalog()
        keys = browser["nodes"]["node_type_013"]
        self.assertEqual(keys, ["secret_trader_shelves:component", "secret_trader_shelves_f1:component"])
        regular = set(browser["pools"][keys[0]]["itemIds"])
        first = set(browser["pools"][keys[1]]["itemIds"])
        self.assertEqual(len(regular), 23)
        self.assertEqual(len(first), 20)
        known = entries()
        self.assertEqual({known[item_id]["name"] for item_id in regular - first}, {"白模鸟", "白模狗", "白模鱼"})
        self.assertIn("component_001", first)
        self.assertTrue(all(known[item_id]["category"] == "component" for item_id in regular | first))
        self.assertNotIn("node_scrap_shop_seed_cultivation:component", keys)

    def test_observed_probabilities_preserved_and_not_exposed(self):
        before = DATA_PATH.read_bytes()
        source = NodeRewardPoolCatalog()
        observations = deepcopy(source.get("node_wish_relic")["members"])
        browser = browser_catalog()
        self.assertTrue(any(row["probability"] is not None for row in observations))
        self.assertEqual(DATA_PATH.read_bytes(), before)
        self.assertEqual(source.get("node_wish_relic")["members"], observations)
        self.assertNotIn("probability", json.dumps(browser))


if __name__ == "__main__":
    unittest.main()
