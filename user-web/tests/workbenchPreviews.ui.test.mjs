import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { MemoryRouter } from "react-router-dom";

const dom = new JSDOM('<div id="root"></div>', { url: "http://test/create/edit" });
for (const key of [
  "window",
  "document",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLTextAreaElement",
  "Event",
  "MouseEvent",
  "CustomEvent",
])
  globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");
await build({
  entryPoints: ["src/pages/WorkbenchPage.tsx"],
  outfile: "node_modules/.tmp/workbench-previews-test.mjs",
  bundle: true,
  format: "esm",
  platform: "node",
  packages: "external",
  alias: { "@": process.cwd() + "/src" },
  define: { "import.meta.env": '{"VITE_API_BASE_URL":"http://test"}' },
  jsx: "automatic",
});
const { WorkbenchPage } = await import("../node_modules/.tmp/workbench-previews-test.mjs");
const original = "http://test/image2-assets/result.png";
const output = {
  id: 0,
  url: original,
  thumbnail_url: "/image-tasks/7/thumbnail?token=signed",
  mime_type: "image/png",
};
const inputs = [0, 1].map((index) => ({
  id: 0,
  url: `http://test/image2-assets/input-${index}.png`,
  thumbnail_url: `/image-tasks/7/thumbnail?token=input-${index}&input_index=${index}`,
  mime_type: "image/png",
}));
const task = {
  id: 7,
  task_no: "IMG-7",
  work_type: "image_edit",
  status: "succeeded",
  input_images: inputs,
  output_images: [output],
  prompt: "test",
  created_at: "2026-10-07T00:00:00Z",
  credit_cost: 3,
};
let fixture, root, downloads, historyRequests;
let modelsFixture = [];
dom.window.HTMLAnchorElement.prototype.click = function () {
  downloads.push({ url: this.href, name: this.download });
};
globalThis.fetch = async (url, options) => {
  const parsed = new URL(url);
  const path = parsed.pathname;
  let data;
  if (path === "/models") data = modelsFixture;
  else if (/^\/models\/\d+\/quote$/.test(path)) data = { credit_cost: 1 };
  else if (path === "/image-tasks") {
    historyRequests.push({ params: parsed.searchParams, signal: options.signal });
    data = typeof fixture === "function" ? await fixture(parsed.searchParams) : fixture;
  } else if (options.method === "DELETE" && path.startsWith("/image-tasks/")) data = {};
  else data = null;
  assert.ok(data !== null, `unexpected request ${path}`);
  return new Response(JSON.stringify({ code: 0, message: "ok", data }), {
    headers: { "Content-Type": "application/json" },
  });
};
async function mount(records = [task]) {
  fixture = records;
  downloads = [];
  historyRequests = [];
  root = createRoot(document.getElementById("root"));
  await act(async () => {
    root.render(
      createElement(
        MemoryRouter,
        { initialEntries: ["/create/edit"] },
        createElement(WorkbenchPage),
      ),
    );
    await new Promise((r) => setTimeout(r, 20));
  });
}
async function close() {
  await act(async () => root.unmount());
}
async function click(element) {
  assert.ok(element);
  await act(async () => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

test("all inline input and output images use thumbnails and defer loading", async () => {
  await mount();
  const images = [...document.querySelectorAll(".comparison__media img")];
  assert.equal(images.length, 3);
  assert.deepEqual(
    images.map((i) => i.getAttribute("src")),
    [...inputs, output].map((a) => "http://test" + a.thumbnail_url),
  );
  assert.ok(
    images.every(
      (i) => i.getAttribute("loading") === "lazy" && i.getAttribute("decoding") === "async",
    ),
  );
  assert.equal(document.querySelector(`img[src="${original}"]`), null);
  await close();
});

test("clicking input and output previews opens the original, and download preserves its PNG", async () => {
  await mount();
  await click(document.querySelectorAll(".image-preview-trigger")[0]);
  assert.equal(document.querySelector(".image-preview-dialog img").src, inputs[0].url);
  await click(document.querySelector('[aria-label="关闭预览"]'));
  await click(document.querySelectorAll(".image-preview-trigger")[2]);
  assert.equal(document.querySelector(".image-preview-dialog img").src, original);
  await click(document.querySelector('[aria-label="关闭预览"]'));
  await click(
    [...document.querySelectorAll(".task-actions button")].find(
      (b) => b.textContent.trim() === "下载",
    ),
  );
  assert.deepEqual(downloads, [{ url: original, name: "image2ai-IMG-7.png" }]);
  await close();
});

test("a failed thumbnail displays a recovery action without silently downloading the full image", async () => {
  await mount();
  const image = document.querySelectorAll(".comparison__media img")[2];
  await act(async () => image.dispatchEvent(new Event("error")));
  assert.ok(document.body.textContent.includes("预览加载失败"));
  assert.equal(document.querySelector(`.result-list img[src="${original}"]`), null);
  await click(document.querySelectorAll(".image-preview-trigger")[2]);
  assert.equal(document.querySelector(".image-preview-dialog img").src, original);
  await close();
});

test("legacy assets without a thumbnail still render lazily", async () => {
  await mount([
    { ...task, input_images: [], output_images: [{ ...output, thumbnail_url: undefined }] },
  ]);
  const image = document.querySelector(".comparison__media img");
  assert.equal(image.src, original);
  assert.equal(image.getAttribute("loading"), "lazy");
  await close();
});

const historyButton = () => document.querySelector(".workbench-history button");
const cards = () => [...document.querySelectorAll(".creation-card")];
const records = (count, newest = 200) => Array.from({ length: count }, (_, index) => ({
  ...task, id: newest - index, task_no: `IMG-${newest - index}`, input_images: [], output_images: [],
}));

test("loads more than 80 edit records using filtered cursor pages and stops at the end", async () => {
  const all = records(85);
  await mount((params) => {
    assert.equal(params.get("limit"), "40");
    assert.deepEqual(params.getAll("work_types"), ["image_edit", "image_to_image", "batch_edit"]);
    const before = Number(params.get("before_id") || Infinity);
    return all.filter((record) => record.id < before).slice(0, 40);
  });
  assert.equal(cards().length, 40);
  await click(historyButton());
  assert.equal(cards().length, 80);
  await click(historyButton());
  assert.equal(cards().length, 85);
  assert.equal(historyButton(), null);
  assert.match(document.querySelector(".workbench-history").textContent, /已加载 85 条.*全部记录/);
  assert.deepEqual(historyRequests.map(({ params }) => params.get("before_id")), [null, "161", "121"]);
  await close();
});

test("page errors preserve loaded cards and retry the same cursor without duplicates", async () => {
  let fail = true;
  await mount((params) => {
    if (!params.has("before_id")) return records(40);
    if (fail) { fail = false; throw new Error("temporary network error"); }
    return records(3, 160);
  });
  await click(historyButton());
  assert.equal(cards().length, 40);
  assert.match(document.querySelector('[role="alert"]').textContent, /temporary network error/);
  assert.equal(historyButton().textContent.trim(), "重试加载");
  await click(historyButton());
  assert.equal(cards().length, 43);
  assert.equal(document.querySelector('[role="alert"]'), null);
  assert.deepEqual(historyRequests.map(({ params }) => params.get("before_id")), [null, "161", "161"]);
  await close();
});

test("initial loading and errors do not show a misleading empty state and can retry", async () => {
  let finish;
  await mount(() => new Promise((resolve, reject) => { finish = { resolve, reject }; }));
  assert.equal(document.querySelector(".empty-state"), null);
  assert.equal(historyButton().disabled, true);
  await act(async () => finish.reject(new Error("offline")));
  assert.equal(document.querySelector(".empty-state"), null);
  assert.equal(historyButton().textContent.trim(), "重试加载");
  fixture = [];
  await click(historyButton());
  assert.match(document.querySelector(".empty-state").textContent, /近 7 天暂无/);
  assert.equal(historyButton(), null);
  assert.equal(document.querySelector(".workbench-history__summary").textContent, "");
  await close();
});

test("repeated load clicks share one request and unmount cancels it", async () => {
  let finish;
  await mount((params) => params.has("before_id") ? new Promise((resolve) => { finish = resolve; }) : records(40));
  const button = historyButton();
  await act(async () => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  assert.equal(historyRequests.length, 2);
  assert.equal(historyButton().disabled, true);
  await close();
  assert.equal(historyRequests[1].signal.aborted, true);
  await act(async () => finish(records(2, 160)));
});

test("deleting the oldest card does not change the next page cursor", async () => {
  await mount((params) => params.has("before_id") ? records(2, 160) : records(40));
  await click(cards().at(-1).querySelector(".task-button--red"));
  await click(document.querySelector('.confirm-dialog .button--danger'));
  assert.equal(cards().length, 39);
  await click(historyButton());
  assert.equal(historyRequests[1].params.get("before_id"), "161");
  assert.equal(cards().length, 41);
  await close();
});

test("overlapping results are deduplicated and later pages still advance", async () => {
  await mount((params) => {
    const cursor = params.get("before_id");
    if (!cursor) return records(40);
    if (cursor === "161") return records(40, 161);
    return records(2, 121);
  });
  await click(historyButton());
  assert.equal(cards().length, 79);
  await click(historyButton());
  assert.equal(historyRequests[2].params.get("before_id"), "122");
  assert.equal(cards().length, 81);
  await close();
});


test("Banana 2 and 2.1 expose output resolution without a quality selector", async () => {
  for (const name of ["Banana 2", "Banana 2.1"]) {
    modelsFixture = [{
      id: 266, name, code: "banana", description: "", work_type: "image_edit",
      max_input_images: 14, max_output_images: 1, supports_quality: false,
      supported_resolutions: ["1k", "2k", "4k"].map(value => ({ value, label: value.toUpperCase() })),
      supported_aspect_ratios: [{ value: "1:1", label: "1:1" }],
    }];
    await mount([]);
    const labels = [...document.querySelectorAll(".config-field > span")].map(e => e.textContent);
    assert.ok(labels.includes("分辨率"));
    assert.ok(!labels.includes("质量"));
    const field = [...document.querySelectorAll(".config-field")].find(e => e.firstElementChild?.textContent === "分辨率");
    await click(field.querySelector("button"));
    assert.deepEqual([...field.querySelectorAll('[role="option"]')].map(e => e.textContent.trim()), ["1K", "2K", "4K"]);
    await click([...field.querySelectorAll('[role="option"]')][2]);
    assert.ok(field.querySelector("button").textContent.includes("4K"));
    await close();
  }
  modelsFixture = [];
});
