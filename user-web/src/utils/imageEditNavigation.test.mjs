import assert from "node:assert/strict";
import test from "node:test";

import {
  createImageEditNavigationState,
  mergeImageEditAssets,
  readImageEditAssets,
  readImageEditPrompt,
} from "./imageEditNavigation.ts";

const asset = (id, url) => ({
  id,
  url,
  mime_type: "image/png",
  width: null,
  height: null,
  size_bytes: 0,
  sha256: "",
  source: "model_output",
});

test("continue edit keeps the result first and preserves unique original references", () => {
  const result = asset(0, "https://cdn.example.test/result.png");
  const originalA = asset(0, "https://cdn.example.test/original-a.png");
  const originalB = asset(0, "https://cdn.example.test/original-b.png");

  const merged = mergeImageEditAssets(result, [originalA, result, originalB]);

  assert.deepEqual(merged.map((item) => item.url), [
    result.url,
    originalA.url,
    originalB.url,
  ]);
});

test("navigation state restores the result and original references without re-upload", () => {
  const result = asset(0, "https://cdn.example.test/result.png");
  const original = asset(0, "https://cdn.example.test/original.png");

  const state = createImageEditNavigationState(result, [original], "把背景改成暖色");

  assert.deepEqual(
    readImageEditAssets(state).map((item) => item.url),
    [result.url, original.url],
  );
  assert.equal(readImageEditPrompt(state), "把背景改成暖色");
});

test("invalid navigation state does not populate the editor", () => {
  assert.deepEqual(readImageEditAssets({ imageEditSourceAsset: { id: 1 } }), []);
  assert.equal(readImageEditPrompt({ imageEditSourceAsset: { id: 1 } }), "");
});
