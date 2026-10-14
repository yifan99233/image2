import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement } from "react";

const dom = new JSDOM('<div id="root"></div>', { url: "http://test/tasks" });
for (const name of [
  "window",
  "document",
  "HTMLElement",
  "HTMLInputElement",
  "HTMLTextAreaElement",
  "Event",
  "CustomEvent",
])
  globalThis[name] = dom.window[name];
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");
await build({
  entryPoints: ["src/pages/management/TasksPage.tsx"],
  outfile: "node_modules/.tmp/tasks-ui.mjs",
  bundle: true,
  platform: "node",
  format: "esm",
  packages: "external",
  jsx: "automatic",
  define: { "import.meta.env": '{"VITE_ADMIN_API_BASE_URL":"http://test"}' },
});
const { TasksPage } = await import("../node_modules/.tmp/tasks-ui.mjs");
const records = Array.from({ length: 61 }, (_, i) => ({
  id: i + 1,
  task_no: `IMG-${i + 1}`,
  user_id: i < 50 ? 1 : i < 55 ? 2 : 3,
  username: i < 50 ? "张三" : i < 55 ? "李四" : "测试用户",
  model_name: "测试模型",
  status:
    i < 45
      ? "succeeded"
      : i < 50
        ? "refunded"
        : i < 55
          ? "failed"
          : i < 60
            ? "running"
            : "pending",
  prompt: "客厅",
  credit_cost: 7,
  is_gallery_featured: false,
  gallery_review_status: i < 30 ? "pending" : "none",
  output_image_url: "https://example.invalid/result.png",
  gallery_sort_order: 0,
  created_at: "2026-10-07T00:00:00Z",
}));
let root, queries, rejectNext, holdNext, held, errors;
window.addEventListener("admin-web:request-error", (event) =>
  errors.push(event.detail),
);
globalThis.fetch = async (url, options = {}) => {
  if (options.method === "PATCH") {
    const record = records.find((task) => task.id === Number(new URL(url).pathname.split("/").at(-2)));
    const payload = JSON.parse(options.body);
    record.is_gallery_featured = payload.featured;
    record.gallery_review_status = payload.featured ? "approved" : "rejected";
    record.reviewReason = payload.reason;
    return new Response(JSON.stringify({code:0, data:{}}), {headers:{"Content-Type":"application/json"}});
  }
  const params = new URL(url).searchParams;
  queries.push(Object.fromEntries(params));
  if (rejectNext) {
    rejectNext = false;
    throw new Error("模拟查询失败");
  }
  let items = records.filter(
    (task) =>
      (!params.get("status") ||
        (params.get("status") === "failed"
          ? ["failed", "refunded"].includes(task.status)
          : task.status === params.get("status"))) &&
      (!params.get("gallery_review_status") || task.gallery_review_status === params.get("gallery_review_status")) &&
      (!params.get("user_id") ||
        task.user_id === Number(params.get("user_id"))) &&
      (!params.get("username") ||
        task.username.includes(params.get("username"))) &&
      (!params.get("keyword") ||
        [task.task_no, task.username, task.model_name, task.prompt].some(
          (value) => value.includes(params.get("keyword")),
        )),
  );
  const page = Number(params.get("page_no")),
    size = Number(params.get("page_size"));
  const response = () =>
    new Response(
      JSON.stringify({
        code: 0,
        message: "ok",
        data: {
          items: items.slice((page - 1) * size, page * size),
          total: items.length,
          page,
          page_size: size,
        },
      }),
      { headers: { "Content-Type": "application/json" } },
    );
  if (holdNext) {
    const mode = holdNext;
    holdNext = false;
    return new Promise((resolve, reject) => {
      held = { signal: options.signal, resolve: () => resolve(response()) };
      if (mode === "abort")
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
    });
  }
  return response();
};
const button = (text) =>
  [...document.querySelectorAll("button")].find(
    (el) => el.textContent === text,
  );
const input = (label) => document.querySelector(`[aria-label="${label}"]`);
const select = (label) =>
  [...document.querySelectorAll("label.filter-select")]
    .find((el) => el.textContent.startsWith(label))
    .querySelector("select");
const settle = async () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 10));
  });
const click = async (el) => {
  assert.ok(el);
  await act(async () => el.click());
  await settle();
};
const value = async (el, text) => {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    ).set.call(el, text);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const choice = async (el, text) =>
  act(async () => {
    el.value = text;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
const submit = async () => {
  await act(async () =>
    document
      .querySelector('form[aria-label="任务查询条件"]')
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  await settle();
};
const mount = async () => {
  queries = [];
  errors = [];
  rejectNext = false;
  holdNext = false;
  held = null;
  root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(TasksPage)));
  await settle();
};
const unmount = async () => act(async () => root.unmount());

test("status, username and keyword combine on page one and survive page and page-size changes", async () => {
  await mount();
  try {
    assert.equal(document.querySelectorAll("tbody tr").length, 20);
    await click(button("下一页"));
    assert.equal(queries.at(-1).page_no, "2");
    await choice(select("任务状态"), "succeeded");
    await value(input("查询用户"), " 张三 ");
    await value(input("任务关键词"), " 客厅 ");
    await submit();
    assert.deepEqual(queries.at(-1), {
      keyword: "客厅",
      page_no: "1",
      page_size: "20",
      status: "succeeded",
      username: "张三",
    });
    assert.match(
      document.querySelector(".pagination-bar").textContent,
      /共 45 条/,
    );
    assert.ok(
      [...document.querySelectorAll("tbody tr")].every(
        (row) =>
          row.textContent.includes("成功") &&
          row.textContent.includes("用户 ID：1"),
      ),
    );
    await click(button("下一页"));
    assert.equal(queries.at(-1).status, "succeeded");
    assert.equal(queries.at(-1).username, "张三");
    await choice(document.querySelector(".page-size-select select"), "50");
    await settle();
    assert.equal(queries.at(-1).page_no, "1");
    assert.equal(queries.at(-1).page_size, "50");
    assert.equal(document.querySelectorAll("tbody tr").length, 45);
  } finally {
    await unmount();
  }
});

test("exact user ID query validates input, switches dimension, and reset clears every filter", async () => {
  await mount();
  try {
    await value(input("查询用户"), "张三");
    await choice(select("用户维度"), "id");
    assert.equal(input("查询用户").value, "");
    await choice(select("任务状态"), "failed");
    await value(input("查询用户"), "0");
    let count = queries.length;
    await submit();
    assert.equal(queries.length, count);
    assert.match(
      document.querySelector('[role="alert"]').textContent,
      /正整数/,
    );
    await value(input("查询用户"), "2");
    await submit();
    assert.equal(queries.at(-1).user_id, "2");
    assert.equal(queries.at(-1).username, undefined);
    assert.equal(document.querySelectorAll("tbody tr").length, 5);
    assert.ok(
      [...document.querySelectorAll("tbody tr")].every((row) =>
        row.textContent.includes("李四"),
      ),
    );
    await click(button("重置"));
    assert.equal(select("任务状态").value, "all");
    assert.equal(select("用户维度").value, "username");
    assert.equal(input("查询用户").value, "");
    assert.equal(queries.at(-1).user_id, undefined);
    assert.equal(queries.at(-1).status, undefined);
  } finally {
    await unmount();
  }
});

test("failed includes refunds, refunded and pending are individually queryable, and no matches show zero rows", async () => {
  await mount();
  try {
    await choice(select("任务状态"), "failed");
    await submit();
    assert.equal(document.querySelectorAll("tbody tr").length, 10);
    assert.equal(
      document.querySelectorAll("tbody .status-pill.failed").length,
      10,
    );
    await choice(select("任务状态"), "refunded");
    await submit();
    assert.equal(document.querySelectorAll("tbody tr").length, 5);
    await choice(select("任务状态"), "pending");
    await submit();
    assert.match(document.querySelector("tbody").textContent, /待处理/);
    await value(input("查询用户"), "不存在");
    await submit();
    assert.equal(document.querySelectorAll("tbody tr").length, 0);
    assert.match(document.body.textContent, /当前条件没有匹配任务/);
  } finally {
    await unmount();
  }
});

test("query failure is recoverable and retry retains the current user and status", async () => {
  await mount();
  try {
    await choice(select("任务状态"), "succeeded");
    await value(input("查询用户"), "张三");
    rejectNext = true;
    await submit();
    assert.match(document.body.textContent, /模拟查询失败/);
    assert.equal(document.querySelectorAll("tbody tr").length, 0);
    await click(button("重试"));
    assert.equal(queries.at(-1).username, "张三");
    assert.equal(queries.at(-1).status, "succeeded");
    assert.equal(document.querySelectorAll("tbody tr").length, 20);
  } finally {
    await unmount();
  }
});

test("slow stale results cannot replace a newer reset, and cancelled requests produce no global error", async () => {
  await mount();
  try {
    await value(input("查询用户"), "张三");
    holdNext = "late";
    await submit();
    const old = held;
    assert.match(document.body.textContent, /正在查询任务/);
    await click(button("重置"));
    assert.equal(old.signal.aborted, true);
    assert.equal(document.querySelectorAll("tbody tr").length, 20);
    await act(async () => old.resolve());
    await settle();
    assert.match(
      document.querySelector(".pagination-bar").textContent,
      /共 61 条/,
    );
    holdNext = "abort";
    await submit();
    await click(button("重置"));
    assert.equal(errors.length, 0);
    holdNext = "abort";
    await submit();
    await unmount();
    await settle();
    assert.equal(held.signal.aborted, true);
    assert.equal(errors.length, 0);
    root = null;
  } finally {
    if (root) await unmount();
  }
});


test("gallery moderation filters combine, paginate, approve and reject with a reason", async () => {
  await mount();
  try {
    await choice(select("广场状态"), "pending");
    await choice(select("任务状态"), "succeeded");
    await value(input("查询用户"), "张三");
    await submit();
    assert.equal(queries.at(-1).gallery_review_status, "pending");
    assert.equal(document.querySelectorAll("tbody tr").length, 20);
    await click(button("下一页"));
    assert.equal(queries.at(-1).gallery_review_status, "pending");
    assert.equal(queries.at(-1).status, "succeeded");
    assert.equal(document.querySelectorAll("tbody tr").length, 10);
    await click(button("上一页"));
    await click(button("审核通过"));
    assert.match(document.querySelector(".modal").textContent, /图片和提示词/);
    await click(button("通过并展示"));
    assert.equal(records[0].gallery_review_status, "approved");
    await click(button("驳回"));
    const reason = document.querySelector("textarea");
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,"value").set.call(reason,"内容不适合公开");
      reason.dispatchEvent(new Event("input",{bubbles:true}));
    });
    await click(button("确认驳回"));
    assert.equal(records[1].gallery_review_status,"rejected");
    assert.equal(records[1].reviewReason,"内容不适合公开");
    await click(button("重置"));
    assert.equal(queries.at(-1).gallery_review_status,undefined);
  } finally { await unmount(); }
});
