import { request } from "@/services/http";
import type { WorkItem } from "@/types/api";

export const workService = {
  async getGalleryWorks(): Promise<WorkItem[]> {
    return request<WorkItem[]>("/gallery");
  },

  async getWorks(options?: { limit?: number; beforeId?: number }): Promise<WorkItem[]> {
    const params = new URLSearchParams();
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.beforeId) params.set("before_id", String(options.beforeId));
    return request<WorkItem[]>(`/works${params.size ? `?${params}` : ""}`);
  },

  async updateWork(workId: number, patch: Partial<Pick<WorkItem, "is_collected" | "is_recommended">>): Promise<WorkItem> {
    return request<WorkItem>(`/works/${workId}`, {
      method: "PATCH",
      body: patch,
    });
  },

  async deleteWork(workId: number): Promise<void> {
    return request<void>(`/works/${workId}`, { method: "DELETE" });
  },
};
