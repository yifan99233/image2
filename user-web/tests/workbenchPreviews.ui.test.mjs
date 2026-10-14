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
let fixture, root, downloads;
dom.window.HTMLAnchorElement.prototype.click = function () {
  downloads.push({ url: this.href, name: this.download });
};
globalThis.fetch = async (url) => {
  const path = new URL(url).pathname;
  const data = path === "/models" ? [] : path === "/image-tasks" ? fixture : null;
  assert.ok(data !== null, `unexpected request ${path}`);
  return new Response(JSON.stringify({ code: 0, message: "ok", data }), {
    headers: { "Content-Type": "application/json" },
  });
};
async function mount(records = [task]) {
  fixture = records;
  downloads = [];
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
