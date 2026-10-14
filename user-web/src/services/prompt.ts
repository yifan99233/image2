import { appConfig } from "@/config/env";
import { request } from "@/services/http";
import { sessionStorageService } from "@/services/session";

export type PromptOptimizeOptions = {
  media?: "image" | "video";
  has_images?: boolean;
};

export type PromptOptimizeStreamHandlers = {
  onStatus?: (message: string) => void;
  onDelta?: (text: string) => void;
};

export type AgentDocument = {
  id: string;
  name: string;
  mime_type: string;
  text: string;
  char_count: number;
};

export type AgentPlanIntent = "script_to_images" | "multi_prompts" | "single_prompt" | "image_edit_plan" | string;

export type AgentPlan = {
  intent: AgentPlanIntent;
  summary: string;
  prompts: string[];
  notes?: string;
  source?: string;
  media?: string;
  has_images?: boolean;
  prompt_count?: number;
  refused?: boolean;
  allowed_scope?: string[];
  /** Whether user asked to optimize prompt text (not image). Default false. */
  optimize_prompt?: boolean;
  /** Natural-language model preference, e.g. 即梦 */
  model_hint?: string | null;
  /** Resolved generation model id from catalog, if any */
  model_id?: number | null;
  model_name?: string | null;
  model_code?: string | null;
  needs_images?: boolean;
  /** Number of tasks requested by the Agent. A shared prompt is expanded client-side. */
  task_count?: number;
  /** Reuse the sole prompt for every planned task. */
  reuse_prompt?: boolean;
  /** Document task handling chosen by the Agent planner. */
  document_mode?: "none" | "verbatim_split";
  execution?: {
    action?: string;
    optimize_prompt?: boolean;
    use_user_prompt_as_is?: boolean;
    model_resolved?: boolean;
    history_source?: string;
  };
  history_query?: { mode?: "summary" | "latest"; range_hours?: number | null };
  history_reply?: string;
  retry_query?: { scope?: "recent_batch" | "recent_n"; limit?: number };
  delete_query?: { status?: "failed"; limit?: number };
};

export type AgentPlanStreamHandlers = {
  onStatus?: (message: string) => void;
};

export const promptService = {
  optimize(
    modelId: number,
    prompt: string,
    options: PromptOptimizeOptions = {},
  ): Promise<{ prompt: string; media?: string; has_images?: boolean }> {
    return request<{ prompt: string; media?: string; has_images?: boolean }>("/prompt/optimize", {
      method: "POST",
      body: {
        model_id: modelId,
        prompt,
        media: options.media ?? "image",
        has_images: Boolean(options.has_images),
      },
    });
  },

  async optimizeStream(
    modelId: number,
    prompt: string,
    options: PromptOptimizeOptions = {},
    handlers: PromptOptimizeStreamHandlers = {},
  ): Promise<{ prompt: string; media?: string; has_images?: boolean }> {
    const token = sessionStorageService.getAccessToken();
    const response = await fetch(`${appConfig.apiBaseUrl}/prompt/optimize/stream`, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        model_id: modelId,
        prompt,
        media: options.media ?? "image",
        has_images: Boolean(options.has_images),
      }),
    });

    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.message ?? "提示词优化失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let eventName = "message";
    let dataLines: string[] = [];
    let completedPrompt = "";

    const consumeEvent = () => {
      if (!dataLines.length) return;
      const rawData = dataLines.join("\n");
      dataLines = [];
      let payload: { message?: string; text?: string; prompt?: string };
      try {
        payload = JSON.parse(rawData);
      } catch {
        throw new Error("提示词优化流响应格式无效");
      }
      if (eventName === "status") handlers.onStatus?.(String(payload.message ?? "正在优化提示词…"));
      if (eventName === "delta") handlers.onDelta?.(String(payload.text ?? ""));
      if (eventName === "error") throw new Error(String(payload.message ?? "提示词优化失败"));
      if (eventName === "complete") completedPrompt = String(payload.prompt ?? "").trim();
      eventName = "message";
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = done ? "" : lines.pop() ?? "";
      for (const line of lines) {
        if (!line) {
          consumeEvent();
        } else if (line.startsWith("event:")) {
          eventName = line.slice("event:".length).trim() || "message";
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice("data:".length).trimStart());
        }
      }
      if (done) break;
    }
    consumeEvent();
    if (!completedPrompt) throw new Error("文本模型未返回优化结果");
    return { prompt: completedPrompt, media: options.media, has_images: options.has_images };
  },

  async extractDocument(file: File): Promise<AgentDocument> {
    const token = sessionStorageService.getAccessToken();
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${appConfig.apiBaseUrl}/prompt/extract-document`, {
      method: "POST",
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: form,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(payload?.message ?? "文档解析失败");
    }
    const data = payload?.data ?? payload;
    return {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: String(data?.name || file.name),
      mime_type: String(data?.mime_type || file.type || "text/plain"),
      text: String(data?.text || ""),
      char_count: Number(data?.char_count || 0),
    };
  },

  agentPlan(input: {
    modelId: number;
    prompt: string;
    /** Private continuity context; it is never a generation instruction. */
    sessionContext?: string;
    documentText?: string;
    media?: "image" | "video";
    hasImages?: boolean;
    maxPrompts?: number;
    /** Current page generation model catalog for NL model selection */
    availableModels?: Array<{
      id: number;
      name: string;
      code: string;
      work_type?: string;
      capability_type?: string;
      description?: string;
    }>;
  }): Promise<AgentPlan> {
    return request<AgentPlan>("/prompt/agent-plan", {
      method: "POST",
      body: {
        model_id: input.modelId,
        prompt: input.prompt,
        session_context: input.sessionContext ?? "",
        document_text: input.documentText ?? "",
        media: input.media ?? "image",
        has_images: Boolean(input.hasImages),
        max_prompts: input.maxPrompts ?? 12,
        available_models: (input.availableModels || []).map((item) => ({
          id: item.id,
          name: item.name,
          code: item.code,
          work_type: item.work_type,
          capability_type: item.capability_type,
          description: item.description,
        })),
      },
    });
  },

  async agentPlanStream(input: {
    modelId: number;
    prompt: string;
    sessionContext?: string;
    documentText?: string;
    media?: "image" | "video";
    hasImages?: boolean;
    maxPrompts?: number;
    availableModels?: Array<{
      id: number;
      name: string;
      code: string;
      work_type?: string;
      capability_type?: string;
      description?: string;
    }>;
  }, handlers: AgentPlanStreamHandlers = {}): Promise<AgentPlan> {
    const token = sessionStorageService.getAccessToken();
    const response = await fetch(`${appConfig.apiBaseUrl}/prompt/agent-plan/stream`, {
      method: "POST",
      headers: {
        Accept: "text/event-stream",
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        model_id: input.modelId,
        prompt: input.prompt,
        session_context: input.sessionContext ?? "",
        document_text: input.documentText ?? "",
        media: input.media ?? "image",
        has_images: Boolean(input.hasImages),
        max_prompts: input.maxPrompts ?? 12,
        available_models: input.availableModels || [],
      }),
    });
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.message ?? "Agent 规划失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let eventName = "message";
    let dataLines: string[] = [];
    let completedPlan: AgentPlan | null = null;

    const consumeEvent = () => {
      if (!dataLines.length) return;
      const rawData = dataLines.join("\n");
      dataLines = [];
      let payload: { message?: string; plan?: AgentPlan };
      try {
        payload = JSON.parse(rawData);
      } catch {
        throw new Error("Agent 流响应格式无效");
      }
      if (eventName === "status") handlers.onStatus?.(String(payload.message ?? "Agent 正在规划…"));
      if (eventName === "error") throw new Error(String(payload.message ?? "Agent 规划失败"));
      if (eventName === "complete") completedPlan = payload.plan ?? null;
      eventName = "message";
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split(/\r?\n/);
      buffer = done ? "" : lines.pop() ?? "";
      for (const line of lines) {
        if (!line) consumeEvent();
        else if (line.startsWith("event:")) eventName = line.slice("event:".length).trim() || "message";
        else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trimStart());
      }
      if (done) break;
    }
    consumeEvent();
    if (!completedPlan) throw new Error("Agent 未返回计划");
    return completedPlan;
  },
};
