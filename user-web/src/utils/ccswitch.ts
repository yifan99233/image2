import type { OpenAgentKey } from "@/types/api";

export type CcsImportApp = "claude" | "codex" | "gemini" | "opencode";

export type CcsImportOptions = {
  app?: CcsImportApp;
  model?: string;
};

const USAGE_SCRIPT = `({
  request: {
    url: "{{baseUrl}}/v1/usage",
    method: "GET",
    headers: { "Authorization": "Bearer {{apiKey}}" }
  },
  extractor: function(response) {
    const remaining = response?.remaining ?? response?.quota?.remaining ?? response?.balance;
    const unit = response?.unit ?? response?.quota?.unit ?? "USD";
    return {
      isValid: response?.is_active ?? response?.isValid ?? true,
      remaining,
      unit
    };
  }
})`;

const encodeBase64 = (value: string) => window.btoa(value);
const DEFAULT_OPENAI_MODEL = "gpt-5.6-sol";

const defaultAppForPlatform = (platform: string): CcsImportApp =>
  platform === "openai" ? "codex" : platform === "gemini" ? "gemini" : "claude";

export function buildCcsImportUrl(
  key: OpenAgentKey,
  baseUrl: string,
  siteName: string,
  options: CcsImportOptions = {},
): string {
  const normalizedBaseUrl = baseUrl.replace(/\/+$/, "");
  const platform = key.group?.platform || "anthropic";
  const app = options.app || defaultAppForPlatform(platform);
  const model = options.model?.trim() || ((app === "codex" || app === "opencode") && platform === "openai" ? DEFAULT_OPENAI_MODEL : "");
  if (app === "opencode" && !model) {
    throw new Error("OpenCode 导入需要指定可用模型");
  }
  const endpoint = `${normalizedBaseUrl}/v1`;
  const params = new URLSearchParams([
    ["resource", "provider"],
    ["app", app],
    ...(model ? [["model", model]] : []),
    ["name", siteName.trim() || "API 服务"],
    ["homepage", normalizedBaseUrl],
    ["endpoint", endpoint],
    ["apiKey", key.key],
    ["configFormat", "json"],
    ["usageEnabled", "true"],
    ["usageScript", encodeBase64(USAGE_SCRIPT)],
    ["usageAutoInterval", "30"],
  ]);
  return `ccswitch://v1/import?${params.toString()}`;
}
