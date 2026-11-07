// Shared with user-web. Keep this file independent of either application's aliases.
export const CANVAS_CHANNEL = "image2-canvas-v1";
export type CanvasModel = {
    id: number; name: string; work_type: string; max_input_images: number; max_output_images: number;
    supported_resolutions: { value: string; label: string }[];
    supported_aspect_ratios: { value: string; label: string }[];
};
export type CanvasAsset = { id: number; url: string; width: number; height: number; bytes: number; mimeType: string };
export type ProjectSummary = { id: string; title: string; revision: number; created_at: string; updated_at: string; node_count?: number; connection_count?: number };
export type ProjectRecord = ProjectSummary & { document: Record<string, unknown> };
export type ProjectSave = { id: string; title: string; revision: number; mutation_id: string; document: Record<string, unknown> };
export type GenerationInput = {
    modelId: number; prompt: string; resolution: string; aspectRatio: string;
    quality: "auto" | "high" | "medium" | "low"; count: number; references: string[];
};
export type TaskResult = { id: number; status: string; error?: string | null; assets: CanvasAsset[] };
export type CanvasMethods = {
    bootstrap: { input: null; output: { models: CanvasModel[]; theme: "light" | "dark"; userId: number } };
    "projects.list": { input: { before_created_at?: string; before_id?: string }; output: { items: ProjectSummary[]; has_more: boolean } };
    "projects.get": { input: { id: string }; output: ProjectRecord };
    "projects.save": { input: ProjectSave; output: ProjectRecord };
    "projects.delete": { input: { id: string; revision: number }; output: null };
    "assets.upload": { input: { file: File }; output: CanvasAsset };
    "assets.list": { input: { page: number; keyword: string }; output: { items: (CanvasAsset & { title: string })[]; total: number; pageSize: number } };
    "assets.save": { input: { url: string; title: string }; output: null };
    "generation.quote": { input: GenerationInput; output: { credit_cost: number } };
    "generation.create": { input: GenerationInput; output: TaskResult[] };
    "generation.status": { input: { ids: number[] }; output: TaskResult[] };
};
export type CanvasMethod = keyof CanvasMethods;
