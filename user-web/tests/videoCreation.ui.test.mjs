import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";
import { MemoryRouter } from "react-router-dom";

const dom = new JSDOM('<div id="root"></div>', { url: "http://test/create/video" });
for (const key of ["window", "document", "HTMLElement", "HTMLInputElement", "HTMLTextAreaElement", "Event", "MouseEvent", "CustomEvent"]) globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
HTMLElement.prototype.scrollIntoView = () => {};
const { createRoot } = await import("react-dom/client");
await build({ entryPoints: ["src/pages/tools/ToolPages.tsx"], outfile: "node_modules/.tmp/video-creation.mjs", bundle: true, format: "esm", platform: "node", packages: "external", alias: { "@": process.cwd() + "/src" }, define: { "import.meta.env": '{"VITE_API_BASE_URL":"http://test"}' }, jsx: "automatic" });
const { CreativeToolPage } = await import("../node_modules/.tmp/video-creation.mjs");
const mib = 1024 * 1024;
const base = { code: "video", description: "", work_type: "video", supported_work_types: ["text_to_video", "image_to_video"], max_input_images: 1, max_output_images: 1, supported_resolutions: [{ value: "720p", label: "720P" }], supported_aspect_ratios: [{ value: "16:9", label: "16:9" }], supported_durations: [{ value: "4s", label: "4 秒" }] };
const museCaps = { kinds: ["image", "video", "audio"], mime_types: ["image/png", "image/jpeg", "image/webp", "video/mp4", "audio/wav"], max_total: 4, max_by_kind: { image: 4, video: 4, audio: 4 }, max_bytes_by_kind: { image: 24 * mib, video: 24 * mib, audio: 24 * mib }, max_total_bytes: 24 * mib, frame_order: false };
const models = [
  { ...base, id: 1, name: "Muse 视频", reference_capabilities: museCaps },
  { ...base, id: 2, name: "Veo Lite", reference_capabilities: { kinds: ["image"], mime_types: ["image/png", "image/jpeg"], max_total: 2, max_by_kind: { image: 2 }, max_bytes_by_kind: { image: 50 * mib }, frame_order: true } },
  { ...base, id: 3, name: "Omni Flash", reference_capabilities: { ...museCaps, kinds: ["image", "video"], mime_types: ["image/png", "image/jpeg", "video/mp4"], max_total: 10, max_by_kind: { image: 10, video: 3 }, max_total_bytes: null } },
];
const response = data => new Response(JSON.stringify({ code: 0, data }), { headers: { "Content-Type": "application/json" } });
let posts, uploads, quotes, historyQueries, root, nextId, failUploadAt, pendingUpload, finishUpload;
globalThis.fetch = async (url, options = {}) => {
  const parsed = new URL(url), path = parsed.pathname;
  if (path === "/models") {
    assert.equal(parsed.searchParams.get("work_type"), "video");
    return response(models);
  }
  if (path.endsWith("/quote")) { quotes.push(JSON.parse(options.body)); return response({ credit_cost: 5 }); }
  if (path === "/uploads/video-references") {
    const file = options.body.get("file");
    uploads.push({ name: file.name, model: options.body.get("model_id") });
    if (pendingUpload) await new Promise(resolve => { finishUpload = resolve; });
    if (uploads.length === failUploadAt) return new Response(JSON.stringify({ code: 500, message: "素材上传失败" }), { status: 500 });
    return response({ id: ++nextId, url: `http://test/${file.name}`, mime_type: file.type, size_bytes: file.size, source: "upload" });
  }
  if (path === "/image-tasks" && options.method === "POST") {
    const payload = JSON.parse(options.body); posts.push(payload);
    return response({ ...payload, id: ++nextId, task_no: `VIDEO-${nextId}`, status: "succeeded", created_at: new Date().toISOString(), input_images: [], output_images: [], credit_cost: 5 });
  }
  if (path === "/image-tasks") { historyQueries.push(parsed.searchParams.getAll("work_types")); return response([]); }
  return response([]);
};
const settle = () => act(async () => { await new Promise(resolve => setTimeout(resolve, 15)); });
const button = label => [...document.querySelectorAll("button")].find(el => el.textContent.trim().includes(label));
const submit = () => button("开始生成视频");
async function click(el) { assert.ok(el); await act(async () => el.click()); await settle(); }
async function prompt(value = "保持主体外观，镜头缓慢推进") {
  const input = document.querySelector("textarea");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function mount(mode = "video") {
  window.localStorage.clear(); posts = []; uploads = []; quotes = []; historyQueries = []; nextId = 10; failUploadAt = -1; pendingUpload = false;
  root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(MemoryRouter, {}, createElement(CreativeToolPage, { mode }))));
  await settle();
}
async function unmount() { await act(async () => root.unmount()); }
async function upload(files) {
  const input = document.querySelector('input[aria-label="上传参考素材（选填）"]');
  Object.defineProperty(input, "files", { value: files, configurable: true });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  await settle();
}
async function chooseModel(name) {
  await click(document.querySelector(".model-picker__trigger"));
  await click([...document.querySelectorAll('[role="option"]')].find(el => el.textContent.includes(name)));
}
const file = (name, mime) => new File(["test bytes"], name, { type: mime });

for (const mode of ["video", "text-to-video", "image-to-video"]) {
  test(`${mode}: unified optional-reference page creates text video and combines both histories`, async () => {
    await mount(mode);
    try {
      assert.match(document.body.textContent, /视频生成/);
      assert.match(document.body.textContent, /添加参考素材（选填）/);
      assert.deepEqual(historyQueries, [["text_to_video", "image_to_video"]]);
      await prompt();
      assert.equal(submit().disabled, false);
      await click(submit());
      assert.equal(posts[0].work_type, "text_to_video");
      assert.deepEqual(posts[0].input_image_ids, []);
      assert.equal(quotes.at(-1).work_type, "text_to_video");
    } finally { await unmount(); }
  });
}

test("Muse uploads mixed references, previews each media type, preserves order and requotes reference generation", async () => {
  await mount();
  try {
    await prompt();
    await upload([file("first.png", "image/png"), file("motion.mp4", "video/mp4"), file("voice.wav", "audio/wav")]);
    assert.deepEqual(uploads.map(x => x.model), ["1", "1", "1"]);
    assert.equal(document.querySelectorAll(".asset-grid img").length, 1);
    assert.equal(document.querySelectorAll(".asset-grid video").length, 1);
    assert.equal(document.querySelectorAll(".asset-grid audio").length, 1);
    assert.equal(quotes.at(-1).work_type, "image_to_video");
    await click(document.querySelectorAll('[aria-label="上移素材"]')[2]);
    await click(submit());
    assert.equal(posts[0].work_type, "image_to_video");
    assert.deepEqual(posts[0].input_image_ids, [11, 13, 12]);
    assert.deepEqual(posts[0].input_image_urls, ["http://test/first.png", "http://test/voice.wav", "http://test/motion.mp4"]);
  } finally { await unmount(); }
});

test("switching to Veo keeps unsupported media visible and blocks submit until removal", async () => {
  await mount();
  try {
    await prompt(); await upload([file("motion.mp4", "video/mp4")]);
    await chooseModel("Veo Lite");
    assert.equal(document.querySelectorAll(".asset-grid video").length, 1);
    assert.match(document.querySelector('[role="alert"]').textContent, /不支持/);
    assert.equal(submit().disabled, true);
    const input = document.querySelector('input[aria-label="上传参考素材（选填）"]');
    assert.equal(input.accept, "image/png,image/jpeg");
    await click(document.querySelector('[aria-label="移除"]'));
    assert.equal(submit().disabled, false);
    await upload([file("first.png", "image/png"), file("last.png", "image/png")]);
    assert.match(document.querySelector(".asset-grid").textContent, /首帧/);
    assert.match(document.querySelector(".asset-grid").textContent, /尾帧/);
    await click(submit()); assert.equal(posts[0].model_id, 2);
  } finally { await unmount(); }
});

test("upload failures retain completed assets; unsupported and oversized media never upload", async () => {
  await mount();
  try {
    failUploadAt = 2;
    await upload([file("first.png", "image/png"), file("voice.wav", "audio/wav")]);
    assert.equal(document.querySelectorAll(".asset-grid figure").length, 1);
    await chooseModel("Omni Flash");
    await upload([file("voice.wav", "audio/wav")]);
    assert.equal(uploads.length, 2);
    assert.match(document.body.textContent, /不支持/);
    const oversized = file("large.mp4", "video/mp4");
    Object.defineProperty(oversized, "size", { value: 51 * mib });
    await upload([oversized]); assert.equal(uploads.length, 2);
  } finally { await unmount(); }
});

test("upload in flight disables submission and model changes", async () => {
  await mount();
  try {
    await prompt(); pendingUpload = true;
    await upload([file("voice.wav", "audio/wav")]);
    assert.equal(submit().disabled, true);
    assert.equal(document.querySelector(".model-picker__trigger").disabled, true);
    await click(submit()); assert.equal(posts.length, 0);
    pendingUpload = false;
    await act(async () => finishUpload()); await settle();
    assert.equal(submit().disabled, false);
    await click(submit()); assert.equal(posts[0].work_type, "image_to_video");
  } finally { await unmount(); }
});
