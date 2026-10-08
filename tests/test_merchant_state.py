from copy import deepcopy
from dataclasses import replace
import unittest

from fulcrum.component_box import add_component
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.merchant_state import (confirm_shop_visit, set_investment_balance,
                                      set_shop_shelves, shelf_fraction, withdrawal_quote)
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime, update_node, validate_playtime
from fulcrum.route_planner import RoutePlanner, _State
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


def shop_playtime():
    p = new_playtime("shop-state")
    template = TemplateCatalog().candidates("main", 1)[0]
    slots = [slot for slot in template.occupied_slots if slot != template.start_slot and slot not in template.terminal_slots]
    green, yellow = [template.coord(slot).key for slot in slots[:2]]
    observation = {"success": True, "area": "main", "floor": 1, "templateId": template.id,
        "nodes": [{"id": template.coord(slot).key, "coord": [template.coord(slot).x, template.coord(slot).y],
                   "slot": list(slot), "visibility": "revealed", "marks": [],
                   "categoryId": "start" if slot == template.start_slot else
                       "node_type_004" if template.coord(slot).key == green else
                       "node_type_013" if template.coord(slot).key == yellow else "node_type_001"}
                  for slot in template.occupied_slots],
        "edges": [[template.coord(a).key, template.coord(b).key] for a, b in template.edges],
        "playerPositionObservation": {"status": "recognized", "nodeId": "0,0"}}
    instance = merge_map_observation(p, "I", observation)
    instance["actionPoints"] = 6
    return p, green, yellow


class MerchantStateTests(unittest.TestCase):
    def test_investment_default_override_and_validation(self):
        self.assertEqual(new_playtime("default")["resources"]["investmentBalance"], 99)
        self.assertEqual(new_playtime("empty", investment_balance=0)["resources"]["investmentBalance"], 0)
        for value in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                new_playtime("bad", investment_balance=value)

    def test_exact_costs_and_partial_withdrawal(self):
        first = withdrawal_quote(99)
        second = withdrawal_quote(first["balanceAfter"])
        third = withdrawal_quote(second["balanceAfter"])
        self.assertEqual((first["cash"], first["investmentCost"], first["balanceAfter"]), (10, 49, 50))
        self.assertEqual((second["cash"], second["investmentCost"], second["balanceAfter"]), (10, 49, 1))
        self.assertEqual((third["cash"], third["investmentCost"], third["balanceAfter"]), (1, 1, 0))
        self.assertEqual(withdrawal_quote(48)["cash"], 9)
        self.assertEqual(withdrawal_quote(63, 12)["cash"], 12)
        self.assertEqual(withdrawal_quote(0)["cash"], 0)

    def test_shelf_fraction_counts_initial_display(self):
        self.assertEqual([shelf_fraction(i) for i in range(6)], [1, .8, .6, .4, .2, 0])
        for value in (-1, 6, True, 1.5):
            with self.assertRaises(ValueError):
                shelf_fraction(value)

    def test_manual_shop_and_investment_updates_are_snapshot_fields(self):
        p, green, yellow = shop_playtime()
        set_shop_shelves(p, "I", green, 4)
        set_shop_shelves(p, "I", yellow, 1)
        set_investment_balance(p, 50)
        validate_playtime(p)
        m, s = route_inputs(p)
        self.assertEqual(s["scoringContext"]["resources"]["investmentBalance"], 50)
        counts = {row["id"]: row["merchantViewedShelves"] for row in m["nodes"]}
        self.assertEqual((counts[green], counts[yellow]), (4, 1))

    def test_confirmed_visit_never_applies_predicted_spending(self):
        p, green, _ = shop_playtime()
        before_cash = p["resources"]["originiumIngot"]
        confirmation = confirm_shop_visit(p, "I", green, withdrawn_ingots=10)
        self.assertEqual(confirmation["remainingFraction"], .8)
        self.assertEqual(p["resources"]["investmentBalance"], 50)
        self.assertEqual(p["resources"]["originiumIngot"], before_cash + 10)
        confirm_shop_visit(p, "I", green, viewed=4, withdrawn_ingots=10, record_only=True)
        self.assertEqual(p["resources"]["originiumIngot"], before_cash + 10)
        self.assertEqual(p["resources"]["investmentBalance"], 1)
        self.assertEqual(len(p["componentBox"]["items"]), 2)

    def test_invalid_withdrawal_does_not_partially_mutate(self):
        p, green, yellow = shop_playtime()
        set_investment_balance(p, 1)
        for node, amount in ((green, 10), (yellow, 1)):
            before = deepcopy(p)
            with self.assertRaises(ValueError):
                confirm_shop_visit(p, "I", node, withdrawn_ingots=amount)
            self.assertEqual(p, before)

    def test_legacy_completed_shop_defaults_to_eighty_percent(self):
        p, green, _ = shop_playtime()
        update_node(p, "I", green, completion="completed")
        m, _ = route_inputs(p)
        self.assertEqual(next(row for row in m["nodes"] if row["id"] == green)["merchantViewedShelves"], 1)
        update_node(p, "I", green, category_id="node_type_001")
        validate_playtime(p)

    def test_scorer_resets_economy_and_movement_proxy_but_not_actual_snapshot(self):
        c = context(options={"merchantReserve": 0})
        before = deepcopy(c)
        scorer = SnapshotScorer([{"id": "g", "categoryId": "node_type_004"}], c, state(3))
        row = scorer.step(["g"], {"g"}, [], before_done=set(), prefix_cash=20, appraisal=4,
                          path_steps=3, processing=False)
        shop = row["nodeTerms"][0]["merchant"]
        self.assertEqual(shop["economyInput"], 37)
        transition = row["merchantTransition"]
        self.assertEqual((transition["cashAfter"], transition["appraisalAfter"], transition["movementProxyStepsAfter"]), (0, 0, 0))
        self.assertEqual(transition["investmentBalanceAfter"], 50)
        self.assertEqual(c, before)

    def test_cash_earned_after_shop_can_reach_later_shop(self):
        nodes = [{"id": "y", "categoryId": "node_type_013"}, {"id": "b", "categoryId": "node_type_001"}]
        scorer = SnapshotScorer(nodes, context("I"), state(3))
        first = scorer.step(["y"], {"y"}, [], before_done=set(), prefix_cash=20, appraisal=4,
                            path_steps=1, processing=False)["merchantTransition"]
        battle = scorer.step(["b"], {"b"}, [], before_done={"y"}, prefix_cash=first["cashAfter"],
                             appraisal=first["appraisalAfter"], path_steps=1, processing=False,
                             investment_balance=first["investmentBalanceAfter"], merchant_shelves=first["viewedShelvesAfter"])
        t = battle["merchantTransition"]
        second = scorer.step(["y"], set(), [], before_done={"y", "b"}, prefix_cash=t["cashAfter"],
                             appraisal=t["appraisalAfter"], path_steps=t["movementProxyStepsAfter"] + 1, processing=False,
                             investment_balance=t["investmentBalanceAfter"], merchant_shelves=t["viewedShelvesAfter"])
        shop = second["nodeTerms"][0]["merchant"]
        self.assertEqual(shop["remainingShelfFraction"], .8)
        self.assertEqual(shop["economyInput"], battle["expectedCashDelta"] + 2)

    def test_unknown_shop_reset_is_probability_weighted(self):
        node = {"id": "u", "categoryId": "unknown_mystery",
                "categoryProbabilities": {"node_type_004": .5, "node_type_020": .5}}
        scorer = SnapshotScorer([node], context(options={"merchantReserve": 0}), state(2))
        row = scorer.step(["u"], {"u"}, [], before_done=set(), prefix_cash=10, appraisal=4,
                          path_steps=1, processing=False)
        t = row["merchantTransition"]
        self.assertEqual((t["cashAfter"], t["appraisalAfter"], t["movementProxyStepsAfter"]), (5, 2, .5))
        self.assertEqual(t["investmentBalanceAfter"], 74.5)
        self.assertEqual(t["retainedAppraisalFraction"], .5)

    def test_withdrawal_cash_reward_is_independent_of_stock_and_reserve(self):
        scorer = SnapshotScorer([{"id": "g", "categoryId": "node_type_004"}],
                                context(options={"merchantReserve": 20}), state(2))
        for viewed in (1, 4, 5):
            value = scorer.shop("node_type_004", 1, 0, done={"g"}, repeated=True,
                                node_id="g", viewed_shelves=viewed, investment_balance=50)
            self.assertEqual(value["stockAdjustedPoints"], 0)
            self.assertEqual(value["points"], 80)
            self.assertEqual(value["parts"]["withdrawalCash"], 80)
        partial = scorer.shop("node_type_004", 0, 0, done={"g"}, repeated=True,
                              node_id="g", viewed_shelves=5, investment_balance=1)
        self.assertEqual(partial["withdrawalPoints"], 8)
        empty = scorer.shop("node_type_004", 0, 0, done={"g"}, repeated=True,
                            node_id="g", viewed_shelves=5, investment_balance=0)
        self.assertEqual(empty["points"], 0)
        yellow = scorer.shop("node_type_013", 20, 0, done=set(), repeated=False, investment_balance=99)
        self.assertEqual(yellow["withdrawalPoints"], 0)

    def test_withdrawal_cash_does_not_require_gaining_shopping_opportunity(self):
        scorer = SnapshotScorer([{"id": "g", "categoryId": "node_type_004"}],
                                context(options={"merchantReserve": 20}), state(2))
        row = scorer.step(["g"], set(), [], before_done={"g"}, prefix_cash=0, appraisal=0,
                          path_steps=1, processing=False, investment_balance=50, merchant_shelves={"g": 1})
        self.assertEqual(row["nodeValue"], 80)
        self.assertEqual(row["expectedCashDelta"], 0)
        self.assertEqual(row["merchantTransition"]["cashAfter"], 0)
        self.assertEqual(row["merchantTransition"]["investmentBalanceAfter"], 1)

    def test_old_item_exhaustion_after_shop_does_not_spend_new_appraisal(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_013"),
                      (2, 0, "node_type_017"), (5, 0, "node_type_004")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        c = context(options={"merchantReserve": 0})
        add_component(c["componentBox"], "component_004", estimated_value=1)
        item = add_component(c["componentBox"], "component_022", estimated_value=10, remaining_uses=1)
        s = state(3, pursuit=True, topN=50, scoringContext=c, items=[{
            "instanceId": item["instanceId"], "componentId": "component_022", "remainingUses": 1,
            "estimatedValue": 10}])
        routes = RoutePlanner(m).plan(s)["routes"]
        route = next(r for r in routes
                     if [step["arrived"] for step in r["steps"]] == ["1,0", "2,0", "5,0"]
                     and [step["movement"] for step in r["steps"]] == ["walk", "walk", "item"])
        self.assertEqual(route["steps"][0]["expectedPrefixAppraisalAfter"], 0)
        self.assertEqual(route["steps"][1]["expectedPrefixAppraisalAfter"], 9)
        shop = route["steps"][2]["scoreBreakdown"]["nodeTerms"][0]["merchant"]
        self.assertEqual(shop["economyInput"], 9 + 4 + 2 + 10)

    def test_investment_stock_and_post_shop_proxy_are_future_state_dimensions(self):
        initial = _State(0, 2, 7, 7, 0, (), prefix_cash=1, merchant_shelves=(1,), investment_balance=50)
        for candidate in (replace(initial, investment_balance=1), replace(initial, merchant_shelves=(4,)),
                          replace(initial, economy_movements=2), replace(initial, retained_appraisal_fraction=0)):
            self.assertNotEqual(RoutePlanner._state_key(initial, ()), RoutePlanner._state_key(candidate, ()))

    def test_search_consumes_quote_once_and_reference_agrees(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_004")], [("0,0", "1,0")])
        s = state(3, pursuit=True, topN=30, scoringContext=context(options={"merchantReserve": 0}))
        before = deepcopy(s)
        optimized = RoutePlanner(m).plan(s)
        reference = RoutePlanner(m).plan({**s, "searchMode": "reference"})
        self.assertTrue(optimized["searchComplete"] and reference["searchComplete"])
        self.assertEqual([r["metrics"]["weightedValue"] for r in optimized["routes"]],
                         [r["metrics"]["weightedValue"] for r in reference["routes"]])
        route = next(r for r in optimized["routes"] if all(step["arrived"] == "1,0" for step in r["steps"]))
        quotes = [step["scoreBreakdown"]["nodeTerms"][0]["merchant"] for step in route["steps"]]
        self.assertEqual([q["withdrawal"]["cash"] for q in quotes], [10, 10, 1])
        self.assertEqual([q["remainingShelfFraction"] for q in quotes], [1, .8, .6])
        self.assertEqual([step["expectedInvestmentBalanceAfter"] for step in route["steps"]], [50, 1, 0])
        self.assertEqual(s, before)


if __name__ == "__main__":
    unittest.main()
