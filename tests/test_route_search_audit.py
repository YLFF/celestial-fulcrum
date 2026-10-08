from __future__ import annotations

import unittest

from scripts.audit_route_search import audit


class SmallSearchAuditTests(unittest.TestCase):
    def test_fully_explored_orders_agree_and_low_queue_rank_can_reach_top_tier(self) -> None:
        report = audit(2, 30000, [500, 5000])
        policies = report["policies"]
        self.assertTrue(all(case["searchComplete"] for case in policies.values()))
        self.assertEqual(len({case["bestScore"] for case in policies.values()}), 1)
        self.assertEqual(len({case["generatedStates"] for case in policies.values()}), 1)
        current = policies["current"]
        late = current["latestFirstTopTierRewardSet"]
        self.assertGreater(late["prefixQueueRankAtFirstGoal"], late["frontierSizeAtFirstGoal"] / 2)
        self.assertGreaterEqual(late["score"], 0.95 * current["bestScore"])
        self.assertLess(current["budgetComparisons"][0]["bestScore"], current["bestScore"])
        self.assertEqual(current["budgetComparisons"][1]["bestScore"], current["bestScore"])
        self.assertEqual(len(report["state"]["items"]), 6)
        self.assertEqual(current["randomMovement"]["excludedItemInstanceIds"], ["component_019"])


if __name__ == "__main__":
    unittest.main()
