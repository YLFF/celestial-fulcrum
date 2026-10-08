from copy import deepcopy
import unittest

from fulcrum.node_scoring import SnapshotScorer
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


def dystopia(policy="dystopia_011", *, source="source", ideology="dystopia_001", covered=("a", "source", "b")):
    return {"active": True, "ideologyId": ideology, "policyId": policy,
            "affectedNodeIds": list(covered), "uncertainNodeIds": [], "idealSourceNodeId": source}


def advance(scorer, entered, *, done=(), cash=0, appraisal=4, steps=0, fresh=None, revealed=()):
    return scorer.step(list(entered), set(entered) - set(done) if fresh is None else set(fresh), list(revealed),
                       before_done=set(done), prefix_cash=cash, appraisal=appraisal,
                       path_steps=steps, processing=False)


class DystopiaScoringTests(unittest.TestCase):
    def test_improvement_cash_floor_never_deducts_appraisal(self):
        for cash, loss in ((0, 0), (1, 1), (2, 2), (30, 2)):
            with self.subTest(cash=cash):
                c = context()
                c["resources"]["originiumIngot"] = cash
                s = state(2, dystopia=dystopia())
                scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_020"}], c, s)
                self.assertEqual(scorer.values["a"]["points"], -8 * loss)
                step = advance(scorer, ["a"], cash=cash)
                self.assertEqual(step["nodeValue"], -8 * loss)
                self.assertEqual(step["merchantTransition"]["cashAfter"], cash - loss)
                self.assertEqual(step["merchantTransition"]["appraisalAfter"], 4)
                self.assertEqual(step["expectedCashDelta"], -loss)

    def test_ordinary_reward_is_priced_once_and_cash_is_deducted_before_reward(self):
        c = context()
        c["resources"]["originiumIngot"] = 0
        nodes = [{"id": "a", "categoryId": "node_type_001"}]
        scorer = SnapshotScorer(nodes, c, state(1, dystopia=dystopia()))
        step = advance(scorer, ["a"], cash=0, steps=1)
        ordinary = scorer.base_values["a"]
        self.assertEqual(step["nodeValue"], ordinary["points"] - 8)
        self.assertEqual(step["merchantTransition"]["cashAfter"], ordinary["expectedCashDelta"])
        self.assertEqual(step["merchantTransition"]["movementProxyStepsAfter"], 0)
        self.assertEqual(step["expectedCashDelta"], ordinary["expectedCashDelta"] - 1)

    def test_only_confirmed_coverage_and_supported_policies_are_applied(self):
        d = dystopia(covered=("a",))
        d["uncertainNodeIds"] = ["b"]
        nodes = [{"id": key, "categoryId": "node_type_020"} for key in ("a", "b")]
        scorer = SnapshotScorer(nodes, context(), state(2, dystopia=d))
        self.assertEqual(scorer.values["a"]["points"], -16)
        self.assertEqual(scorer.values["b"]["points"], 0)
        d["policyId"] = "dystopia_012"
        self.assertEqual(SnapshotScorer(nodes, context(), state(2, dystopia=d)).values["a"]["points"], 0)

    def test_benefit_applies_on_every_pass_and_counts_naturals_only(self):
        c = context()
        c["componentBox"]["items"].extend([
            {"componentId": "component_015", "remainingUses": 3, "estimatedValue": 5},
            {"componentId": "component_030", "estimatedValue": 1}])
        before = deepcopy(c)
        scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_020"}], c,
                                state(3, dystopia=dystopia("dystopia_014")))
        self.assertEqual(scorer.values["a"]["points"], 32)
        for done in ((), ("a",)):
            step = advance(scorer, ["a"], done=done, appraisal=4)
            self.assertEqual(step["nodeValue"], 32)
            self.assertEqual(step["merchantTransition"]["appraisalAfter"], 8)
            self.assertEqual(step["expectedAppraisalDelta"], 4)
        self.assertEqual(c, before)

    def test_source_settles_then_disables_following_policy_and_reveal_value(self):
        c = context()
        c["prediction"] = {"unknownNodes": {"b": {"candidates": [
            {"categoryId": "node_type_001", "distanceFrequency": 1}]}}}
        nodes = [{"id": "source", "categoryId": "node_type_002"},
                 {"id": "b", "categoryId": "unknown_ferocity"}]
        scorer = SnapshotScorer(nodes, c, state(3, dystopia=dystopia("dystopia_014")))
        first = advance(scorer, ["source"], revealed=["b"])
        self.assertEqual(first["nodeValue"], scorer.base_values["source"]["points"] + 32)
        self.assertTrue(first["nodeTerms"][0]["policyAdjustment"]["sourceDestroyedAfter"])
        self.assertFalse(first["dystopiaTransition"]["policyActiveAfter"])
        self.assertEqual(first["revealTerms"][0]["opportunityPoints"], scorer.base_values["b"]["points"])
        second = advance(scorer, ["b"], done=["source"])
        self.assertEqual(second["nodeValue"], scorer.base_values["b"]["points"])
        self.assertNotIn("policyAdjustment", second["nodeTerms"][0])
        already = SnapshotScorer(nodes, c, state(3, completedNodes=["source"], dystopia=dystopia("dystopia_014")))
        self.assertEqual(already.values["b"]["points"], already.base_values["b"]["points"])

    def test_hopeful_soil_benefit_is_not_removed(self):
        d = dystopia("dystopia_014", source=None, ideology="dystopia_008")
        scorer = SnapshotScorer([{"id": "a", "categoryId": "node_type_020"}], context(), state(3, dystopia=d))
        first = advance(scorer, ["a"])
        self.assertTrue(first["dystopiaTransition"]["policyActiveAfter"])
        self.assertFalse(first["nodeTerms"][0]["policyAdjustment"]["sourceDestroyedAfter"])
        self.assertEqual(advance(scorer, ["a"], done=["a"])["nodeValue"], 32)

    def test_natural_tribute_removes_two_from_following_benefit_count(self):
        c = context()
        c["goals"]["preferences"]["ending3_trade"] = "required"
        nodes = [{"id": "a", "categoryId": "node_type_008", "confirmedMarkIds": ["node_mark_006"]},
                 {"id": "b", "categoryId": "node_type_020"}]
        scorer = SnapshotScorer(nodes, c, state(3, dystopia=dystopia("dystopia_014")))
        first = advance(scorer, ["a"])
        self.assertEqual(first["nodeValue"], 32)
        self.assertEqual(first["nodeTerms"][0]["policyAdjustment"]["naturalCount"], 2)
        self.assertEqual(advance(scorer, ["b"], done=["a"])["nodeValue"], 0)

    def test_shop_economy_includes_policy_before_settlement(self):
        c = context()
        nodes = [{"id": "a", "categoryId": "node_type_013"}]
        scorer = SnapshotScorer(nodes, c, state(3, dystopia=dystopia()))
        first = advance(scorer, ["a"], cash=10, appraisal=4, steps=1)
        row = first["nodeTerms"][0]
        self.assertEqual(row["merchant"]["cashBeforeWithdrawal"], 9)
        self.assertEqual(row["merchant"]["economyInput"], 13)
        self.assertEqual(first["merchantTransition"]["cashAfter"], 0)
        self.assertEqual(first["merchantTransition"]["appraisalAfter"], 0)
        self.assertEqual(row["parts"]["dystopiaCashCost"], -16)

    def test_portal_entry_arrival_order_controls_source_cutoff(self):
        nodes = [{"id": "source", "categoryId": "node_type_020"},
                 {"id": "a", "categoryId": "node_type_020"}]
        scorer = SnapshotScorer(nodes, context(), state(3, dystopia=dystopia("dystopia_014")))
        source_first = advance(scorer, ["source", "a"])
        source_last = advance(scorer, ["a", "source"])
        self.assertEqual(source_first["nodeValue"], 32)
        self.assertEqual(source_last["nodeValue"], 64)

    def test_route_results_match_reference_and_report_source_transition(self):
        m = make_map([(0, 0, "start"), (1, 0, "node_type_002"), (2, 0, "node_type_020")],
                     [("0,0", "1,0"), ("1,0", "2,0")])
        s = state(2, pursuit=True, scoringContext=context("I"),
                  dystopia=dystopia("dystopia_014", source="1,0", covered=("1,0", "2,0")), topN=5)
        before = deepcopy(s)
        result = RoutePlanner(m).plan(s)
        reference = RoutePlanner(m).plan({**s, "searchMode": "reference"})
        self.assertEqual([row["metrics"]["weightedValue"] for row in result["routes"]],
                         [row["metrics"]["weightedValue"] for row in reference["routes"]])
        route = next(row for row in result["routes"] if row["endNode"] == "2,0")
        self.assertFalse(route["steps"][0]["scoreBreakdown"]["dystopiaTransition"]["policyActiveAfter"])
        self.assertEqual(route["steps"][1]["nodeValue"], 0)
        self.assertEqual(s, before)

    def test_benefit_exit_reentry_is_not_pruned_as_no_effect(self):
        m = make_map([(0, 0, "node_type_015")], [])
        result = RoutePlanner(m).plan(state(2, scoringContext=context("I"), topN=5,
            dystopia=dystopia("dystopia_014", source=None, ideology="dystopia_008", covered=("0,0",))))
        self.assertEqual(result["searchDiagnostics"]["noEffectEndReentriesSkipped"], 0)
        self.assertEqual(len(result["routes"][0]["steps"]), 2)
        self.assertEqual(sum(step["nodeValue"] for step in result["routes"][0]["steps"]), 64)

    def test_reference_losses_include_units_without_entering_planning_score(self):
        c = context()
        c["goals"]["preferences"]["ending3_trade"] = "required"
        scorer = SnapshotScorer([], c, state(2))
        loss = scorer.natural_tribute()
        self.assertEqual(loss["points"], 0)
        self.assertEqual(loss["referenceLoss"]["componentUnitPoints"], 250)
        self.assertEqual(loss["referenceLoss"]["cashEquivalentPoints"], -32)
        self.assertTrue(loss["scoringBasis"])
        cash = scorer.cash_tribute(30)
        self.assertEqual(cash["referenceLoss"]["points"], -240)
        self.assertEqual(cash["referenceLoss"]["cashUnitPoints"], 8)
        self.assertEqual(cash["points"], 0)

    def test_policy_respects_node_weight_in_preview_and_route(self):
        c = context("I", options={"nodeWeights": {"0,0": -1}})
        m = make_map([(0, 0, "node_type_015")], [])
        s = state(2, scoringContext=c, topN=5,
                  dystopia=dystopia(covered=("0,0",), source=None))
        preview = RoutePlanner(m).score_snapshot(s)["nodeValues"]["0,0"]
        self.assertEqual(preview["parts"]["dystopiaCashCost"], 16)
        result = RoutePlanner(m).plan(s)
        self.assertEqual(result["searchDiagnostics"]["noEffectEndReentriesSkipped"], 0)
        self.assertEqual(len(result["routes"][0]["steps"]), 2)
        self.assertEqual(sum(step["nodeValue"] for step in result["routes"][0]["steps"]), 32)


if __name__ == "__main__":
    unittest.main()
