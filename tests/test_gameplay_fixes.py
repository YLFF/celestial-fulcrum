from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fulcrum.component_box import add_component
from fulcrum.manual_map import create_manual_map
from fulcrum.map_catalog import TemplateCatalog
from fulcrum.playtime_state import new_playtime, rebuild_derived, merge_map_observation, update_node
from fulcrum.service.store import RunStore
from fulcrum.service.updates import apply_commands
from fulcrum.vision_node_text import decode_label_sheet


class GameplayFixTests(unittest.TestCase):
    def test_mechanist_rewards_are_independent_of_hope_payment(self):
        state = new_playtime('mechanist-rewards')
        hope, capacity = state['resources']['hope'], state['componentBox']['capacity']
        apply_commands(state, [{'type': 'operatorAdd', 'name': '机械师', 'recordOnly': True,
                                'settleRewards': True, 'instanceId': 'mechanist'}])
        self.assertEqual(state['resources']['hope'], hope)
        self.assertEqual(state['componentBox']['capacity'], capacity + 2)
        apply_commands(state, [{'type': 'operatorPromote', 'instanceId': 'mechanist', 'recordOnly': True,
                                'settleRewards': True}])
        self.assertEqual(state['resources']['hope'], hope)
        self.assertEqual(sum(row['componentId'] == 'component_023' for row in state['componentBox']['items']), 1)
        previous = deepcopy(state)
        apply_commands(state, [{'type': 'operatorPromote', 'instanceId': 'mechanist', 'recordOnly': True,
                                'settleRewards': True}])
        self.assertEqual(state, previous)

    def test_direct_promoted_mechanist_gets_both_rewards_but_support_does_not(self):
        for source, expected in [('normal', 2), ('temporary', 2), ('emergency', 0)]:
            state = new_playtime('direct-recruit')
            apply_commands(state, [{'type': 'operatorRemove', 'instanceId': state['operators'][0]['instanceId']},
                                   {'type': 'operatorAdd', 'name': '机械师', 'source': source, 'elite': 2,
                                    'recordOnly': True, 'settleRewards': True}])
            self.assertEqual(state['componentBox']['capacity'], 8 + expected)
            self.assertEqual(sum(row['componentId'] == 'component_023' for row in state['componentBox']['items']), bool(expected))

    def test_thin_bag_acquisition_is_once_and_removal_does_not_retract(self):
        state = new_playtime('thin-bag')
        command = {'type': 'relics', 'items': [{'id': 'relic_198'}]}
        apply_commands(state, [command])
        self.assertEqual(state['componentBox']['capacity'], 12)
        apply_commands(state, [command])
        apply_commands(state, [{'type': 'relics', 'items': []}])
        self.assertEqual(state['componentBox']['capacity'], 12)
        apply_commands(state, [command])
        self.assertEqual(state['componentBox']['capacity'], 16)

    def test_first_floor_multiple_fixed_shops_resolve_from_template(self):
        template = next(row for row in TemplateCatalog().candidates('main', 1) if row.id == 'floor-1-vertical-fork')
        observation = {'success': True, 'area': 'main', 'floor': 1, 'templateId': template.id,
                       'nodes': [{'id': template.coord(slot).key, 'coord': [template.coord(slot).x, template.coord(slot).y],
                                  'slot': list(slot), 'categoryId': 'start' if slot == template.start_slot else 'unknown_mystery',
                                  'templateHint': template.fixed_nodes.get(slot), 'visibility': 'hidden', 'marks': []}
                                 for slot in template.occupied_slots],
                       'edges': [[template.coord(a).key, template.coord(b).key] for a, b in template.edges]}
        state = new_playtime('fixed-shops')
        instance = merge_map_observation(state, 'I', observation)
        self.assertEqual(instance['nodes']['-1,1']['resolvedCategoryId'], 'node_type_004')
        self.assertEqual(instance['nodes']['2,0']['resolvedCategoryId'], 'node_type_004')
        instance['nodes']['-1,1']['resolvedCategoryId'] = None
        rebuild_derived(state)
        self.assertEqual(instance['nodes']['-1,1']['resolvedCategoryId'], 'node_type_004')

    def test_treehole_peace_guardian_uses_treehole_pool_and_outpost_condition(self):
        state = new_playtime('guardian')
        instance = create_manual_map(state, 'III-treehole', 'treehole-06')
        def ids():
            return {row['id'] for row in instance['prediction']['encounterPool']['candidates']}
        self.assertNotIn('encounter_020', ids())
        update_node(state, 'III-treehole', '2,-2', category_id='node_type_019')
        self.assertIn('encounter_020', ids())
        from fulcrum.node_scoring import SnapshotScorer
        from fulcrum.playtime_route import route_inputs
        instance['actionPoints'] = 3
        result, inputs = route_inputs(state, 'III-treehole')
        scorer = SnapshotScorer(result['nodes'], inputs['scoringContext'], inputs)
        probability = next(row['probability'] for row in scorer.event_distribution['events'] if row['eventId'] == 'encounter_020')
        self.assertGreater(probability, 0)
        update_node(state, 'III-treehole', '2,-2', completion='completed')
        self.assertIn('encounter_020', ids())

    def test_controller_eligibility_survives_sale_but_not_undo_before_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            current = store.create('controller-history')
            current = store.update(current['runId'], current['revision'], lambda state: apply_commands(state, [
                {'type': 'componentAdd', 'componentId': 'component_012', 'instanceId': 'controller'}]), map_update=True)
            current = store.update(current['runId'], current['revision'], lambda state: apply_commands(state, [
                {'type': 'componentRemove', 'instanceId': 'controller'}]))
            self.assertTrue(current['state']['acquisitionFacts']['controllerEverObtained'])
            pool = current['state']['areas']['IV']['encounterPool']
            self.assertEqual(next(row for row in pool if row['id'] == 'encounter_010')['eligibility'], 'possible')
            current = store.undo(current['runId'], current['revision'])
            self.assertFalse(current['state'].get('acquisitionFacts', {}).get('controllerEverObtained', False))
            current = store.redo(current['runId'], current['revision'])
            self.assertTrue(current['state']['acquisitionFacts']['controllerEverObtained'])

    def test_old_save_recovers_controller_fact_from_past_not_future(self):
        old = new_playtime('legacy-controller')
        observed = deepcopy(old)
        add_component(observed['componentBox'], 'component_012')
        old['_serviceHistory'] = {'past': [observed], 'future': []}
        with tempfile.TemporaryDirectory() as directory:
            current = RunStore(directory).restore(old)
            self.assertTrue(current['state']['acquisitionFacts']['controllerEverObtained'])
        old['_serviceHistory'] = {'past': [], 'future': [observed]}
        with tempfile.TemporaryDirectory() as directory:
            current = RunStore(directory).restore(old)
            self.assertFalse(current['state'].get('acquisitionFacts', {}).get('controllerEverObtained', False))

    def test_rare_ferocity_glyph_substitution_keeps_confidence_threshold(self):
        labels = json.loads((Path(__file__).resolve().parents[1] / 'data/vision_labels.json').read_text(encoding='utf-8'))['nodeTypes']
        rows = {'a': {'top': 0, 'bottom': 80, 'box': [0, 0, 100, 20]}}
        for text, confidence, expected in [('未知的凶导', 82, 'unknown_ferocity'), ('未知的凶导', 74, None),
                                           ('凶导', 99, None), ('未知的凶', 99, None), ('未知的凶A', 99, None)]:
            tsv = f'5\t1\t1\t1\t1\t1\t0\t20\t100\t20\t{confidence}\t{text}\n'
            self.assertEqual(decode_label_sheet(tsv, rows, labels)['a']['categoryId'], expected)

    def test_soil_without_a_matching_deformation_sample_remains_unconfirmed(self):
        import numpy as np
        from fulcrum.map_model import Coord, MapNode
        from fulcrum.vision_dystopia import recognize_visual_nodes

        image = np.zeros((200, 200, 3), np.uint8)
        node = MapNode(Coord(0, 0), (0, 0), (100, 100), category_id='node_type_001')
        observation = {'active': True, 'ideologyId': 'dystopia_008', 'sourceStatus': 'not_applicable'}
        with patch('fulcrum.vision_dystopia.soil_texture_scores', return_value=[]), \
                patch('fulcrum.vision_icons.IconMatcher._score', return_value=.8):
            result = recognize_visual_nodes(image, [node], 100, observation)
        self.assertIsNone(result['nodeEvidence']['0,0']['affected'])

