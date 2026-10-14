import { request, requestFormData } from "@/services/http";
import type { MaterialAsset, MaterialFolder, PageResult } from "@/types/api";

export type MaterialUploadMode = "local" | "cdn";

export type MaterialUploadOptions = {
  default_mode: MaterialUploadMode;
  cdn_credit_cost: number;
};

export const materialService = {
  getFolders(parentId?: number | null): Promise<MaterialFolder[]> {
    const params = new URLSearchParams();
    if (parentId) params.set("parent_id", String(parentId));
    return request<MaterialFolder[]>(`/materials/folders${params.toString() ? `?${params}` : ""}`);
  },

  createFolder(name: string, parentId?: number | null): Promise<MaterialFolder> {
    return request<MaterialFolder>("/materials/folders", { method: "POST", body: { name, parent_id: parentId ?? null } });
  },

  updateFolder(id: number, name: string): Promise<MaterialFolder> {
    return request<MaterialFolder>(`/materials/folders/${id}`, { method: "PATCH", body: { name } });
  },

  getMaterials(folderId?: number | null, keyword = "", page = 1, pageSize = 40): Promise<PageResult<MaterialAsset>> {
    const params = new URLSearchParams({ page_no: String(page), page_size: String(pageSize) });
    if (folderId) params.set("folder_id", String(folderId));
    if (keyword.trim()) params.set("keyword", keyword.trim());
    return request<PageResult<MaterialAsset>>(`/materials?${params}`);
  },

  updateMaterial(id: number, input: { name: string; folder_id?: number | null }): Promise<MaterialAsset> {
    return request<MaterialAsset>(`/materials/assets/${id}`, { method: "PATCH", body: input });
  },

  getUploadOptions(): Promise<MaterialUploadOptions> {
    return request<MaterialUploadOptions>("/materials/upload-options");
  },

  async uploadMaterials(
    files: File[],
    folderId: number | null | undefined,
    uploadMode: MaterialUploadMode = "local",
  ): Promise<MaterialAsset[]> {
    const formData = new FormData();
    files.forEach((file) => formData.append("images", file));
    if (folderId) formData.append("folder_id", String(folderId));
    formData.append("upload_mode", uploadMode);
    return requestFormData<MaterialAsset[]>("/materials/assets", formData, { method: "POST" });
  },
};
