from copy import deepcopy
import tempfile
import unittest

import cv2
import numpy as np
from fastapi.testclient import TestClient

from fulcrum.manual_map import create_manual_map, template_options, templates_for_area
from fulcrum.playtime_state import AREA_SPECS, active_instance, merge_map_observation, new_playtime
from fulcrum.opening import opening_action_points
from fulcrum.service.app import create_app
from fulcrum.service.updates import apply_commands


class ManualMapTests(unittest.TestCase):
    def test_every_area_lists_only_its_legal_templates(self):
        for area in AREA_SPECS:
            with self.subTest(area=area):
                rows = template_options(area)
                self.assertTrue(rows)
                self.assertEqual([row['id'] for row in rows], [row.id for row in templates_for_area(area)])
                for row in rows:
                    preview = row['preview']
                    self.assertEqual(len(preview['nodes']), row['nodeCount'])
                    self.assertEqual(preview['playerPosition'], '0,0')
                    self.assertTrue(all(a in preview['nodes'] and b in preview['nodes'] for a, b in preview['edges']))

    def test_only_start_and_terminals_are_confirmed(self):
        for area in AREA_SPECS:
            for template in templates_for_area(area):
                with self.subTest(area=area, template=template.id):
                    state = new_playtime('manual', squad_id='squad_014')
                    instance = create_manual_map(state, area, template.id)
                    terminals = {template.coord(slot).key for slot in template.terminal_slots}
                    for node_id, node in instance['nodes'].items():
                        if node_id == '0,0':
                            self.assertEqual(node['resolvedCategoryId'], 'start')
                            self.assertEqual(node['completion'], 'completed')
                        elif node_id in terminals:
                            self.assertIn(node['resolvedCategoryId'], ('node_type_015', 'node_type_003'))
                            self.assertEqual(node['completion'], 'pending')
                        else:
                            self.assertIsNone(node['observedCategoryId'])
                            self.assertIsNone(node['resolvedCategoryId'])
                            self.assertIsNone(node['templateHint'])
                            self.assertEqual(node['completion'], 'pending')
                    self.assertEqual(instance['mapOrigin'], 'manual')

    def test_existing_map_requires_confirmation_and_keeps_old_instance(self):
        state = new_playtime('manual', squad_id='squad_014')
        first, second = templates_for_area('II')[:2]
        create_manual_map(state, 'II', first.id, action_points=5)
        original = deepcopy(state)
        with self.assertRaisesRegex(ValueError, '本层已有地图'):
            create_manual_map(state, 'II', second.id)
        self.assertEqual(state, original)
        replacement = create_manual_map(state, 'II', second.id, replace_existing=True)
        self.assertEqual(len(state['areas']['II']['instances']), 2)
        self.assertEqual(state['areas']['II']['instances'][0], original['areas']['II']['instances'][0])
        self.assertEqual(active_instance(state, 'II'), replacement)

    def test_bad_area_template_and_action_points_do_not_mutate_state(self):
        state = new_playtime('manual', squad_id='squad_014')
        before = deepcopy(state)
        for area, template, points in [('VII', 'invalid', None), ('II', templates_for_area('I')[0].id, None),
                                      ('II', templates_for_area('II')[0].id, -1),
                                      ('II', templates_for_area('II')[0].id, True)]:
            with self.subTest(area=area, points=points), self.assertRaises(ValueError):
                create_manual_map(state, area, template, action_points=points)
            self.assertEqual(state, before)

    def test_normal_node_edits_work_after_manual_creation(self):
        state = new_playtime('manual', squad_id='squad_014')
        instance = create_manual_map(state, 'II', templates_for_area('II')[0].id, action_points=4)
        node_id = next(node_id for node_id, node in instance['nodes'].items() if node['resolvedCategoryId'] is None)
        apply_commands(state, [{'type': 'node', 'areaKey': 'II', 'nodeId': node_id,
                               'changes': {'categoryId': 'node_type_006', 'encounterId': 'encounter_001', 'visibility': 'revealed'}}])
        self.assertEqual(instance['nodes'][node_id]['resolvedCategoryId'], 'node_type_006')
        self.assertEqual(instance['nodes'][node_id]['encounterId'], 'encounter_001')

    def test_first_floor_uses_opening_action_points(self):
        state = new_playtime('manual', squad_id='squad_014')
        instance = create_manual_map(state, 'I', templates_for_area('I')[0].id)
        self.assertEqual(instance['actionPoints'], opening_action_points(state['opening'], 'I'))

    def test_later_recognition_merges_into_manually_edited_map(self):
        from fulcrum.manual_map import template_observation
        state = new_playtime('manual', squad_id='squad_014')
        template = templates_for_area('II')[0]
        instance = create_manual_map(state, 'II', template.id)
        node_id = next(node_id for node_id, node in instance['nodes'].items() if node['resolvedCategoryId'] is None)
        apply_commands(state, [{'type': 'node', 'areaKey': 'II', 'nodeId': node_id,
            'changes': {'categoryId': 'node_type_006', 'encounterId': 'encounter_001', 'completion': 'completed'}}])
        observation = template_observation(template, 'II')
        next(row for row in observation['nodes'] if row['id'] == node_id).update(categoryId='node_type_020', visibility='revealed')
        merged = merge_map_observation(state, 'II', observation)
        self.assertEqual(len(state['areas']['II']['instances']), 1)
        self.assertEqual(merged['nodes'][node_id]['resolvedCategoryId'], 'node_type_006')
        self.assertEqual(merged['nodes'][node_id]['encounterId'], 'encounter_001')
        self.assertEqual(merged['nodes'][node_id]['completion'], 'completed')


class ManualMapAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.client = self.enterContext(TestClient(create_app(self.temp.name)))
        self.client.headers['X-Fulcrum-Token'] = self.client.get('/api/session').json()['token']
        self.client.post('/api/runs', json={'runId': 'manual-api', 'squadId': 'squad_014'})

    def body(self, area='II', revision=1):
        return {'expectedRevision': revision, 'areaKey': area, 'templateId': templates_for_area(area)[0].id}

    def test_list_requires_auth_and_valid_area(self):
        self.assertEqual(self.client.get('/api/map-templates?areaKey=II', headers={'X-Fulcrum-Token': 'bad'}).status_code, 401)
        self.assertEqual(self.client.get('/api/map-templates?areaKey=VII').status_code, 422)
        data = self.client.get('/api/map-templates?areaKey=II').json()
        self.assertEqual(len(data['templates']), 10)
        self.assertEqual(self.client.get('/api/runs/manual-api').json()['revision'], 1)

    def test_create_is_a_map_update_with_undo_redo_and_no_resource_guess(self):
        def snapshot(state):
            return {key: value for key, value in state.items() if key not in ('_serviceRevision', 'updatedAt')}
        before = self.client.get('/api/runs/manual-api').json()
        response = self.client.post('/api/runs/manual-api/manual-map', json={**self.body(), 'actionPoints': 5})
        self.assertEqual(response.status_code, 200, response.text)
        created = response.json()
        self.assertEqual(created['state']['currentAreaKey'], 'II')
        self.assertEqual(created['state']['resources'], before['state']['resources'])
        self.assertTrue(created['history']['canUndo'])
        reverted = self.client.post('/api/runs/manual-api/undo', json={'expectedRevision': 2})
        self.assertEqual(snapshot(reverted.json()['state']), snapshot(before['state']))
        redone = self.client.post('/api/runs/manual-api/redo', json={'expectedRevision': 3})
        self.assertEqual(snapshot(redone.json()['state']), snapshot(created['state']))

    def test_stale_and_invalid_requests_preserve_existing_map(self):
        response = self.client.post('/api/runs/manual-api/manual-map', json=self.body())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.post('/api/runs/manual-api/manual-map', json=self.body()).status_code, 409)
        self.assertEqual(self.client.post('/api/runs/manual-api/manual-map', json=self.body(revision=2)).status_code, 422)
        self.assertEqual(self.client.post('/api/runs/manual-api/manual-map', json={**self.body(revision=2), 'actionPoints': -1}).status_code, 422)
        self.assertEqual(self.client.get('/api/runs/manual-api').json()['revision'], 2)

    def test_image_reference_must_exist_and_be_opaque(self):
        self.assertEqual(self.client.post('/api/runs/manual-api/manual-map', json={**self.body(), 'assetId': '0' * 32}).status_code, 404)
        self.assertEqual(self.client.post('/api/runs/manual-api/manual-map', json={**self.body(), 'assetId': '../image.png'}).status_code, 422)
        encoded = cv2.imencode('.png', np.zeros((40, 60, 3), dtype=np.uint8))[1].tobytes()
        asset = self.client.post('/api/images', files={'file': ('test.png', encoded)}).json()
        created = self.client.post('/api/runs/manual-api/manual-map', json={**self.body(), 'assetId': asset['assetId']})
        self.assertEqual(created.status_code, 200, created.text)
        instance = active_instance(created.json()['state'], 'II')
        self.assertEqual(instance['sourceAssetId'], asset['assetId'])


if __name__ == '__main__':
    unittest.main()
