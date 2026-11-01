import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { MemoryRouter } from "react-router-dom";

const dom = new JSDOM('<div id="root"></div>', { url: "http://test/create/edit" });
for (const key of ["window", "document", "HTMLElement", "HTMLInputElement", "HTMLTextAreaElement", "Event", "MouseEvent", "CustomEvent"]) globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
HTMLElement.prototype.scrollIntoView = () => {};
const { createRoot } = await import("react-dom/client");
await build({ entryPoints: ["src/pages/WorkbenchPage.tsx", "src/pages/tools/ToolPages.tsx"], outdir: "node_modules/.tmp/output-settings", outExtension: { ".js": ".mjs" }, bundle: true, format: "esm", platform: "node", packages: "external", alias: { "@": process.cwd() + "/src" }, define: { "import.meta.env": '{"VITE_API_BASE_URL":"http://test"}' }, jsx: "automatic" });
const { WorkbenchPage } = await import("../node_modules/.tmp/output-settings/WorkbenchPage.mjs");
const { CreativeToolPage } = await import("../node_modules/.tmp/output-settings/tools/ToolPages.mjs");
const asset = { id: 1, url: "http://test/input.png", mime_type: "image/png" };
const model = { id: 5, name: "GPT Image 2", max_input_images: 4, max_output_images: 9, supported_resolutions: [{ value: "1k", label: "1K" }], supported_aspect_ratios: [{ value: "1:1", label: "1:1" }], supports_custom_size: true, supports_output_format: true };
let posts = [], root, records = [];
const reply = (data) => new Response(JSON.stringify({ code: 0, data }), { headers: { "Content-Type": "application/json" } });
globalThis.fetch = async (url, options = {}) => {
  const path = new URL(url).pathname;
  if (path === "/models") return reply(String(url).includes("prompt_optimize") ? [] : [model]);
  if (path.endsWith("/quote")) return reply({ credit_cost: 7 });
  if (path === "/image-tasks" && options.method === "POST") {
    const payload = JSON.parse(options.body);
    posts.push(payload);
    return reply({ ...payload, id: 100, task_no: "TEST-100", status: "succeeded", created_at: new Date().toISOString(), input_images: [asset], output_images: [], credit_cost: 7 });
  }
  if (path === "/image-tasks") return reply(records);
  if (path === "/ux/config") return reply({ max_batch_tasks: 2000 });
  return reply([]);
};
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); });
const button = (label) => [...document.querySelectorAll("button")].find(el => el.textContent.trim().includes(label));
async function click(el) { assert.ok(el); await act(async () => el.click()); await settle(); }
async function setValue(el, value) {
  assert.ok(el);
  await act(async () => {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(mode) {
  root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(MemoryRouter, { initialEntries: [{ pathname: "/create/edit", state: { imageEditSourceAsset: asset, imageEditPrompt: "original prompt" } }] }, mode === "edit" ? createElement(WorkbenchPage) : createElement(CreativeToolPage, { mode }))));
  await settle();
}
async function unmount() { await act(async () => root.unmount()); }
for (const mode of ["edit", "text-to-image"]) {
  test(`${mode}: exact dimensions and JPEG submit, survive remount, and reset to presets`, async () => {
    window.localStorage.clear(); posts = [];
    await mount(mode);
    try {
      const customChoice = button("自定义");
      assert.equal(customChoice.getAttribute("role"), "radio");
      assert.ok(customChoice.closest('[role="radiogroup"]'), "custom size belongs to the ratio options");
      await click(customChoice);
      assert.equal(customChoice.getAttribute("aria-checked"), "true");
      assert.equal(button("1:1").getAttribute("aria-checked"), "false");
      assert.equal(customChoice.closest(".config-field--aspect").querySelectorAll(".image-custom-size input").length, 2);
      const inputs = document.querySelectorAll(".image-custom-size input");
      await setValue(inputs[0], "2048");
      await setValue(inputs[1], "3072");
      await click(button("JPEG"));
      if (mode !== "edit") await setValue(document.querySelector("textarea"), "original prompt");
      await click(button("开始生成"));
      assert.equal(posts.length, 1);
      assert.equal(posts[0].size, "2048x3072");
      assert.equal(posts[0].output_format, "jpeg");
      assert.equal(posts[0].prompt, "original prompt");
      await unmount();
      await mount(mode);
      assert.equal(document.querySelectorAll(".image-custom-size input")[0].value, "2048");
      assert.equal(button("JPEG").getAttribute("aria-pressed"), "true");
      await click(button("1:1"));
      assert.equal(document.querySelector(".image-custom-size"), null);
      assert.equal(button("自定义").getAttribute("aria-checked"), "false");
      assert.equal(button("1:1").getAttribute("aria-checked"), "true");
      await click(button("默认"));
      if (mode !== "edit") await setValue(document.querySelector("textarea"), "original prompt");
      await click(button("开始生成"));
      assert.equal(posts.length, 2);
      assert.equal(posts[1].size, undefined);
      assert.equal(posts[1].output_format, undefined);
    } finally { await unmount(); }
  });
}

test("unsupported models hide and omit saved output options", async () => {
  model.supports_custom_size = false; model.supports_output_format = false;
  window.localStorage.setItem("image2ai.toolPreference.text_to_image", JSON.stringify({ modelId: 5, resolution: "1k", aspectRatio: "1:1", quality: "auto", imageSize: "2048x3072", outputFormat: "webp" }));
  posts = [];
  await mount("text-to-image");
  try {
    assert.equal(document.querySelector(".image-output-settings"), null);
    await setValue(document.querySelector("textarea"), "test");
    await click(button("开始生成"));
    assert.equal(posts.length, 1);
    assert.equal(posts[0].size, undefined);
    assert.equal(posts[0].output_format, undefined);
  } finally { await unmount(); model.supports_custom_size = true; model.supports_output_format = true; }
});

for (const mode of ["edit", "text-to-image"]) {
  test(`${mode}: regenerate uses recorded size and format`, async () => {
    records = [{ id: 7, task_no: "TEST-7", work_type: mode === "edit" ? "image_edit" : "text_to_image", model_id: 5, prompt: "saved prompt", resolution: "1k", aspect_ratio: "1:1", quality: "high", size: "2048x3072", output_format: "webp", status: "succeeded", input_images: [asset], output_images: [asset], created_at: new Date().toISOString(), credit_cost: 7 }];
    posts = [];
    await mount(mode);
    try {
      await click(button("重新生成"));
      assert.equal(posts.length, 1);
      assert.equal(posts[0].size, "2048x3072");
      assert.equal(posts[0].output_format, "webp");
      assert.equal(posts[0].quality, "high");
    } finally { await unmount(); records = []; }
  });
}

for (const imagesPerGeneration of [1, 4]) {
  test(`mobile count selector submits three ${imagesPerGeneration === 4 ? 'Midjourney groups' : 'images'} without losing group labels`, async () => {
    model.images_per_generation = imagesPerGeneration;
    window.localStorage.clear(); posts = [];
    await mount('text-to-image');
    try {
      const select = document.querySelector('#text-to-image-output-count');
      assert.equal(select.tagName, 'SELECT');
      assert.equal(select.options[2].textContent, imagesPerGeneration === 4 ? '3 组' : '3 张');
      await act(async () => {
        Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, 'value').set.call(select, '3');
        select.dispatchEvent(new Event('change', {bubbles: true}));
      });
      await setValue(document.querySelector('textarea'), 'test count');
      await click(button('开始生成'));
      assert.equal(posts.length, 3);
      assert.ok(posts.every(payload => payload.n === 1));
    } finally { await unmount(); delete model.images_per_generation; }
  });
}
