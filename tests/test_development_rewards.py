from copy import deepcopy
import unittest

from fulcrum.battle_rewards import BattleRewardCatalog
from fulcrum.development_bonuses import battle_reward_modifiers, reward_amount
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.route_planner import RoutePlanner
from tests.test_route_planner import make_map, state
from tests.test_snapshot_scoring import context


class DevelopmentRewardTests(unittest.TestCase):
    def test_each_confirmed_relic_targets_only_its_own_resource(self):
        for relic_id, xp, cash in [('relic_025', 10, 15), ('relic_026', 12, 10), ('relic_027', 13, 10),
                                   ('relic_138', 14, 14), ('relic_141', 12, 10)]:
            with self.subTest(relic=relic_id):
                modifiers = battle_reward_modifiers([{'id': relic_id}])
                self.assertEqual(reward_amount(10, modifiers['battle_experience_reward']), xp)
                self.assertEqual(reward_amount(10, modifiers['battle_cash_reward']), cash)

    def test_experience_relics_add_cash_factors_multiply_and_round_once(self):
        modifiers = battle_reward_modifiers([{'id': key} for key in ('relic_025', 'relic_026', 'relic_027', 'relic_138', 'relic_141')])
        battle = BattleRewardCatalog().resolve(area_key='III', mode='normal', reward_modifiers=modifiers)
        self.assertEqual(battle['experienceAward'], 36)  # floor(13 * 1.1^3 * (1 + .2 + .3 + .4 + .2))
        self.assertEqual(battle['originiumIngot']['value'], 4)  # floor(2 * 1.5 * 1.4)
        self.assertTrue(all(term['operation'] == 'base_ratio_delta' for term in modifiers['battle_experience_reward']))
        self.assertTrue(all(term['operation'] == 'factor' for term in modifiers['battle_cash_reward']))
        self.assertEqual(reward_amount(100, modifiers['battle_experience_reward']), 210)
        self.assertEqual(reward_amount(100, modifiers['battle_cash_reward']), 210)
        terms = [{'operation': 'flat_delta', 'value': 2}, {'operation': 'flat_delta', 'value': -1},
                 {'operation': 'factor', 'value': 1.3}, {'operation': 'factor', 'value': 1.4}]
        self.assertEqual(reward_amount(2, terms), 5)
        additive_terms = [{'operation': 'flat_delta', 'value': 1},
                          {'operation': 'base_ratio_delta', 'value': .3},
                          {'operation': 'base_ratio_delta', 'value': .4}]
        self.assertEqual(reward_amount(2, additive_terms), 5)

    def test_rewards_feed_scores_and_route_cash_without_mutating_playtime(self):
        c = context('III', options={'teamThresholdOverride': 'insufficient', 'hopeDeficit': 10})
        c['relics'] = [{'id': 'relic_025'}, {'id': 'relic_027'}, {'id': 'relic_138'}]
        c['resources']['hope'] = 0
        before = deepcopy(c)
        game_map = make_map([(0, 0, 'start'), (1, 0, 'node_type_001'), (2, 0, 'node_type_003')],
                            [('0,0', '1,0'), ('1,0', '2,0')])
        route_state = state(2, scoringContext=c)
        scorer = SnapshotScorer(game_map['nodes'], c, route_state)
        battle = scorer.values['1,0']
        self.assertEqual(battle['expectedCashDelta'], 4)
        self.assertEqual(battle['parts']['cash'], 32)
        self.assertEqual(battle['experienceAward'], 29)
        self.assertGreater(battle['parts']['experience'], 0)
        routes = RoutePlanner(game_map).plan(route_state)['routes']
        self.assertTrue(routes)
        self.assertEqual(routes[0]['steps'][0]['scoreBreakdown']['nodeTerms'][0]['expectedCashDelta'], 4)
        self.assertEqual(c, before)

    def test_event_cash_is_not_modified_and_derived_battles_are_modified_once(self):
        c = context()
        c['relics'] = [{'id': 'relic_025'}, {'id': 'relic_138'}]
        scorer = SnapshotScorer([], c, state(2))
        plain = SnapshotScorer([], context(), state(2))
        self.assertEqual(scorer.encounter('encounter_002')['expectedCashDelta'], plain.encounter('encounter_002')['expectedCashDelta'])
        self.assertEqual(scorer.encounter('encounter_013')['expectedCashDelta'], 6)
        self.assertEqual(scorer.battle('specialNormal', stage='无效验尸')['expectedCashDelta'], 10)
        self.assertEqual(scorer.battle('boss', area='VI')['points'], 0)

    def test_only_held_relics_apply_without_double_counting_duplicates(self):
        modifiers = battle_reward_modifiers([{'id': 'relic_025'}, {'id': 'relic_025'}, {'id': 'relic_138', 'count': 0}])
        self.assertEqual(reward_amount(10, modifiers['battle_cash_reward']), 15)
