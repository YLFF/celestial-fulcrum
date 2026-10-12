"""Assignments persist separately from future combat-effect aggregation."""

from copy import deepcopy
import unittest
from pathlib import Path
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from fulcrum.playtime_state import new_playtime
from fulcrum.relic_presentation import binding_recipients, display_metadata, presentation, runtime_status, validate_binding
from fulcrum.combat_bonuses import summarize_combat_bonuses
from fulcrum.service.catalog import editor_catalog
from fulcrum.service.updates import apply_commands
from fulcrum.service.app import create_app
from fulcrum.service.store import RunStore


class RelicEnchantmentTests(unittest.TestCase):
    def setUp(self):
        self.state = new_playtime("enchantment-unit")
        apply_commands(self.state, [
            {"type": "relics", "items": [{"id": "relic_177", "state": "inactive"}]},
            {"type": "operatorAdd", "name": "机械师", "instanceId": "mechanist", "recordOnly": True},
        ])

    def enchant(self):
        apply_commands(self.state, [{"type": "relicEnchant", "relicId": "relic_177", "operatorInstanceId": "mechanist"}])

    def test_eight_professions_only_and_ui_categories(self):
        data = editor_catalog()
        eligible = [row for row in data["relic"] if row["enchantmentProfession"]]
        self.assertEqual(len(eligible), 8)
        self.assertEqual(len({row["enchantmentProfession"] for row in eligible}), 8)
        self.assertEqual(len([row for row in data["relic"] if row.get("management", {}).get("bindOperator")]), 15)
        self.assertEqual(next(row for row in data["relic"] if row["id"] == "relic_188")["management"]["maxRecipients"], 2)
        self.assertTrue(all(row["name"].endswith("新典训") for row in eligible))
        self.assertTrue(all(row["displayCategory"] in data["relicCategories"] for row in data["relic"]))
        self.assertEqual(presentation()["sortBy"], "id")
        self.assertEqual(presentation()["categorySource"], "bonus_classification")
        self.assertEqual(data["relicCategories"], ["未分类"])
        self.assertEqual({row["displayCategory"] for row in data["relic"]}, {"未分类"})

    def test_bonus_category_overrides_do_not_fall_back_to_game_categories(self):
        config = deepcopy(presentation())
        config["categoryOverrides"] = {"relic_177": "重装增益"}
        config["categoryByName"] = {"其他藏品": "专业工具"}
        with patch("fulcrum.relic_presentation.presentation", return_value=config):
            self.assertEqual(display_metadata({"id": "relic_177", "name": "重装新典训"})["displayCategory"], "重装增益")
            self.assertEqual(display_metadata({"id": "relic_001", "name": "其他藏品"})["displayCategory"], "未分类")

    def test_training_binding_promotes_for_free_and_settles_mechanist_reward(self):
        hope = self.state["resources"]["hope"]
        box = deepcopy(self.state["componentBox"])
        self.enchant()
        row = self.state["relics"][0]
        self.assertEqual(row["state"], "active")
        self.assertEqual(row["enchantment"], {"operatorInstanceId": "mechanist", "operatorName": "机械师", "profession": "重装"})
        operator = next(row for row in self.state["operators"] if row["instanceId"] == "mechanist")
        self.assertEqual(operator["elite"], 2)
        self.assertEqual(self.state["resources"]["hope"], hope)
        self.assertEqual(len(self.state["componentBox"]["items"]), len(box["items"]) + 1)
        self.assertEqual(self.state["componentBox"]["items"][-1]["componentId"], "component_023")
        with self.assertRaisesRegex(ValueError, "再次附魔"):
            self.enchant()

    def test_explicit_free_promotion_still_settles_mechanist_reward(self):
        self.enchant()
        hope = self.state["resources"]["hope"]
        apply_commands(self.state, [{"type": "operatorPromote", "instanceId": "mechanist", "hopeCost": 0}])
        self.assertEqual(self.state["resources"]["hope"], hope)
        self.assertEqual(sum(row["componentId"] == "component_023" for row in self.state["componentBox"]["items"]), 1)

    def test_wrong_profession_missing_or_active_relic_rejected(self):
        for relic_id in ("relic_174", "relic_014"):
            with self.assertRaises(ValueError):
                apply_commands(self.state, [{"type": "relicEnchant", "relicId": relic_id, "operatorInstanceId": "mechanist"}])
        with self.assertRaisesRegex(ValueError, "重装"):
            apply_commands(self.state, [{"type": "relicEnchant", "relicId": "relic_177", "operatorInstanceId": "missing"}])
        self.state["relics"][0]["state"] = "已生效"
        with self.assertRaisesRegex(ValueError, "再次附魔"):
            self.enchant()
        with self.assertRaisesRegex(ValueError, "改回未生效"):
            apply_commands(self.state, [{"type": "relics", "items": [{"id": "relic_177", "state": "inactive"}]}])

    def test_binding_survives_inventory_edit_and_operator_departure(self):
        self.enchant()
        rows = deepcopy(self.state["relics"])
        rows[0]["note"] = "used once"
        apply_commands(self.state, [{"type": "relics", "items": rows}, {"type": "operatorRemove", "instanceId": "mechanist"}])
        self.assertEqual(self.state["relics"][0]["enchantment"]["operatorName"], "机械师")
        rows[0]["enchantment"]["operatorInstanceId"] = "another"
        with self.assertRaisesRegex(ValueError, "重新绑定"):
            apply_commands(self.state, [{"type": "relics", "items": rows}])

    def test_already_promoted_operator_does_not_grant_promotion_twice(self):
        self.state["operators"][-1]["elite"] = 2
        before = deepcopy(self.state["componentBox"])
        self.enchant()
        self.assertEqual(self.state["componentBox"], before)

    def test_forged_binding_and_invalid_state_rejected(self):
        row = {"id": "relic_177", "state": "active", "enchantment": {
            "operatorInstanceId": "mechanist", "operatorName": "机械师", "profession": "重装"}}
        with self.assertRaisesRegex(ValueError, "附魔操作"):
            apply_commands(self.state, [{"type": "relics", "items": [row]}])
        row["enchantment"]["profession"] = "近卫"
        with self.assertRaises(ValueError):
            validate_binding(row)

    def test_cookie_two_recipients_and_multiple_relics_for_same_operator(self):
        apply_commands(self.state, [
            {"type": "relics", "items": [{"id": item, "state": "inactive"} for item in ("relic_177", "relic_188", "relic_187", "relic_185")]},
            {"type": "operatorAdd", "name": "予愿安洁莉娜", "instanceId": "angelina", "recordOnly": True},
            {"type": "relicEnchant", "relicId": "relic_177", "operatorInstanceId": "mechanist"},
            {"type": "relicEnchant", "relicId": "relic_188", "operatorInstanceIds": ["mechanist", "angelina"]},
            {"type": "relicEnchant", "relicId": "relic_187", "operatorInstanceId": "mechanist"},
            {"type": "relicEnchant", "relicId": "relic_185", "operatorInstanceId": "angelina"},
        ])
        self.assertEqual(len(binding_recipients(self.state["relics"][1])), 2)
        self.assertEqual(self.state["operators"][-1]["elite"], 1)
        report = summarize_combat_bonuses(self.state)
        for view in report["operators"]:
            cookie = [source for group in view["categories"] for row in group["rows"] for source in row["sources"] if source["id"] == "relic_188"]
            self.assertTrue(cookie)
        for row in self.state["relics"]:
            validate_binding(row)
        saved = deepcopy(self.state["relics"])
        apply_commands(self.state, [{"type": "relics", "items": saved}])
        self.assertEqual(self.state["relics"], saved)

    def test_invalid_cookie_recipients_rejected_without_using_relic(self):
        apply_commands(self.state, [{"type": "relics", "items": [{"id": "relic_188"}]}])
        for ids in ([], ["mechanist", "mechanist"], ["missing"], ["mechanist", "missing"], ["x", "y", "z"]):
            with self.assertRaises(ValueError):
                apply_commands(self.state, [{"type": "relicEnchant", "relicId": "relic_188", "operatorInstanceIds": ids}])
            self.assertNotIn("enchantment", self.state["relics"][0])

    def test_snapshot_counters_and_dragon_layers_are_automatic(self):
        self.state["resources"]["originiumIngot"] = 24
        self.state["componentBox"]["items"] = [{}] * 8
        self.state["currentAreaKey"] = "II"
        self.assertEqual(runtime_status(self.state, {"id": "relic_192", "state": 99})["value"], 4)
        self.assertEqual(runtime_status(self.state, {"id": "relic_199", "state": 99})["value"], 8)
        self.assertEqual(runtime_status(self.state, {"id": "relic_034", "state": 99})["value"], 2)
        self.state["currentAreaKey"] = "III-treehole"
        self.assertEqual(runtime_status(self.state, {"id": "relic_034"})["value"], 4)
        self.assertTrue(runtime_status(self.state, {"id": "relic_034"})["expired"])
        self.assertEqual(runtime_status(self.state, {"id": "relic_001", "state": 99})["value"], None)
        self.assertFalse(runtime_status(self.state, {"id": "relic_193", "state": 4})["automatic"])

    def test_cookie_api_revision_and_persistence(self):
        apply_commands(self.state, [{"type": "relics", "items": [{"id": "relic_188"}]},
            {"type": "operatorAdd", "name": "予愿安洁莉娜", "instanceId": "angelina", "recordOnly": True}])
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            client.headers["X-Fulcrum-Token"] = client.get("/api/session").json()["token"]
            client.post("/api/runs/restore", json={"state": self.state})
            path = "/api/runs/enchantment-unit"
            response = client.patch(path, json={"expectedRevision": 1, "commands": [{"type": "relicEnchant", "relicId": "relic_188", "operatorInstanceIds": ["mechanist", "angelina"]}]})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(binding_recipients(client.get(path).json()["state"]["relics"][0])), 2)
            rejected = client.patch(path, json={"expectedRevision": 2, "commands": [{"type": "relicEnchant", "relicId": "relic_188", "operatorInstanceId": "mechanist"}]})
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(client.get(path).json()["revision"], 2)

    def test_api_persistence_atomic_rejection_and_map_history(self):
        with tempfile.TemporaryDirectory() as folder, TestClient(create_app(folder)) as client:
            client.headers["X-Fulcrum-Token"] = client.get("/api/session").json()["token"]
            response = client.post("/api/runs/restore", json={"state": self.state})
            self.assertEqual(response.status_code, 201, response.text)
            path = "/api/runs/enchantment-unit"
            command = {"type": "relicEnchant", "relicId": "relic_177", "operatorInstanceId": "mechanist"}
            response = client.patch(path, json={"expectedRevision": 1, "commands": [command]})
            self.assertEqual(response.status_code, 200, response.text)
            stored = response.json()
            self.assertFalse(stored["history"]["canUndo"])
            self.assertEqual(client.get(path).json()["state"]["relics"], stored["state"]["relics"])
            rejected = client.patch(path, json={"expectedRevision": 2, "commands": [command]})
            self.assertEqual(rejected.status_code, 422)
            self.assertEqual(client.get(path).json()["revision"], 2)
            store = RunStore(Path(folder) / "runs")
            store.update("enchantment-unit", 2, lambda state: state.update(memo="map checkpoint"), map_update=True)
            apply = lambda state: apply_commands(state, [{"type": "operatorRemove", "instanceId": "mechanist"}])
            store.update("enchantment-unit", 3, apply)
            undone = store.undo("enchantment-unit", 4)
            redone = store.redo("enchantment-unit", 5)
            self.assertEqual(undone["state"]["relics"], redone["state"]["relics"])
            self.assertFalse(any(row["instanceId"] == "mechanist" for row in redone["state"]["operators"]))


if __name__ == "__main__":
    unittest.main()
