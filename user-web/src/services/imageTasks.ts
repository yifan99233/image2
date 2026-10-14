import { request, requestFormData } from "@/services/http";
import { defaultUserExperienceConfig } from "@/services/ux";
import { appConfig } from "@/config/env";
import type { CreateImageTaskRequest, ImageAsset, ImageTask, ImageBatchPage, ImageBatchSummary, ImageBatchSubmission, ImageBatchRetryQuote } from "@/types/api";

export const imageTaskService = {
  async getTasks(options?: { limit?: number; beforeId?: number; batchId?: string; status?: ImageTask["status"]; signal?: AbortSignal }): Promise<ImageTask[]> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.beforeId) params.set("before_id", String(options.beforeId));
    if (options?.batchId) params.set("batch_id", options.batchId);
    if (options?.status) params.set("status", options.status);
    const query = params.size ? `?${params.toString()}` : "";
    return request<ImageTask[]>(`/image-tasks${query}`, { signal: options?.signal });
  },

  async createTask(payload: CreateImageTaskRequest, inputAssets: ImageAsset[]): Promise<ImageTask> {
    return request<ImageTask>("/image-tasks", {
      method: "POST",
      body: {
        ...payload,
        // The browser renders the R2 hot URL, while the server sends the
        // durable local copy upstream so an expired R2 object never breaks an
        // edit task.
        input_image_url: payload.input_image_url ?? inputAssets[0]?.local_url ?? inputAssets[0]?.url,
        input_image_urls: payload.input_image_urls ?? inputAssets.map((asset) => asset.local_url ?? asset.url),
      },
    });
  },

  async createBatchTasks(payload: CreateImageTaskRequest, inputAssets: ImageAsset[]): Promise<ImageTask[]> {
    return (await imageTaskService.createBatch(payload, inputAssets)).tasks;
  },

  async createBatch(payload: CreateImageTaskRequest, inputAssets: ImageAsset[], limits?: { maxBytes?: number; maxPromptChars?: number; maxTasks?: number }): Promise<ImageBatchSubmission> {
    if (payload.work_type === "batch_generate") {
      const prompts = payload.prompts ?? payload.prompt.split(/\r?\n/).map(prompt => prompt.trim()).filter(Boolean);
      const maxTasks = Math.min(limits?.maxTasks ?? defaultUserExperienceConfig.max_batch_tasks, 20000);
      const maxChars = limits?.maxPromptChars ?? defaultUserExperienceConfig.batch_upload_max_prompt_chars!;
      if (!prompts.length || prompts.length > maxTasks) throw new Error(`请提交 1 至 ${maxTasks} 条提示词`);
      if (prompts.some(prompt => prompt.length > maxChars)) throw new Error(`每条提示词最多 ${maxChars} 个字符`);
      const manifest = {
        version: 1, work_type: "batch_generate", batch_id: payload.batch_id ?? `batch-${crypto.randomUUID()}`,
        model_id: payload.model_id, resolution: payload.resolution, aspect_ratio: payload.aspect_ratio,
        quality: payload.quality ?? "auto", prompts, folder_names: payload.folder_names,
      };
      const file = new Blob([JSON.stringify(manifest)], { type: "application/json" });
      if (file.size > (limits?.maxBytes ?? defaultUserExperienceConfig.batch_upload_max_bytes!)) {
        throw new Error("提示词文件超过上传大小限制，请拆分后提交");
      }
      const body = new FormData();
      body.append("manifest", file, "batch-prompts.json");
      return requestFormData<ImageBatchSubmission>("/image-tasks/batch-upload", body, {
        method: "POST", timeoutMs: 1_800_000,
      });
    }
    const result = await request<ImageTask[] | ImageBatchSubmission>("/image-tasks/batch", {
      method: "POST",
      timeoutMs: 1_800_000,
      body: {
        ...payload,
        input_image_url: payload.input_image_url ?? inputAssets[0]?.local_url ?? inputAssets[0]?.url,
        input_image_urls: payload.input_image_urls ?? inputAssets.map((asset) => asset.local_url ?? asset.url),
      },
    });
    return Array.isArray(result) ? { tasks: result, task_ids: result.map(task => task.id), task_count: result.length, batch_id: result[0]?.batch_id ?? payload.batch_id ?? "" } : result;
  },

  async getBatches(workType: string, options?: { beforeId?: number; signal?: AbortSignal }): Promise<ImageBatchPage> {
    const params = new URLSearchParams({ work_type: workType, limit: "10" });
    if (options?.beforeId) params.set("before_id", String(options.beforeId));
    return request<ImageBatchPage>(`/image-tasks/batches?${params}`, { signal: options?.signal });
  },

  async getBatchStatuses(batchIds: string[], signal?: AbortSignal): Promise<ImageBatchSummary[]> {
    if (!batchIds.length) return [];
    if (batchIds.length > 20) {
      const summaries: ImageBatchSummary[] = [];
      for (let i = 0; i < batchIds.length; i += 20) {
        summaries.push(...await imageTaskService.getBatchStatuses(batchIds.slice(i, i + 20), signal));
      }
      return summaries;
    }
    return request<ImageBatchSummary[]>("/image-tasks/batches/statuses", { method: "POST", body: { batch_ids: batchIds }, signal });
  },

  async createExportDownloadUrl(taskIds: number[], batchId?: string): Promise<string> {
    const data = await request<{ download_url: string }>("/image-tasks/export-ticket", {
      method: "POST",
      body: { task_ids: taskIds, ...(batchId ? { batch_id: batchId } : {}) },
    });
    return `${appConfig.apiBaseUrl}${data.download_url}`;
  },

  async getBatchRetryQuote(batchId: string, signal?: AbortSignal): Promise<ImageBatchRetryQuote> {
    return request<ImageBatchRetryQuote>("/image-tasks/batches/retry-quote", {
      method: "POST",
      body: { batch_id: batchId },
      signal,
    });
  },

  async retryBatch(quote: ImageBatchRetryQuote, requestId: string): Promise<ImageBatchSubmission> {
    return request<ImageBatchSubmission>("/image-tasks/batches/retry", {
      method: "POST",
      timeoutMs: 30_000,
      body: {
        batch_id: quote.batch_id,
        task_ids: quote.task_ids,
        quote_token: quote.quote_token,
        request_id: requestId,
      },
    });
  },

  async getTask(taskId: number): Promise<ImageTask> {
    return request<ImageTask>(`/image-tasks/${taskId}`);
  },

  async getTaskStatuses(taskIds: number[]): Promise<ImageTask[]> {
    if (taskIds.length > 200) {
      const chunks = Array.from({ length: Math.ceil(taskIds.length / 200) }, (_, index) => taskIds.slice(index * 200, (index + 1) * 200));
      return (await Promise.all(chunks.map((chunk) => imageTaskService.getTaskStatuses(chunk)))).flat();
    }
    return request<ImageTask[]>("/image-tasks/statuses", {
      method: "POST",
      body: { task_ids: taskIds },
    });
  },

  async deleteTask(taskId: number): Promise<void> {
    return request<void>(`/image-tasks/${taskId}`, { method: "DELETE" });
  },
};
