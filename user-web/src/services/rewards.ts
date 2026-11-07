import { request } from "@/services/http";
import type { SigninResult, SigninStatus } from "@/types/api";

export const rewardService = {
  async getSigninStatus(): Promise<SigninStatus> {
    return request<SigninStatus>("/rewards/signin/status");
  },

  async signin(): Promise<SigninResult> {
    return request<SigninResult>("/rewards/signin", { method: "POST" });
  },
};
