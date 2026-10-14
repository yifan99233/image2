import assert from "node:assert/strict";
import test from "node:test";
import { ZipReader, Uint8ArrayReader, TextWriter } from "@zip.js/zip.js";
import { writeBrowserBatchExport } from "./browserBatchExport.ts";

const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5T8AAAAASUVORK5CYII=", "base64");
const item = (id, status = "succeeded") => ({ id, status, url: `https://cdn.test/${id}.png`, folder: "【系列】", stem: `image-${id}`, error: status === "failed" ? "生成失败" : "" });
const page = (items, more = false) => ({ items, max_id: 4, total: 4, has_more: more, next_cursor: items.at(-1)?.id ?? 0, max_image_bytes: 64 * 1024 ** 2 });
const streamText = text => new Blob([text]).stream();

test("direct CDN export pages metadata, writes ZIP64, and reports generation/download failures separately", async () => {
  const chunks = [], calls = [], reports = [];
  let closed = false;
  const target = new WritableStream({ write: chunk => chunks.push(chunk), close: () => { closed = true; } });
  const source = {
    page: async (after, max) => {
      calls.push([after, max]);
      return after ? page([item(3, "failed"), item(4, "running")]) : page([item(1), item(2)], true);
    },
    report: async (kind, results) => { reports.push([kind, structuredClone(results)]); return streamText(kind); },
  };
  const urls = [];
  const result = await writeBrowserBatchExport(target, source, new AbortController().signal, () => {}, async (url, options) => {
    urls.push(url);
    assert.equal(options.credentials, "omit");
    assert.equal(options.mode, "cors");
    assert.equal(options.headers, undefined);
    return url.endsWith("2.png") ? new Response("missing", { status: 404 }) : new Response(png);
  });
  assert.equal(closed, true);
  assert.deepEqual(calls, [[0, undefined], [2, 4]]);
  assert.deepEqual(urls.sort(), ["https://cdn.test/1.png", "https://cdn.test/2.png"]);
  assert.deepEqual([result.succeeded, result.failed, result.pending], [1, 2, 1]);
  assert.deepEqual(reports[0][1].map(r => r.status), ["成功", "失败", "失败", "未完成"]);
  assert.match(reports[0][1][1].error, /HTTP 404/);
  const reader = new ZipReader(new Uint8ArrayReader(Buffer.concat(chunks)), { useWebWorkers: false });
  const entries = await reader.getEntries();
  assert.deepEqual(entries.map(e => e.filename), ["【系列】/", "【系列】/image-1.png", "完整汇总.xlsx", "失败汇总.xlsx", "结果统计.txt"]);
  assert.ok(entries.every(entry => entry.zip64));
  assert.equal(await entries.at(-1).getData(new TextWriter(), { checkSignature: true }), "成功 1 张，失败 2 张，未完成 1 张（本次下载快照）\n");
  await reader.close();
});

test("cancellation aborts the disk writer and in-flight CDN reads without scheduling the rest", async () => {
  const controller = new AbortController();
  let started = 0, stopped = 0, aborted = false, closed = false;
  const target = new WritableStream({ write() {}, abort() { aborted = true; }, close() { closed = true; } });
  const done = writeBrowserBatchExport(target, { page: async () => page([item(1), item(2), item(3), item(4)]), report: async () => { throw new Error("must not build reports"); } }, controller.signal, () => {},
    async (_url, options) => new Promise((_resolve, reject) => {
      started++;
      options.signal.addEventListener("abort", () => { stopped++; reject(options.signal.reason); }, { once: true });
      if (started === 2) setTimeout(() => controller.abort(), 5);
    }));
  await assert.rejects(done, /abort/i);
  assert.equal(started, 2);
  assert.equal(stopped, 2);
  assert.equal(aborted, true);
  assert.equal(closed, false);
});

test("disk errors fail the archive instead of being counted as image download failures", async () => {
  const target = new WritableStream({ write() { throw new Error("disk full"); } });
  let reports = 0;
  await assert.rejects(writeBrowserBatchExport(target, { page: async () => ({ ...page([item(1)]), total: 1 }), report: async () => { reports++; return streamText(""); } }, new AbortController().signal, () => {}, async () => new Response(png)), /disk full/);
  assert.equal(reports, 0);
});

test("oversized or non-image CDN responses are reported and never written as image entries", async () => {
  let results;
  const target = new WritableStream({ write() {} });
  const source = { page: async () => ({ ...page([item(1), item(2)]), total: 2, max_image_bytes: 32 }), report: async (_kind, values) => { results = values; return streamText(""); } };
  await writeBrowserBatchExport(target, source, new AbortController().signal, () => {}, async url => new Response(url.endsWith("1.png") ? png : "<html>error</html>"));
  assert.deepEqual(results.map(r => r.status), ["失败", "失败"]);
  assert.match(results[0].error, /超过/);
  assert.match(results[1].error, /不是支持的图片/);
});

test("transient CDN errors retry only the image GET and recovered images count as success", async () => {
  let attempts = 0;
  const result = await writeBrowserBatchExport(new WritableStream({ write() {} }), {
    page: async () => ({ ...page([item(1)]), total: 1 }), report: async () => streamText("report"),
  }, new AbortController().signal, () => {}, async url => {
    assert.equal(url, "https://cdn.test/1.png");
    attempts++;
    return attempts === 1 ? new Response("busy", { status: 503 }) : new Response(png);
  });
  assert.equal(attempts, 2);
  assert.equal(result.succeeded, 1);
  assert.equal(result.failed, 0);
});
