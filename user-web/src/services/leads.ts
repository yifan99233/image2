import { request } from "@/services/http";
import type { LeadModuleCredentials, LeadModuleStatus, LeadTrialApplication, LeadTrialApplicationInput } from "@/types/api";

export const leadService = {
  getModuleStatus() {
    return request<LeadModuleStatus>("/leads/module");
  },

  revealCredentials() {
    return request<LeadModuleCredentials>("/leads/module/credentials", { method: "POST" });
  },

  getLatestTrialApplication() {
    return request<LeadTrialApplication | null>("/leads/trial-applications/latest");
  },

  submitTrialApplication(input: LeadTrialApplicationInput) {
    return request<LeadTrialApplication>("/leads/trial-applications", { method: "POST", body: input });
  },
};
