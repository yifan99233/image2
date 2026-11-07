import { request } from "@/services/http";
import type { UserExperienceConfig } from "@/types/api";

export const DEFAULT_MAX_BATCH_TASKS = 20000;

export const defaultUserExperienceConfig: UserExperienceConfig = {
  max_batch_tasks: DEFAULT_MAX_BATCH_TASKS,
  batch_upload_max_bytes: 64 * 1024 * 1024,
  batch_upload_max_prompt_chars: 100_000,
  qiniu_storage_enabled: false,
  updated_at: null,
};

export const uxService = {
  getConfig: () => request<UserExperienceConfig>("/ux/config"),
};
