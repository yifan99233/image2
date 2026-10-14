import { request } from "@/services/http";
import type { OpenAgentDownload, OpenAgentKey, OpenAgentKeyCreateInput, OpenAgentKeyPage, OpenAgentKeyUpdateInput, OpenAgentUsageRecord, OpenCodeBalance, OpenCodeLoginResponse, PageResult } from "@/types/api";

export const opencodeService = {
  async login(username: string, password: string): Promise<OpenCodeLoginResponse> {
    return request<OpenCodeLoginResponse>("/opencode/login", {
      method: "POST",
      body: { username, password },
      skipAuth: true,
    });
  },

  async getBalance(): Promise<OpenCodeBalance> {
    return request<OpenCodeBalance>("/opencode/balance");
  },

  async regenerateAccount(): Promise<OpenCodeBalance> {
    return request<OpenCodeBalance>("/opencode/account/regenerate", {
      method: "POST",
    });
  },

  async getUsage(page = 1, pageSize = 20): Promise<PageResult<OpenAgentUsageRecord>> {
    return request<PageResult<OpenAgentUsageRecord>>(`/opencode/usage?page=${page}&page_size=${pageSize}`);
  },

  async getKeys(): Promise<OpenAgentKeyPage> {
    return request<OpenAgentKeyPage>("/opencode/keys");
  },

  async createKey(input: OpenAgentKeyCreateInput): Promise<OpenAgentKey> {
    return request<OpenAgentKey>("/opencode/keys", { method: "POST", body: input });
  },

  async updateKey(keyId: number, input: OpenAgentKeyUpdateInput): Promise<OpenAgentKey> {
    return request<OpenAgentKey>(`/opencode/keys/${keyId}`, { method: "PATCH", body: input });
  },

  async deleteKey(keyId: number): Promise<void> {
    return request<void>(`/opencode/keys/${keyId}`, { method: "DELETE" });
  },

  async getDownloads(): Promise<OpenAgentDownload[]> {
    return request<OpenAgentDownload[]>("/opencode/releases");
  },
};
