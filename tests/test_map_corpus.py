import json
import os
from pathlib import Path
import unittest

from fulcrum.vision_pipeline import MapRecognizer


SAMPLES = Path(os.environ.get('FULCRUM_VISION_SAMPLES', Path(__file__).resolve().parents[1] / 'samples/maps'))


@unittest.skipUnless((SAMPLES / 'manifest.json').is_file(), 'local screenshot regression corpus unavailable')
class MapCorpusTests(unittest.TestCase):
    def test_complete_maps_partial_maps_categories_and_marks(self):
        manifest = json.loads((SAMPLES / 'manifest.json').read_text(encoding='utf-8'))
        recognizer = MapRecognizer()
        for case in manifest['samples']:
            with self.subTest(file=case['file']):
                result = recognizer.recognize(SAMPLES / case['file'], difficulty=15)
                self.assertEqual(result.success, case['expectMap'])
                if not case['expectMap']:
                    self.assertFalse(result.nodes)
                    continue
                self.assertEqual(result.template_id, case['templateId'])
                nodes = {node.coord.key: node for node in result.nodes}
                if case['file'] == 'desktop_floor4_two_exits.png':
                    self.assertEqual(nodes['-1,1'].category_id, 'node_type_011')
                    self.assertIn('node_mark_004', [mark['id'] for mark in nodes['-5,0'].marks])
                if case['file'] == 'attachment_06.jpg':
                    self.assertIn('node_mark_001', [mark['id'] for mark in nodes['3,0'].marks])
