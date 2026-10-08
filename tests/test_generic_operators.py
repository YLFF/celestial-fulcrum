import unittest

from fulcrum.operator_catalog import find_operator, search_operators
from fulcrum.operators import add_operator
from fulcrum.playtime_state import new_playtime
from fulcrum.recruitment import initial_roster
from fulcrum.service.updates import apply_commands


class GenericOperatorTests(unittest.TestCase):
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
