import assert from "node:assert/strict";
import test from "node:test";

const { getGalleryAspectRatio } = await import("./galleryAspectRatio.ts");

test("prefers the asset dimensions when they are available", () => {
  assert.equal(getGalleryAspectRatio({ width: 1200, height: 1600 }, "16:9"), "1200 / 1600");
});

test("uses the task aspect ratio for generated assets without dimensions", () => {
  assert.equal(getGalleryAspectRatio({ width: null, height: null }, "9:16"), "9 / 16");
});

test("ignores incomplete or invalid dimensions", () => {
  assert.equal(getGalleryAspectRatio({ width: 0, height: 1200 }, "not-a-ratio"), undefined);
  assert.equal(getGalleryAspectRatio(undefined, "16:9:1"), undefined);
});
