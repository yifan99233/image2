import assert from "node:assert/strict";
import test from "node:test";
import { File } from "node:buffer";
import { JSDOM } from "jsdom";
import { build } from "esbuild";
import { act, createElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { utils, write } from "xlsx";

const dom = new JSDOM('<html><body><div id="root"></div></body></html>', {
  url: "http://test/create/batch-edit",
});
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
URL.createObjectURL = () => "blob:test-preview";
URL.revokeObjectURL = () => {};
const { createRoot } = await import("react-dom/client");
await build({
  entryPoints: ["src/pages/tools/ToolPages.tsx"],
  outfile: "node_modules/.tmp/batch-groups-test.mjs",
  bundle: true,
  format: "esm",
  platform: "node",
  packages: "external",
  alias: { "@": process.cwd() + "/src" },
  define: { "import.meta.env": '{"VITE_API_BASE_URL":"http://test"}' },
  jsx: "automatic",
});
const { CreativeToolPage } = await import("../node_modules/.tmp/batch-groups-test.mjs");
const model = {
  id: 5,
  name: "测试多图模型",
  work_type: "batch_edit",
  max_input_images: 2,
  max_output_images: 1,
  is_recommended: true,
  supported_resolutions: [{ value: "1k", label: "1K" }],
  supported_aspect_ratios: [{ value: "1:1", label: "1:1" }],
};
const reply = (data) =>
  new Response(JSON.stringify({ code: 0, message: "ok", data }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
let statusRequests = [],
  historyFixture = [],
  detailRequests = [];
let batchFixture = [], batchMoreFixture = [], batchStatusFixture = [], batchStatusRequests = [], batchListRequests = [], exportRequests = [], failureFixture = [], failureRequests = [], downloadLinks = [], rejectBatchList = false;
let retryRequests = [],
  retryQuotes = [],
  retryFailure = null,
  retryCost = 7,
  retryResult = null;
dom.window.HTMLAnchorElement.prototype.click = function () { downloadLinks.push(this.href); };
window.showSaveFilePicker = async ({ suggestedName }) => ({ createWritable: async () => new WritableStream({ write() {}, close() { downloadLinks.push(suggestedName); } }) });
let quoteRequests = [], useQualityPrices = false;
let priceQuoteFixture = { credit_cost: 7 };
let siteBatchLimit = 2000;
let asyncUploadFixture = false, uploadedManifests = [];
let posts = [],
  uploads = [],
  loseResponse = false;
globalThis.fetch = async (url, options = {}) => {
  const path = new URL(url).pathname;
  if (new URL(url).hostname === "cdn-export.test") return new Response(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j5T8AAAAASUVORK5CYII=", "base64"));
  if (path === "/image-tasks/browser-export/items") {
    const batchId = new URL(url).searchParams.get("batch_id");
    exportRequests.push({ batch_id: batchId });
    return reply({ items: [{ id: 1, folder: "【系列】", stem: "image-1", url: "https://cdn-export.test/1.png", status: "succeeded", error: "" }, { id: 2, folder: "【系列】", stem: "image-2", url: "", status: "queued", error: "" }], total: 2, max_id: 2, has_more: false, next_cursor: 2, max_image_bytes: 64 * 1024 ** 2 });
  }
  if (path.startsWith("/image-tasks/browser-export/reports/")) return new Response("xlsx fixture");
  if (path === "/models") return reply(String(url).includes("prompt_optimize") ? [] : [model]);
  if (path === "/models/5/quote") {
    const payload = JSON.parse(options.body);
    quoteRequests.push(payload);
    return reply(useQualityPrices ? {credit_cost: {low: 3, medium: 5, high: 6, auto: 5}[payload.quality]} : priceQuoteFixture);
  }
  if (path === "/ux/config") return reply({ max_batch_tasks: siteBatchLimit });
  if (path === "/image-tasks/batches") {
    batchListRequests.push(String(url));
    if (rejectBatchList) {rejectBatchList = false; throw new Error("模拟批次读取失败");}
    const more = new URL(url).searchParams.has("before_id");
    return reply({items: more ? batchMoreFixture : batchFixture, has_more: !more && batchMoreFixture.length > 0, next_cursor: !more && batchMoreFixture.length ? batchFixture.at(-1).latest_task_id : null,
    });
  }
  if (path === "/image-tasks/batches/statuses") {
    batchStatusRequests.push(JSON.parse(options.body).batch_ids);
    return reply(batchStatusFixture.length
        ? batchStatusFixture
        : batchFixture.filter((item) => JSON.parse(options.body).batch_ids.includes(item.batch_id)),
    );
  }
  if (path === "/image-tasks/batches/retry-quote") {
    const payload = JSON.parse(options.body);
    retryQuotes.push(payload);
    if (retryFailure === "quote") {
      retryFailure = null;
      return new Response(JSON.stringify({ code: 40404, message: "原模型不可用", data: null }), {
        status: 404,
      });
    }
    const batch = batchFixture.find((item) => item.batch_id === payload.batch_id);
    const count = batch.retryable_count;
    return reply({
      batch_id: payload.batch_id,
      task_count: count,
      task_ids: Array.from({ length: count }, (_, i) => 7000 + i),
      total_credit_cost: count * retryCost,
      quote_token: retryCost === 7 ? "a".repeat(64) : "b".repeat(64),
    });
  }
  if (path === "/image-tasks/batches/retry") {
    const payload = JSON.parse(options.body);
    retryRequests.push(payload);
    await new Promise((r) => setTimeout(r, 40));
    if (retryFailure === "conflict") {
      retryFailure = null;
      return new Response(
        JSON.stringify({ code: 40944, message: "模型价格已变化，请重新确认重试费用", data: null }),
        { status: 409 },
      );
    }
    if (!retryResult) {
      const tasks = payload.task_ids.map(id => taskRecord(id, payload.batch_id, "queued"));
      const retriedIds = new Set(tasks.map(task => task.id));
      historyFixture = historyFixture.filter(task => !retriedIds.has(task.id));
      historyFixture.push(...tasks);
      retryResult = {
        batch_id: payload.batch_id,
        task_count: tasks.length,
        task_ids: tasks.map((task) => task.id),
        tasks: [],
        submission_status: "queued",
      };
      batchFixture = batchFixture.map((item) =>
          item.batch_id === payload.batch_id
            ? { ...item, failed_count: item.failed_count - tasks.length,
                queued_count: item.queued_count + tasks.length, retryable_count: 0, already_retried_count: 0 }
            : item,
        );
    }
    if (retryFailure === "network") {
      retryFailure = null;
      throw new Error("模拟重试响应丢失");
    }
    return reply(retryResult);
  }
  if (path === "/image-tasks/export-ticket") {
    exportRequests.push(JSON.parse(options.body));
    return reply({download_url: "/image-tasks/export?ticket=test-ticket"});
  }
  if (path === "/image-tasks" && options.method !== "POST") {
    const params = new URL(url).searchParams;
    if (!params.has("batch_id")) return reply([]);
    const failed = params.get("status") === "failed";
    (failed ? failureRequests : detailRequests).push(Object.fromEntries(params));
    const before = Number(params.get("before_id") || Infinity);
    return reply(
      (failed ? failureFixture : historyFixture)
        .filter((task) => task.batch_id === params.get("batch_id") && task.id < before).sort((a, b) => b.id - a.id)
        .slice(0, Number(params.get("limit"))),
    );
  }
  if (path === "/uploads/images") {
    assert.ok([null, "5"].includes(options.body.get("model_id")));
    const file = options.body.get("image");
    uploads.push(file.name);
    return reply({
      id: uploads.length,
      url: `https://cdn.test/${uploads.length}.png`,
      mime_type: "image/png",
      size_bytes: 5,
    });
  }
  if (path === "/image-tasks/statuses") {
    const ids = JSON.parse(options.body).task_ids;
    statusRequests.push(ids);
    return reply(
      ids.map((id) => ({ id, status: "queued", progress_stage: "queued", output_images: [] })),
    );
  }
  if (path === "/image-tasks/batch" || path === "/image-tasks/batch-upload") {
    const uploaded = path === "/image-tasks/batch-upload" ? JSON.parse(await options.body.get("manifest").text()) : null;
    if (uploaded) uploadedManifests.push(uploaded);
    const payload = uploaded ? { ...uploaded, prompt: uploaded.prompts.join("\n") } : JSON.parse(options.body);
    posts.push(payload);
    if (loseResponse) {
      loseResponse = false;
      throw new Error("模拟提交响应丢失");
    }
    if (payload.work_type === "batch_generate") {
      const count = payload.prompt.split("\n").filter(Boolean).length;
      if (asyncUploadFixture) {
        batchFixture = [summary(payload.batch_id, { task_count: count, pending_count: count, submission_status: "queued" })];
        return reply({ batch_id: payload.batch_id, task_count: count, task_ids: [], tasks: [], submission_status: "queued" });
      }
      batchFixture = [summary("new-batch", {task_count: count, queued_count: count})];
      historyFixture = Array.from({length: count }, (_,i) => taskRecord(i+1, "new-batch", "queued"),
      );
      const tasks = historyFixture.slice(0, 80);
      return reply({batch_id: "new-batch", task_count: count, task_ids: Array.from({length:count},(_,i)=>i+1), tasks,
      });
    }
    const tasks = payload.groups.flatMap((g) =>
      Array.from({ length: g.output_count }, (_, i) => ({
        id: 100 + posts.length * 10000 + i + payload.groups.indexOf(g) * 10,
        task_no: `IMG-${g.group_name}-${i}`,
        input_group_id: g.group_id,
        input_group_name: g.group_name,
        batch_id: payload.batch_id,
        work_type: "batch_edit",
        model_id: 5,
        model_name: model.name,
        prompt: g.prompt,
        resolution: "1k",
        aspect_ratio: "1:1",
        quality: "auto",
        credit_cost: 7,
        status: "queued",
        progress_stage: "queued",
        input_images: g.input_image_ids.map((id) => ({ id, url: `https://cdn.test/${id}.png` })),
        output_images: [],
        created_at: new Date().toISOString(),
      })),
    );
    historyFixture.push(...tasks);
    batchFixture = [
      summary(payload.batch_id, { task_count: tasks.length, queued_count: tasks.length }),
      ...batchFixture,
    ];
    return reply({
      batch_id: payload.batch_id,
      task_count: tasks.length,
      task_ids: tasks.map((t) => t.id),
      tasks,
    });
  }
  return reply([]);
};
const byLabel = (label) => document.querySelector(`[aria-label="${label}"]`);
const button = (label) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent.includes(label));
const settle = async () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 20));
  });
const click = async (el) => {
  assert.ok(el, "control exists");
  await act(async () => el.click());
  await settle();
};
const setValue = async (el, value) => {
  await act(async () => {
    const proto =
      el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const select = async (el, value) =>
  act(async () => {
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
const chooseFiles = async (label, files) => {
  const input = byLabel(label);
  Object.defineProperty(input, "files", { value: files, configurable: true });
  await act(async () => {
    input.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 30));
  });
  await settle();
};
const picture = (path) => {
  const file = new File(["image"], path.split("/").pop(), { type: "image/png" });
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
};
let root;
const mount = async (grouped = true, batchLimit = 2000, mode = "batch-edit", batches = [], more = [],
) => {
  siteBatchLimit = batchLimit;
  uploadedManifests = [];
  asyncUploadFixture = false;
  posts = [];
  statusRequests = [];
  uploads = [];
  batchFixture = batches;
  batchMoreFixture = more;
  batchStatusFixture = [];
  batchListRequests = [];
  batchStatusRequests = [];
  historyFixture = [];
  detailRequests = [];
  failureRequests = [];
  failureFixture = [];
  exportRequests = [];
  downloadLinks = [];
  retryRequests = [];
  retryQuotes = [];
  retryFailure = null;
  retryCost = 7;
  retryResult = null;
  window.localStorage.clear();
  root = createRoot(document.getElementById("root"));
  await act(async () =>
    root.render(
      createElement(MemoryRouter, null, createElement(CreativeToolPage, { mode }))),
  );
  await settle();
  if (grouped) await click(button("文件夹任务组"));
};
const unmount = async () => act(async () => root.unmount());

const summary = (id, overrides = {}) => ({batch_id:id, latest_task_id:2000, created_at:"2026-10-06T08:00:00Z", task_count:2000, pending_count:0, queued_count:0, running_count:0, succeeded_count:0, failed_count:0, downloadable_count:0,
  retryable_count: overrides.failed_count || 0,
  already_retried_count: 0,
  retry_of_batch_id: null,
  ...overrides,
});
const taskRecord = (id, batchId, status) => ({id, batch_id:batchId, task_no:`IMG-${id}`, work_type:"batch_generate", model_id:5, model_name:model.name, prompt:`prompt-${id}`, resolution:"1k", aspect_ratio:"1:1", quality:"auto", credit_cost:7, status, input_images:[], output_images:[], failure_message:status === "failed" ? "模型超时" : "已退款：上游失败", created_at:"2026-10-06T08:00:00Z",
});

test("batch generation submits Auto dimensions separately from Auto quality and keeps prompt text", async () => {
  const oldResolutions = model.supported_resolutions;
  const oldRatios = model.supported_aspect_ratios;
  model.supported_resolutions = [...oldResolutions, { value: "auto", label: "自动（Auto）" }];
  model.supported_aspect_ratios = [...oldRatios, { value: "auto", label: "自动（Auto）" }];
  await mount(false, 20000, "batch-generate");
  try {
    const prompt = "Portrait 2:3, 2048 x 3072, keep this text unchanged.";
    const resolutionField = [...document.querySelectorAll(".config-field")].find(el => el.firstElementChild?.textContent === "分辨率");
    await click(resolutionField.querySelector("button"));
    await click([...byLabel("选择分辨率").querySelectorAll("button")].find(el => el.textContent === "自动（Auto）"));
    const ratio = [...byLabel("选择比例").querySelectorAll("button")].find(el => el.textContent === "自动（Auto）");
    await click(ratio);
    assert.equal(ratio.getAttribute("aria-checked"), "true");
    assert.ok(ratio.querySelector("svg"));
    assert.doesNotMatch(ratio.innerHTML, /NaN/);
    assert.match(document.body.textContent, /质量“自动”不控制尺寸/);
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), prompt);
    await click(button("提交批量任务"));
    assert.equal(posts.length, 1);
    assert.equal(posts[0].resolution, "auto");
    assert.equal(posts[0].aspect_ratio, "auto");
    assert.equal(posts[0].quality, "auto");
    assert.equal(posts[0].prompt, prompt);
  } finally {
    await unmount();
    model.supported_resolutions = oldResolutions;
    model.supported_aspect_ratios = oldRatios;
  }
});

test("shared supplement, append and overwrite affect every folder group, synchronize imported rows, and submit the exact final prompts", async () => {
  await mount();
  try {
    await chooseFiles("选择任务组文件夹",Array.from({length:200},(_,i)=>picture(`素材/商品${i}/参考.png`)),
    );
    const csv="文件夹名,提示词\n"+Array.from({length:100},(_,i)=> `商品${i},${i === 50 ? "" : `白底${i}`}`).join("\n");
    await chooseFiles("选择任务组提示词文件",[new File([csv],"p.csv")]);
    const mode=(label)=>[...byLabel("共同提示词应用方式").querySelectorAll("button")].find(
        (b) =>b.textContent===label,
      );
    assert.equal(mode("补充").getAttribute("aria-checked"),"true");
    assert.equal(button("填充缺少的提示词").disabled,true);
    await setValue(byLabel("查找任务组"),"商品150");
    await setValue(byLabel("任务组 151 提示词"),"手写150");
    await setValue(byLabel("查找任务组"),"商品199");
    await setValue(document.querySelector("#group-common-prompt"),"统一补充");
    await click(button("填充缺少的提示词"));
    assert.equal(byLabel("任务组 200 提示词").value,"统一补充");
    assert.match(document.querySelector(".batch-groups__message").textContent,/100 个缺少提示词/);
    await setValue(byLabel("查找任务组"),"商品150");
    assert.equal(byLabel("任务组 151 提示词").value,"手写150");
    await setValue(byLabel("查找任务组"),"");
    assert.equal(byLabel("任务组 1 提示词").value,"白底0");
    await click(mode("追加"));
    await setValue(document.querySelector("#group-common-prompt"),"补充尾词");
    await click(button("追加到全部 200 组末尾"));
    assert.equal(byLabel("任务组 1 提示词").value,"白底0\n补充尾词");
    assert.equal(document.querySelector(".batch-groups__mapping-row p").title,"白底0\n补充尾词");
    await setValue(byLabel("查找任务组"),"商品150");
    assert.equal(byLabel("任务组 151 提示词").value,"手写150\n补充尾词");
    await click(mode("覆盖"));
    await setValue(document.querySelector("#group-common-prompt"),"覆盖正文");
    await click(button("覆盖全部 200 组提示词"));
    assert.equal(byLabel("任务组 151 提示词").value,"覆盖正文");
    assert.equal(document.querySelector(".batch-groups__mapping-row p").title,"覆盖正文");
    await click(mode("追加"));
    await setValue(document.querySelector("#group-common-prompt"),"最终尾词");
    await click(button("追加到全部 200 组末尾"));
    assert.equal(button("提交批量改图").disabled,false);
    await click(button("提交批量改图"));
    assert.equal(posts[0].groups.length,200);
    assert.ok(posts[0].groups.every((g) =>g.prompt==="覆盖正文\n最终尾词"));
  } finally {await unmount();}
});

test("uniform output count updates all 200 groups across pagination and search, recalculates cost, and preserves individual edits in the submitted payload", async () => {
  await mount();
  try {
    await chooseFiles("选择任务组文件夹",Array.from({length:200},(_,i)=>picture(`素材/商品${i}/参考.png`)),
    );
    const csv="文件夹名,提示词\n"+Array.from({length:200},(_,i)=>`商品${i},白底${i}`).join("\n");
    await chooseFiles("选择任务组提示词文件",[new File([csv],"p.csv")]);
    await setValue(byLabel("统一每组生成张数"),"2");
    assert.match(document.querySelector(".batch-groups__output-settings").textContent,/200 组 × 2 张 = 400 张/,
    );
    await click(button("应用到全部 200 组"));
    assert.match(document.querySelector(".batch-groups__summary").textContent,/生成 400 张/);
    assert.match(document.querySelector(".tool-cost").textContent,/预计 2800 积分/);
    await click(button("下一页任务组"));
    assert.equal(byLabel("任务组 21 生成张数").value,"2");
    await setValue(byLabel("查找任务组"),"商品199");
    await setValue(byLabel("统一每组生成张数"),"3");
    await click(button("应用到全部 200 组"));
    assert.equal(byLabel("任务组 200 生成张数").value,"3");
    assert.match(document.querySelector(".batch-groups__summary").textContent,/生成 600 张/);
    await setValue(byLabel("查找任务组"),"");
    assert.equal(byLabel("任务组 1 生成张数").value,"3");
    await setValue(byLabel("任务组 1 生成张数"),"1");
    assert.match(document.querySelector(".tool-cost").textContent,/预计 4186 积分/);
    await click(button("提交批量改图"));
    assert.equal(posts[0].groups.length,200);
    assert.equal(posts[0].groups[0].output_count,1);
    assert.ok(posts[0].groups.slice(1).every((g) =>g.output_count===3));
    assert.equal(posts[0].groups.reduce((n,g)=>n+g.output_count,0),598,
    );
  } finally {await unmount();}
});

test("uniform output count rejects invalid inputs and totals above the configured site limit without changing drafts", async () => {
  await mount(true,50);
  try {
    await chooseFiles("选择任务组文件夹",Array.from({length:30},(_,i)=>picture(`素材/商品${i}/参考.png`)),
    );
    for(const value of ["","0","10","1.5","2"]) {
      await setValue(byLabel("统一每组生成张数"),value);
      assert.equal(button("应用到全部 30 组").disabled,true);
      assert.equal(byLabel("任务组 1 生成张数").value,"1");
    }
    assert.match(document.querySelector(".batch-groups__output-settings").textContent,/超过单批 50 张上限/,
    );
    assert.match(document.querySelector(".batch-groups__summary").textContent,/生成 30 张/);
    await setValue(byLabel("统一每组生成张数"),"1");
    assert.equal(button("应用到全部 30 组").disabled,false);
    assert.equal(uploads.length,0);
    assert.equal(posts.length,0);
  } finally {await unmount();}
});

for (const promptsFirst of [false,true]) test(`200 named TXT prompts automatically match folder groups with ${promptsFirst ? "prompts" : "ZIP"} imported first`, async () => {
  const {zipSync,strToU8}=await import("fflate");
  await mount();
  try {
    const entries={};
    for(let i=1;i<=200;i++) {
      const folder= `测试组_${String(i).padStart(3, "0")}`;
      entries[`${folder}/正面.png`]=strToU8("front");
      entries[`${folder}/侧面.png`]=strToU8("side");
    }
    const zip=new File([zipSync(entries)],"200组.zip");
    const txt=new File([Array.from({length:200},(_,i)=>{
      const id=String(200-i).padStart(3,"0");
      return `本任务对应文件夹“测试组_${id}”，商品编号 ${id}。保留编号和颜色`;
    }).join("\n"),
        ],
        "200组提示词.txt",
      );
    if(promptsFirst) {
      await chooseFiles("选择任务组提示词文件",[txt]);
      assert.match(document.querySelector(".batch-groups__mapping").textContent,/0\/200/);
      await chooseFiles("选择任务组 ZIP",[zip]);
    } else {
      await chooseFiles("选择任务组 ZIP",[zip]);
      await chooseFiles("选择任务组提示词文件",[txt]);
    }
    assert.match(document.querySelector(".batch-groups__mapping").textContent,/200\/200/);
    assert.equal(byLabel("任务组 1 提示词").value,
        "本任务对应文件夹“测试组_001”，商品编号 001。保留编号和颜色",
      );
    assert.match(document.querySelector(".batch-groups__message").textContent,promptsFirst ? /已添加 200 个任务组/ : /200 条包含文件夹名/,
      );
    assert.equal(button("提交批量改图").disabled,false);
    assert.ok(button("TXT 模板"));
    assert.equal(uploads.length,0);
  } finally { await unmount(); }
});

test("default image upload accepts a 200-folder ZIP and automatically opens the grouped editor without uploading the archive as an image", async () => {
  const { zipSync, strToU8 } = await import("fflate");
  await mount(false);
  try {
    const input=byLabel("上传批量改图图片或 ZIP");
    assert.match(input.accept,/\.zip/);
    assert.ok(button("导入 ZIP 按文件夹分组"));
    const entries={};
    for(let i=1;i<=200;i++) {
      entries[`测试组_${String(i).padStart(3, "0")}/正面.png`]=strToU8("front");
      entries[`测试组_${String(i).padStart(3, "0")}/侧面.png`]=strToU8("side");
    }
    await chooseFiles("上传批量改图图片或 ZIP",[new File([zipSync(entries)],"200组参考图.zip",{type:"application/zip"}),
    ]);
    assert.equal(button("文件夹任务组").getAttribute("aria-checked"),"true");
    assert.equal(document.querySelectorAll(".batch-group-card").length,20);
    assert.match(document.querySelector(".batch-groups__summary").textContent,/200 组 · 400 张参考图 · 生成 200 张/,
    );
    assert.equal(uploads.length,0);
    const csv="文件夹名,提示词\n"+Array.from({length:200},(_,i)=> `测试组_${String(200 - i).padStart(3, "0")},白底${200 - i}`,
      ).join("\n");
    await chooseFiles("选择任务组提示词文件",[new File([csv],"200.csv")]);
    assert.match(document.querySelector(".batch-groups__mapping").textContent,/200\/200/);
    assert.equal(byLabel("任务组 1 提示词").value,"白底1");
    assert.equal(button("提交批量改图").disabled,false);
  } finally { await unmount(); }
});

test("default ZIP shortcut opens a ZIP picker; invalid or mixed archives preserve the original mode and can be retried", async () => {
  const { zipSync, strToU8 } = await import("fflate");
  await mount(false);
  try {
    const picker=byLabel("从默认入口导入 ZIP");
    assert.match(picker.accept,/application\/zip/);
    let opened=false;
    picker.click=()=>{opened=true;};
    await click(button("导入 ZIP 按文件夹分组"));
    assert.equal(opened,true);
    await chooseFiles("上传批量改图图片或 ZIP",[picture("原散图.png")]);
    assert.equal(uploads.length,1);
    assert.equal(document.querySelectorAll(".batch-edit-asset-item").length,1);
    await chooseFiles("从默认入口导入 ZIP",[new File(["broken"],"损坏.zip")]);
    assert.equal(button("统一提示词").getAttribute("aria-checked"),"true");
    assert.equal(document.querySelectorAll(".batch-group-card").length,0);
    assert.equal(uploads.length,1);
    assert.equal(document.querySelectorAll(".batch-edit-asset-item").length,1);
    assert.match(document.body.textContent,/ZIP|没有找到/);
    const zip=new File([zipSync({"商品A/正面.png":strToU8("front")})],"素材.ZIP");
    await chooseFiles("上传批量改图图片或 ZIP",[zip,picture("图片.png")]);
    assert.match(document.body.textContent,/一次选择一个 ZIP/);
    assert.equal(uploads.length,1);
    await chooseFiles("从默认入口导入 ZIP",[zip]);
    assert.equal(button("文件夹任务组").getAttribute("aria-checked"),"true");
    assert.equal(document.querySelectorAll(".batch-group-card").length,1);
    assert.equal(document.querySelectorAll(".batch-edit-asset-item").length,0);
    await click(button("统一提示词"));
    assert.equal(document.querySelectorAll(".batch-edit-asset-item").length,1);
    await click(button("文件夹任务组"));
    assert.equal(document.querySelectorAll(".batch-group-card").length,1);
  } finally { await unmount(); }
});

test("rendered page imports folders + reversed XLSX rows, previews output-based cost, retries the same batch, and displays all task groups", async () => {
  await mount();
  try {
    await chooseFiles("选择任务组文件夹", [
      picture("素材/商品A/正面.png"),
      picture("素材/商品A/侧面.png"),
      picture("素材/商品B/包装.png"),
    ]);
    assert.equal(document.querySelectorAll(".batch-group-card").length, 2);
    const book = utils.book_new();
    utils.book_append_sheet(
      book,
      utils.aoa_to_sheet([
        ["文件夹名", "提示词"],
        ["商品B", "客厅包装"],
        ["商品A", "白底商品"],
      ]),
      "提示词",
    );
    await chooseFiles("选择任务组提示词文件", [
      new File([write(book, { type: "array", bookType: "xlsx" })], "prompts.xlsx"),
    ]);
    assert.equal(byLabel("任务组 1 提示词").value, "白底商品");
    assert.equal(byLabel("任务组 2 提示词").value, "客厅包装");
    await setValue(byLabel("任务组 1 生成张数"), "2");
    assert.match(
      document.querySelector(".batch-groups__summary").textContent,
      /2 组 · 3 张参考图 · 生成 3 张/,
    );
    assert.match(document.querySelector(".tool-cost").textContent, /预计 21 积分/);
    assert.equal(button("提交批量改图").disabled, false);
    loseResponse = true;
    await click(button("提交批量改图"));
    assert.match(document.body.textContent, /模拟提交响应丢失/);
    assert.equal(document.querySelectorAll(".batch-group-card").length, 2);
    await click(button("提交批量改图"));
    assert.equal(posts.length, 2);
    assert.deepEqual(posts[0], posts[1]);
    assert.equal(uploads.length, 3);
    assert.deepEqual(
      posts[0].groups.map((g) => [
        g.group_name,
        g.prompt,
        g.input_image_ids.length,
        g.output_count,
      ]),
      [
        ["商品A", "白底商品", 2, 2],
        ["商品B", "客厅包装", 1, 1],
      ],
    );
    assert.equal(posts[0].prompt_mode, "grouped");
    assert.deepEqual(posts[0].input_image_ids, []);
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    await click(button("展开具体记录（3）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 3);
    assert.equal(document.querySelectorAll(".batch-group-card").length, 0);
    assert.match(document.querySelector(".result-preview-panel").textContent, /商品A/);
  } finally {
    await unmount();
  }
});
test("TXT stays unmatched, manual mapping and shared fill resolve drafts, conflicts and model limits block submit", async () => {
  await mount();
  try {
    await chooseFiles("选择任务组文件夹", [
      picture("素材/商品A/正面.png"),
      picture("素材/商品A/侧面.png"),
      picture("素材/商品B/包装.png"),
    ]);
    await chooseFiles("选择任务组提示词文件", [new File(["TXT白底"], "prompts.txt")]);
    assert.equal(byLabel("提示词 1 对应任务组").value, "");
    assert.equal(button("提交批量改图").disabled, true);
    const target = [...byLabel("提示词 1 对应任务组").options][1].value;
    await select(byLabel("提示词 1 对应任务组"), target);
    await setValue(document.querySelector("#group-common-prompt"), "统一柔光");
    await click(button("填充缺少的提示词"));
    assert.equal(byLabel("任务组 1 提示词").value, "TXT白底");
    assert.equal(byLabel("任务组 2 提示词").value, "统一柔光");
    assert.equal(button("提交批量改图").disabled, false);
    await chooseFiles("选择任务组提示词文件", [new File(["第二条"], "extra.txt")]);
    await select(byLabel("提示词 2 对应任务组"), target);
    assert.match(document.body.textContent, /提示词冲突/);
    assert.equal(button("提交批量改图").disabled, true);
    await click(byLabel("移除导入提示词 2"));
    assert.equal(button("提交批量改图").disabled, false);
    await click(button("移除组"));
    assert.equal(document.querySelectorAll(".batch-group-card").length, 2);
    await click(button("保留"));
    assert.equal(document.querySelectorAll(".batch-group-card").length, 2);
    await setValue(byLabel("任务组 1 生成张数"), "10");
    assert.equal(button("提交批量改图").disabled, true);
    assert.equal(posts.length, 0);
    assert.equal(uploads.length, 0);
  } finally {
    await unmount();
  }
});

test("rendered ZIP import flags too many references, removal resolves the model limit and selecting the first reference changes submitted order", async () => {
  const { zipSync, strToU8 } = await import("fflate");
  await mount();
  try {
    const packed = zipSync({
      "商品A/正面.png": strToU8("front"),
      "商品A/侧面.png": strToU8("side"),
      "商品A/包装.png": strToU8("pack"),
    });
    await chooseFiles("选择任务组 ZIP", [new File([packed], "素材.zip")]);
    assert.equal(document.querySelectorAll(".batch-group-card").length, 1);
    await setValue(byLabel("任务组 1 提示词"), "白底商品");
    assert.equal(button("提交批量改图").disabled, true);
    assert.match(document.body.textContent, /1–2 张参考图/);
    await click(byLabel("从任务组 1 移除 包装.png"));
    assert.equal(button("提交批量改图").disabled, false);
    await click(button("设为首图"));
    const filenames = [...document.querySelectorAll(".batch-group-card__images figcaption")].map(
      (el) => el.textContent,
    );
    assert.deepEqual(filenames, ["侧面.png", "正面.png"]);
    await click(button("提交批量改图"));
    assert.deepEqual(uploads, ["侧面.png", "正面.png"]);
    assert.equal(posts[0].groups[0].input_image_ids.length, 2);
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    await click(button("展开具体记录（1）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 1);
  } finally {
    await unmount();
  }
});

test("1000 folder groups auto-match, paginate and search, submit together, then poll in batches of at most 200", async () => {
  await mount();
  try {
    await chooseFiles(
      "选择任务组文件夹",
      Array.from({ length: 1000 }, (_, i) => picture(`素材/商品${i}/参考.png`)),
    );
    assert.equal(document.querySelectorAll(".batch-group-card").length, 20);
    assert.match(
      document.querySelector(".batch-groups__summary").textContent,
      /1000 组.*生成 1000 张/,
    );
    await click(button("下一页任务组"));
    assert.ok(byLabel("任务组 21 名称"));
    await setValue(byLabel("查找任务组"), "商品999");
    assert.equal(document.querySelectorAll(".batch-group-card").length, 1);
    assert.ok(byLabel("任务组 1000 名称"));
    const csv =
      "文件夹名,提示词\n" +
      Array.from({ length: 1000 }, (_, i) => `商品${999 - i},白底${999 - i}`).join("\n");
    await chooseFiles("选择任务组提示词文件", [new File([csv], "1000.csv")]);
    assert.equal(byLabel("任务组 1000 提示词").value, "白底999");
    assert.match(document.querySelector(".batch-groups__mapping").textContent, /1000\/1000/);
    assert.equal(document.querySelectorAll(".batch-groups__mapping-row").length, 20);
    assert.equal(button("提交批量改图").disabled, false);
    assert.match(document.querySelector(".tool-cost").textContent, /预计 7000 积分/);
    await click(button("提交批量改图"));
    assert.equal(posts[0].groups.length, 1000);
    assert.equal(uploads.length, 1000);
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    assert.equal(statusRequests.length, 0);
    await click(button("展开具体记录（1000）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 40);
    await click(button("加载更多批次记录"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 80);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 1700));
    });
    assert.ok(statusRequests.length >= 1);
    assert.ok(statusRequests.every((ids) => ids.length <= 200));
    assert.equal(new Set(statusRequests.flat()).size, 80);
  } finally {
    await unmount();
  }
});


test("ordinary batch generation keeps its key after a lost response and renews it after success", async () => {
  await mount(false, 2000, "batch-generate");
  try {
    const prompt = "leaf\nflower";
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), prompt);
    loseResponse = true;
    await click(button("提交批量任务"));
    assert.match(document.body.textContent, /模拟提交响应丢失/);
    assert.ok(posts[0].batch_id);
    await click(button("提交批量任务"));
    assert.equal(posts[1].batch_id, posts[0].batch_id);
    assert.match(document.body.textContent, /已提交 2 个任务/);
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), prompt);
    await click(button("提交批量任务"));
    assert.notEqual(posts[2].batch_id, posts[0].batch_id);
  } finally { await unmount(); }
});

test("named single-column import preserves multiline prompts and folders through submission", async () => {
  await mount(false, 10000, "batch-generate");
  try {
    asyncUploadFixture = true;
    const book = utils.book_new();
    const prompts = ["portrait 2:3; 10×15cm; 300dpi\nKeep this newline", "second prompt"];
    utils.book_append_sheet(book, utils.aoa_to_sheet([["【XMAS-SER-001】"], [prompts[0]], [], ["【XMAS-SER-480】"], [prompts[1]]]), "提示词");
    const file = new File([write(book, { bookType: "xlsx", type: "array" })], "series.xlsx");
    const input = document.querySelector('input[accept^=".txt,.csv,.xlsx,.xls"]');
    assert.ok(input);
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    await settle();
    assert.match(document.body.textContent, /已导入 2 条提示词 · 2 个文件夹/);
    assert.equal(button("一词多图").disabled, true);
    assert.equal(document.querySelector("textarea.prompt-mention-editor--plain"), null);
    // An invalid replacement must not erase the valid import.
    Object.defineProperty(input, "files", { value: [new File(["bad"], "bad.xlsx")], configurable: true });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    await settle();
    assert.match(document.body.textContent, /格式不符/);
    await click(button("提交批量任务"));
    assert.deepEqual(uploadedManifests[0].prompts, prompts);
    assert.deepEqual(uploadedManifests[0].folder_names, ["【XMAS-SER-001】", "【XMAS-SER-480】"]);
    assert.ok(document.querySelector("textarea.prompt-mention-editor--plain"));
  } finally { await unmount(); }
});

test("500 long prompts upload automatically and pending intake survives remount until task creation", async () => {
  await mount(false, 2000, "batch-generate");
  let batchId;
  try {
    asyncUploadFixture = true;
    const prompts = Array.from({ length: 500 }, (_, i) => `${i}:` + "完整长提示词内容 ".repeat(600));
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), prompts.join("\n"));
    await click(button("提交批量任务"));
    assert.equal(uploadedManifests.length, 1);
    assert.deepEqual(uploadedManifests[0].prompts, prompts.map(p => p.trim()));
    batchId = uploadedManifests[0].batch_id;
    assert.match(document.body.textContent, /已接收 500 条提示词/);
    assert.match(document.querySelector(".batch-progress").textContent, /正在创建任务/);
    assert.equal(button("展开具体记录（500）").disabled, true);
  } finally {
    await unmount();
  }
  await mount(false, 2000, "batch-generate", [summary(batchId, { task_count: 500, pending_count: 500, submission_status: "queued" })]);
  try {
    assert.match(document.querySelector(".batch-progress").textContent, /正在创建任务/);
    batchStatusFixture = [summary(batchId, { task_count: 500, queued_count: 500 })];
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 3100)); });
    assert.match(document.querySelector(".batch-progress").textContent, /批次处理中/);
    assert.equal(button("展开具体记录（500）").disabled, false);
    batchStatusFixture = [summary(batchId, { task_count: 500, submission_status: "failed", submission_error: "任务创建失败，余额已退还，请重新提交" })];
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 3100)); });
    assert.match(document.querySelector(".batch-progress").textContent, /批次提交失败/);
    assert.match(document.querySelector(".batch-progress [role=alert]").textContent, /余额已退还/);
  } finally {
    await unmount();
  }
});

test("batch generation reports all 2000 submissions despite an 80-card response and recovers batches after remount", async () => {
  await mount(false, 2000, "batch-generate");
  try {
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), Array.from({length:2000},(_,i)=>`prompt-${i}`).join("\n"),
    );
    await click(button("提交批量任务"));
    assert.match(document.body.textContent,/已提交 2000 个任务/);
    assert.match(document.querySelector(".batch-progress").textContent,/共 2000 张/);
    assert.equal(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow"),"0");
    assert.equal(button("打包下载已成功（0）").disabled,true);
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    await click(button("展开具体记录（2000）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 40);
    assert.equal(batchListRequests.length,2,"new submission refreshes persisted summary");
  } finally { await unmount(); }
  await mount(false,2000,"batch-generate",[summary("new-batch", {succeeded_count:1990,failed_count:10,downloadable_count:1990}),
  ]);
  try {
    assert.match(document.querySelector(".batch-progress").textContent,/批次已结束 · 有失败/);
    assert.equal(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow"),"100",
    );
    assert.equal(document.querySelectorAll(".tool-result-card").length,0,"batch download works with no loaded cards",
    );
    await click(button("打包下载已成功（1990）"));
    assert.deepEqual(exportRequests,[{batch_id:"new-batch"}]);
    assert.deepEqual(downloadLinks,["批量图片-new-batch.zip"]);
    assert.match(document.querySelector(".batch-progress").textContent,/ZIP/);
  } finally { await unmount(); }
});

test("batch polling updates full counts, exposes paginated failure reasons, and stops once terminal", async () => {
  await mount(false,2000,"batch-generate",[summary("active",{succeeded_count:1700,failed_count:25,downloadable_count:1700,queued_count:270,running_count:5,
    }),
  ]);
  try {
    const counts = () => [...document.querySelectorAll(".batch-progress__counts dd")].map((el) =>Number(el.textContent),
      );
    assert.deepEqual(counts(),[270,5,1700,25]);
    assert.equal(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow"),"86",
    );
    await click(button("打包下载已成功（1700）"));
    assert.match(document.querySelector(".batch-progress").textContent,/ZIP 已保存.*未完成 1 张/);
    failureFixture = Array.from({length:25},(_,i)=>taskRecord(125-i,"active",i<20?"failed":"refunded"),
    );
    failureFixture.push(taskRecord(999,"wrong-batch","failed"));
    await click(button("查看失败（25）"));
    assert.match(document.querySelector('[aria-label="批次失败详情"]').textContent,/模型超时/);
    assert.equal(document.querySelectorAll(".batch-progress__failures > div").length,20);
    await click(button("加载更多失败项"));
    assert.equal(document.querySelectorAll(".batch-progress__failures > div").length,25);
    assert.match(document.querySelector('[aria-label="批次失败详情"]').textContent,/已退款/);
    assert.deepEqual(failureRequests.map((q) =>[q.batch_id,q.status,q.limit,q.before_id]),[["active","failed","20",undefined],["active","failed","20","106"],
      ],
    );
    batchStatusFixture = [summary("active",{succeeded_count:1975,failed_count:25,downloadable_count:1975}),
    ];
    await act(async()=> {await new Promise((r) =>setTimeout(r,3100));});
    assert.deepEqual(counts(),[0,0,1975,25]);
    assert.equal(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow"),"100",
    );
    assert.deepEqual(batchStatusRequests,[["active"]]);
    await act(async()=> {await new Promise((r) =>setTimeout(r,3100));});
    assert.equal(batchStatusRequests.length,1,"completed batches stop polling");
  } finally {await unmount();}
});

test("batch list errors can be retried and pagination downloads the selected whole batch", async () => {
  rejectBatchList = true;
  await mount(false,2000,"batch-edit",[summary("first",{task_count:2,succeeded_count:2,downloadable_count:2})],[summary("second",{task_count:150,succeeded_count:150,downloadable_count:150})],
  );
  try {
    assert.match(document.querySelector('[role="alert"]').textContent,/模拟批次读取失败/);
    await click(button("重试"));
    await click(button("加载更多批次"));
    assert.equal(document.querySelectorAll(".batch-progress__card").length,2);
    assert.match(batchListRequests.at(-1),/before_id=2000/);
    await click(button("打包下载已成功（150）"));
    assert.deepEqual(exportRequests,[{task_ids:[],batch_id:"second"}]);
  } finally {await unmount();}
});

test("batch retry previews cost and continues in the original batch without changing its total", async () => {
  await mount(false, 2000, "batch-generate", [
    summary("source-retry", {
      succeeded_count: 1980,
      failed_count: 10,
      queued_count: 10,
      downloadable_count: 1980,
    }),
  ]);
  try {
    historyFixture = Array.from({length:10}, (_, i) => taskRecord(7000+i,"source-retry","failed"));
    await click(button("展开具体记录（2000）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 10);
    const priorDetailRequests = detailRequests.length;
    const trigger = button("重试失败项（10）");
    trigger.focus();
    await click(trigger);
    const dialog = document.querySelector('[role="dialog"]');
    assert.match(dialog.textContent, /10 张/);
    assert.match(dialog.textContent, /70 积分/);
    assert.deepEqual(retryQuotes, [{ batch_id: "source-retry" }]);
    assert.equal(retryRequests.length, 0);
    const confirm = button("确认重试");
    confirm.focus();
    document.dispatchEvent(
      new window.KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true }),
    );
    assert.equal(document.activeElement, document.querySelector('[aria-label="关闭重试窗口"]'));
    await act(async () => {
      confirm.click();
      confirm.click();
      await new Promise((r) => setTimeout(r, 80));
    });
    await settle();
    assert.equal(retryRequests.length, 1);
    assert.equal(retryRequests[0].task_ids.length, 10);
    assert.equal(retryRequests[0].quote_token, "a".repeat(64));
    assert.ok(retryRequests[0].request_id);
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(document.body.style.overflow, "");
    assert.match(document.querySelector(".batch-progress").textContent, /已接收 10 个失败重试任务/);
    assert.match(
      document.querySelector('[aria-label="批次 source-retry"]').textContent,
      /批次处理中/,
    );
    assert.equal(document.querySelectorAll(".batch-progress__card").length, 1);
    assert.match(document.querySelector(".batch-progress__card").textContent, /共 2000 张/);
    assert.ok(detailRequests.length > priorDetailRequests);
    assert.equal(document.querySelectorAll(".tool-result-card").length, 10);
  } finally {
    await unmount();
  }
});

test("lost retry response retains the same request ID and quote when submitting again", async () => {
  await mount(false, 2000, "batch-edit", [
    summary("source-lost", { task_count: 2, failed_count: 2 }),
  ]);
  try {
    await click(button("重试失败项（2）"));
    retryFailure = "network";
    await click(button("确认重试"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    assert.match(document.querySelector('[role="dialog"]').textContent, /重复提交不会重复创建/);
    await click(button("确认重试"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    await settle();
    assert.equal(retryRequests.length, 2);
    assert.deepEqual(retryRequests[0], retryRequests[1]);
    assert.equal(document.querySelectorAll('[aria-label="批次 source-lost"]').length, 1);
  } finally {
    await unmount();
  }
});

test("stale retry prices require a fresh preview and cancellation creates no retry tasks", async () => {
  await mount(false, 2000, "batch-generate", [
    summary("source-price", { task_count: 2, failed_count: 2 }),
  ]);
  try {
    await click(button("重试失败项（2）"));
    retryFailure = "conflict";
    await click(button("确认重试"));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 60));
    });
    assert.equal(button("确认重试").disabled, true);
    assert.match(document.querySelector('[role="dialog"]').textContent, /价格已变化/);
    retryCost = 12;
    await click(button("重新获取费用"));
    assert.match(document.querySelector('[role="dialog"]').textContent, /24 积分/);
    await click(button("取消"));
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(retryRequests.length, 1);
    const trigger = button("重试失败项（2）");
    trigger.focus();
    await click(trigger);
    await act(async () =>
      document.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", bubbles: true })),
    );
    await settle();
    assert.equal(document.querySelector('[role="dialog"]'), null);
    assert.equal(document.activeElement, trigger);
  } finally {
    await unmount();
  }
});

test("retry quote errors offer recovery and already retried attempts have no active retry button", async () => {
  await mount(false, 2000, "batch-edit", [
    summary("source-quote", {
      task_count: 3,
      failed_count: 3,
      retryable_count: 2,
      already_retried_count: 1,
    }),
  ]);
  try {
    assert.match(document.querySelector(".batch-progress").textContent, /历史版本已另批重试 1 项/);
    retryFailure = "quote";
    await click(button("重试失败项（2）"));
    assert.match(document.querySelector('[role="dialog"]').textContent, /原模型不可用/);
    assert.equal(button("确认重试").disabled, true);
    await click(button("重新获取费用"));
    assert.match(document.querySelector('[role="dialog"]').textContent, /14 积分/);
    await click(button("取消"));
    assert.equal(retryRequests.length, 0);
  } finally {
    await unmount();
  }
});

test("batch edit keeps records inside their selected batch, paginates and retains existing card actions", async () => {
  await mount(false, 2000, "batch-edit", [
    summary("batch-A", { task_count: 45, succeeded_count: 45, downloadable_count: 45 }),
    summary("batch-B", { task_count: 2, succeeded_count: 2, downloadable_count: 2 }),
  ]);
  try {
    historyFixture = [
      ...Array.from({ length: 45 }, (_, i) => ({
        ...taskRecord(100 + i, "batch-A", "succeeded"),
        work_type: "batch_edit",
        input_group_name: "商品A",
        input_images: [{ id: 1, url: "https://cdn.test/input.png" }],
        output_images: [{ id: 2, url: "https://cdn.test/output.png" }],
      })),
      ...Array.from({ length: 2 }, (_, i) => taskRecord(300 + i, "batch-B", "succeeded")),
    ];
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    assert.equal(detailRequests.length, 0, "collapsed batches never load a mixed history feed");
    await click(button("展开具体记录（45）"));
    const selected = document.querySelector('[aria-label="批次 batch-A"]');
    assert.equal(selected.querySelectorAll(".tool-result-card").length, 40);
    assert.equal(
      document.querySelector('[aria-label="批次 batch-B"]').querySelectorAll(".tool-result-card")
        .length,
      0,
    );
    assert.match(selected.textContent, /商品A/);
    for (const action of ["收藏", "预览", "下载", "删除"])
      assert.ok(
        [...selected.querySelectorAll("button")].some((b) => b.textContent.includes(action)),
      );
    await click(button("加载更多批次记录"));
    assert.equal(selected.querySelectorAll(".tool-result-card").length, 45);
    assert.deepEqual(
      detailRequests.map((q) => [q.batch_id, q.before_id, q.limit]),
      [
        ["batch-A", undefined, "40"],
        ["batch-A", "105", "40"],
      ],
    );
    await click(button("收起具体记录"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 0);
    await click(button("展开具体记录（2）"));
    assert.equal(document.querySelectorAll(".tool-result-card").length, 2);
    assert.equal(
      document.querySelector('[aria-label="批次 batch-A"]').querySelectorAll(".tool-result-card")
        .length,
      0,
    );
    assert.equal(detailRequests.at(-1).batch_id, "batch-B");
    assert.equal(statusRequests.length, 0, "completed records do not poll");
  } finally {
    await unmount();
  }
});

test("unsupported browsers show CDN download requirements without falling back to server image transfer", async () => {
  const picker = window.showSaveFilePicker;
  window.showSaveFilePicker = undefined;
  await mount(false, 20000, "batch-generate", [summary("unsupported", { task_count: 1, succeeded_count: 1, downloadable_count: 1 })]);
  try {
    await click(button("打包下载已成功（1）"));
    assert.match(document.querySelector(".batch-progress").textContent, /电脑端 Chrome 或 Edge/);
    assert.deepEqual(exportRequests, []);
    assert.deepEqual(downloadLinks, []);
    assert.equal(button("打包下载已成功（1）").disabled, false);
  } finally { window.showSaveFilePicker = picker; await unmount(); }
});

test("cancelling the file picker starts no CDN or server download and restores the button", async () => {
  const picker = window.showSaveFilePicker;
  window.showSaveFilePicker = async () => { throw new DOMException("cancelled", "AbortError"); };
  await mount(false, 20000, "batch-generate", [summary("cancel-save", { task_count: 1, succeeded_count: 1, downloadable_count: 1 })]);
  try {
    await click(button("打包下载已成功（1）"));
    assert.match(document.querySelector(".batch-progress").textContent, /下载已取消/);
    assert.deepEqual(exportRequests, []);
    assert.equal(button("打包下载已成功（1）").disabled, false);
  } finally { window.showSaveFilePicker = picker; await unmount(); }
});


test("VIP quote shows fixed surcharge separately and exact fractional batch total", async () => {
  priceQuoteFixture = { credit_cost: 2.8, pricing: { base_price: "1", discount_rate: "0.8", fixed_surcharge: "2", vip_tier_name: "VIP1" } };
  await mount(false, 20000, "batch-generate");
  try {
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), "first\nsecond\nthird");
    const badge = document.querySelector(".tool-cost").textContent;
    assert.match(badge, /预计 8.4 积分/);
    assert.match(badge, /VIP1：基础 1 × 0.8 \+ 固定 2 = 2.8 积分/);
    assert.doesNotMatch(badge, /8.399999/);
  } finally { await unmount(); priceQuoteFixture = { credit_cost: 7 }; }
});


test("changing quality requotes displayed credits and submits the same quality", async () => {
  useQualityPrices = true; quoteRequests = [];
  await mount(false, 20000, "batch-generate");
  try {
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), "first\nsecond");
    for (const [quality, label, cost] of [["low", "低", 3], ["high", "高", 6], ["medium", "中", 5]]) {
      const field = [...document.querySelectorAll(".config-field")].find(el => el.firstElementChild?.textContent === "质量");
      await click(field.querySelector("button"));
      await click([...byLabel("选择生成质量").querySelectorAll("button")].find(el => el.textContent === label));
      assert.equal(quoteRequests.at(-1).quality, quality);
      assert.match(document.querySelector(".tool-cost").textContent, new RegExp(`预计 ${cost * 2} 积分`));
    }
    await click(button("提交批量任务"));
    assert.equal(posts.at(-1).quality, "medium");
  } finally { await unmount(); useQualityPrices = false; }
});

test("custom batch dimensions and WebP survive file submission; invalid sizes cannot submit", async () => {
  model.supports_custom_size = true;
  model.supports_output_format = true;
  await mount(false, 20000, "batch-generate");
  try {
    await click(button("自定义"));
    const fields = document.querySelectorAll(".image-custom-size input");
    await setValue(fields[0], "2048");
    await setValue(fields[1], "3072");
    await click(button("WebP"));
    await setValue(document.querySelector("textarea.prompt-mention-editor--plain"), "first prompt\nsecond prompt");
    await setValue(fields[0], "2049");
    await click(button("提交批量任务"));
    assert.equal(posts.length, 0);
    assert.match(document.body.textContent, /16 的正整数倍/);
    await setValue(fields[0], "2048");
    await click(button("提交批量任务"));
    assert.equal(uploadedManifests.length, 1);
    assert.equal(uploadedManifests[0].size, "2048x3072");
    assert.equal(uploadedManifests[0].output_format, "webp");
    assert.deepEqual(uploadedManifests[0].prompts, ["first prompt", "second prompt"]);
    const preference = JSON.parse(window.localStorage.getItem("image2ai.toolPreference.batch_generate"));
    assert.equal(preference.imageSize, "2048x3072");
    assert.equal(preference.outputFormat, "webp");
  } finally {
    await unmount();
    delete model.supports_custom_size;
    delete model.supports_output_format;
  }
});
