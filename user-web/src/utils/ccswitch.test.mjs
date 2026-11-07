import assert from "node:assert/strict";
import test from "node:test";
import { URL } from "node:url";

globalThis.window = { btoa: globalThis.btoa };

const { buildCcsImportUrl } = await import("./ccswitch.ts");

const openAiKey = {
  key: "sk-test-only",
  group: { platform: "openai" },
};

test("keeps the existing Codex import as the default for OpenAI keys", () => {
  const url = new URL(buildCcsImportUrl(openAiKey, "https://api.example.com/", "测试服务"));

  assert.equal(url.protocol, "ccswitch:");
  assert.equal(url.searchParams.get("resource"), "provider");
  assert.equal(url.searchParams.get("app"), "codex");
  assert.equal(url.searchParams.get("model"), "gpt-5.6-sol");
  assert.equal(url.searchParams.get("endpoint"), "https://api.example.com/v1");
  assert.equal(url.searchParams.get("apiKey"), "sk-test-only");
});

test("builds a usable OpenCode provider import", () => {
  const url = new URL(
    buildCcsImportUrl(openAiKey, "https://api.example.com/", "测试服务", { app: "opencode" }),
  );

  assert.equal(url.searchParams.get("app"), "opencode");
  assert.equal(url.searchParams.get("model"), "gpt-5.6-sol");
  assert.equal(url.searchParams.get("endpoint"), "https://api.example.com/v1");
  assert.equal(url.searchParams.get("usageEnabled"), "true");
  assert.equal(url.searchParams.get("usageAutoInterval"), "30");
});

test("requires an explicit model when OpenCode cannot infer one", () => {
  const geminiKey = {
    key: "sk-test-only",
    group: { platform: "gemini" },
  };

  assert.throws(
    () => buildCcsImportUrl(geminiKey, "https://api.example.com", "测试服务", { app: "opencode" }),
    /需要指定可用模型/,
  );
});

test("accepts an explicit OpenCode model for other key platforms", () => {
  const geminiKey = {
    key: "sk-test-only",
    group: { platform: "gemini" },
  };
  const url = new URL(
    buildCcsImportUrl(geminiKey, "https://api.example.com", "测试服务", {
      app: "opencode",
      model: "gemini-test-model",
    }),
  );

  assert.equal(url.searchParams.get("app"), "opencode");
  assert.equal(url.searchParams.get("model"), "gemini-test-model");
});
