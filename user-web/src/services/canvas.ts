import { request } from "@/services/http";
import type { ProjectRecord, ProjectSave, ProjectSummary } from "../../../canvas-web/src/integration/protocol";

export const canvasService = {
  list(cursor: { before_created_at?: string; before_id?: string }) {
    const query = new URLSearchParams({ limit: "20", ...cursor });
    return request<{ items: ProjectSummary[]; has_more: boolean }>(`/canvas/projects?${query}`);
  },
  get(id: string) { return request<ProjectRecord>(`/canvas/projects/${encodeURIComponent(id)}`); },
  save({ id, ...body }: ProjectSave) {
    return request<ProjectRecord>(`/canvas/projects/${encodeURIComponent(id)}`, { method: "PUT", body });
  },
  remove(id: string, revision: number) {
    return request<null>(`/canvas/projects/${encodeURIComponent(id)}?revision=${revision}`, { method: "DELETE" });
  },
};
