import assert from "node:assert/strict";
import test from "node:test";

const { getAssetPreviewSource } = await import("./assetPreview.ts");

test("uses the lightweight thumbnail for inline previews", () => {
  assert.equal(
    getAssetPreviewSource({
      url: "https://example.com/generated/original.png",
      thumbnail_url: "/image-tasks/8127/thumbnail?token=signed",
    }),
    "/image-tasks/8127/thumbnail?token=signed",
  );
});

test("falls back to the original asset when no thumbnail is available", () => {
  assert.equal(
    getAssetPreviewSource({ url: "https://example.com/generated/original.png" }),
    "https://example.com/generated/original.png",
  );
  assert.equal(
    getAssetPreviewSource({
      url: "https://example.com/generated/original.png",
      thumbnail_url: "  ",
    }),
    "https://example.com/generated/original.png",
  );
});
