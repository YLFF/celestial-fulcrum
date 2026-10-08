import { test } from 'node:test';
import assert from 'node:assert/strict';
import { emptyDystopia, setCoverage, coverageStatus, dystopiaFromObservation } from '../src/dystopia.js';

test('per-node coverage keeps holes and clears a removed ideal source', () => {
  const value = { ...emptyDystopia(), active: true, affectedNodeIds: ['0,0', '2,0'], idealSourceNodeId: '2,0' };
  assert.equal(coverageStatus(value, '1,0'), 'outside');
  const next = setCoverage(value, ['2,0'], 'unknown');
  assert.equal(next.idealSourceNodeId, null);
  assert.deepEqual(next.affectedNodeIds, ['0,0']);
  assert.deepEqual(next.uncertainNodeIds, ['2,0']);
  assert.deepEqual(value.affectedNodeIds, ['0,0', '2,0']);
});

test('candidate import preserves old confirmation on uncertain evidence and cannot give fertile soil a source', () => {
  const previous = { ...emptyDystopia(), active: true, ideologyId: 'dystopia_005', affectedNodeIds: ['0,0'] };
  const observation = { nodes: [{ id: '0,0' }, { id: '1,0' }], dystopiaObservation: { active: true,
    ideologyId: 'dystopia_005', nodeEvidence: { '1,0': { affected: false } } } };
  assert.deepEqual(dystopiaFromObservation(observation, previous).affectedNodeIds, ['0,0']);
  observation.dystopiaObservation = { active: true, ideologyId: 'dystopia_008', idealSourceNodeId: '1,0' };
  assert.equal(dystopiaFromObservation(observation).idealSourceNodeId, null);
});

test('uncertain refresh retains confirmed policy and completed source only on the same map', () => {
  const previous = { ...emptyDystopia(), active: true, ideologyId: 'dystopia_005', policyId: 'dystopia_012',
    affectedNodeIds: ['0,0'], idealSourceNodeId: '0,0' };
  const observation = { nodes: [{ id: '0,0' }], dystopiaObservation: { active: true, ideologyId: 'dystopia_005' } };
  assert.equal(dystopiaFromObservation(observation, previous).idealSourceNodeId, '0,0');
  assert.equal(dystopiaFromObservation(observation, previous).policyId, 'dystopia_012');
  observation.nodes = [{ id: '1,0' }];
  assert.equal(dystopiaFromObservation(observation, previous).idealSourceNodeId, null);
});
