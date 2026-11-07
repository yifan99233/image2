import type { AiConfig } from "@/stores/use-config-store";
import type { ReferenceImage } from "@/types/image";
import { callHost } from "./bridge";
import type { CanvasAsset, CanvasModel, GenerationInput } from "./protocol";

let models: CanvasModel[] = [];
const knownImages = new Map<string, CanvasAsset>();
export function setHostModels(value: CanvasModel[]) { models = value; }
export function getHostModels() { return models; }
export function getHostModel(value: string) { return models.find((model) => String(model.id) === value.split("::").at(-1)); }
export function rememberImage(asset: CanvasAsset) { knownImages.set(asset.url, asset); return asset; }

export function generationInput(config: AiConfig, prompt = "", references: string[] = []): GenerationInput {
    const model = getHostModel(config.model);
    if (!model) throw new Error("请选择本站可用的生图模型");
    const [requestedResolution, requestedRatio] = config.size.split("|");
    const resolution = model.supported_resolutions.find((item) => item.value === requestedResolution)?.value || model.supported_resolutions[0]?.value || "";
    const aspectRatio = model.supported_aspect_ratios.find((item) => item.value === (requestedRatio || config.size))?.value || model.supported_aspect_ratios[0]?.value || "";
    return { modelId: model.id, resolution, aspectRatio, prompt, references, quality: config.quality as GenerationInput["quality"], count: Number(config.count) || 1 };
}

export async function uploadHostImage(input: string | Blob, signal?: AbortSignal): Promise<{ url: string; width: number; height: number; bytes: number; mimeType: string }> {
    if (typeof input === "string" && knownImages.has(input)) return knownImages.get(input)!;
    const response = typeof input === "string" ? await fetch(input, { signal, credentials: "omit" }) : null;
    if (response && !response.ok) throw new Error("图片读取失败");
    const blob = response ? await response.blob() : input as Blob;
    if (!blob.type.startsWith("image/")) throw new Error("请选择图片文件");
    const file = input instanceof File ? input : new File([blob], "canvas.png", { type: blob.type });
    return rememberImage(await callHost("assets.upload", { file }, signal));
}

export async function generateHostImages(config: AiConfig, prompt: string, references: ReferenceImage[] = [], options?: { signal?: AbortSignal; onTaskCreated?: (ids: number[]) => void | Promise<void> }) {
    const urls: string[] = [];
    for (const reference of references) {
        const url = reference.dataUrl;
        if (/^(data:|blob:)/.test(url)) urls.push((await uploadHostImage(url, options?.signal)).url);
        else urls.push(url);
    }
    const input = generationInput(config, prompt, urls);
    const tasks = await callHost("generation.create", input, options?.signal);
    await options?.onTaskCreated?.(tasks.map((task) => task.id));
    return waitForHostImages(tasks.map((task) => task.id), options?.signal);
}

export async function waitForHostImages(ids: number[], signal?: AbortSignal) {
    for (;;) {
        const tasks = await callHost("generation.status", { ids }, signal);
        if (tasks.length !== ids.length) throw new Error("生成任务不存在，请到我的作品检查记录");
        if (tasks.every((task) => ["succeeded", "failed", "refunded"].includes(task.status))) {
            const images = tasks.flatMap((task) => task.assets).map((asset) => ({ id: String(asset.id), dataUrl: rememberImage(asset).url }));
            if (!images.length) throw new Error(tasks.find((task) => task.error)?.error || "生成失败，积分按本站规则退回");
            return images;
        }
        await new Promise<void>((resolve, reject) => {
            const abort = () => { clearTimeout(timer); reject(new DOMException("已停止等待", "AbortError")); };
            const timer = window.setTimeout(() => { signal?.removeEventListener("abort", abort); resolve(); }, 2000);
            if (signal?.aborted) abort();
            else signal?.addEventListener("abort", abort, { once: true });
        });
    }
}
