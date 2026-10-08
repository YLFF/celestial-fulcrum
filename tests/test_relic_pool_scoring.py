"""Relic-pool bindings and protection of player-edited score sheets."""

import json
from pathlib import Path
import tempfile
import unittest

from fulcrum.node_rewards import NodeRewardPoolCatalog
from scripts.export_relic_pool_scoring import build_index, export_sheet, markdown


class RelicPoolScoreSheetTests(unittest.TestCase):
    def test_pool_members_bind_stable_ids_without_merging_condition_frequencies(self):
        index = build_index()
        catalog = NodeRewardPoolCatalog()
        self.assertEqual(len(index["pools"]), 14)
        self.assertEqual(len({p["id"] for p in index["pools"]}), 14)
        for pool in index["pools"]:
            definition = catalog.get_pool(pool["id"])
            self.assertEqual({row["id"] for row in pool["members"]},
                             {row["itemId"] for row in definition["members"]})
            self.assertEqual(len({row["id"] for row in pool["members"]}), len(pool["members"]))
            self.assertTrue(all(row["id"].startswith("relic_") for row in pool["members"]))
            for context in pool["contexts"]:
                source = catalog.get(context["id"])
                self.assertEqual(context["statistics"], source["statistics"])
                self.assertEqual(context["observations"], [
                    {"id": m["itemId"], "count": m["occurrenceCount"], "probability": m["probability"]}
                    for m in source["members"]])
        pools = {pool["id"]: pool for pool in index["pools"]}
        self.assertEqual(len(pools["node_incident_lake_fairy"]["contexts"]), 3)
        self.assertEqual(len(pools["node_wish_relic"]["contexts"]), 3)

    def test_fixed_relics_and_hidden_companion_pool_bindings_are_explicit(self):
        index = build_index()
        fixed = {row["id"]: row for row in index["fixedRelics"]}
        self.assertEqual(fixed["relic_209"]["name"], "猎印")
        self.assertEqual(fixed["relic_215"]["name"], "犬植浆")
        self.assertEqual(fixed["relic_207"]["name"], "同行者")
        pending = " ".join(row["usage"] for row in index["pendingBindings"])
        for name in ("思乡心切", "划算买卖", "鸭托邦", "传奇团伙"):
            self.assertNotIn(name, pending)
        self.assertEqual({row["id"] for row in index["eventBindings"]},
                         {"encounter_013", "encounter_014", "encounter_015", "encounter_016"})
        self.assertTrue(all(row["relicContextId"] == "node_hidden_collectible" for row in index["eventBindings"]))
        specials = {row["id"]: row for row in index["specialComponentPools"]}
        self.assertEqual(len(specials["hopeful_fruits"]["members"]), 19)
        self.assertEqual(len(specials["node_battle_savage_scrap_right"]["members"]), 20)
        self.assertEqual(specials["node_battle_savage_scrap_right"]["selection"]["candidateCount"], 2)
        self.assertIn("不是整个事件总分", markdown(index))
        self.assertIn("单件期望分覆盖", markdown(index))
        self.assertIn("不能再乘2", markdown(index))

    def test_generated_index_and_sheet_are_deterministic(self):
        before = build_index()
        self.assertEqual(before, build_index())
        self.assertEqual(markdown(before), markdown(build_index()))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sheet, data = root / "score.md", root / "index.json"
            export_sheet(sheet, data)
            self.assertEqual(sheet.read_text(encoding="utf-8"), markdown(before))
            self.assertEqual(json.loads(data.read_text(encoding="utf-8")), before)

    def test_existing_manual_sheet_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sheet, data = root / "score.md", root / "index.json"
            sheet.write_text("manual score edits", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                export_sheet(sheet, data)
            self.assertEqual(sheet.read_text(encoding="utf-8"), "manual score edits")
            self.assertFalse(data.exists())

    def test_existing_index_is_checked_before_creating_sheet(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sheet, data = root / "score.md", root / "index.json"
            data.write_text("manual index edits", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                export_sheet(sheet, data)
            self.assertEqual(data.read_text(encoding="utf-8"), "manual index edits")
            self.assertFalse(sheet.exists())

    def test_sheet_and_index_paths_must_differ(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "score.md"
            with self.assertRaises(ValueError):
                export_sheet(path, path)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
