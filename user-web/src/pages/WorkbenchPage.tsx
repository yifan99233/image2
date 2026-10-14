import { useEffect, useMemo, useRef, useState, type CompositionEvent, type CSSProperties, type ChangeEvent, type DragEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type RefObject } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronDown,
  Download,
  Edit3,
  FolderPlus,
  ImageOff,
  ImagePlus,
  Loader2,
  RotateCcw,
  Trash2,
  UploadCloud,
  X,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MaterialPicker } from "@/components/materials/MaterialPicker";
import { ModelPicker } from "@/components/models/ModelPicker";
import { AssetPreviewImage } from "@/components/images/AssetPreviewImage";
import { DEFAULT_IMAGE_QUALITY, IMAGE_QUALITY_OPTIONS } from "@/constants/imageGeneration";
import { imageTaskService } from "@/services/imageTasks";
import { modelService } from "@/services/models";
import { promptService } from "@/services/prompt";
import { uploadService } from "@/services/uploads";
import { workService } from "@/services/works";
import type { ImageAsset, ImageModel, ImageQuality, ImageTask } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import { downloadImage, startBrowserDownload } from "@/utils/download";
import { getImageTaskProcessingMessage, getImageTaskStatusLabel } from "@/utils/imageTaskStatus";
import { createImageTaskPoller } from "@/utils/imageTaskPolling";
import { formatElapsedTime, getTaskElapsedMs } from "@/utils/time";
import { mergeImageEditAssets, readImageEditAssets, readImageEditPrompt } from "@/utils/imageEditNavigation";
import { readToolPreference, resolveToolPreference, writeToolPreference } from "@/utils/toolPreferences";

const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;
const DEFAULT_MAX_INPUT_IMAGES = 1;
const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const ACCEPTED_IMAGE_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp"];
const WORKBENCH_PREFERENCE_SCOPE = "image_edit";
const MAX_OUTPUT_COUNT = 9;
type MentionMenuState = {
  query: string;
  start: number;
  end: number;
};

type PendingUpload = {
  id: number;
  file: File;
  previewUrl: string;
};

const getMentionState = (value: string, cursorPosition: number): MentionMenuState | null => {
  const beforeCursor = value.slice(0, cursorPosition);
  const halfWidthAtIndex = beforeCursor.lastIndexOf("@");
  const fullWidthAtIndex = beforeCursor.lastIndexOf("＠");
  const atIndex = Math.max(halfWidthAtIndex, fullWidthAtIndex);
  if (atIndex < 0) return null;
  const query = beforeCursor.slice(atIndex + 1);
  if (/[\r\n]/.test(query)) return null;
  if (/\s/.test(query) && !/^图片\s*\d*$/.test(query)) return null;
  return { query, start: atIndex, end: cursorPosition };
};

const formatBytes = (bytes: number) => {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

const getAspectRatioStyle = (value: string): CSSProperties => {
  const [width, height] = value.split(":").map(Number);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return {
      "--aspect-preview-height": "28px",
      "--aspect-preview-width": "28px",
    } as CSSProperties;
  }
  const maxWidth = 42;
  const maxHeight = 28;
  const scale = Math.min(maxWidth / width, maxHeight / height);
  return {
    "--aspect-preview-height": `${Math.max(12, height * scale)}px`,
    "--aspect-preview-width": `${Math.max(12, width * scale)}px`,
  } as CSSProperties;
};

const statusCopy: Record<ImageTask["status"], string> = {
  pending: "等待创建",
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
  refunded: "已退款",
};

const hasAcceptedImageExtension = (fileName: string) => {
  const normalizedName = fileName.toLowerCase();
  return ACCEPTED_IMAGE_EXTENSIONS.some((extension) => normalizedName.endsWith(extension));
};

const formatTaskTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

const isEditTask = (task: ImageTask) => ["image_edit", "image_to_image", "batch_edit"].includes(task.work_type);

const PROMPT_COLLAPSE_CHARS = 72;

const isPromptCollapsible = (prompt?: string | null) => {
  if (!prompt) return false;
  return prompt.length > PROMPT_COLLAPSE_CHARS || prompt.includes("\n");
};

export const WorkbenchPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const promptInputRef = useRef<HTMLTextAreaElement>(null);
  const promptStepRef = useRef<HTMLElement>(null);
  const pollingRef = useRef<ReturnType<typeof createImageTaskPoller<ImageTask>> | null>(null);
  const submitInFlightRef = useRef(false);
  const [models, setModels] = useState<ImageModel[]>([]);
  const [textModels, setTextModels] = useState<ImageModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [selectedTextModelId, setSelectedTextModelId] = useState<number | null>(null);
  const [openConfigMenu, setOpenConfigMenu] = useState<"resolution" | "quality" | "aspect" | null>(null);
  const [uploadedAssets, setUploadedAssets] = useState<ImageAsset[]>([]);
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([]);
  const nextPendingUploadId = useRef(-1);
  const pendingUploadsRef = useRef<PendingUpload[]>([]);
  const [previewUrls, setPreviewUrls] = useState<Record<number, string>>({});
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [resolution, setResolution] = useState("");
  const [aspectRatio, setAspectRatio] = useState("");
  const [quality, setQuality] = useState<ImageQuality>(DEFAULT_IMAGE_QUALITY);
  const [outputCount, setOutputCount] = useState(1);
  const [quote, setQuote] = useState<number | null>(null);
  const [isQuoteLoading, setIsQuoteLoading] = useState(false);
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isOptimizingPrompt, setIsOptimizingPrompt] = useState(false);
  const [isMaterialPickerOpen, setIsMaterialPickerOpen] = useState(false);
  const [confirmDeleteTaskId, setConfirmDeleteTaskId] = useState<number | null>(null);
  const [previewAsset, setPreviewAsset] = useState<ImageAsset | null>(null);
  const [collectingTaskIds, setCollectingTaskIds] = useState<number[]>([]);
  const [regeneratingTaskIds, setRegeneratingTaskIds] = useState<number[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [expandedPromptIds, setExpandedPromptIds] = useState<number[]>([]);

  useEffect(() => {
    const poller = createImageTaskPoller({
      fetchStatuses: (ids) => imageTaskService.getTaskStatuses(ids),
      onUpdates: (updates) => {
        const byId = new Map(updates.map((task) => [task.id, task]));
        setTasks((current) => current.map((item) => {
          const update = byId.get(item.id);
          if (!update) return item;
          // Status responses omit immutable task metadata, including inputs.
          return { ...item, ...update, input_images: update.input_images ?? item.input_images };
        }));
      },
      onSettled: notifyCreditBalanceChanged,
    });
    pollingRef.current = poller;
    return () => {
      poller.dispose();
      pollingRef.current = null;
    };
  }, []);


  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );
  const showResolutionSelector = (selectedModel?.supported_resolutions.length ?? 0) > 1;
  const maxOutputCount = MAX_OUTPUT_COUNT;

  useEffect(() => {
    pendingUploadsRef.current = pendingUploads;
  }, [pendingUploads]);

  useEffect(() => {
    return () => {
      pendingUploadsRef.current.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    };
  }, []);

  useEffect(() => {
    const sourceAssets = readImageEditAssets(location.state);
    if (!sourceAssets.length) return;
    const sourcePrompt = readImageEditPrompt(location.state);
    setUploadedAssets(sourceAssets);
    setPendingUploads((current) => {
      current.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      return [];
    });
    setPreviewUrls({});
    setPrompt(sourcePrompt);
    setUploadError(null);
    setSubmitError(null);
    setNotice(
      sourceAssets.length > 1
        ? `已载入结果图和 ${sourceAssets.length - 1} 张原始参考图${sourcePrompt ? "，原提示词也已带入" : ""}`
        : `已把结果图带入图生图${sourcePrompt ? "，原提示词也已带入" : ""}`,
    );
    navigate(location.pathname, { replace: true, state: null });
    window.setTimeout(() => {
      promptStepRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      promptInputRef.current?.focus();
    }, 0);
  }, [location.pathname, location.state, navigate]);

  useEffect(() => {
    if (!uploadError) return;
    const timerId = window.setTimeout(() => setUploadError(null), 5000);
    return () => window.clearTimeout(timerId);
  }, [uploadError]);

  useEffect(() => {
    if (!submitError) return;
    const timerId = window.setTimeout(() => setSubmitError(null), 5000);
    return () => window.clearTimeout(timerId);
  }, [submitError]);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(null), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  useEffect(() => {
    let ignore = false;

    const loadModels = async () => {
      const modelList = await modelService.getModels("image_edit");
      if (ignore) return;
      setModels(modelList);
      const preference = resolveToolPreference(modelList, readToolPreference(WORKBENCH_PREFERENCE_SCOPE));
      setSelectedModelId(preference.modelId);
      setResolution(preference.resolution);
      setAspectRatio(preference.aspectRatio);
      setQuality(preference.quality);
    };

    void loadModels();
    modelService.getModels("prompt_optimize").then((items) => {
      if (ignore) return;
      setTextModels(items);
      setSelectedTextModelId(items[0]?.id ?? null);
    }).catch(() => undefined);

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedModelId || !resolution || !aspectRatio) return;
    writeToolPreference(WORKBENCH_PREFERENCE_SCOPE, { modelId: selectedModelId, resolution, aspectRatio, duration: "", quality });
  }, [selectedModelId, resolution, aspectRatio, quality]);

  useEffect(() => {
    let ignore = false;

    imageTaskService
      .getTasks()
      .then((items) => {
        if (ignore) return;
        const editTasks = items.filter(isEditTask);
        setTasks((current) => {
          const knownIds = new Set(current.map((task) => task.id));
          return [...current, ...editTasks.filter((task) => !knownIds.has(task.id))];
        });
        const activeTaskIds = editTasks
          .filter((task) => ["pending", "queued", "running"].includes(task.status))
          .map((task) => task.id);
        if (activeTaskIds.length) pollTasks(activeTaskIds);
      })
      .catch((error) => {
        if (!ignore) setSubmitError(error instanceof Error ? error.message : "任务记录加载失败");
      });

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedModel || !resolution || !aspectRatio) return;
    let ignore = false;
    setIsQuoteLoading(true);

    modelService
      .quote(selectedModel.id, "image_edit", resolution, aspectRatio, 1)
      .then((nextQuote) => {
        if (!ignore) setQuote(nextQuote.credit_cost);
      })
      .catch(() => {
        if (!ignore) setQuote(null);
      })
      .finally(() => {
        if (!ignore) setIsQuoteLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, [selectedModel, resolution, aspectRatio]);

  useEffect(() => {
    setOutputCount((current) => Math.min(Math.max(1, current), maxOutputCount));
  }, [maxOutputCount]);

  useEffect(() => {
    return () => {
      Object.values(previewUrls).forEach((url) => URL.revokeObjectURL(url));
    };
  }, [previewUrls]);

  useEffect(() => {
    const hasActiveTask = tasks.some((task) => ["pending", "queued", "running"].includes(task.status));
    if (!hasActiveTask) return;
    const timerId = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timerId);
  }, [tasks]);

  useEffect(() => {
    if (!previewAsset) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPreviewAsset(null);
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [previewAsset]);

  const validateFile = (file: File) => {
    if (!ACCEPTED_IMAGE_TYPES.includes(file.type) || !hasAcceptedImageExtension(file.name)) {
      return "仅支持 JPG、PNG、WEBP 图片";
    }
    if (file.size > MAX_UPLOAD_SIZE) return "图片不能超过 10MB";
    return null;
  };

  const uploadFiles = async (files: File[]) => {
    const maxInputImages = selectedModel?.max_input_images || DEFAULT_MAX_INPUT_IMAGES;
    const remainingSlots = Math.max(0, maxInputImages - uploadedAssets.length - pendingUploads.length);
    const nextFiles = files.slice(0, remainingSlots);
    if (!nextFiles.length) {
      setUploadError(`当前最多上传 ${maxInputImages} 张图片`);
      return;
    }

    const invalidMessage = nextFiles.map(validateFile).find(Boolean);
    if (invalidMessage) {
      setUploadError(invalidMessage);
      return;
    }

    setUploadError(null);
    const pending = nextFiles.map((file) => ({
      id: nextPendingUploadId.current--,
      file,
      previewUrl: URL.createObjectURL(file),
    }));
    setPendingUploads((current) => [...current, ...pending]);
    if (files.length > nextFiles.length) {
      setUploadError(`已按数量限制暂存前 ${nextFiles.length} 张，当前最多上传 ${maxInputImages} 张图片`);
    }
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    if (files.length) void uploadFiles(files);
    event.currentTarget.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files ?? []);
    if (files.length) void uploadFiles(files);
  };

  const removeUpload = (assetId: number) => {
    const pending = pendingUploads.find((item) => item.id === assetId);
    if (pending) {
      URL.revokeObjectURL(pending.previewUrl);
      setPendingUploads((items) => items.filter((item) => item.id !== assetId));
      return;
    }
    const previewUrl = previewUrls[assetId];
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setUploadedAssets((assets) => assets.filter((asset) => asset.id !== assetId));
    setPreviewUrls((urls) => {
      const next = { ...urls };
      delete next[assetId];
      return next;
    });
  };

  const addMaterialAssets = (assets: ImageAsset[]) => {
    setUploadedAssets((current) => {
      const existingIds = new Set(current.map((asset) => asset.id));
      return [...current, ...assets.filter((asset) => !existingIds.has(asset.id))];
    });
    setPreviewUrls({});
  };

  const clearReferenceUploads = () => {
    pendingUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    Object.values(previewUrls).forEach((url) => URL.revokeObjectURL(url));
    setPendingUploads([]);
    setUploadedAssets([]);
    setPreviewUrls({});
    setUploadError(null);
  };

  const displayAssets = useMemo<ImageAsset[]>(
    () => [
      ...uploadedAssets,
      ...pendingUploads.map((item) => ({
        id: item.id,
        url: item.previewUrl,
        local_url: item.previewUrl,
        mime_type: item.file.type || "image/png",
        size_bytes: item.file.size,
        sha256: "",
        source: "upload" as const,
      })),
    ],
    [pendingUploads, uploadedAssets],
  );

  const optimizeCurrentPrompt = async () => {
    if (!selectedTextModelId || !prompt.trim()) return;
    setIsOptimizingPrompt(true);
    setSubmitError(null);
    try {
      const result = await promptService.optimize(selectedTextModelId, prompt);
      setPrompt(result.prompt);
      setNotice("提示词已优化");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "提示词优化失败");
    } finally {
      setIsOptimizingPrompt(false);
    }
  };

  function pollTask(taskId: number) {
    pollTasks([taskId]);
  }

  function pollTasks(taskIds: number[]) {
    pollingRef.current?.watch(taskIds);
  }

  const submitTask = async () => {
    if (submitInFlightRef.current) return;
    if (!selectedModel || !resolution || !aspectRatio) return;
    if (!uploadedAssets.length && !pendingUploads.length) {
      setSubmitError("请先上传至少一张图片");
      return;
    }
    if (!prompt.trim()) {
      setSubmitError("请输入本次图片修改指令");
      return;
    }

    submitInFlightRef.current = true;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      let inputAssets = uploadedAssets;
      if (pendingUploads.length) {
        setIsUploading(true);
        const newlyUploaded = await uploadService.uploadImagesForModel(
          pendingUploads.map((item) => item.file),
          selectedModel.id,
        );
        inputAssets = [...uploadedAssets, ...newlyUploaded];
        pendingUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
        setPendingUploads([]);
        setUploadedAssets(inputAssets);
      }
      const payload = {
        work_type: "image_edit",
        model_id: selectedModel.id,
        prompt: prompt.trim(),
        resolution,
        aspect_ratio: aspectRatio,
        quality,
        input_image_ids: inputAssets.map((asset) => asset.id),
        output_count: 1,
        n: outputCount,
      };
      const singleOutputPayload = { ...payload, output_count: 1, n: 1 };
      const createdTasks = outputCount > 1
        ? await Promise.all(
          Array.from({ length: outputCount }, () => imageTaskService.createTask(singleOutputPayload, inputAssets)),
        )
        : [await imageTaskService.createTask(singleOutputPayload, inputAssets)];
      setTasks((current) => [...createdTasks.reverse(), ...current]);
      pollTasks(createdTasks.map((task) => task.id));
      clearReferenceUploads();
      notifyCreditBalanceChanged();
      setNotice(outputCount > 1 ? `已提交 ${outputCount} 张图，结果会自动刷新` : "任务已提交，结果会自动刷新");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "任务提交失败");
    } finally {
      setIsUploading(false);
      setIsSubmitting(false);
      submitInFlightRef.current = false;
    }
  };

  const continueEdit = (task: ImageTask, nextPrompt = task.prompt) => {
    const output = task.output_images[0];
    if (!output) return;
    const editAssets = mergeImageEditAssets(output, task.input_images);
    setUploadedAssets(editAssets);
    setPreviewUrls({});
    setPrompt(nextPrompt);
    setQuality(task.quality ?? DEFAULT_IMAGE_QUALITY);
    setSubmitError(null);
    const sourceSummary = editAssets.length > 1
      ? `结果图和 ${editAssets.length - 1} 张原始参考图`
      : "结果图";
    setNotice(`已把${sourceSummary}及原提示词放入左侧编辑区，可直接修改后重新生成`);
    window.setTimeout(() => {
      promptStepRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      promptInputRef.current?.focus();
    }, 0);
  };

  const regenerateTask = async (task: ImageTask) => {
    if (regeneratingTaskIds.includes(task.id)) return;
    if (!task.input_images.length) {
      setSubmitError("该任务没有可复用的原图，无法重新生成");
      return;
    }

    setRegeneratingTaskIds((ids) => [...ids, task.id]);
    setSubmitError(null);
    try {
      const workType = task.work_type === "image_to_image" ? "image_to_image" : "image_edit";
      const createdTask = await imageTaskService.createTask(
        {
          work_type: workType,
          model_id: task.model_id,
          prompt: task.prompt,
          resolution: task.resolution,
          aspect_ratio: task.aspect_ratio,
          quality: task.quality ?? DEFAULT_IMAGE_QUALITY,
          input_image_ids: task.input_images.map((asset) => asset.id),
          output_count: 1,
        },
        task.input_images,
      );
      setTasks((current) => [createdTask, ...current]);
      pollTask(createdTask.id);
      notifyCreditBalanceChanged();
      setNotice("已重新提交生成任务");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "重新生成失败");
    } finally {
      setRegeneratingTaskIds((ids) => ids.filter((id) => id !== task.id));
    }
  };

  const deleteTask = async (taskId: number) => {
    try {
      await imageTaskService.deleteTask(taskId);
      pollingRef.current?.unwatch([taskId]);
      setTasks((current) => current.filter((task) => task.id !== taskId));
      setConfirmDeleteTaskId(null);
      setNotice("任务记录已删除");
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "任务删除失败");
    }
  };

  const toggleTaskCollection = async (task: ImageTask) => {
    if (task.status !== "succeeded" || collectingTaskIds.includes(task.id)) return;
    const nextCollected = !task.is_collected;
    setCollectingTaskIds((ids) => [...ids, task.id]);
    setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, is_collected: nextCollected } : item)));
    try {
      const work = await workService.updateWork(task.id, { is_collected: nextCollected });
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, is_collected: work.is_collected } : item)));
      setNotice(work.is_collected ? "已收藏到我的作品" : "已取消收藏");
    } catch (error) {
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, is_collected: task.is_collected } : item)));
      setSubmitError(error instanceof Error ? error.message : "收藏状态更新失败");
    } finally {
      setCollectingTaskIds((ids) => ids.filter((id) => id !== task.id));
    }
  };

  const downloadTaskOutput = async (task: ImageTask) => {
    const output = task.output_images[0];
    if (!output) return;
    try {
      await downloadImage(output.url, `image2ai-${task.task_no}`, output.mime_type);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "图片下载失败，请稍后重试");
    }
  };

  const exportTaskOutputs = async () => {
    const taskIds = tasks.filter((task) => task.output_images[0]).map((task) => task.id);
    try {
      const downloadUrl = await imageTaskService.createExportDownloadUrl(taskIds);
      startBrowserDownload(downloadUrl);
      setNotice(`已导出 ${taskIds.length} 张结果图`);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "批量导出失败，请稍后重试");
    }
  };

  const canSubmit = Boolean(selectedModel && (uploadedAssets.length + pendingUploads.length) && prompt.trim() && !isUploading && !isSubmitting);
  const exportableTaskCount = tasks.filter((task) => task.output_images[0]).length;

  const selectGenerationModel = (nextModel: ImageModel) => {
    const supportsResolution = nextModel.supported_resolutions.some((option) => option.value === resolution);
    const supportsAspectRatio = nextModel.supported_aspect_ratios.some((option) => option.value === aspectRatio);
    const nextResolution = supportsResolution ? resolution : nextModel.supported_resolutions[0]?.value ?? "";
    const nextAspectRatio = supportsAspectRatio ? aspectRatio : nextModel.supported_aspect_ratios[0]?.value ?? "";
    const adjustedFields = [
      nextResolution !== resolution ? "清晰度" : "",
      nextAspectRatio !== aspectRatio ? "画幅" : "",
    ].filter(Boolean);

    setSelectedModelId(nextModel.id);
    setResolution(nextResolution);
    setAspectRatio(nextAspectRatio);
    const imageLimitExceeded = uploadedAssets.length + pendingUploads.length > nextModel.max_input_images;
    if (adjustedFields.length || imageLimitExceeded) {
      const messages = [
        adjustedFields.length ? `已调整${adjustedFields.join("、")}以兼容该模型` : "",
        imageLimitExceeded ? `当前 ${uploadedAssets.length + pendingUploads.length} 张参考图超过该模型的 ${nextModel.max_input_images} 张上限` : "",
      ].filter(Boolean);
      setNotice(`已切换至 ${nextModel.name}，${messages.join("；")}`);
    }
  };

  return (
    <main className="workspace creation-tool-page creation-tool-page--edit">
      <section className="workspace__form" aria-labelledby="workspace-title">
        <div className="tool-title creation-tool-page__header">
          <span>
            <Edit3 size={22} />
          </span>
          <div>
            <h1 id="workspace-title">图生图</h1>
            <p>选择模型、上传图片并输入修改指令，提交后在右侧查看进度和结果。</p>
          </div>
        </div>

        <div className="tool-scroll">
          <section className="tool-step">
            <header className="tool-step__head">
              <span>1</span>
              <strong>生成配置</strong>
            </header>
            <div className={showResolutionSelector ? "config-row" : "config-row config-row--without-resolution"}>
              <div className="config-field config-field--model model-select">
                <span>模型</span>
                <ModelPicker
                  models={models}
                  selectedModelId={selectedModelId}
                  onChange={selectGenerationModel}
                  triggerClassName="model-select__trigger"
                />
              </div>
              {showResolutionSelector ? (
                <div
                  className="config-field model-select"
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget)) setOpenConfigMenu(null);
                  }}
                >
                  <span>分辨率</span>
                  <button
                    className={openConfigMenu === "resolution" ? "model-select__trigger is-open" : "model-select__trigger"}
                    type="button"
                    aria-haspopup="listbox"
                    aria-expanded={openConfigMenu === "resolution"}
                    disabled={!selectedModel?.supported_resolutions.length}
                    onClick={() => setOpenConfigMenu((menu) => (menu === "resolution" ? null : "resolution"))}
                  >
                    <span>{selectedModel?.supported_resolutions.find((option) => option.value === resolution)?.label ?? "请选择"}</span>
                    <ChevronDown size={16} />
                  </button>
                  {openConfigMenu === "resolution" ? (
                    <div className="model-select__menu" role="listbox" aria-label="选择分辨率">
                      {selectedModel?.supported_resolutions.map((option) => (
                        <button
                          className={option.value === resolution ? "model-select__option is-selected" : "model-select__option"}
                          key={option.value}
                          type="button"
                          role="option"
                          aria-selected={option.value === resolution}
                          onClick={() => {
                            setResolution(option.value);
                            setOpenConfigMenu(null);
                          }}
                        >
                          <span>
                            <strong>{option.label}</strong>
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <div
                className="config-field model-select"
                onBlur={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget)) setOpenConfigMenu(null);
                }}
              >
                <span>质量</span>
                <button
                  className={openConfigMenu === "quality" ? "model-select__trigger is-open" : "model-select__trigger"}
                  type="button"
                  aria-haspopup="listbox"
                  aria-expanded={openConfigMenu === "quality"}
                  onClick={() => setOpenConfigMenu((menu) => (menu === "quality" ? null : "quality"))}
                >
                  <span>{IMAGE_QUALITY_OPTIONS.find((option) => option.value === quality)?.label ?? "自动"}</span>
                  <ChevronDown size={16} />
                </button>
                {openConfigMenu === "quality" ? (
                  <div className="model-select__menu" role="listbox" aria-label="选择生成质量">
                    {IMAGE_QUALITY_OPTIONS.map((option) => (
                      <button
                        className={option.value === quality ? "model-select__option is-selected" : "model-select__option"}
                        key={option.value}
                        type="button"
                        role="option"
                        aria-selected={option.value === quality}
                        onClick={() => {
                          setQuality(option.value);
                          setOpenConfigMenu(null);
                        }}
                      >
                        <span><strong>{option.label}</strong></span>
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="config-field config-field--aspect">
                <span>尺寸</span>
                <div className="aspect-choice-grid" role="radiogroup" aria-label="选择尺寸比例">
                  {selectedModel?.supported_aspect_ratios.map((option) => (
                    <button
                      className={option.value === aspectRatio ? "aspect-choice is-active" : "aspect-choice"}
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={option.value === aspectRatio}
                      onClick={() => setAspectRatio(option.value)}
                    >
                      <span className="aspect-choice__preview">
                        <i style={getAspectRatioStyle(option.value)} />
                      </span>
                      <strong>{option.label}</strong>
                    </button>
                  ))}
                </div>
              </div>
            </div>
            {selectedModel?.speed_hint ? <p className="speed-hint">{selectedModel.speed_hint}</p> : null}
          </section>

          <section className="tool-step">
            <header className="tool-step__head">
              <span>2</span>
              <strong>上传需要修改的图片</strong>
              <small>最多 {selectedModel?.max_input_images ?? 0} 张，单张 10MB</small>
            </header>
            <div className="upload-panel">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept={ACCEPTED_IMAGE_TYPES.join(",")}
                className="visually-hidden"
                onChange={handleFileChange}
              />
              <button
                className="upload-dropzone"
                type="button"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleDrop}
              >
                <span>{isUploading ? <Loader2 className="spin-icon" size={25} /> : <UploadCloud size={25} />}</span>
                <strong>{isUploading ? "正在上传图片" : "点击或拖拽图片上传"}</strong>
                <small>仅支持 JPG、PNG、WEBP，单张不超过 10MB，点击生成时按当前模型线路上传</small>
              </button>
              <Button variant="secondary" type="button" onClick={() => setIsMaterialPickerOpen(true)}>
                <ImagePlus size={16} />
                从素材库选择
              </Button>
              {displayAssets.length ? (
                <div className="upload-list">
                  {displayAssets.map((asset, index) => (
                    <div className="upload-chip" key={asset.id}>
                      <img src={previewUrls[asset.id] || resolveAssetUrl(asset.url)} alt="已上传图片" />
                      <div>
                        <strong>图片 {index + 1}</strong>
                        <small>{formatBytes(asset.size_bytes)}</small>
                      </div>
                      <button type="button" aria-label="移除图片" onClick={() => removeUpload(asset.id)}>
                        <X size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              {uploadError ? <p className="field-error">{uploadError}</p> : null}
            </div>
          </section>

          <section className="tool-step" ref={promptStepRef}>
            <header className="tool-step__head">
              <span>3</span>
              <strong>文字描述</strong>
            </header>
            <div className="batch-generate-output-count" aria-label="图生图生成张数">
              <label htmlFor="image-edit-output-count">生成张数 n</label>
              <input
                id="image-edit-output-count"
                type="number"
                min={1}
                max={MAX_OUTPUT_COUNT}
                value={outputCount}
                onChange={(event) => {
                  const next = Number(event.target.value);
                  setOutputCount(Number.isFinite(next) ? Math.min(Math.max(1, Math.floor(next)), MAX_OUTPUT_COUNT) : 1);
                }}
              />
              <small>范围 1–{MAX_OUTPUT_COUNT} 张，默认 1 张。</small>
            </div>
            <PromptMentionEditor
              value={prompt}
              onChange={setPrompt}
              placeholder="例如：把房间改成温暖的木质风格，增加墙面装饰和更柔和的灯光"
              uploadedAssets={displayAssets}
              textareaRef={promptInputRef}
            />
            <div className="prompt-tools-row">
              <select value={selectedTextModelId ?? ""} onChange={(event) => setSelectedTextModelId(Number(event.target.value) || null)} disabled={!textModels.length}>
                {textModels.length ? textModels.map((model) => <option key={model.id} value={model.id}>{model.name}</option>) : <option value="">暂无文本模型</option>}
              </select>
              <Button variant="secondary" type="button" disabled={!prompt.trim() || !selectedTextModelId || isOptimizingPrompt} isLoading={isOptimizingPrompt} onClick={() => void optimizeCurrentPrompt()}>
                优化提示词
              </Button>
            </div>
          </section>
        </div>

        <div className="generate-bar">
          <Button type="button" disabled={!canSubmit} onClick={submitTask}>
            {isSubmitting ? <Loader2 className="spin-icon" size={17} /> : <Zap size={17} />}
            开始生成
            <span>（消耗 {isQuoteLoading ? "--" : quote === null ? "--" : quote * outputCount} 积分）</span>
          </Button>
          <p>温馨提示：请遵守网络安全相关法规，禁止生成违法违规内容。</p>
        </div>
        {submitError ? <p className="field-error">{submitError}</p> : null}
        {notice ? (
          <div className="inline-notice">
            <CheckCircle2 size={17} />
            <span>{notice}</span>
          </div>
        ) : null}
      </section>

      <aside className="workspace__results" aria-labelledby="results-title">
        <header className="result-header">
          <div>
            <h2 id="results-title">我的创作</h2>
            <p>任务提交后会实时呈现进度、结果和后续操作。</p>
          </div>
          <Button variant="ghost" type="button" disabled={!exportableTaskCount} onClick={() => void exportTaskOutputs()}>
            <Check size={17} />
            批量导出{exportableTaskCount ? `（${exportableTaskCount}）` : ""}
          </Button>
        </header>

        {tasks.length === 0 ? (
          <div className="empty-state">
            <ImagePlus size={36} />
            <h3>还没有创作任务</h3>
            <p>上传图片并提交生成后，处理中和结果卡片会显示在这里。</p>
          </div>
        ) : (
          <div className="result-list">
            {tasks.map((task) => {
                const isFailedTask = task.status === "failed" || task.status === "refunded";
                const isProcessingTask = ["pending", "queued", "running"].includes(task.status);
                const failureMessage = task.failure_message ?? "任务失败，系统会按规则自动退款或进入人工处理。";
                return (
                  <article className="creation-card" key={task.id}>
                    <div className="creation-card__top">
                      <div className="task-meta" aria-label="任务信息">
                        <div className="task-meta__item">
                          <span className="task-meta__label">ID</span>
                          <span className="task-meta__value task-meta__value--accent">{task.task_no}</span>
                        </div>
                        <div className="task-meta__item">
                          <span className="task-meta__label">生成时间</span>
                          <time className="task-meta__value" dateTime={task.created_at} title={task.created_at}>
                            {formatTaskTime(task.created_at)}
                          </time>
                        </div>
                        <div className="task-meta__item">
                          <span className="task-meta__label">模型名称</span>
                          <span className="task-meta__value">{task.model_name || "未命名模型"}</span>
                        </div>
                        {task.owner_name ? (
                          <div className="task-meta__item">
                            <span className="task-meta__label">创建人</span>
                            <span className="task-meta__value">{task.owner_name}</span>
                          </div>
                        ) : null}
                        <div className="task-meta__item">
                          <span className="task-meta__label">生图耗时</span>
                          <span className="task-meta__value">{formatElapsedTime(getTaskElapsedMs(task, now))}</span>
                        </div>
                      </div>
                      <span className={`status-badge status-badge--${task.status}`}>
                        {isProcessingTask ? <Loader2 className="spin-icon" size={14} /> : null}
                        {getImageTaskStatusLabel(task, statusCopy)}
                      </span>
                    </div>

                    <div className="creation-card__specs" aria-label="输出规格">
                      <span>{task.resolution || "默认清晰度"}</span>
                      <span>{task.aspect_ratio || "默认比例"}</span>
                    </div>

                    {(() => {
                      const promptText = task.prompt || "（无提示词）";
                      const promptExpanded = expandedPromptIds.includes(task.id);
                      const promptCollapsible = isPromptCollapsible(task.prompt);
                      return (
                        <div className="creation-prompt-wrap">
                          <p className={promptExpanded ? "creation-prompt is-expanded" : "creation-prompt"} title={promptExpanded || !promptCollapsible ? undefined : task.prompt || undefined}>
                            {promptText}
                          </p>
                          {promptCollapsible ? (
                            <button
                              type="button"
                              className="creation-prompt-toggle"
                              onClick={() =>
                                setExpandedPromptIds((current) =>
                                  current.includes(task.id)
                                    ? current.filter((id) => id !== task.id)
                                    : [...current, task.id],
                                )
                              }
                            >
                              {promptExpanded ? "收起" : "展开"}
                            </button>
                          ) : null}
                        </div>
                      );
                    })()}

                    {isFailedTask ? (
                      <div className="result-note result-note--failed">
                        <AlertTriangle size={18} />
                        <span>{failureMessage}</span>
                      </div>
                    ) : null}

                    <div className="comparison">
                      <figure>
                        <figcaption>{task.input_images.length > 1 ? `原图（${task.input_images.length} 张）` : "原图"}</figcaption>
                        <div className={task.input_images.length > 1 ? "comparison__media comparison__media--multi" : "comparison__media"}>
                          {task.input_images.length ? (
                            task.input_images.map((asset, index) => (
                              <button className="image-preview-trigger" type="button" key={`${asset.url}-${index}`} onClick={() => setPreviewAsset(asset)}>
                                <AssetPreviewImage asset={asset} alt={`原图 ${index + 1}`} />
                              </button>
                            ))
                          ) : (
                            <div className="processing-tile processing-tile--empty">
                              <ImagePlus size={24} />
                              <span>无输入图片</span>
                            </div>
                          )}
                        </div>
                      </figure>
                      <figure>
                        <figcaption>结果图</figcaption>
                        <div className="comparison__media">
                          {task.output_images[0] ? (
                            <button className="image-preview-trigger" type="button" onClick={() => setPreviewAsset(task.output_images[0])}>
                              <AssetPreviewImage asset={task.output_images[0]} alt="结果图" />
                            </button>
                          ) : isFailedTask ? (
                            <div className="failure-tile">
                              <ImageOff size={34} />
                              <strong>生成失败</strong>
                              <span>{failureMessage}</span>
                            </div>
                          ) : (
                            <div className="processing-tile">
                              <Loader2 className="spin-icon" size={28} />
                              <span>{getImageTaskProcessingMessage(task)}</span>
                            </div>
                          )}
                        </div>
                      </figure>
                    </div>

                    <div className="task-actions">
                  <button
                    className={task.is_collected ? "task-button task-button--green is-active" : "task-button task-button--green"}
                    type="button"
                    disabled={task.status !== "succeeded" || collectingTaskIds.includes(task.id)}
                    aria-pressed={task.is_collected}
                    onClick={() => void toggleTaskCollection(task)}
                  >
                    {collectingTaskIds.includes(task.id) ? <Loader2 className="spin-icon" size={17} /> : <FolderPlus size={17} />}
                    {task.is_collected ? "已收藏" : "收藏"}
                  </button>
                  <button
                    className="task-button task-button--blue"
                    type="button"
                    disabled={!task.output_images[0]}
                    onClick={() => void downloadTaskOutput(task)}
                  >
                    <Download size={17} />
                    下载
                  </button>
                  <button
                    className="task-button task-button--orange"
                    type="button"
                    disabled={task.status !== "succeeded" || !task.output_images[0]}
                    title={task.status === "succeeded" && task.output_images[0] ? "使用结果图、原始参考图和原提示词重新编辑" : "结果生成后可重新编辑"}
                    onClick={() => continueEdit(task)}
                  >
                    <Edit3 size={17} />
                    重新编辑
                  </button>
                  <button
                    className="task-button task-button--cyan"
                    type="button"
                    disabled={regeneratingTaskIds.includes(task.id) || !task.input_images.length}
                    title={task.input_images.length ? "复用原图和文案重新生成" : "没有可复用的原图"}
                    onClick={() => void regenerateTask(task)}
                  >
                    {regeneratingTaskIds.includes(task.id) ? <Loader2 className="spin-icon" size={17} /> : <RotateCcw size={17} />}
                    重新生成
                  </button>
                  <button
                    className="task-button task-button--red"
                    type="button"
                    disabled={isProcessingTask}
                    title={isProcessingTask ? "生成过程中暂不能删除" : "删除记录"}
                    onClick={() => setConfirmDeleteTaskId(task.id)}
                  >
                    <Trash2 size={17} />
                    删除
                  </button>
                    </div>
                  </article>
                );
              })}
          </div>
        )}
      </aside>

      {confirmDeleteTaskId ? (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
            <div className="dialog-icon dialog-icon--danger">
              <Trash2 size={22} />
            </div>
            <h2 id="delete-title">删除这条创作记录</h2>
            <p>删除后当前结果卡片会从列表移除。已经下载到本地的文件不会受到影响。</p>
            <div className="dialog-actions">
              <Button variant="ghost" type="button" onClick={() => setConfirmDeleteTaskId(null)}>
                取消
              </Button>
              <Button
                variant="danger"
                type="button"
                onClick={() => void deleteTask(confirmDeleteTaskId)}
              >
                删除记录
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {previewAsset ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setPreviewAsset(null)}>
          <div className="image-preview-dialog" role="dialog" aria-modal="true" aria-label="图片预览">
            <button type="button" aria-label="关闭预览" onClick={() => setPreviewAsset(null)}>
              <X size={20} />
            </button>
            <img src={resolveAssetUrl(previewAsset.url)} alt="创作结果预览" onClick={(event) => event.stopPropagation()} />
          </div>
        </div>
      ) : null}
      <MaterialPicker open={isMaterialPickerOpen} onClose={() => setIsMaterialPickerOpen(false)} onSelect={addMaterialAssets} />
    </main>
  );
};

const PromptMentionEditor = ({
  value,
  onChange,
  placeholder,
  uploadedAssets,
  textareaRef,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  uploadedAssets: ImageAsset[];
  textareaRef: RefObject<HTMLTextAreaElement | null>;
}) => {
  const [mentionState, setMentionState] = useState<MentionMenuState | null>(null);
  const [activeMentionIndex, setActiveMentionIndex] = useState(0);
  const mentionOptions = useMemo(
    () =>
      uploadedAssets
        .map((asset, index) => ({
          asset,
          index,
          label: `图片 ${index + 1}`,
          detail: asset.width && asset.height ? `${asset.width} x ${asset.height}` : asset.mime_type,
        }))
        .filter((option) => !mentionState?.query.trim() || option.label.replace(/\s/g, "").includes(mentionState.query.replace(/\s/g, ""))),
    [mentionState?.query, uploadedAssets],
  );
  const showMentionMenu = Boolean(mentionState);

  useEffect(() => {
    if (!mentionOptions.length) {
      setActiveMentionIndex(0);
      return;
    }
    setActiveMentionIndex((index) => Math.min(index, mentionOptions.length - 1));
  }, [mentionOptions.length]);

  const syncMentionState = (nextValue: string, cursorPosition: number | null) => {
    if (cursorPosition === null) {
      setMentionState(null);
      return;
    }
    setMentionState(getMentionState(nextValue, cursorPosition));
  };

  const syncMentionStateFromTextarea = (textarea: HTMLTextAreaElement | null) => {
    if (!textarea) {
      setMentionState(null);
      return;
    }
    syncMentionState(textarea.value, textarea.selectionStart);
  };

  const insertMention = (optionIndex: number) => {
    if (!mentionState) return;
    const option = mentionOptions[optionIndex];
    if (!option) return;
    const beforeMention = value.slice(0, mentionState.start);
    const afterMention = value.slice(mentionState.end);
    const needsTrailingSpace = afterMention.length > 0 && !/^\s/.test(afterMention);
    const nextValue = `${beforeMention}@${option.label}${needsTrailingSpace ? " " : ""}${afterMention}`;
    const nextCursorPosition = beforeMention.length + option.label.length + 1 + (needsTrailingSpace ? 1 : 0);

    onChange(nextValue);
    setMentionState(null);
    window.requestAnimationFrame(() => {
      const textarea = textareaRef.current;
      if (!textarea) return;
      textarea.focus();
      textarea.setSelectionRange(nextCursorPosition, nextCursorPosition);
    });
  };

  const handleChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    const nextValue = event.target.value;
    onChange(nextValue);
    syncMentionState(nextValue, event.target.selectionStart);
  };

  const handleInput = (event: FormEvent<HTMLTextAreaElement>) => {
    syncMentionState(event.currentTarget.value, event.currentTarget.selectionStart);
  };

  const handleCompositionEnd = (event: CompositionEvent<HTMLTextAreaElement>) => {
    syncMentionState(event.currentTarget.value, event.currentTarget.selectionStart);
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "@" || event.key === "＠") {
      window.requestAnimationFrame(() => syncMentionStateFromTextarea(textareaRef.current));
      return;
    }
    if (!showMentionMenu) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveMentionIndex((index) => Math.min(index + 1, Math.max(mentionOptions.length - 1, 0)));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveMentionIndex((index) => Math.max(index - 1, 0));
      return;
    }
    if ((event.key === "Enter" || event.key === "Tab") && mentionOptions.length) {
      event.preventDefault();
      insertMention(activeMentionIndex);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setMentionState(null);
    }
  };

  // Normal selectable textarea only — the old transparent+highlight overlay
  // made the last character of the last line hard to select/copy.
  return (
    <div className={showMentionMenu ? "prompt-mention-editor prompt-mention-editor--workbench is-menu-open" : "prompt-mention-editor prompt-mention-editor--workbench"}>
      <textarea
        ref={textareaRef}
        className="prompt-mention-editor__input prompt-input"
        value={value}
        onChange={handleChange}
        onCompositionEnd={handleCompositionEnd}
        onClick={(event) => syncMentionState(event.currentTarget.value, event.currentTarget.selectionStart)}
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onKeyUp={(event) => syncMentionState(event.currentTarget.value, event.currentTarget.selectionStart)}
        placeholder={placeholder}
        spellCheck={false}
      />
      {showMentionMenu ? (
        <div className="prompt-mention-menu" role="listbox" aria-label="选择要引用的图片">
          {mentionOptions.length ? (
            mentionOptions.map((option, index) => (
              <button
                className={index === activeMentionIndex ? "prompt-mention-option is-active" : "prompt-mention-option"}
                key={option.asset.id}
                type="button"
                role="option"
                aria-selected={index === activeMentionIndex}
                onMouseDown={(event) => {
                  event.preventDefault();
                  insertMention(index);
                }}
              >
                <img src={resolveAssetUrl(option.asset.url)} alt="" />
                <span>
                  <strong>@{option.label}</strong>
                  <small>{option.detail}</small>
                </span>
              </button>
            ))
          ) : (
            <div className="prompt-mention-menu__empty">{uploadedAssets.length ? "没有匹配的图片" : "请先选择素材"}</div>
          )}
        </div>
      ) : null}
    </div>
  );
};
