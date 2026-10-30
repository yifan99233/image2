import test from 'node:test';
import assert from 'node:assert/strict';
import { applyMask } from '../src/utils/cutout.ts';

test('cutout preserves source RGB and changes only alpha, including translucent source pixels', () => {
  const source = new Uint8ClampedArray([12, 34, 56, 255, 78, 90, 123, 128, 200, 150, 100, 255]);
  const mask = new Uint8ClampedArray([255, 255, 255, 255, 128, 128, 128, 255, 0, 0, 0, 255]);
  const result = applyMask(source, mask);
  assert.deepEqual([...result], [12, 34, 56, 255, 78, 90, 123, 64, 200, 150, 100, 0]);
  assert.equal(source[7], 128);
});
