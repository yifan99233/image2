import { request } from "@/services/http";
import type { PageResult, UserFeedback } from "@/types/api";

export const feedbackService = {
  create(description: string, imageAssetIds: number[]) {
    return request<UserFeedback>("/feedbacks", {
      method: "POST",
      body: { description, image_asset_ids: imageAssetIds },
    });
  },
  list(page = 1, pageSize = 10) {
    return request<PageResult<UserFeedback>>(`/feedbacks?page_no=${page}&page_size=${pageSize}`);
  },
};
