import assert from "node:assert/strict";
import test from "node:test";
import { File } from "node:buffer";
import { uploadGroupReferences } from "./batchGroupUploads.ts";
const groups = () => [
  {
    id: "A",
    images: Array.from({ length: 6 }, (_, i) => ({
      path: `A/${i}.png`,
      file: new File(["image"], `${i}.png`),
    })),
  },
  { id: "B", images: [{ path: "B/x.png", file: new File(["image"], "x.png") }] },
];
test("uploads use at most four workers and keep reference order despite out-of-order completions", async () => {
  const draft = groups();
  let active = 0,
    max = 0;
  const progress = [];
  const result = await uploadGroupReferences(
    draft,
    5,
    async (file, model) => {
      assert.equal(model, 5);
      max = Math.max(max, ++active);
      await new Promise((resolve) => setTimeout(resolve, file.name === "0.png" ? 20 : 2));
      active--;
      return {
        id: file.name === "x.png" ? 99 : Number(file.name.split(".")[0]) + 1,
        url: file.name,
      };
    },
    new WeakMap(),
    (completed, total) => progress.push([completed, total]),
  );
  assert.equal(max, 4);
  assert.deepEqual(
    result.get("A").map((asset) => asset.id),
    [1, 2, 3, 4, 5, 6],
  );
  assert.equal(result.get("B")[0].id, 99);
  assert.deepEqual(progress.at(-1), [7, 7]);
});
test("a failed upload stops pending work, waits for in-flight files, and retry reuses successful files", async () => {
  const draft = groups(),
    cache = new WeakMap(),
    calls = [];
  let fail = true;
  const upload = async (file) => {
    calls.push(file.name);
    await new Promise((resolve) => setTimeout(resolve, 2));
    if (file.name === "0.png" && fail) throw new Error("upload failed");
    return { id: 1, url: file.name };
  };
  await assert.rejects(
    uploadGroupReferences(draft, 5, upload, cache, () => {}),
    /upload failed/,
  );
  assert.ok(calls.length <= 4);
  const completed = calls.filter((name) => name !== "0.png");
  fail = false;
  const result = await uploadGroupReferences(draft, 5, upload, cache, () => {});
  assert.equal(result.get("A").length, 6);
  for (const name of completed) assert.equal(calls.filter((value) => value === name).length, 1);
  assert.equal(calls.filter((value) => value === "0.png").length, 2);
});
test("cached uploads are scoped to the selected model storage policy", async () => {
  const draft = groups(),
    cache = new WeakMap();
  let count = 0;
  const upload = async () => ({ id: ++count, url: "image" });
  await uploadGroupReferences(draft, 5, upload, cache, () => {});
  assert.equal(count, 7);
  await uploadGroupReferences(draft, 5, upload, cache, () => {});
  assert.equal(count, 7);
  await uploadGroupReferences(draft, 6, upload, cache, () => {});
  assert.equal(count, 14);
});
