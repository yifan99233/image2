import test from 'node:test';
import assert from 'node:assert/strict';
import { getImageTaskStatusLabel } from './imageTaskStatus.ts';

test('expired successful output is labelled expired without changing billing status', () => {
  const task = {status: 'succeeded', progress_stage: 'succeeded', output_expired_at: '2026-10-19T00:00:00Z'};
  assert.equal(getImageTaskStatusLabel(task, {succeeded: '生成成功'}), '图片已过期');
  assert.equal(task.status, 'succeeded');
});
test('unexpired success keeps the existing label', () => {
  assert.equal(getImageTaskStatusLabel({status: 'succeeded', progress_stage: 'succeeded'}, {succeeded: '生成成功'}), '生成成功');
});
