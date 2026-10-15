import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from fulcrum.map_catalog import TemplateCatalog
from fulcrum.map_model import TemplateMatch
from fulcrum.vision_geometry import Circle, refine_node_positions
from fulcrum.vision_icons import IconMatcher
from fulcrum.vision_layer import recognize_layer
from fulcrum.vision_node_text import decode_label_sheet, label_crop

ROOT = Path(__file__).resolve().parents[1]
LABELS = json.loads((ROOT/'data/vision_labels.json').read_text(encoding='utf-8'))['nodeTypes']


class VisionEvidenceTests(unittest.TestCase):
    def test_blank_header_has_no_layer_or_fabricated_confidence(self):
        result = recognize_layer(np.zeros((720,1280,3),np.uint8))
        self.assertIsNone(result.floor)
        self.assertIsNone(result.area)
        self.assertEqual(result.confidence, 0)

    def test_whole_markers_survive_small_bracket_fragments(self):
        with np.load(ROOT/'assets/vision/layers/markers.npz') as atlas:
            for label in ('I','II','III','IV','V','VI','treehole'):
                key = next(key for key in atlas.files if key.startswith(label+'_'))
                mask = atlas[key]
                mask = cv2.resize(mask,(round(mask.shape[1]*21/mask.shape[0]),21),interpolation=cv2.INTER_AREA)
                image = np.zeros((1152,2048,3),np.uint8)
                image[65:86,980:980+mask.shape[1]][mask>100]=(0,210,255)
                self.assertEqual(recognize_layer(image).label,label)

    def test_grid_refinement_uses_connector_consensus_and_keeps_topology(self):
        template = TemplateCatalog().candidates('main',3)[0]
        match = TemplateMatch(template,330,130,101,105,1,1,len(template.occupied_slots),0,1)
        slots = [(0,0),(2,1),(4,3)]
        # Use actual slots spanning the layout rather than arbitrary dense points.
        slots = [min(template.occupied_slots,key=lambda s: abs(s[0]-x)+abs(s[1]-y)) for x,y in slots]
        circles = [Circle(332+col*100,140+row*100,8,'connector') for col,row in slots]
        circles += [Circle(200,200,28,'hough')]
        refined, info = refine_node_positions(match,np.zeros((720,1280,3),np.uint8),circles)
        self.assertTrue(info['refined'])
        self.assertLess(info['residualAfterPx'],.01)
        self.assertEqual(refined.template, template)
        self.assertAlmostEqual(refined.step_y,100)

    def test_approximate_text_proposes_but_does_not_confirm_a_category(self):
        tsv='5\t1\t1\t1\t1\t1\t10\t20\t100\t20\t94\t未知的谁秘\n'
        result=decode_label_sheet(tsv,{'a':{'top':0,'bottom':80,'box':[0,0,100,20]}},LABELS)['a']
        self.assertIsNone(result['categoryId'])
        self.assertEqual(result['candidateCategoryId'],'unknown_mystery')

    def test_short_landmark_candidate_requires_image_confirmation(self):
        tsv='5\t1\t1\t1\t1\t1\t10\t20\t60\t20\t56\t羽晤点\n'
        result=decode_label_sheet(tsv,{'a':{'top':0,'bottom':80,'box':[0,0,100,20]}},LABELS)['a']
        self.assertIsNone(result['categoryId'])
        self.assertEqual(result['candidateCategoryId'], 'node_type_018')

    def test_distinctive_prefix_only_proposes_a_category(self):
        tsv='5\t1\t1\t1\t1\t1\t10\t20\t100\t20\t60\t曲折更这\n'
        result=decode_label_sheet(tsv,{'a':{'top':0,'bottom':80,'box':[0,0,100,20]}},LABELS)['a']
        self.assertIsNone(result['categoryId'])
        self.assertEqual(result['candidateCategoryId'], 'node_type_014')
        self.assertEqual(result['matchKind'], 'prefix')

    def test_exact_ordinary_text_is_more_trusted_than_similar_unknown_labels(self):
        rows={'a':{'top':0,'bottom':80,'box':[0,0,100,20]}}
        for text, expected in [('曲折密道', 'node_type_014'), ('未知的凶戾', None)]:
            tsv=f'5\t1\t1\t1\t1\t1\t10\t20\t100\t20\t70\t{text}\n'
            self.assertEqual(decode_label_sheet(tsv, rows, LABELS)['a']['categoryId'], expected)

    def test_relaxed_text_crop_recovers_shift_without_treating_it_as_recognized(self):
        image=np.full((250,360,3),20,np.uint8)
        cv2.putText(image,'ABCD',(130,137),cv2.FONT_HERSHEY_SIMPLEX,.6,(240,240,240),2)
        crop=label_crop(image,(170,120),120,(0,0,360,250),relaxed=True)
        self.assertIsNotNone(crop)

    def test_labeled_node_cannot_take_the_small_connector_shortcut(self):
        matcher=IconMatcher()
        image=np.zeros((220,260,3),np.uint8)
        with patch.object(matcher,'_empty_score',return_value=1.), patch.object(matcher,'_score',return_value=.2):
            chosen,_=matcher.classify_node(image,(130,110),100,[],has_label=True)
        self.assertIsNone(chosen)

    def test_contrast_only_ring_cannot_veto_a_clear_connector(self):
        matcher = IconMatcher()
        image = np.zeros((220, 260, 3), np.uint8)
        circles = [Circle(130, 110, 8, 'connector'), Circle(130, 110, 32, 'contrast')]
        with patch.object(matcher, '_empty_score', return_value=1.):
            chosen, _ = matcher.classify_node(image, (130, 110), 100, circles)
        self.assertEqual(chosen.id, 'node_type_020')

    def test_layout_text_and_color_anchors_are_not_evidence_of_a_clearing(self):
        matcher = IconMatcher()
        image = np.zeros((220, 260, 3), np.uint8)
        for source in ('label', 'color'):
            self.assertLess(matcher._empty_score(image, (130, 110), [Circle(130, 110, 0, source)]), .72)


if __name__=='__main__':
    unittest.main()
