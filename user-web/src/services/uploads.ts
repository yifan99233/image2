import { appConfig } from "@/config/env";
import { ApiError } from "@/services/apiError";
import { sessionStorageService } from "@/services/session";
import type { ApiEnvelope, ApiErrorPayload, ImageAsset } from "@/types/api";

const buildUrl = (path: string) => {
  if (/^https?:\/\//.test(path)) {
    return path;
  }
  return `${appConfig.apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
};

export const uploadService = {
  async uploadImages(files: File[], concurrency = 4): Promise<ImageAsset[]> {
    if (!files.length) return [];
    const results = new Array<ImageAsset>(files.length);
    let nextIndex = 0;
    let firstError: unknown = null;
    let hasError = false;
    const workerCount = Math.min(Math.max(1, concurrency), files.length);

    const worker = async () => {
      while (!hasError) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= files.length) return;
        try {
          results[index] = await uploadService.uploadImage(files[index]);
        } catch (error) {
          hasError = true;
          firstError = error;
          return;
        }
      }
    };

    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    if (firstError !== null) throw firstError;
    return results;
  },

  async uploadImagesForModel(files: File[], modelId: number, concurrency = 4): Promise<ImageAsset[]> {
    if (!files.length) return [];
    const results = new Array<ImageAsset>(files.length);
    let nextIndex = 0;
    let firstError: unknown = null;
    let hasError = false;
    const workerCount = Math.min(Math.max(1, concurrency), files.length);

    const worker = async () => {
      while (!hasError) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= files.length) return;
        try {
          results[index] = await uploadService.uploadImageForModel(files[index], modelId);
        } catch (error) {
          hasError = true;
          firstError = error;
          return;
        }
      }
    };

    await Promise.all(Array.from({ length: workerCount }, () => worker()));
    if (firstError !== null) throw firstError;
    return results;
  },

  async uploadImage(file: File): Promise<ImageAsset> {
    try {
      return await this.uploadImageDirectToR2(file);
    } catch (error) {
      // R2 is an optimization layer. If it is not configured yet, the bucket
      // CORS rule is temporarily missing, or the presign endpoint is down,
      // keep the legacy multipart path available.
      if (error instanceof Error && error.name === "R2UploadCompleted") {
        throw error;
      }
      return this.uploadImageMultipart(file);
    }
  },

  async uploadImageForModel(file: File, modelId: number): Promise<ImageAsset> {
    // Model-bound uploads must use the multipart path so the server can apply
    // the selected model's storage/CDN mode. R2 presign has no model context.
    return this.uploadImageMultipart(file, modelId);
  },

  async uploadImageDirectToR2(file: File): Promise<ImageAsset> {
    const token = sessionStorageService.getAccessToken();
    const prepareResponse = await fetch(buildUrl("/uploads/images/r2/presign"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        filename: file.name || "image.png",
        content_type: file.type || "image/png",
        size_bytes: file.size,
      }),
    });
    const preparePayload = (await prepareResponse.json().catch(() => null)) as
      | ApiEnvelope<{
          upload_url: string;
          upload_method: "PUT";
          content_type: string;
          object_key: string;
          completion_token: string;
        }>
      | ApiErrorPayload
      | null;
    if (!prepareResponse.ok || !preparePayload || preparePayload.code !== 0) {
      throw new ApiError(
        {
          code: preparePayload?.code ?? prepareResponse.status,
          message: preparePayload?.message ?? "R2 上传初始化失败",
          data: null,
        },
        prepareResponse.status,
      );
    }

    const uploadData = (preparePayload as ApiEnvelope<{
      upload_url: string;
      upload_method: "PUT";
      content_type: string;
      object_key: string;
      completion_token: string;
    }>).data;
    const objectResponse = await fetch(uploadData.upload_url, {
      method: uploadData.upload_method,
      headers: { "Content-Type": uploadData.content_type },
      body: file,
    });
    if (!objectResponse.ok) {
      throw new ApiError(
        { code: objectResponse.status, message: "R2 图片直传失败", data: null },
        objectResponse.status,
      );
    }

    const completeResponse = await fetch(buildUrl("/uploads/images/r2/complete"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        object_key: uploadData.object_key,
        completion_token: uploadData.completion_token,
        content_type: uploadData.content_type,
      }),
    });
    const completePayload = (await completeResponse.json().catch(() => null)) as
      | ApiEnvelope<ImageAsset>
      | ApiErrorPayload
      | null;
    if (!completeResponse.ok || !completePayload || completePayload.code !== 0) {
      const error = new ApiError(
        {
          code: completePayload?.code ?? completeResponse.status,
          message: completePayload?.message ?? "R2 图片确认失败",
          data: null,
        },
        completeResponse.status,
      );
      error.name = "R2UploadCompleted";
      throw error;
    }
    return (completePayload as ApiEnvelope<ImageAsset>).data;
  },

  async uploadImageMultipart(file: File, modelId?: number): Promise<ImageAsset> {
    const formData = new FormData();
    formData.append("image", file);
    if (modelId !== undefined) formData.append("model_id", String(modelId));

    const token = sessionStorageService.getAccessToken();
    const response = await fetch(buildUrl("/uploads/images"), {
      method: "POST",
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: formData,
    });

    const payload = (await response.json().catch(() => null)) as
      | ApiEnvelope<ImageAsset>
      | ApiErrorPayload
      | null;

    if (!response.ok || !payload || payload.code !== 0) {
      throw new ApiError(
        {
          code: payload?.code ?? response.status,
          message: payload?.message ?? "图片上传失败，请稍后重试",
          data: null,
        },
        response.status,
      );
    }

    return (payload as ApiEnvelope<ImageAsset>).data;
  },
};
