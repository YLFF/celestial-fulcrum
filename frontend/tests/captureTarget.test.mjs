import test from 'node:test';
import assert from 'node:assert/strict';
import { captureTarget, rememberedCaptureWindow } from '../src/captureTarget.js';

const target = { windowId: '0x12', pid: 345, process: 'Arknights.exe', title: 'Game', minimized: false };
test('only the capture target is remembered, never authorization', () => {
  assert.deepEqual(captureTarget({ ...target, consent: true, authorizationId: 'secret' }),
    { windowId: '0x12', pid: 345, process: 'Arknights.exe' });
  assert.equal(rememberedCaptureWindow([target], captureTarget(target)), target);
});
test('missing, minimized, ambiguous or reused processes require selection', () => {
  for (const rows of [[], [{ ...target, minimized: true }], [{ ...target, pid: 678 }], [{ ...target, process: 'Other.exe' }],
    [{ ...target, windowId: '0x14' }, { ...target, windowId: '0x15' }]]) {
    assert.equal(rememberedCaptureWindow(rows, captureTarget(target)), null);
  }
});
test('a single replacement window for the same live process can be reused', () => {
  const replacement = { ...target, windowId: '0x13' };
  assert.equal(rememberedCaptureWindow([replacement], captureTarget(target)), replacement);
});
