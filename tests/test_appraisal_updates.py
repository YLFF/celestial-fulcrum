from copy import deepcopy
import unittest

from fulcrum.component_box import acquire_component, add_component, apply_appraisal_event, new_component_box
from fulcrum.operators import add_operator, promote_operator
from fulcrum.playtime_state import new_playtime, active_instance
from fulcrum.service.updates import apply_commands
from fulcrum.team_status import team_status
from tests.test_snapshot_scoring import context, state
from fulcrum.node_scoring import SnapshotScorer
from tests.test_local_service import fixture


class AppraisalUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.box = {"capacity": 20, "items": []}
        for component in ("component_004", "component_002", "component_006", "component_007", "component_009", "component_015", "component_025"):
            add_component(self.box, component, estimated_value=10)

    def value(self, component, box=None):
        return next(row["estimatedValue"] for row in (box or self.box)["items"] if row["componentId"] == component)

    def test_explicit_events_are_targeted(self):
        apply_appraisal_event(self.box, "recruit")
        self.assertEqual(self.value("component_004"), 13)
        apply_appraisal_event(self.box, "battle", 2)
        self.assertEqual(self.value("component_002"), 14)
        self.assertEqual(self.value("component_006"), 18)
        apply_appraisal_event(self.box, "acquire")
        self.assertEqual(self.value("component_007"), 11)
        self.assertEqual(self.value("component_009"), 14)
        before = deepcopy(self.box)
        apply_appraisal_event(self.box, "soilMove")
        for row, old in zip(self.box["items"], before["items"]):
            self.assertEqual(row["estimatedValue"] - old["estimatedValue"], 2 if int(row["componentId"][-3:]) <= 12 else 0)

    def test_unknown_values_remain_unknown_and_invalid_events_do_not_mutate(self):
        self.box["items"][0]["estimatedValue"] = None
        apply_appraisal_event(self.box, "recruit")
        self.assertIsNone(self.box["items"][0]["estimatedValue"])
        before = deepcopy(self.box)
        for event, count in (("bad", 1), ("battle", 0), ("battle", True)):
            with self.assertRaises(ValueError):
                apply_appraisal_event(self.box, event, count)
            self.assertEqual(before, self.box)

    def test_reveal_grows_every_mist_grass_only_and_updates_total(self):
        for value in (2, 9, None):
            add_component(self.box, "component_003", estimated_value=value)
        state = new_playtime("reveal-appraisal")
        state["componentBox"] = self.box
        state["resources"]["totalEstimatedValue"] = 100
        old = deepcopy(self.box["items"])
        apply_commands(state, [{"type": "componentAppraisal", "event": "reveal", "count": 2}])
        self.assertEqual([row["estimatedValue"] for row in self.box["items"][-3:]], [4, 11, None])
        self.assertEqual(self.box["items"][:-3], old[:-3])
        self.assertEqual(state["resources"]["totalEstimatedValue"], 104)

    def test_moss_bundle_and_growth_count_all_four_acquisitions(self):
        row = acquire_component(self.box, "component_007", instance_id="new-moss")
        self.assertEqual(row["estimatedValue"], 5)
        self.assertEqual(sum(item["componentId"] == "component_008" for item in self.box["items"]), 3)
        self.assertEqual(self.value("component_007"), 14)
        self.assertEqual(self.value("component_009"), 26)
        self.assertEqual(len({item["instanceId"] for item in self.box["items"]}), len(self.box["items"]))

    def test_new_board_does_not_grow_from_its_own_acquisition(self):
        row = acquire_component(self.box, "component_009")
        self.assertEqual(row["estimatedValue"], 8)
        self.assertEqual(self.value("component_009"), 14)

    def test_moss_bundle_may_overflow_and_still_grows_existing_items(self):
        self.box["capacity"] = len(self.box["items"]) + 3
        acquire_component(self.box, "component_007")
        self.assertEqual(len(self.box["items"]), self.box["capacity"] + 1)
        self.assertEqual(self.value("component_007"), 14)
        self.assertEqual(self.value("component_009"), 26)
        acquire_component(self.box, "component_001")
        self.assertEqual(self.value("component_007"), 15)
        self.assertEqual(self.value("component_009"), 30)

    def test_invalid_confirmed_moss_appraisal_does_not_mutate_box(self):
        before = deepcopy(self.box)
        with self.assertRaises(ValueError):
            acquire_component(self.box, "component_007", estimated_value=-1)
        self.assertEqual(before, self.box)

    def test_new_operator_does_not_automatically_grow_corn(self):
        s = new_playtime("appraisal")
        s["componentBox"] = self.box
        add_operator(s, "test recruit", instance_id="first", rarity=6, record_only=True)
        self.assertEqual(self.value("component_004", s["componentBox"]), 10)
        promote_operator(s, "first", record_only=True)
        self.assertEqual(self.value("component_004", s["componentBox"]), 10)
        add_operator(s, "test aid", source="assistance", rarity=6, record_only=True)
        self.assertEqual(self.value("component_004", s["componentBox"]), 10)
        apply_commands(s, [{"type": "componentAppraisal", "event": "recruit", "count": 2}])
        self.assertEqual(self.value("component_004", s["componentBox"]), 16)

    def test_snapshot_add_and_update_do_not_double_settle_growth(self):
        s = new_playtime("snapshot")
        s["componentBox"] = self.box
        old = deepcopy(self.box)
        apply_commands(s, [{"type": "componentAdd", "componentId": "component_001", "instanceId": "snapshot-item", "estimatedValue": 2, "recordOnly": True}])
        self.assertEqual(self.value("component_009", s["componentBox"]), self.value("component_009", old))
        apply_commands(s, [{"type": "componentUpdate", "instanceId": "snapshot-item", "changes": {"estimatedValue": 8}}])
        self.assertEqual(self.value("component_009", s["componentBox"]), 10)

    def test_service_acquisition_and_total_appraisal_delta(self):
        s = new_playtime("service-grow")
        s["componentBox"] = self.box
        s["resources"]["totalEstimatedValue"] = 90  # Includes values not individually confirmed.
        apply_commands(s, [{"type": "componentAdd", "componentId": "component_001"}])
        self.assertEqual(self.value("component_009", s["componentBox"]), 14)
        self.assertEqual(s["resources"]["totalEstimatedValue"], 97)
        apply_commands(s, [{"type": "componentAppraisal", "event": "battle"}])
        self.assertEqual(s["resources"]["totalEstimatedValue"], 103)


class TeamStatusTests(unittest.TestCase):
    def test_counts_exclude_support_and_force_does_not_rewrite_facts(self):
        operators = [{"name": "a", "source": "normal", "rarity": 6, "elite": 2},
                     {"name": "b", "source": "temporary", "rarity": 6, "elite": 1},
                     {"name": "c", "source": "assistance", "rarity": 6, "elite": 2, "remainingBattles": 1}]
        automatic = team_status(operators, 2)
        forced = team_status(operators, 2, options={"teamThresholdOverride": "enough"})
        self.assertEqual(forced["actualCounts"], {"totalOperators": 2, "sixStars": 2, "elite2SixStars": 1})
        self.assertFalse(automatic["met"])
        self.assertTrue(forced["met"])
        self.assertFalse(forced["automaticMet"])
        self.assertEqual(forced["deficits"], automatic["deficits"])
        self.assertEqual(team_status(operators, 2, "squad_005")["required"]["power"], 5)

    def test_forced_insufficient_changes_ticket_scoring(self):
        c = context("III")
        nodes = [{"id": "a", "categoryId": "node_type_001"}]
        a = SnapshotScorer(nodes, c, state(2))
        c["options"]["teamThresholdOverride"] = "insufficient"
        b = SnapshotScorer(nodes, c, state(2))
        self.assertTrue(b.threshold["automaticMet"])
        self.assertFalse(b.threshold["met"])
        self.assertAlmostEqual(b.ticket("先锋招募券"), a.ticket("先锋招募券") * 1.25)

    def test_override_roundtrip_and_validation(self):
        s = fixture()
        apply_commands(s, [{"type": "strategy", "areaKey": "I", "value": {"scoringOptions": {"teamThresholdOverride": "insufficient"}}}])
        self.assertEqual(active_instance(s, "I")["strategy"]["scoringOptions"]["teamThresholdOverride"], "insufficient")
        with self.assertRaises(ValueError):
            apply_commands(s, [{"type": "strategy", "areaKey": "I", "value": {"scoringOptions": {"teamThresholdOverride": "bad"}}}])


if __name__ == "__main__":
    unittest.main()
