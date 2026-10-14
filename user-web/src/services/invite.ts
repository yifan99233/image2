import { request } from "@/services/http";
import type { InviteRewardConfig, InviteSummary } from "@/types/api";

export const inviteService = {
  async getRewardConfig(): Promise<InviteRewardConfig> {
    return request<InviteRewardConfig>("/invite/reward-config");
  },

  async getSummary(): Promise<InviteSummary> {
    return request<InviteSummary>("/invite/summary");
  },
};
