from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient

from fulcrum.opening import build_opening
from fulcrum.operator_catalog import find_operator, operators, search_operators
from fulcrum.recruitment import hope_price
from fulcrum.service.app import create_app


class OpeningSetupTests(unittest.TestCase):
    def test_lookout_split_api_persists_checkbox(self):
        with TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            client.headers["X-Fulcrum-Token"] = client.get("/api/session").json()["token"]
            for name, options, expected in (("default", {}, True), ("disabled", {"lookoutSplitUnlocked": False}, False)):
                payload = {"runId": name, "squadId": "squad_014", **options}
                self.assertEqual(client.post("/api/opening/preview", json=payload).status_code, 200)
                created = client.post("/api/runs", json=payload)
                self.assertEqual(created.status_code, 201, created.text)
                self.assertEqual(created.json()["state"]["opening"]["lookoutSplitUnlocked"], expected)
            self.assertEqual(client.post("/api/runs", json={"runId": "invalid", "squadId": "squad_014",
                "lookoutSplitUnlocked": 1}).status_code, 422)

    def test_directory_identity_and_stats(self):
        self.assertGreater(len(operators()), 300)
        row = find_operator("机械师")
        self.assertEqual((row["rarity"], row["profession"], row["position"]), (6, "重装", "近战位"))
        self.assertEqual(row["stats"]["attackIntervalSeconds"], 1.2)
        self.assertEqual(row["stats"]["deploymentCosts"], [19, 21, 23])
        self.assertIn(row, search_operators("mcnist", "重装"))
        self.assertIn(find_operator("予愿安洁莉娜"), search_operators("予愿安"))

    def test_rarity_prices_and_squad_discounts(self):
        for rarity, initial, later, promote in [(4, 0, 0, 1), (5, 2, 3, 1), (6, 6, 7, 3)]:
            row = {"rarity": rarity, "profession": "重装"}
            self.assertEqual(hope_price(row, initial=True), initial)
            self.assertEqual(hope_price(row), later)
            self.assertEqual(hope_price(row, promotion=True), promote)
        row = find_operator("机械师")
        self.assertEqual(hope_price(row, initial=True), 2)
        self.assertEqual(hope_price(row), 3)
        self.assertEqual(hope_price(row, promotion=True), 1)
        self.assertEqual(hope_price(row, initial=True, squad_id="squad_006"), 0)
        self.assertEqual(hope_price(row, source="temporary"), 0)
        self.assertEqual(hope_price(row, source="temporary", promotion=True), 1)

    def test_opening_supports_and_fixed_aid(self):
        state = build_opening(squad_id="squad_003", cocoons={"猫": 2, "狗": 2},
                              initial_supports=["cash", "capacity", "life_relic", "rare_relic", "processing"])
        self.assertEqual(state["resources"]["hope"], 10)
        self.assertEqual(state["resources"]["originiumIngot"], 52)
        self.assertEqual(state["componentBox"]["capacity"], 9)
        self.assertEqual(state["resources"]["life"], {"current": 2, "max": 2})
        aid = state["operators"][0]
        self.assertEqual((aid["rarity"], aid["profession"], aid["elite"], aid["remainingBattles"]), (6, "重装", 2, 1))
        self.assertEqual(len(state["pendingOpeningRewards"]), 3)

    def test_special_squad_initial_promotion(self):
        state = build_opening(squad_id="squad_002", initial_tickets=["重装招募券"], promote_initial_mechanist=True)
        row = next(row for row in state["operators"] if row["name"] == "机械师")
        self.assertEqual(row["elite"], 2)
        self.assertEqual(state["resources"]["hope"], 4)
        self.assertEqual(state["recruitmentTickets"], [])
        self.assertEqual(state["componentBox"]["items"][-1]["componentId"], "component_023")
        with self.assertRaises(ValueError):
            build_opening(squad_id="squad_002", promote_initial_mechanist=True)

    def test_preview_and_creation_share_cost_authority(self):
        with TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            token = client.get("/api/session").json()["token"]
            client.headers["X-Fulcrum-Token"] = token
            self.assertEqual(client.post("/api/runs", json={"runId": "missing-squad"}).status_code, 422)
            payload = {"runId": "new", "squadId": "squad_003", "cocoons": {"狗": 2},
                       "initialOperators": [{"name": "予愿安洁莉娜", "hopeCost": 0, "rarity": 1}]}
            preview = client.post("/api/opening/preview", json=payload).json()
            self.assertEqual((preview["initialHope"], preview["hopeCost"], preview["remainingHope"]), (10, 6, 4))
            result = client.post("/api/runs", json=payload)
            self.assertEqual(result.status_code, 201, result.text)
            state = result.json()["state"]
            self.assertEqual(state["resources"]["hope"], 4)
            self.assertEqual(next(row for row in state["operators"] if row["name"] == "予愿安洁莉娜")["elite"], 1)
            payload.update(runId="too-expensive", squadId="squad_014", cocoons={})
            payload["initialOperators"].append({"name": "维什戴尔"})
            self.assertFalse(client.post("/api/opening/preview", json=payload).json()["affordable"])
            self.assertEqual(client.post("/api/runs", json=payload).status_code, 422)
            self.assertNotIn("too-expensive", [row["runId"] for row in client.get("/api/runs").json()["runs"]])


if __name__ == "__main__":
    unittest.main()
