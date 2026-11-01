import { canvasService } from "@/services/canvas";
import { modelService } from "@/services/models";
import { imageTaskService } from "@/services/imageTasks";
import { materialService } from "@/services/materials";
import { uploadService } from "@/services/uploads";
import { request } from "@/services/http";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import type { ImageAsset, ImageTask } from "@/types/api";
import type { CanvasAsset, CanvasMethods, CanvasMethod, CanvasModel, GenerationInput, TaskResult } from "../../../../canvas-web/src/integration/protocol";

export function toCanvasAsset(asset: ImageAsset): CanvasAsset {
  return { id: asset.id, url: asset.local_url || asset.url, width: asset.width || 0, height: asset.height || 0, bytes: asset.size_bytes, mimeType: asset.mime_type };
}
function taskResult(task: ImageTask): TaskResult {
  return { id: task.id, status: task.status, error: task.failure_message, assets: task.output_images.map(toCanvasAsset) };
}

export function createCanvasHost() {
  let models: CanvasModel[] = [];
  const assets = new Map<string, ImageAsset>();
  const remember = (asset: ImageAsset) => {
    [asset.url, asset.local_url].filter(Boolean).forEach((url) => assets.set(url!, asset));
    return toCanvasAsset(asset);
  };
  const validateGeneration = (input: GenerationInput) => {
    const model = models.find((item) => item.id === input.modelId);
    if (!model) throw new Error("模型已不可用，请重新加载画布");
    if (!input.prompt?.trim()) throw new Error("请输入提示词");
    if (!Number.isInteger(input.count) || input.count < 1 || input.count > model.max_output_images) throw new Error("生成张数超出模型支持范围");
    if (input.references.length > model.max_input_images) throw new Error(`当前模型最多支持 ${model.max_input_images} 张参考图`);
    if (!model.supported_resolutions.some((option) => option.value === input.resolution) || !model.supported_aspect_ratios.some((option) => option.value === input.aspectRatio)) throw new Error("当前模型不支持所选图片规格，请重新选择");
    return model;
  };
  const handlers: { [K in CanvasMethod]: (input: CanvasMethods[K]["input"]) => Promise<CanvasMethods[K]["output"]> } = {
    async bootstrap() {
      const user = useAuthStore.getState().user;
      if (!user) throw new Error("请先登录");
      const lists = await Promise.all([modelService.getModels("text_to_image"), modelService.getModels("image_edit")]);
      models = [...new Map(lists.flat().map((model) => [model.id, model])).values()].filter((model) => !('capability_type' in model) || model.capability_type !== "video");
      return { models, userId: user.id, theme: useThemeStore.getState().themeMode };
    },
    "projects.list": canvasService.list,
    "projects.get": ({ id }) => canvasService.get(id),
    "projects.save": canvasService.save,
    "projects.delete": ({ id, revision }) => canvasService.remove(id, revision),
    async "assets.upload"({ file }) {
      if (!(file instanceof File)) throw new Error("图片文件无效");
      return remember(await uploadService.uploadImage(file));
    },
    async "assets.list"({ page, keyword }) {
      const result = await materialService.getMaterials(null, keyword, page, 20);
      return { items: result.items.map((item) => ({ ...remember(item.asset), title: item.name })), total: result.total, pageSize: 20 };
    },
    async "assets.save"({ url, title }) {
      let asset = assets.get(url);
      if (!asset) {
        const response = await fetch(url, { credentials: "omit" });
        if (!response.ok) throw new Error("读取图片失败");
        const blob = await response.blob();
        asset = await uploadService.uploadImage(new File([blob], "canvas.png", { type: blob.type }));
        remember(asset);
      }
      await request("/materials/assets/link", { method: "POST", body: { folder_id: null, assets: [{ asset_id: asset.id, name: title }] } });
      return null;
    },
    async "generation.quote"(input) {
      validateGeneration(input);
      return modelService.quote(input.modelId, input.references.length ? "image_edit" : "text_to_image", input.resolution, input.aspectRatio, input.count, undefined, input.quality);
    },
    async "generation.create"(input) {
      validateGeneration(input);
      const payload = {
        model_id: input.modelId, prompt: input.prompt, work_type: input.references.length ? "image_edit" : "text_to_image",
        resolution: input.resolution, aspect_ratio: input.aspectRatio, quality: input.quality,
        output_count: input.count, input_image_ids: [], input_image_urls: input.references,
      };
      try {
        const tasks = input.count > 1 ? await imageTaskService.createBatchTasks(payload, []) : [await imageTaskService.createTask(payload, [])];
        return tasks.map(taskResult);
      } finally { notifyCreditBalanceChanged(); }
    },
    async "generation.status"({ ids }) {
      const tasks = await imageTaskService.getTaskStatuses(ids);
      tasks.forEach((task) => task.output_images.forEach(remember));
      if (tasks.some((task) => ["failed", "refunded", "succeeded"].includes(task.status))) notifyCreditBalanceChanged();
      return tasks.map(taskResult);
    },
  };
  return async <K extends CanvasMethod>(method: K, input: CanvasMethods[K]["input"]): Promise<CanvasMethods[K]["output"]> => {
    if (!Object.hasOwn(handlers, method)) throw new Error("不支持的画布操作");
    return handlers[method](input);
  };
}
