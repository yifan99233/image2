import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";

await build({
  entryPoints: ["src/services/imageTasks.ts"],
  outfile: "node_modules/.tmp/image-batch-submission-test.mjs",
  bundle: true,
  format: "esm",
  platform: "node",
  alias: { "@": process.cwd() + "/src" },
  define: { "import.meta.env": '{"VITE_API_BASE_URL":"http://test"}' },
});
const { imageTaskService } = await import("../node_modules/.tmp/image-batch-submission-test.mjs");

for (const mode of ["batch_generate", "batch_edit", "grouped"]) {
  test(`${mode} submission survives 31 seconds but still has a bounded timeout`, async () => {
    const originalWindow = globalThis.window;
    const originalFetch = globalThis.fetch;
    let timer, deadline, signal, finish;
    globalThis.window = {
      localStorage: { getItem: () => null },
      setTimeout(callback, delay) { timer = callback; deadline = delay; return 1; },
      clearTimeout() { timer = null; },
    };
    globalThis.fetch = async (_url, options) => {
      signal = options.signal;
      return new Promise((resolve, reject) => {
        finish = resolve;
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    };
    const payload = {
      work_type: mode === "grouped" ? "batch_edit" : mode,
      prompt_mode: mode === "grouped" ? "grouped" : undefined,
      model_id: 57, prompt: "leaf\nflower", resolution: "1k", aspect_ratio: "3:2",
    };
    try {
      const submission = imageTaskService.createBatch(payload, []);
      if (deadline <= 31_000) timer();
      assert.equal(signal.aborted, false, "client must wait for a batch taking more than 30 seconds");
      const data = { batch_id: "batch-test", task_count: 2, task_ids: [1, 2], tasks: [] };
      finish(new Response(JSON.stringify({ code: 0, data }), { status: 200 }));
      assert.deepEqual(await submission, data);
      assert.equal(timer, null, "completed request clears its timeout");

      const slowSubmission = imageTaskService.createBatch(payload, []);
      const rejection = assert.rejects(slowSubmission, { name: "TimeoutError" });
      assert.ok(deadline > 31_000 && deadline <= 1_800_000);
      timer();
      await rejection;
    } finally {
      globalThis.window = originalWindow;
      globalThis.fetch = originalFetch;
    }
  });
}

test("500 long prompts upload as a JSON file and receive a batch before tasks exist", async () => {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.window = { localStorage: { getItem: () => null }, setTimeout: () => 1, clearTimeout() {} };
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ code: 0, data: { batch_id: "batch-500", task_count: 500, task_ids: [], tasks: [], submission_status: "queued" } }), { status: 202 });
  };
  try {
    const prompts = Array.from({ length: 500 }, (_, i) => `${i}:` + "完整长提示词内容 ".repeat(600));
    const result = await imageTaskService.createBatch({ work_type: "batch_generate", batch_id: "batch-500", model_id: 57, prompt: prompts.join("\n"), resolution: "1k", aspect_ratio: "3:2" }, []);
    assert.equal(captured.url, "http://test/image-tasks/batch-upload");
    assert.ok(captured.options.body instanceof FormData);
    assert.equal(captured.options.headers.has("Content-Type"), false, "browser generates the multipart boundary");
    const file = captured.options.body.get("manifest");
    assert.ok(file.size > 1_000_000);
    const manifest = JSON.parse(await file.text());
    assert.equal(manifest.version, 1);
    assert.equal(manifest.batch_id, "batch-500");
    assert.deepEqual(manifest.prompts, prompts.map(p => p.trim()));
    assert.equal(manifest.prompt, undefined);
    assert.equal(result.submission_status, "queued");
    captured = null;
    await assert.rejects(imageTaskService.createBatch({ work_type: "batch_generate", model_id: 57, prompt: "过长的提示词", resolution: "1k", aspect_ratio: "3:2" }, [], { maxPromptChars: 2 }), /每条提示词/);
    await assert.rejects(imageTaskService.createBatch({ work_type: "batch_generate", model_id: 57, prompt: "提示词", resolution: "1k", aspect_ratio: "3:2" }, [], { maxBytes: 1 }), /上传大小限制/);
    assert.equal(captured, null, "invalid uploads fail before sending a request");
  } finally {
    globalThis.window = originalWindow;
    globalThis.fetch = originalFetch;
  }
});
