from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from fulcrum.playtime_state import merge_map_observation
from fulcrum.service.app import create_app
from fulcrum.service.assets import AssetStore
from fulcrum.service.jobs import JobManager
from fulcrum.service.store import RunStore, atomic_json
from tests.test_playtime_prediction import chain_map


class SnapshotHistoryReviewTests(unittest.TestCase):
    def test_export_restore_preserves_both_history_directions_under_new_id(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(Path(directory) / 'runs')
            store.create('original')
            store.update('original', 1, lambda state: merge_map_observation(state, 'III', chain_map(3)), map_update=True)
            store.update('original', 2, lambda state: merge_map_observation(state, 'IV', chain_map(4)), map_update=True)
            store.undo('original', 3)
            original_bytes = store.path('original').read_bytes()
            source = store.export('original')
            before = deepcopy(source)
            copied = store.restore(source, run_id='copy')
            self.assertEqual(copied['history']['undoCount'], 1)
            self.assertEqual(copied['history']['redoCount'], 1)
            self.assertEqual(store.redo('copy', 1)['state']['currentAreaKey'], 'IV')
            self.assertEqual(store.undo('copy', 2)['state']['currentAreaKey'], 'III')
            self.assertIsNone(store.undo('copy', 3)['state']['currentAreaKey'])
            self.assertEqual(store.redo('copy', 4)['state']['currentAreaKey'], 'III')
            self.assertEqual(source, before)
            self.assertEqual(store.path('original').read_bytes(), original_bytes)
            self.assertTrue(all(row['runId'] == 'copy' for rows in store.export('copy')['_serviceHistory'].values() for row in rows))

    def test_invalid_history_is_rejected_before_creating_import(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            store.create('original')
            store.update('original', 1, lambda state: state['resources'].update(hope=8), map_update=True)
            for change in ('wrong-id', 'invalid-state', 'nested-history'):
                source = store.export('original')
                row = source['_serviceHistory']['past'][0]
                if change == 'wrong-id':
                    row['runId'] = 'unrelated'
                elif change == 'invalid-state':
                    row['resources']['hope'] = -1
                else:
                    row['_serviceHistory'] = {'past': [], 'future': []}
                with self.subTest(change=change), self.assertRaises(ValueError):
                    store.restore(source, run_id='invalid')
                self.assertFalse(store.path('invalid').exists())

    def test_api_export_restore_history_round_trip(self):
        with tempfile.TemporaryDirectory() as directory, TestClient(create_app(directory)) as client:
            client.headers['X-Fulcrum-Token'] = client.get('/api/session').json()['token']
            store = client.app.state.store
            store.create('export-api')
            store.update('export-api', 1, lambda state: state['resources'].update(hope=11), map_update=True)
            exported = client.get('/api/runs/export-api/export')
            self.assertEqual(exported.status_code, 200)
            restored = client.post('/api/runs/restore', json={'state': exported.json(), 'runId': 'import-api'})
            self.assertEqual(restored.status_code, 201, restored.text)
            self.assertTrue(restored.json()['history']['canUndo'])
            undone = client.post('/api/runs/import-api/undo', json={'expectedRevision': 1})
            self.assertEqual(undone.status_code, 200, undone.text)
            self.assertEqual(undone.json()['state']['resources']['hope'], 6)


class JobRecoveryReviewTests(unittest.TestCase):
    def test_polling_checks_latest_revision_without_rebuilding_maps(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'runs')
            store.create('polling')
            store.update('polling', 1, lambda state: merge_map_observation(state, 'III', chain_map(3)), map_update=True)
            manager = JobManager(root / 'jobs', store, AssetStore(root / 'images'))
            job_id = 'a' * 32
            atomic_json(manager.path(job_id), {'jobId': job_id, 'runId': 'polling',
                        'sourceRevision': 2, 'status': 'completed', 'result': {}})
            try:
                for revision in (2, 3):
                    if revision == 3:
                        store.update('polling', 2, lambda state: state['resources'].update(hope=8))
                    before = store.path('polling').read_bytes()
                    with patch.object(store, 'load', side_effect=AssertionError('full load during polling')), \
                            patch('fulcrum.service.store.rebuild_derived') as rebuild:
                        result = manager.get(job_id)
                        self.assertEqual(result['currentRevision'], revision)
                        self.assertEqual(result['stale'], revision != 2)
                        rebuild.assert_not_called()
                    self.assertEqual(store.path('polling').read_bytes(), before)
                store.path('polling').unlink()
                result = manager.get(job_id)
                self.assertIsNone(result['currentRevision'])
                self.assertTrue(result['stale'])
            finally:
                manager.close()

    def test_revision_metadata_is_validated_and_legacy_revision_defaults_to_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory)
            store.create('revision')
            valid = {'runId': 'revision', '_serviceRevision': 1}
            for changes in ({'_serviceRevision': True}, {'_serviceRevision': -1},
                            {'_serviceRevision': '1'}, {'runId': 'different'}):
                with self.subTest(changes=changes):
                    atomic_json(store.path('revision'), {**valid, **changes})
                    with self.assertRaises(ValueError):
                        store.get_revision('revision')
            atomic_json(store.path('revision'), [])
            with self.assertRaises(ValueError):
                store.get_revision('revision')
            atomic_json(store.path('revision'), {'runId': 'revision'})
            self.assertEqual(store.get_revision('revision'), 0)

    def test_malformed_old_job_files_do_not_prevent_service_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = root / 'jobs'
            jobs.mkdir()
            bad_json = jobs / ('a' * 32 + '.json')
            bad_json.write_text('{incomplete', encoding='utf-8')
            atomic_json(jobs / ('b' * 32 + '.json'), [])
            atomic_json(jobs / ('c' * 32 + '.json'), {'jobId': 'd' * 32, 'status': 'running'})
            atomic_json(jobs / ('e' * 32 + '.json'), {'jobId': 'e' * 32, 'status': 'running'})
            with self.assertLogs('fulcrum.service.jobs', level='WARNING') as logs:
                manager = JobManager(jobs, RunStore(root / 'runs'), AssetStore(root / 'images'))
            try:
                self.assertEqual(len(logs.output), 3)
                self.assertEqual(json.loads((jobs / ('e' * 32 + '.json')).read_text(encoding='utf-8'))['status'], 'interrupted')
                self.assertEqual(bad_json.read_text(encoding='utf-8'), '{incomplete')
            finally:
                manager.close()
