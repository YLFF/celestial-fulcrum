import unittest

from fulcrum.operator_catalog import find_operator, search_operators
from fulcrum.operators import add_operator, promote_operator
from fulcrum.playtime_state import new_playtime
from fulcrum.recruitment import initial_roster
from fulcrum.service.updates import apply_commands


class GenericOperatorTests(unittest.TestCase):
    def test_latest_prts_operators_are_searchable_with_complete_stats(self):
        for name, rarity, profession, subprofession in (
            ("克莱门莎", 6, "近卫", "本源近卫"),
            ("旅骨", 5, "特种", "炼金师"),
            ("德·托莱多", 5, "辅助", "削弱者"),
        ):
            with self.subTest(name=name):
                entry = find_operator(name)
                self.assertEqual((entry["rarity"], entry["profession"], entry["subprofession"]),
                                 (rarity, profession, subprofession))
                self.assertIn(entry, search_operators(entry["code"]))
                for field in ("hp", "attack", "defense", "resistance", "redeploySeconds", "block",
                              "attackIntervalSeconds", "deploymentCosts"):
                    self.assertIn(field, entry["stats"])

    def test_catalog_and_fuzzy_search(self):
        for name, rarity in (("罗德岛预备干员", 3), ("罗德岛精英干员", 5)):
            entry = find_operator(name)
            self.assertEqual(entry["rarity"], rarity)
            self.assertIsNone(entry["profession"])
            self.assertTrue(entry["repeatable"])
            self.assertTrue(entry["professionEditable"])
            self.assertEqual(entry["source"], "local")
        self.assertEqual({row["name"] for row in search_operators("罗德岛干员")},
                         {"罗德岛预备干员", "罗德岛精英干员"})

    def test_repeatable_entries_retain_independent_professions_and_ids(self):
        state = new_playtime("generic-operators")
        state["operators"] = []
        commands = []
        for index, (name, profession) in enumerate((
            ("罗德岛预备干员", None), ("罗德岛预备干员", "近卫"),
            ("罗德岛精英干员", "医疗"), ("罗德岛精英干员", "重装"),
        )):
            commands.append({"type": "operatorAdd", "name": name, "profession": profession,
                             "instanceId": f"generic-{index}", "rarity": 6, "recordOnly": True})
        apply_commands(state, commands)
        self.assertEqual([row["rarity"] for row in state["operators"]], [3, 3, 5, 5])
        self.assertEqual([row["profession"] for row in state["operators"]], [None, "近卫", "医疗", "重装"])
        apply_commands(state, [{"type": "operatorUpdate", "instanceId": "generic-0",
                                "changes": {"profession": "狙击"}}])
        self.assertEqual([row["profession"] for row in state["operators"]], ["狙击", "近卫", "医疗", "重装"])
        self.assertEqual(len({row["instanceId"] for row in state["operators"]}), 4)

    def test_regular_operator_is_still_unique(self):
        state = new_playtime("regular-unique")
        add_operator(state, "芬", record_only=True)
        with self.assertRaises(ValueError):
            add_operator(state, "芬", record_only=True)

    def test_placeholders_are_repeatable_and_keep_independent_editable_fields(self):
        entry = find_operator("新干员临时占位")
        self.assertTrue(entry["repeatable"])
        self.assertTrue(entry["professionEditable"])
        self.assertTrue(entry["rarityEditable"])
        self.assertIn(entry, search_operators("新干员占位"))
        state = new_playtime("placeholder-roster")
        state["operators"] = []
        apply_commands(state, [{"type": "operatorAdd", "name": entry["name"], "instanceId": f"placeholder-{index}",
                                "profession": profession, "rarity": rarity, "recordOnly": True}
                               for index, (profession, rarity) in enumerate((("近卫", 6), ("医疗", 5)))])
        self.assertEqual([row["rarity"] for row in state["operators"]], [6, 5])
        self.assertEqual([row["profession"] for row in state["operators"]], ["近卫", "医疗"])
        apply_commands(state, [{"type": "operatorUpdate", "instanceId": "placeholder-0", "changes": {"rarity": 4, "profession": "先锋"}}])
        self.assertEqual([row["rarity"] for row in state["operators"]], [4, 5])
        self.assertEqual([row["profession"] for row in state["operators"]], ["先锋", "医疗"])

    def test_placeholder_costs_follow_confirmed_rarity_and_profession(self):
        state = new_playtime("placeholder-cost", squad_id="squad_007")
        state["resources"]["hope"] = 30
        operator = add_operator(state, "新干员临时占位", rarity=6, profession="医疗")
        self.assertEqual(state["resources"]["hope"], 25)
        promote_operator(state, operator["instanceId"])
        self.assertEqual(state["resources"]["hope"], 23)

    def test_generic_profession_affects_hope_price_and_opening_allows_duplicates(self):
        state = new_playtime("generic-price", squad_id="squad_007")
        state["resources"]["hope"] = 6
        add_operator(state, "罗德岛精英干员", profession="医疗")
        self.assertEqual(state["resources"]["hope"], 5)
        roster = initial_roster([
            {"name": "罗德岛预备干员", "profession": "重装"},
            {"name": "罗德岛预备干员", "profession": "近卫"},
            {"name": "罗德岛精英干员", "profession": "医疗"},
        ], squad_id="squad_007", difficulty=15)
        self.assertEqual([row["profession"] for row in roster], ["重装", "近卫", "医疗"])
        self.assertEqual([row["hopeCost"] for row in roster], [0, 0, 0])


if __name__ == "__main__":
    unittest.main()
