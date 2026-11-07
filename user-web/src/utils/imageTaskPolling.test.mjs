import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import test from "node:test";
import { createImageTaskPoller } from "./imageTaskPolling.ts";

const rows = (ids, status) => ids.map((id) => ({ id, status }));

test("two rounds of three stay watched when round two finishes first", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const requests = [];
  const state = new Map(rows([1, 2, 3, 4, 5, 6], "queued").map((row) => [row.id, row.status]));
  let resolveFirst;
  let settled = 0;
  const poller = createImageTaskPoller({
    fetchStatuses: async (ids) => {
      requests.push(ids);
      if (requests.length === 1) return new Promise((resolve) => { resolveFirst = resolve; });
      if (requests.length === 2) return [...rows([1, 2, 3], "running"), ...rows([4, 5, 6], "succeeded")];
      return rows(ids, "succeeded");
    },
    onUpdates: (updates) => updates.forEach((row) => state.set(row.id, row.status)),
    onSettled: () => { settled++; },
  });
  t.after(() => poller.dispose());

  poller.watch([1, 2, 3]);
  t.mock.timers.tick(1600);
  poller.watch([4, 5, 6]);
  t.mock.timers.tick(3200);
  assert.deepEqual(requests, [[1, 2, 3]], "a slow response must not overlap another request");
  resolveFirst(rows([1, 2, 3], "running"));
  await setImmediate();

  t.mock.timers.tick(1600);
  await setImmediate();
  assert.deepEqual(requests[1], [1, 2, 3, 4, 5, 6]);
  assert.deepEqual([...state.values()], ["running", "running", "running", "succeeded", "succeeded", "succeeded"]);

  t.mock.timers.tick(1600);
  await setImmediate();
  assert.deepEqual(requests[2], [1, 2, 3], "finishing round two must not stop round one");
  assert.ok([...state.values()].every((status) => status === "succeeded"));
  assert.equal(settled, 2);
  t.mock.timers.tick(10000);
  assert.equal(requests.length, 3, "stop only when every watched task has finished");

  poller.watch([7]);
  t.mock.timers.tick(1600);
  await setImmediate();
  assert.deepEqual(requests[3], [7], "regeneration restarts polling after the queue is empty");
});

test("network errors and partial responses keep missing tasks queued", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const requests = [];
  const poller = createImageTaskPoller({
    fetchStatuses: async (ids) => {
      requests.push(ids);
      if (requests.length === 1) throw new Error("offline");
      if (requests.length === 2) return rows([1], "failed");
      return rows(ids, "refunded");
    },
    onUpdates: () => {},
    onSettled: () => {},
  });
  t.after(() => poller.dispose());
  poller.watch([1, 2, 3]);
  for (let i = 0; i < 3; i++) {
    t.mock.timers.tick(1600);
    await setImmediate();
  }
  assert.deepEqual(requests, [[1, 2, 3], [1, 2, 3], [2, 3]]);
  t.mock.timers.tick(1600);
  assert.equal(requests.length, 3);
});

test("loaded tasks are deduplicated and chunked to the 200-ID API limit", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const requests = [];
  const poller = createImageTaskPoller({
    fetchStatuses: async (ids) => { requests.push(ids); return rows(ids, "succeeded"); },
    onUpdates: () => {},
    onSettled: () => {},
  });
  t.after(() => poller.dispose());
  poller.watch(Array.from({ length: 405 }, (_, i) => i + 1));
  poller.watch([1, 2, 3]);
  t.mock.timers.tick(1600);
  await setImmediate();
  assert.deepEqual(requests.map((ids) => ids.length), [200, 200, 5]);
  assert.equal(new Set(requests.flat()).size, 405);
});

test("deleted tasks and responses after unmount cannot update the page", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let resolveResponse;
  const received = [];
  const poller = createImageTaskPoller({
    fetchStatuses: () => new Promise((resolve) => { resolveResponse = resolve; }),
    onUpdates: (updates) => received.push(...updates),
    onSettled: () => {},
  });
  poller.watch([1, 2]);
  t.mock.timers.tick(1600);
  poller.unwatch([1]);
  resolveResponse(rows([1, 2], "running"));
  await setImmediate();
  assert.deepEqual(received, rows([2], "running"));
  t.mock.timers.tick(1600);
  poller.dispose();
  resolveResponse(rows([2], "succeeded"));
  await setImmediate();
  assert.deepEqual(received, rows([2], "running"));
});
