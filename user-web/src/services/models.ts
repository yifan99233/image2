import { request } from "@/services/http";
import type { ImageModel, ImageQuote, ImageQuality } from "@/types/api";

export const modelService = {
  async getModels(workType = "image_edit"): Promise<ImageModel[]> {
    return request<ImageModel[]>(`/models?work_type=${encodeURIComponent(workType)}`);
  },

  async quote(
    modelId: number,
    workType: string,
    resolution: string,
    aspectRatio: string,
    outputCount: number,
    duration?: string,
    quality: ImageQuality = "auto",
  ): Promise<ImageQuote> {
    return request<ImageQuote>(`/models/${modelId}/quote`, {
      method: "POST",
      body: {
        work_type: workType,
        resolution,
        aspect_ratio: aspectRatio,
        duration: duration || undefined,
        output_count: outputCount,
        quality,
      },
    });
  },
};
