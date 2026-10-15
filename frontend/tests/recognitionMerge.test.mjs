import test from 'node:test';
import assert from 'node:assert/strict';
import { recognitionChanges, recognitionReview, mergedRecognitionPreview } from '../src/recognitionMerge.js';

test('blind zone replaces pending observations without reporting category conflicts', () => {
  const previous = { templateId: 't', utopiaId: 'utopia_005', nodes: {
    a: { id: 'a', resolvedCategoryId: 'node_type_006', encounterId: 'event', completion: 'unknown', confirmedMarkIds: [] },
    b: { id: 'b', resolvedCategoryId: 'node_type_011', completion: 'completed', confirmedMarkIds: [] },
  } };
  const observation = { success: true, templateId: 't', edges: [], nodes: [
    { id: 'a', categoryId: 'node_type_020', marks: [], visibility: 'revealed' },
    { id: 'b', categoryId: 'node_type_007', marks: [], visibility: 'revealed' },
  ] };
  assert.deepEqual(recognitionChanges(observation, previous), []);
  assert.deepEqual(recognitionReview(observation, previous), []);
  const preview = mergedRecognitionPreview(observation, previous, {
    nodeChanges: {}, completions: {}, encounters: {}, markChoices: {}, utopiaId: 'utopia_005',
  });
  assert.equal(preview.nodes.a.resolvedCategoryId, 'node_type_020');
  assert.equal(preview.nodes.a.encounterId, null);
  assert.deepEqual(preview.nodes.b, previous.nodes.b);
});
