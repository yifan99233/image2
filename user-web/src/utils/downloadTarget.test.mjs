import assert from "node:assert/strict";
import { Blob } from "node:buffer";
import test from "node:test";

const { fetchDownloadBlob, planDownloadTarget } = await import("./downloadTarget.ts");

const PAGE_HREF = "https://magic.shyfai.com/create/imagine";
const PAGE_ORIGIN = "https://magic.shyfai.com";
const CDN_URL = "https://openagent-cdn.shyfai.cn/image2-assets/generated/20/example.png";

test("keeps a same-origin asset eligible for a direct browser download", () => {
  const target = planDownloadTarget(
    "https://magic.shyfai.com/image2-assets/generated/20/example.png",
    PAGE_HREF,
    PAGE_ORIGIN,
  );

  assert.equal(target.canDownloadDirectly, true);
  assert.equal(target.url, "https://magic.shyfai.com/image2-assets/generated/20/example.png");
  assert.equal(target.fallbackUrl, undefined);
});

test("preserves an external CDN URL instead of rewriting it to the current origin", () => {
  const target = planDownloadTarget(CDN_URL, PAGE_HREF, PAGE_ORIGIN);

  assert.equal(target.canDownloadDirectly, false);
  assert.equal(target.url, CDN_URL);
  assert.equal(
    target.fallbackUrl,
    "https://magic.shyfai.com/image2-assets/generated/20/example.png",
  );
});

test("downloads from the external CDN when it permits cross-origin reads", async () => {
  const target = planDownloadTarget(CDN_URL, PAGE_HREF, PAGE_ORIGIN);
  const expected = new Blob(["cdn-image"], { type: "image/png" });
  const requestedUrls = [];

  const blob = await fetchDownloadBlob(target, async (url) => {
    requestedUrls.push(url);
    return { ok: true, blob: async () => expected };
  });

  assert.equal(blob, expected);
  assert.deepEqual(requestedUrls, [CDN_URL]);
});

test("canonicalizes legacy asset hosts to the same-origin proxy before downloading", async () => {
  const target = planDownloadTarget(
    "https://magic-old.shyfai.com/image2-assets/generated/20/example.png",
    PAGE_HREF,
    PAGE_ORIGIN,
  );
  const expected = new Blob(["legacy-image"], { type: "image/png" });
  const requestedUrls = [];
  assert.equal(target.canDownloadDirectly, true);
  assert.equal(target.fallbackUrl, undefined);

  const blob = await fetchDownloadBlob(target, async (url) => {
    requestedUrls.push(url);
    if (url.startsWith("https://magic-old.shyfai.com")) throw new Error("CORS");
    return { ok: true, blob: async () => expected };
  });

  assert.equal(blob, expected);
  assert.deepEqual(requestedUrls, [
    "https://magic.shyfai.com/image2-assets/generated/20/example.png",
  ]);
});

test("falls back from an unavailable CDN to the same-origin asset proxy", async () => {
  const target = planDownloadTarget(`${CDN_URL}?v=1`, PAGE_HREF, PAGE_ORIGIN);
  const expected = new Blob(["origin-image"], { type: "image/png" });
  const requestedUrls = [];
  const blob = await fetchDownloadBlob(target, async (url) => {
    requestedUrls.push(url);
    if (url.startsWith("https://openagent-cdn.shyfai.cn")) throw new Error("CORS");
    return { ok: true, blob: async () => expected };
  });
  assert.equal(blob, expected);
  assert.deepEqual(requestedUrls, [
    `${CDN_URL}?v=1`,
    "https://magic.shyfai.com/image2-assets/generated/20/example.png?v=1",
  ]);
});

test("reports a download failure after both sources fail", async () => {
  const target = planDownloadTarget(CDN_URL, PAGE_HREF, PAGE_ORIGIN);

  await assert.rejects(
    () => fetchDownloadBlob(target, async () => ({ ok: false, blob: async () => new Blob() })),
    /媒体下载失败，请稍后重试/,
  );
});
