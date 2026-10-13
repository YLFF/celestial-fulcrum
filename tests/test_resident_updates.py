from copy import deepcopy
import unittest

from fulcrum.manual_map import create_manual_map, template_observation, templates_for_area
from fulcrum.node_scoring import SnapshotScorer
from fulcrum.playtime_route import route_inputs
from fulcrum.playtime_state import merge_map_observation, new_playtime, update_node, set_player_position
from fulcrum.residents import resident_active


class ResidentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.state = new_playtime('resident-updates', squad_id='squad_014')
        self.template = templates_for_area('II')[0]
        self.instance = create_manual_map(self.state, 'II', self.template.id, action_points=4)
        self.ids = [key for key, node in self.instance['nodes'].items() if node['resolvedCategoryId'] is None]

    def observation(self, marked=()):
        observation = template_observation(self.template, 'II')
        for row in observation['nodes']:
            if row['id'] in self.ids:
                row.update(categoryId='node_type_020', visibility='revealed', marks=[
                    {'id': 'node_mark_001', 'status': 'confirmed'}] if row['id'] in marked else [])
        return observation

    def test_completed_outpost_clears_current_map_only_and_not_other_marks(self):
        other = create_manual_map(self.state, 'IV', templates_for_area('IV')[0].id, action_points=4)
        other_key = next(key for key, node in other['nodes'].items() if node['resolvedCategoryId'] is None)
        update_node(self.state, 'IV', other_key, category_id='node_type_020', confirmed_mark_ids=['node_mark_001'])
        update_node(self.state, 'II', self.ids[0], category_id='node_type_020',
                    confirmed_mark_ids=['node_mark_001', 'node_mark_007'])
        update_node(self.state, 'II', self.ids[1], category_id='node_type_019', completion='completed')
        self.assertEqual(self.instance['nodes'][self.ids[0]]['confirmedMarkIds'], ['node_mark_007'])
        self.assertTrue(resident_active(other['nodes'][other_key]))
        merge_map_observation(self.state, 'II', self.observation([self.ids[0]]))
        self.assertNotIn('node_mark_001', self.instance['nodes'][self.ids[0]]['confirmedMarkIds'])

    def test_new_resident_on_completed_clearing_scores_and_can_be_cleared_twice(self):
        key = self.ids[0]
        node = update_node(self.state, 'II', key, category_id='node_type_006', encounter_id='encounter_001', completion='completed')
        for _ in range(2):
            merge_map_observation(self.state, 'II', self.observation([key]))
            self.assertTrue(resident_active(node))
            game_map, route_state = route_inputs(self.state, 'II')
            self.assertNotIn(key, route_state['completedNodes'])
            self.assertEqual(next(row for row in game_map['nodes'] if row['id'] == key)['categoryId'], 'node_type_020')
            scorer = SnapshotScorer(game_map['nodes'], route_state['scoringContext'], route_state)
            self.assertGreater(scorer.values[key]['points'], 0)
            update_node(self.state, 'II', key, completion='completed')
            self.assertFalse(resident_active(node))
            self.assertEqual((node['resolvedCategoryId'], node['encounterId'], node['completedCategoryId']),
                             ('node_type_006', 'encounter_001', 'node_type_006'))
            self.assertIn(key, route_inputs(self.state, 'II')[1]['completedNodes'])

    def test_merge_refreshes_resident_positions_without_inventing_completions(self):
        first, second = self.ids[:2]
        update_node(self.state, 'II', first, category_id='node_type_020', confirmed_mark_ids=['node_mark_001'])
        merge_map_observation(self.state, 'II', self.observation([second]))
        self.assertFalse(resident_active(self.instance['nodes'][first]))
        self.assertTrue(resident_active(self.instance['nodes'][second]))
        self.assertEqual(self.instance['nodes'][first]['completion'], 'pending')
        partial = self.observation()
        next(row for row in partial['nodes'] if row['id'] == second).update(categoryId=None, visibility='unknown')
        merge_map_observation(self.state, 'II', partial)
        self.assertTrue(resident_active(self.instance['nodes'][second]))

    def test_current_resident_is_completed_without_completing_overridden_event(self):
        key = self.ids[0]
        node = update_node(self.state, 'II', key, category_id='node_type_006', encounter_id='encounter_001',
                           confirmed_mark_ids=['node_mark_001'])
        set_player_position(self.instance, key)
        self.assertEqual(node['completedCategoryId'], 'node_type_021')
        self.assertNotIn('node_mark_001', node['confirmedMarkIds'])

    def test_recognized_position_preserves_resident_completion_when_mark_already_disappeared(self):
        key = self.ids[0]
        node = update_node(self.state, 'II', key, category_id='node_type_006', encounter_id='encounter_001',
                           confirmed_mark_ids=['node_mark_001'])
        observation = self.observation()
        observation['playerPositionObservation'] = {'status': 'recognized', 'nodeId': key}
        merge_map_observation(self.state, 'II', observation)
        self.assertEqual(node['completedCategoryId'], 'node_type_021')
        self.assertFalse(resident_active(node))
        event = next(row for row in self.state['globalEncounterPool'] if row['id'] == 'encounter_001')
        self.assertEqual(event['completedCount'], 0)

    def test_fixed_multiple_exits_are_known_even_when_icons_are_unknown(self):
        observation = self.observation()
        terminal_ids = {self.template.coord(slot).key for slot in self.template.terminal_slots}
        for row in observation['nodes']:
            if row['id'] in terminal_ids:
                row.update(categoryId='unknown_mystery', visibility='hidden')
        before = deepcopy(observation)
        instance = merge_map_observation(self.state, 'II', observation)
        self.assertTrue(all(instance['nodes'][key]['resolvedCategoryId'] == 'node_type_015' for key in terminal_ids))
        self.assertEqual(observation, before)
