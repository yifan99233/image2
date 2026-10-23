import { LoadingArt } from "@/components/ui/LoadingArt";
import { LoadingIndicator } from "@/components/ui/LoadingIndicator";
import { CreationMobileTabs } from "@/components/layout/CreationMobileTabs";
import { useCreationPanel } from "@/hooks/useCreationPanel";
import { useEffect, useMemo, useRef, useState, type CompositionEvent, type CSSProperties, type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode } from "react";
import { AlertTriangle, Boxes, Brush, Camera, ChevronDown, ChevronUp, CheckCircle2, Download, Edit3, FileImage, FolderPlus, PackageOpen, Play, RotateCcw, Shirt, Trash2, UploadCloud, X } from "lucide-react";
import { Clapperboard, Film, Image, Images, Layers3, Sparkles } from "@/components/ui/StudioIcons";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/Button";
import { BatchGroupEditor } from "@/components/batch/BatchGroupEditor";
import { BatchTaskPanel } from "@/components/batch/BatchTaskPanel";
import { MAX_GROUPS, MAX_GROUP_OUTPUTS, groupIssues, groupPrompt, matchGroupPromptRows, readGroupZip, validateGroupFiles, type BatchGroup, type GroupPromptRow } from "@/utils/batchGroups";
import { uploadGroupReferences, type GroupAssetCache } from "@/utils/batchGroupUploads";
import { MaterialPicker } from "@/components/materials/MaterialPicker";
import { ModelPicker } from "@/components/models/ModelPicker";
import { DEFAULT_IMAGE_QUALITY, IMAGE_QUALITY_OPTIONS } from "@/constants/imageGeneration";
import { imageTaskService } from "@/services/imageTasks";
import { modelService } from "@/services/models";
import { uploadService } from "@/services/uploads";
import { DEFAULT_MAX_BATCH_TASKS, defaultUserExperienceConfig, uxService } from "@/services/ux";
import { workService } from "@/services/works";
import type { ImageAsset, ImageModel, ImageQuality, ImageTask, ImageBatchSubmission } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import { downloadBlob, downloadMedia, startBrowserDownload } from "@/utils/download";
import { getImageTaskProcessingMessage, getImageTaskStatusLabel } from "@/utils/imageTaskStatus";
import { formatElapsedTime, getTaskElapsedMs } from "@/utils/time";
import { createImageEditNavigationState } from "@/utils/imageEditNavigation";
import { readToolPreference, resolveToolPreference, writeToolPreference } from "@/utils/toolPreferences";
import { getAssetPreviewSource } from "@/utils/assetPreview";
import { isVideoAsset } from "@/pages/shared/mediaConfig";
import { appendBatchPrompts, createBatchPromptTemplate, readBatchPromptFile, readBatchGenerateFile, type BatchPromptImport, splitBatchPrompts, type BatchEditPromptMode, type BatchPromptTemplateFormat } from "@/utils/batchPrompts";

type ToolMode = "text-to-image" | "text-to-video" | "image-to-video" | "batch-generate" | "batch-edit";
type ProductMode = "try-on" | "multi-view" | "pose" | "ootd" | "background" | "scene";
type MentionMenuState = {
  query: string;
  start: number;
  end: number;
};
type BatchGenerateMode = "one_per_prompt" | "multi_output";
const MAX_BATCH_GENERATE_COUNT = 20000;
const MAX_STANDARD_OUTPUT_COUNT = 9;
const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;
const MAX_BATCH_EDIT_TASKS = 200;

type ToolConfig = {
  title: string;
  icon: typeof Image;
  intro: string;
  workType: string;
  needsUpload: boolean;
  submitLabel: string;
};

const creativeConfig: Record<ToolMode, ToolConfig> = {
  "text-to-image": {
    title: "文生图",
    icon: Image,
    intro: "描述想要的画面，选择模型和画幅，开始你的创作。",
    workType: "text_to_image",
    needsUpload: false,
    submitLabel: "开始生成",
  },
  "text-to-video": {
    title: "文生视频",
    icon: Clapperboard,
    intro: "用文字描述生成短视频。可选择画面比例与时长；计费按分辨率 × 时长。",
    workType: "text_to_video",
    needsUpload: false,
    submitLabel: "开始生成视频",
  },
  "image-to-video": {
    title: "图生视频",
    icon: Film,
    intro: "上传参考图并描述运动/镜头，生成短视频。适合商品动效、人物微动与场景延展。",
    workType: "image_to_video",
    needsUpload: true,
    submitLabel: "开始生成视频",
  },
  "batch-generate": {
    title: "批量生图",
    icon: Images,
    intro: "按多条提示词批量创建生成任务，任务结果会进入作品和任务记录。",
    workType: "batch_generate",
    needsUpload: false,
    submitLabel: "提交批量任务",
  },
  "batch-edit": {
    title: "批量改图",
    icon: Layers3,
    intro: "支持文件夹任务组、一图一词和商品套图，批量处理商品与多图参考素材。",
    workType: "batch_edit",
    needsUpload: true,
    submitLabel: "提交批量改图",
  },
};

const relatedTaskWorkTypes: Record<string, string[]> = {
  text_to_image: ["text_to_image", "batch_generate"],
  text_to_video: ["text_to_video"],
  image_to_video: ["image_to_video"],
  batch_generate: ["text_to_image", "batch_generate"],
  batch_edit: ["image_edit", "image_to_image", "batch_edit"],
};

const isRelatedTask = (task: ImageTask, workType: string) => {
  return (relatedTaskWorkTypes[workType] ?? [workType]).includes(task.work_type);
};

const TASK_HISTORY_PAGE_SIZE = 40;

const taskStatusCopy: Record<ImageTask["status"], string> = {
  pending: "等待创建",
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "生成失败",
  refunded: "已退款",
};

const PROMPT_COLLAPSE_CHARS = 72;

const isPromptCollapsible = (prompt?: string | null) => {
  if (!prompt) return false;
  return prompt.length > PROMPT_COLLAPSE_CHARS || prompt.includes("\n");
};


const productConfig: Record<ProductMode, ToolConfig> = {
  "try-on": {
    title: "模特换装",
    icon: Shirt,
    intro: "上传服装和模特参考图，生成贴合身形、光影自然的试穿主图。",
    workType: "product_model_try_on",
    needsUpload: true,
    submitLabel: "生成换装图",
  },
  "multi-view": {
    title: "多机位生成",
    icon: Camera,
    intro: "基于商品图生成正面、侧面、俯拍和细节特写。",
    workType: "product_multi_view",
    needsUpload: true,
    submitLabel: "生成多机位",
  },
  pose: {
    title: "多种人物姿势生成",
    icon: Brush,
    intro: "保留人物身份和服饰，生成多种展示动作。",
    workType: "product_pose",
    needsUpload: true,
    submitLabel: "生成姿势图",
  },
  ootd: {
    title: "OOTD 穿搭",
    icon: Boxes,
    intro: "把单品组合成完整穿搭图，适合社媒封面、种草图和商品集合页。",
    workType: "product_ootd",
    needsUpload: true,
    submitLabel: "生成穿搭图",
  },
  background: {
    title: "商品抠图换背景",
    icon: PackageOpen,
    intro: "识别商品主体并替换为后端模型支持的背景风格。",
    workType: "product_background_replace",
    needsUpload: true,
    submitLabel: "更换背景",
  },
  scene: {
    title: "商品场景合成",
    icon: Sparkles,
    intro: "将商品自然放入厨房、浴室、户外、节日等营销场景中。",
    workType: "product_scene_compose",
    needsUpload: true,
    submitLabel: "合成场景",
  },
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

const getMentionState = (value: string, cursorPosition: number): MentionMenuState | null => {
  const beforeCursor = value.slice(0, cursorPosition);
  const halfWidthAtIndex = beforeCursor.lastIndexOf("@");
  const fullWidthAtIndex = beforeCursor.lastIndexOf("＠");
  const atIndex = Math.max(halfWidthAtIndex, fullWidthAtIndex);
  if (atIndex < 0) return null;
  const query = beforeCursor.slice(atIndex + 1);
  if (/[\r\n]/.test(query)) return null;
  if (/\s/.test(query) && !/^图片\s*\d*$/.test(query)) return null;
  return {
    query,
    start: atIndex,
    end: cursorPosition,
  };
};

export const CreativeToolPage = ({ mode }: { mode: ToolMode }) => (
  <RealToolPage key={mode} config={creativeConfig[mode]} />
);

export const ProductToolPage = ({ mode }: { mode: ProductMode }) => (
  <RealToolPage key={mode} config={productConfig[mode]} />
);

const RealToolPage = ({ config }: { config: ToolConfig }) => {
  const [mobilePanel, setMobilePanel] = useCreationPanel();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const batchZipInputRef = useRef<HTMLInputElement>(null);
  const promptFileInputRef = useRef<HTMLInputElement>(null);
  const templateMenuRef = useRef<HTMLDivElement>(null);
  const [models, setModels] = useState<ImageModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [openConfigMenu, setOpenConfigMenu] = useState<"resolution" | "quality" | "aspect" | null>(null);
  const [uploadedAssets, setUploadedAssets] = useState<ImageAsset[]>([]);
  const [prompt, setPrompt] = useState("");
  const [importedBatch, setImportedBatch] = useState<BatchPromptImport | null>(null);
  const promptRef = useRef(prompt);
  promptRef.current = prompt;
  const [isImportingPrompts, setIsImportingPrompts] = useState(false);
  const [isTemplateMenuOpen, setIsTemplateMenuOpen] = useState(false);
  const [isDownloadingTemplate, setIsDownloadingTemplate] = useState(false);
  const [batchGenerateMode, setBatchGenerateMode] = useState<BatchGenerateMode>("one_per_prompt");
  const [batchGenerateOutputCount, setBatchGenerateOutputCount] = useState(10);
  const [outputCount, setOutputCount] = useState(1);
  const [batchEditPromptMode, setBatchEditPromptMode] = useState<BatchEditPromptMode>("shared");
  const [batchGroups, setBatchGroups] = useState<BatchGroup[]>([]);
  const [groupPromptRows, setGroupPromptRows] = useState<GroupPromptRow[]>([]);
  const [isGroupLoading, setIsGroupLoading] = useState(false);
  const groupAssetCache = useRef<GroupAssetCache>(new WeakMap());
  const [groupSubmissionProgress, setGroupSubmissionProgress] = useState("");
  const groupSubmissionKey = useRef({ signature: "", batchId: "" });
  const [batchEditPromptsByAssetId, setBatchEditPromptsByAssetId] = useState<Record<number, string>>({});
  const [resolution, setResolution] = useState("");
  const [aspectRatio, setAspectRatio] = useState("");
  const [duration, setDuration] = useState("");
  const [quality, setQuality] = useState<ImageQuality>(DEFAULT_IMAGE_QUALITY);
  const [quote, setQuote] = useState<number | null>(null);
  const [priceBreakdown, setPriceBreakdown] = useState("");
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [latestBatchId, setLatestBatchId] = useState("");
  const [batchRevision, setBatchRevision] = useState(0);
  const [historyCursor, setHistoryCursor] = useState<number | null>(null);
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isMaterialPickerOpen, setIsMaterialPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewErrorAssetIds, setPreviewErrorAssetIds] = useState<number[]>([]);
  const [previewAsset, setPreviewAsset] = useState<ImageAsset | null>(null);
  const [collectingTaskIds, setCollectingTaskIds] = useState<number[]>([]);
  const [regeneratingTaskIds, setRegeneratingTaskIds] = useState<number[]>([]);
  const [confirmDeleteTaskId, setConfirmDeleteTaskId] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [maxBatchTasks, setMaxBatchTasks] = useState(defaultUserExperienceConfig.max_batch_tasks);
  const [batchUploadLimits, setBatchUploadLimits] = useState({ maxBytes: defaultUserExperienceConfig.batch_upload_max_bytes, maxPromptChars: defaultUserExperienceConfig.batch_upload_max_prompt_chars });
  const batchEditMaxTasks = MAX_BATCH_EDIT_TASKS;
  const batchGenerateMaxTasks = Math.min(maxBatchTasks, MAX_BATCH_GENERATE_COUNT);

  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );
  const isVideoTool = config.workType === "text_to_video" || config.workType === "image_to_video";
  const isBatchTool = config.workType === "batch_generate" || config.workType === "batch_edit";
  const batchGeneratePrompts = useMemo(
    () => importedBatch?.prompts ?? splitBatchPrompts(prompt),
    [prompt, importedBatch],
  );
  const maxOutputCount = MAX_STANDARD_OUTPUT_COUNT;
  const batchGenerateTaskCount = batchGenerateMode === "multi_output"
    ? (prompt.trim() ? batchGenerateOutputCount : 0)
    : batchGeneratePrompts.length;
  const batchEditPromptValues = useMemo(
    () => uploadedAssets.map((asset) => batchEditPromptsByAssetId[asset.id]?.trim() ?? ""),
    [batchEditPromptsByAssetId, uploadedAssets],
  );
  const batchEditPromptMissingCount = batchEditPromptValues.filter((value) => !value).length;
  const usesGroupPrompts = config.workType === "batch_edit" && batchEditPromptMode === "grouped";
  const mappedGroupRows = useMemo(() => matchGroupPromptRows(groupPromptRows, batchGroups), [groupPromptRows, batchGroups]);
  const batchGroupIssues = useMemo(() => groupIssues(batchGroups, mappedGroupRows, selectedModel?.max_input_images ?? 8), [batchGroups, mappedGroupRows, selectedModel]);
  const usesPerImagePrompts = config.workType === "batch_edit" && batchEditPromptMode === "per_image";
  const usesMatrixPrompts = config.workType === "batch_edit" && batchEditPromptMode === "matrix";
  const batchEditTaskCount = usesGroupPrompts ? batchGroups.reduce((sum, group) => sum + group.outputs, 0) : usesMatrixPrompts ? uploadedAssets.length * batchGeneratePrompts.length : uploadedAssets.length;
  const batchGeneratePromptOverflow = Math.max(batchGenerateTaskCount - batchGenerateMaxTasks, 0);
  const hasBatchGeneratePromptOverflow = config.workType === "batch_generate" && batchGeneratePromptOverflow > 0;
  const batchEditTaskLimit = usesGroupPrompts ? Math.min(maxBatchTasks, MAX_GROUP_OUTPUTS) : batchEditMaxTasks;
  const batchEditTaskOverflow = Math.max(batchEditTaskCount - batchEditTaskLimit, 0);
  const hasBatchEditTaskOverflow = config.workType === "batch_edit" && batchEditTaskOverflow > 0;
  const hasBatchEditPromptMismatch = config.workType === "batch_edit"
    && batchEditPromptMode === "per_image"
    && uploadedAssets.length > 0
    && batchEditPromptMissingCount > 0;
  const pricedTaskCount = config.workType === "text_to_image"
    ? outputCount
    : config.workType === "batch_generate"
    ? Math.max(batchGenerateTaskCount, 1)
    : config.workType === "batch_edit"
      ? batchEditTaskCount
      : 1;
  const estimatedCreditCost = quote === null ? null : Math.round(quote * 100) * pricedTaskCount / 100;
  const hasPromptContent = usesGroupPrompts ? batchGroupIssues.length === 0 : usesPerImagePrompts
    ? uploadedAssets.length > 0 && batchEditPromptMissingCount === 0
    : Boolean(prompt.trim());

  useEffect(() => {
    if (!isTemplateMenuOpen) return;
    const dismissOutside = (event: MouseEvent) => {
      if (!templateMenuRef.current?.contains(event.target as Node)) setIsTemplateMenuOpen(false);
    };
    const dismissEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setIsTemplateMenuOpen(false);
    };
    document.addEventListener("mousedown", dismissOutside);
    document.addEventListener("keydown", dismissEscape);
    return () => {
      document.removeEventListener("mousedown", dismissOutside);
      document.removeEventListener("keydown", dismissEscape);
    };
  }, [isTemplateMenuOpen]);

  useEffect(() => {
    if (!error) return;
    const timerId = window.setTimeout(() => setError(null), 5000);
    return () => window.clearTimeout(timerId);
  }, [error]);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(null), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  useEffect(() => {
    if (!isBatchTool) return;
    let ignore = false;
    uxService
      .getConfig()
      .then((uxConfig) => {
        if (ignore) return;
        const nextLimit = Number(uxConfig.max_batch_tasks);
        setMaxBatchTasks(Number.isFinite(nextLimit) && nextLimit >= 1 ? Math.floor(nextLimit) : DEFAULT_MAX_BATCH_TASKS);
        setBatchUploadLimits({ maxBytes: uxConfig.batch_upload_max_bytes ?? defaultUserExperienceConfig.batch_upload_max_bytes, maxPromptChars: uxConfig.batch_upload_max_prompt_chars ?? defaultUserExperienceConfig.batch_upload_max_prompt_chars });
      })
      .catch(() => {
        if (!ignore) setMaxBatchTasks(DEFAULT_MAX_BATCH_TASKS);
      });
    return () => {
      ignore = true;
    };
  }, [isBatchTool]);

  useEffect(() => {
    if (config.workType !== "batch_generate") return;
    setBatchGenerateOutputCount((current) => Math.min(Math.max(1, current), MAX_BATCH_GENERATE_COUNT));
  }, [config.workType]);

  useEffect(() => {
    if (config.workType !== "text_to_image") return;
    setOutputCount((current) => Math.min(Math.max(1, current), maxOutputCount));
  }, [config.workType, maxOutputCount]);

  useEffect(() => {
    let ignore = false;
    setIsLoadingModels(true);
    modelService
      .getModels(config.workType)
      .then((items) => {
        if (ignore) return;
        setModels(items);
        const preference = resolveToolPreference(items, readToolPreference(config.workType));
        setSelectedModelId(preference.modelId);
        setResolution(preference.resolution);
        setAspectRatio(preference.aspectRatio);
        setDuration(preference.duration);
        setQuality(preference.quality);
        setError(null);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "模型配置加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoadingModels(false);
      });
    return () => {
      ignore = true;
    };
  }, [config.workType]);


  useEffect(() => {
    if (!selectedModelId || !resolution || !aspectRatio) return;
    if (isVideoTool && !duration) return;
    writeToolPreference(config.workType, { modelId: selectedModelId, resolution, aspectRatio, duration, quality });
  }, [selectedModelId, resolution, aspectRatio, duration, quality, config.workType, isVideoTool]);

  useEffect(() => {
    let ignore = false;
    const controller = new AbortController();
    historyRequest.current = controller;
    setTasks([]);
    setHistoryCursor(null);
    setHasMoreHistory(false);
    setIsLoadingHistory(true);
    setHistoryError(null);
    if (isBatchTool) {
      historyRequest.current = null;
      setIsLoadingHistory(false);
      return () => controller.abort();
    }
    imageTaskService
      .getTasks({ limit: TASK_HISTORY_PAGE_SIZE, signal: controller.signal })
      .then((items) => {
        if (ignore) return;
        setTasks((current) => {
          const knownIds = new Set(current.map((task) => task.id));
          return [...current, ...items.filter((task) => !knownIds.has(task.id) && isRelatedTask(task, config.workType))];
        });
        setHistoryCursor(items.length ? Math.min(...items.map((task) => task.id)) : null);
        setHasMoreHistory(items.length === TASK_HISTORY_PAGE_SIZE);
      })
      .catch((err) => {
        if (!ignore) setHistoryError(err instanceof Error ? err.message : "任务记录加载失败");
      })
      .finally(() => {
        if (!ignore) {
          setIsLoadingHistory(false);
          historyRequest.current = null;
        }
      });

    return () => {
      ignore = true;
      controller.abort();
      historyRequest.current?.abort();
      historyRequest.current = null;
    };
  }, [config.workType]);

  async function loadMoreHistory() {
    if (historyRequest.current || (!hasMoreHistory && !historyError)) return;
    const controller = new AbortController();
    historyRequest.current = controller;
    setIsLoadingHistory(true);
    setHistoryError(null);
    try {
      const items = await imageTaskService.getTasks({
        limit: TASK_HISTORY_PAGE_SIZE,
        beforeId: historyCursor ?? undefined,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setTasks((current) => {
        const knownIds = new Set(current.map((task) => task.id));
        return [...current, ...items.filter((task) => !knownIds.has(task.id) && isRelatedTask(task, config.workType))];
      });
      if (items.length) setHistoryCursor(Math.min(...items.map((task) => task.id)));
      setHasMoreHistory(items.length === TASK_HISTORY_PAGE_SIZE);
    } catch (err) {
      if (!controller.signal.aborted) setHistoryError(err instanceof Error ? err.message : "任务记录加载失败");
    } finally {
      if (!controller.signal.aborted) {
        setIsLoadingHistory(false);
        historyRequest.current = null;
      }
    }
  }

  useEffect(() => {
    if (isBatchTool) return;
    const activeTaskIds = tasks.filter((task) => ["pending", "queued", "running"].includes(task.status)).map((task) => task.id);
    if (!activeTaskIds.length) return;

    const timerId = window.setInterval(() => {
      setNow(Date.now());
      void imageTaskService.getTaskStatuses(activeTaskIds)
        .then((updatedTasks) => {
          setTasks((current) =>
            current.map((task) => {
              const update = updatedTasks.find((updatedTask) => updatedTask.id === task.id);
              if (!update) return task;
              // Status polling returns a partial task. Keep immutable metadata
              // such as input_images for the result card.
              return { ...task, ...update, input_images: update.input_images ?? task.input_images };
            }),
          );
          if (updatedTasks.some((task) => ["succeeded", "failed", "refunded"].includes(task.status))) {
            notifyCreditBalanceChanged();
          }
        })
        .catch(() => undefined);
    }, 1600);

    return () => window.clearInterval(timerId);
  }, [tasks, isBatchTool]);

  useEffect(() => {
    setQuote(null);
    setPriceBreakdown("");
    if (!selectedModel || !resolution || !aspectRatio) return;
    if (isVideoTool && !duration) return;
    let ignore = false;
    modelService
      .quote(selectedModel.id, config.workType, resolution, aspectRatio, 1, isVideoTool ? duration : undefined)
      .then((nextQuote) => {
        if (!ignore) {
          setQuote(nextQuote.credit_cost);
          const pricing = nextQuote.pricing;
          setPriceBreakdown(pricing ? `${pricing.vip_tier_name}：基础 ${Number(pricing.base_price)} × ${Number(pricing.discount_rate)} + 固定 ${Number(pricing.fixed_surcharge)} = ${nextQuote.credit_cost} 积分/次` : "");
        }
      })
      .catch(() => {
        if (!ignore) { setQuote(null); setPriceBreakdown(""); }
      });
    return () => {
      ignore = true;
    };
  }, [resolution, aspectRatio, duration, selectedModel, config.workType, isVideoTool]);

  const maxInputImages = selectedModel?.max_input_images ?? (config.needsUpload ? 8 : 0);
  const maxSelectableImages = config.workType === "batch_edit" ? batchEditMaxTasks : maxInputImages;

  const selectGenerationModel = (nextModel: ImageModel) => {
    const supportsResolution = nextModel.supported_resolutions.some((option) => option.value === resolution);
    const supportsAspectRatio = nextModel.supported_aspect_ratios.some((option) => option.value === aspectRatio);
    const supportsDuration = nextModel.supported_durations?.some((option) => option.value === duration) ?? !isVideoTool;
    const nextResolution = supportsResolution ? resolution : nextModel.supported_resolutions[0]?.value ?? "";
    const nextAspectRatio = supportsAspectRatio ? aspectRatio : nextModel.supported_aspect_ratios[0]?.value ?? "";
    const nextDuration = supportsDuration ? duration : nextModel.supported_durations?.[0]?.value ?? "";
    const adjustedFields = [
      nextResolution !== resolution ? "清晰度" : "",
      nextAspectRatio !== aspectRatio ? "画幅" : "",
      isVideoTool && nextDuration !== duration ? "时长" : "",
    ].filter(Boolean);

    setSelectedModelId(nextModel.id);
    setResolution(nextResolution);
    setAspectRatio(nextAspectRatio);
    setDuration(nextDuration);
    const imageLimitExceeded = config.workType !== "batch_edit" && uploadedAssets.length > nextModel.max_input_images;
    if (adjustedFields.length || imageLimitExceeded) {
      const messages = [
        adjustedFields.length ? `已调整${adjustedFields.join("、")}以兼容该模型` : "",
        imageLimitExceeded ? `当前 ${uploadedAssets.length} 张参考图超过该模型的 ${nextModel.max_input_images} 张上限` : "",
      ].filter(Boolean);
      setNotice(`已切换至 ${nextModel.name}，${messages.join("；")}`);
    }
  };

  const uploadFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    if (!files.length) return;
    if (isSubmitting || isUploading || isGroupLoading) return;
    const archives = files.filter((file) => /\.zip$/i.test(file.name) || /^(application\/zip|application\/x-zip-compressed)$/i.test(file.type));
    if (config.workType === "batch_edit" && archives.length) {
      if (files.length !== 1) {
        setError("请一次选择一个 ZIP 压缩包；散图请单独上传");
        return;
      }
      setIsGroupLoading(true);
      setError(null);
      try {
        const imported = await readGroupZip(archives[0]);
        const nextGroups = [...batchGroups, ...imported.groups];
        if (nextGroups.length > MAX_GROUPS) throw new Error(`每批最多 ${MAX_GROUPS} 个任务组`);
        validateGroupFiles(nextGroups.flatMap((group) => group.images));
        setBatchGroups(nextGroups);
        setBatchEditPromptMode("grouped");
        setNotice(`已按文件夹导入 ${imported.groups.length} 个任务组、${imported.groups.reduce((sum, group) => sum + group.images.length, 0)} 张参考图，请导入对应提示词${imported.skipped ? `；跳过 ${imported.skipped} 个非图片文件` : ""}${uploadedAssets.length ? "；原有散图保留在原提示词模式中" : ""}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "ZIP 导入失败");
      } finally {
        setIsGroupLoading(false);
      }
      return;
    }
    const oversizedFile = files.find((file) => file.size > MAX_UPLOAD_SIZE);
    if (oversizedFile) {
      setError(`图片“${oversizedFile.name}”超过 10MB，请压缩后再上传`);
      return;
    }
    const remaining = Math.max(0, maxSelectableImages - uploadedAssets.length);
    const nextFiles = maxSelectableImages > 0 ? files.slice(0, remaining) : files;
    if (maxSelectableImages > 0 && !nextFiles.length) {
      setError(`当前最多支持 ${maxSelectableImages} 张图片`);
      return;
    }
    setIsUploading(true);
    setError(null);
    try {
      const assets = await Promise.all(nextFiles.map((file) => uploadService.uploadImage(file)));
      setUploadedAssets((current) => [...current, ...assets]);
      if (files.length > nextFiles.length) {
        setNotice(`已按上限上传 ${nextFiles.length} 张（最多 ${maxSelectableImages} 张）`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片上传失败");
    } finally {
      setIsUploading(false);
    }
  };

  const removeUpload = (assetId: number) => {
    setUploadedAssets((current) => current.filter((asset) => asset.id !== assetId));
    setBatchEditPromptsByAssetId((current) => {
      const next = { ...current };
      delete next[assetId];
      return next;
    });
  };

  const moveUploadedAsset = (assetId: number, direction: -1 | 1) => {
    setUploadedAssets((current) => {
      const index = current.findIndex((asset) => asset.id === assetId);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  };

  const updateBatchEditPrompt = (assetId: number, value: string) => {
    setBatchEditPromptsByAssetId((current) => ({ ...current, [assetId]: value }));
  };

  const switchBatchEditPromptMode = (nextMode: BatchEditPromptMode) => {
    if (nextMode === batchEditPromptMode || isSubmitting || isGroupLoading) return;
    if (nextMode === "per_image" && prompt.trim()) {
      setBatchEditPromptsByAssetId((current) => {
        const next = { ...current };
        uploadedAssets.forEach((asset) => {
          if (!next[asset.id]?.trim()) next[asset.id] = prompt.trim();
        });
        return next;
      });
    }
    if (nextMode === "shared" && !prompt.trim()) {
      const firstPrompt = batchEditPromptValues.find(Boolean);
      if (firstPrompt) setPrompt(firstPrompt);
    }
    setBatchEditPromptMode(nextMode);
  };

  const addMaterialAssets = (assets: ImageAsset[]) => {
    setUploadedAssets((current) => {
      const existingIds = new Set(current.map((asset) => asset.id));
      const merged = [...current];
      for (const asset of assets) {
        if (existingIds.has(asset.id)) continue;
        if (maxSelectableImages > 0 && merged.length >= maxSelectableImages) break;
        merged.push(asset);
      }
      return merged;
    });
  };

  const importBatchPrompts = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file || isImportingPrompts) return;
    setIsImportingPrompts(true);
    setError(null);
    try {
      const limit = config.workType === "batch_edit" ? batchEditMaxTasks : batchGenerateMaxTasks;
      if (config.workType === "batch_generate") {
        const imported = await readBatchGenerateFile(file, limit);
        setImportedBatch(imported);
        setPrompt(imported.prompts.slice(0, 3).join("\n\n"));
        setBatchGenerateMode("one_per_prompt");
        setNotice(`已校验并导入 ${imported.prompts.length} 条提示词、${new Set(imported.folderNames ?? ["生成结果"]).size} 个文件夹，空行已跳过`);
        return;
      }
      const imported = await readBatchPromptFile(file, limit);
      const combined = appendBatchPrompts(promptRef.current, imported, limit);
      setPrompt(combined);
      if (config.workType === "batch_edit") setBatchEditPromptMode("matrix");
      else setBatchGenerateMode("one_per_prompt");
      setNotice(`已导入 ${imported.length} 条提示词，可继续编辑后提交`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提示词文件读取失败");
    } finally {
      setIsImportingPrompts(false);
    }
  };

  const downloadBatchPromptTemplate = async (format: BatchPromptTemplateFormat) => {
    setIsTemplateMenuOpen(false);
    setIsDownloadingTemplate(true);
    setError(null);
    try {
      const template = await createBatchPromptTemplate(config.workType === "batch_edit", format);
      downloadBlob(template.blob, template.filename);
      setNotice(`${format.toUpperCase()} 示例模板已下载，可填写后直接导入`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "模板下载失败");
    } finally {
      setIsDownloadingTemplate(false);
    }
  };

  const submitTask = async () => {
    if (isImportingPrompts || isGroupLoading) return;
    setQuote(null);
    setPriceBreakdown("");
    if (!selectedModel || !resolution || !aspectRatio) return;
    if (isVideoTool && !duration) return;
    if (usesGroupPrompts && batchGroupIssues.length) {
      setError(batchGroupIssues[0]);
      return;
    }
    if (config.needsUpload && !usesGroupPrompts && !uploadedAssets.length) {
      setError("请先上传图片素材");
      return;
    }
    const submissionPrompt = usesGroupPrompts ? "" : usesPerImagePrompts
      ? batchEditPromptValues.join("\n")
      : config.workType === "batch_generate" && batchGenerateMode === "multi_output"
        ? Array.from({ length: batchGenerateOutputCount }, () => prompt.trim()).join("\n")
      : prompt.trim();
    if (!hasPromptContent) {
      setError(usesPerImagePrompts ? "请为每张图片填写修改指令" : "请输入任务提示词或处理说明");
      return;
    }
    if (hasBatchGeneratePromptOverflow) {
      setError(`单次批量任务最多 ${batchGenerateMaxTasks} 条，请删除 ${batchGeneratePromptOverflow} 条提示词后再提交`);
      return;
    }
    if (hasBatchEditTaskOverflow) {
      setError(`单次批量改图最多 ${batchEditTaskLimit} 个任务，当前共 ${batchEditTaskCount} 个，请减少图片或场景提示词后再提交`);
      return;
    }
    if (config.workType === "batch_edit" && batchEditPromptMode === "per_image" && batchEditPromptMissingCount > 0) {
      setError(`还有 ${batchEditPromptMissingCount} 张图片未填写修改指令`);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      const groups = usesGroupPrompts ? [] as NonNullable<import("@/types/api").CreateImageTaskRequest["groups"]> : undefined;
      let batchId: string | undefined;
      if (groups) {
        const signature = JSON.stringify({ model: selectedModel.id, resolution, aspectRatio, quality, groups: batchGroups.map((group) => ({ id: group.id, name: group.name.trim(), prompt: groupPrompt(group, mappedGroupRows).trim(), outputs: group.outputs, images: group.images.map((image) => image.path) })) });
        if (groupSubmissionKey.current.signature !== signature) groupSubmissionKey.current = { signature, batchId: `batch-${crypto.randomUUID()}` };
        batchId = groupSubmissionKey.current.batchId;
        // Each group retains its reference order; model-bound uploads apply
        // the selected model’s storage policy before task creation.
        setGroupSubmissionProgress("正在准备参考图…");
        const assetsByGroup = await uploadGroupReferences(batchGroups, selectedModel.id, (file, modelId) => uploadService.uploadImageForModel(file, modelId), groupAssetCache.current, (completed, total) => setGroupSubmissionProgress(`正在上传参考图 ${completed}/${total}`));
        setGroupSubmissionProgress(`正在创建 ${batchEditTaskCount} 个任务，请等待提交完成…`);
        for (const group of batchGroups) {
          const assets = assetsByGroup.get(group.id)!;
          groups.push({ group_id: group.id, group_name: group.name.trim(), group_path: group.path, prompt: groupPrompt(group, mappedGroupRows).trim(), input_image_ids: assets.map((asset) => asset.id), output_count: group.outputs });
        }
      }
      const payload = {
        work_type: config.workType,
        prompts: importedBatch?.prompts,
        folder_names: importedBatch?.folderNames,
        batch_id: batchId,
        model_id: selectedModel.id,
        prompt: submissionPrompt,
        prompt_mode: config.workType === "batch_edit" ? batchEditPromptMode : undefined,
        resolution,
        aspect_ratio: aspectRatio,
        quality: isVideoTool ? undefined : quality,
        duration: isVideoTool ? duration : undefined,
        input_image_ids: usesGroupPrompts ? [] : uploadedAssets.map((asset) => asset.id),
        groups,
        output_count: 1,
        n: config.workType === "text_to_image" ? outputCount : undefined,
      };
      if (isBatchTool && !usesGroupPrompts) {
        // Keep the same key after a lost response; clear it only on success.
        const signature = JSON.stringify(payload);
        if (groupSubmissionKey.current.signature !== signature) {
          groupSubmissionKey.current = { signature, batchId: `batch-${crypto.randomUUID()}` };
        }
        payload.batch_id = groupSubmissionKey.current.batchId;
      }
      const singleOutputPayload = { ...payload, output_count: 1, n: 1 };
      let batchSubmission: ImageBatchSubmission | undefined;
      const createdTasks = isBatchTool
        ? (batchSubmission = await imageTaskService.createBatch(payload, uploadedAssets, { ...batchUploadLimits, maxTasks: maxBatchTasks })).tasks
        : config.workType === "text_to_image" && outputCount > 1
          ? await Promise.all(
            Array.from({ length: outputCount }, () => imageTaskService.createTask(singleOutputPayload, uploadedAssets)),
          )
        : await Promise.all(
          Array.from({ length: config.workType === "text_to_image" ? outputCount : 1 }, () => imageTaskService.createTask(singleOutputPayload, uploadedAssets)),
        );
      setTasks((current) => [...createdTasks, ...current]);
      setMobilePanel("results");
      if (batchSubmission) {
        setLatestBatchId(batchSubmission.batch_id);
        groupSubmissionKey.current = { signature: "", batchId: "" };
      }
      if (usesGroupPrompts) { setBatchGroups([]); setGroupPromptRows([]); groupAssetCache.current = new WeakMap(); groupSubmissionKey.current = { signature: "", batchId: "" }; }
      setPrompt("");
      setImportedBatch(null);
      setUploadedAssets([]);
      setPreviewErrorAssetIds([]);
      notifyCreditBalanceChanged();
      setNotice(batchSubmission?.submission_status === "queued" || batchSubmission?.submission_status === "processing"
        ? `已接收 ${batchSubmission.task_count} 条提示词，正在后台创建任务，可在生成结果中查看进度`
        : batchSubmission?.submission_error ?? (batchSubmission ? `已提交 ${batchSubmission.task_count} 个任务，可在生成结果中查看整批进度、失败原因并打包下载` : outputCount > 1 ? `已提交 ${outputCount} 张图，完成后会出现在任务记录和我的作品中` : "任务已提交，完成后会出现在任务记录和我的作品中"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务提交失败");
    } finally {
      setIsSubmitting(false);
      setGroupSubmissionProgress("");
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
    } catch (err) {
      setTasks((current) => current.map((item) => (item.id === task.id ? { ...item, is_collected: task.is_collected } : item)));
      setError(err instanceof Error ? err.message : "收藏状态更新失败");
    } finally {
      setCollectingTaskIds((ids) => ids.filter((id) => id !== task.id));
    }
  };

  const deleteTask = async (taskId: number) => {
    try {
      await imageTaskService.deleteTask(taskId);
      setTasks((current) => current.filter((task) => task.id !== taskId));
      setBatchRevision((value) => value + 1);
      setConfirmDeleteTaskId(null);
      setNotice("任务记录已删除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务删除失败");
    }
  };

  const downloadTaskOutput = async (task: ImageTask) => {
    const output = task.output_images[0];
    if (!output) return;
    try {
      await downloadMedia(output.url, `image2ai-${task.task_no}`, output.mime_type);
    } catch (err) {
      setError(err instanceof Error ? err.message : "下载失败，请稍后重试");
    }
  };

  const continueEditingTask = (task: ImageTask) => {
    const output = task.output_images[0];
    if (!output || isVideoAsset(output)) return;
    navigate("/create/edit", { state: createImageEditNavigationState(output, task.input_images, task.prompt) });
  };

  const regenerateTextToImageTask = async (task: ImageTask) => {
    if (regeneratingTaskIds.includes(task.id) || task.work_type !== "text_to_image") return;
    setRegeneratingTaskIds((taskIds) => [...taskIds, task.id]);
    setError(null);
    try {
      const createdTask = await imageTaskService.createTask(
        {
          work_type: "text_to_image",
          model_id: task.model_id,
          prompt: task.prompt,
          resolution: task.resolution,
          aspect_ratio: task.aspect_ratio,
          input_image_ids: [],
          output_count: 1,
        },
        [],
      );
      setTasks((current) => [createdTask, ...current]);
      notifyCreditBalanceChanged();
      setNotice("已按原参数重新提交文生图任务");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成失败");
    } finally {
      setRegeneratingTaskIds((taskIds) => taskIds.filter((taskId) => taskId !== task.id));
    }
  };

  const exportTaskOutputs = async () => {
    const taskIds = tasks.filter((task) => task.output_images[0]).map((task) => task.id);
    try {
      const downloadUrl = await imageTaskService.createExportDownloadUrl(taskIds);
      startBrowserDownload(downloadUrl);
      setNotice(`已导出 ${taskIds.length} 个结果`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量导出失败，请稍后重试");
    }
  };

  const Icon = config.icon;
  const canSubmit = Boolean(
    selectedModel
    && hasPromptContent
    && (!isVideoTool || Boolean(duration))
    && (!config.needsUpload || (usesGroupPrompts ? batchGroups.length : uploadedAssets.length))
    && !isGroupLoading
    && !hasBatchGeneratePromptOverflow
    && !hasBatchEditTaskOverflow
    && !hasBatchEditPromptMismatch,
  );
  const showResolutionSelector = (selectedModel?.supported_resolutions.length ?? 0) > 1;
  const ratioLabel = "比例";
  const durationLabel = "时长";
  const promptLabel = config.workType === "batch_generate"
    ? "批量提示词"
    : config.workType === "batch_edit"
      ? "批量改图描述"
      : isVideoTool
        ? "视频描述"
        : "提示词 / 处理说明";
  const promptHelp =
    config.workType === "batch_generate"
      ? batchGenerateMode === "multi_output"
          ? `填写一条提示词，生成 ${batchGenerateOutputCount} 张图；适合同一描述快速出多张变体。`
        : "可直接复制多条提示词粘贴进来，一行一个提示词；每行会创建一张图并按张数累计价格。"
      : config.workType === "batch_edit"
        ? usesGroupPrompts
          ? "每个文件夹是一组参考图，提示词按文件夹名匹配；提交前可检查对应关系和生成张数。"
          : usesMatrixPrompts
          ? "商品套图会把每张商品图与每条场景提示词组合；可导入主图、场景图、细节图提示词，按实际任务数计费。"
          : "先添加图片，再选择统一提示词、一图一词或商品套图；导入文件会切换为商品套图。"
        : "";
  const promptPlaceholder =
    config.workType === "batch_generate"
      ? batchGenerateMode === "multi_output"
        ? "填写一条提示词，一次生成多张构图或风格变体\n例如：白底电商主图，一瓶透明护肤精华，柔和阴影"
        : "一行一个提示词，可从表格或文档直接复制粘贴\n复古木质餐桌上的陶瓷杯，暖色自然光\n白底电商主图，一瓶透明护肤精华，柔和阴影\n户外露营场景中的便携咖啡壶，真实产品摄影"
      : config.workType === "batch_edit"
        ? usesMatrixPrompts
          ? "一行一个场景，每张商品图都会套用全部场景\n白底电商主图，保留商品材质和轮廓\n生活方式场景，商品置于客厅边几，柔和自然光\n细节特写，突出纹理和功能"
          : batchEditPromptMode === "per_image"
          ? "一行对应一张上传图片，可从表格或文档直接复制粘贴\n第 1 张改成白底电商主图，保留商品材质\n第 2 张换成浅灰摄影棚背景，增加柔和阴影"
          : "把所有图片统一改成干净的白底电商主图，保留商品形状和材质，统一柔和阴影"
        : config.workType === "text_to_video"
          ? "描述镜头、主体动作、光影和氛围，例如：暖色傍晚的海浪轻拍沙滩，镜头缓慢推进，电影感"
          : config.workType === "image_to_video"
            ? "描述参考图如何动起来：镜头推进、人物微表情、产品旋转、背景光影变化等"
            : "请输入要生成或修改的内容，提交时会原样发送给后端任务接口";
  const hasBatchOverflow = hasBatchGeneratePromptOverflow || hasBatchEditTaskOverflow;
  const quoteLabel = hasBatchOverflow
    ? `超出单次 ${config.workType === "batch_edit" ? batchEditTaskLimit : batchGenerateMaxTasks} 个任务限制`
    : quote === null
    ? "等待报价"
    : isBatchTool || config.workType === "text_to_image"
      ? `预计 ${estimatedCreditCost} 积分`
      : `预计 ${quote} 积分`;
  const quoteDetail = !hasBatchOverflow && quote !== null && (isBatchTool || config.workType === "text_to_image")
    ? config.workType === "text_to_image"
      ? `${outputCount} 张图片 x ${quote} 积分/张`
      : config.workType === "batch_generate"
      ? batchGenerateTaskCount
        ? batchGenerateMode === "multi_output"
          ? `1 条提示词 x ${batchGenerateOutputCount} 张 x ${quote} 积分/张`
          : `${batchGeneratePrompts.length} 条提示词 x ${quote} 积分/张`
        : `输入提示词后按 ${quote} 积分/张累计`
      : batchEditTaskCount
        ? usesGroupPrompts
          ? `${batchGroups.length} 个任务组，共 ${batchEditTaskCount} 张结果 × ${quote} 积分/张`
          : usesMatrixPrompts
          ? `${uploadedAssets.length} 张图片 × ${batchGeneratePrompts.length} 个场景 × ${quote} 积分/张`
          : `${batchEditTaskCount} 张图片 x ${quote} 积分/张`
        : `上传图片后按 ${quote} 积分/张累计`
    : "";
  const promptStepNumber = config.needsUpload ? 3 : 2;

  return (
    <main className="page-surface creation-tool-page" data-mobile-panel={mobilePanel}>
      <header className="page-header creation-tool-page__header">
        <div>
          <h1>{config.title}</h1>
          <p>{config.intro}</p>
        </div>
        <div className="tool-cost">
          <Icon size={18} />
          <span>{quoteLabel}</span>
          {quoteDetail ? <small>{quoteDetail}</small> : null}
          {priceBreakdown && quote !== null ? <small>{priceBreakdown}</small> : null}
        </div>
      </header>

      {error ? <div className="list-state list-state--error">{error}</div> : null}
      {notice ? (
        <div className="inline-notice">
          <CheckCircle2 size={17} />
          <span>{notice}</span>
        </div>
      ) : null}

      <CreationMobileTabs panel={mobilePanel} onChange={setMobilePanel} resultCount={tasks.length} />
      <section className="compose-layout creation-tool-page__layout">
        <fieldset disabled={isSubmitting || isGroupLoading} className="compose-panel creation-tool-page__compose creation-tool-page__form">
          <div className="creation-tool-page__section-head">
            <span>1</span>
            <div>
              <strong>生成设置</strong>
              <small>选择模型、画幅和输出规格</small>
            </div>
          </div>
          <div className={showResolutionSelector ? "config-row compose-config-row" : "config-row compose-config-row config-row--without-resolution"}>
            <div className="config-field config-field--model model-select">
              <span>模型</span>
              <ModelPicker
                models={models}
                selectedModelId={selectedModelId}
                onChange={selectGenerationModel}
                isLoading={isLoadingModels}
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
            {!isVideoTool ? (
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
            ) : null}
            <div
              className="config-field config-field--aspect"
            >
              <span>{ratioLabel}</span>
              <div className="aspect-choice-grid aspect-ratio-grid" role="radiogroup" aria-label="选择比例">
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
                      {option.value === "auto" ? <Sparkles size={24} aria-hidden="true" /> : <i style={getAspectRatioStyle(option.value)} />}
                    </span>
                    <strong>{option.label}</strong>
                  </button>
                ))}
              </div>
              {selectedModel?.supported_aspect_ratios.some((option) => option.value === "auto") ? (
                <small>按提示词决定尺寸时，请将分辨率和比例都选为“自动（Auto）”。质量“自动”不控制尺寸；Auto 不保证精确像素或印刷 DPI。</small>
              ) : null}
            </div>
            {isVideoTool ? (
              <div className="config-field config-field--aspect">
                <span>{durationLabel}</span>
                <div className="aspect-choice-grid" role="radiogroup" aria-label="选择时长">
                  {(selectedModel?.supported_durations ?? []).map((option) => (
                    <button
                      className={option.value === duration ? "aspect-choice is-active" : "aspect-choice"}
                      key={option.value}
                      type="button"
                      role="radio"
                      aria-checked={option.value === duration}
                      onClick={() => setDuration(option.value)}
                    >
                      <strong>{option.label}</strong>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
          </div>

          {promptHelp ? <div className="batch-help"><Layers3 size={17} />{promptHelp}</div> : null}

          {isBatchTool && !usesGroupPrompts ? (
              <div className="batch-import-row">
                <div>
                  <strong>{config.workType === "batch_edit" ? "导入套图提示词" : "批量导入提示词"}</strong>
                  <small>{config.workType === "batch_edit" ? `一行一个场景，每张商品图套用全部场景；最多 ${batchEditMaxTasks} 个任务` : "支持 TXT / CSV / XLSX / XLS；单列【文件夹名称】下填写提示词，空行跳过。重新导入会替换当前文件"}</small>
                </div>
                <div className="batch-import-actions">
                  <div className="batch-template-menu" ref={templateMenuRef}>
                    <Button
                      className="batch-template-trigger"
                      variant="ghost"
                      type="button"
                      aria-haspopup="menu"
                      aria-expanded={isTemplateMenuOpen}
                      disabled={isDownloadingTemplate || isImportingPrompts || isSubmitting}
                      onClick={() => setIsTemplateMenuOpen((current) => !current)}
                    >
                      <Download size={15} />
                      下载示例模板
                      <ChevronDown className={isTemplateMenuOpen ? "is-open" : ""} size={15} />
                    </Button>
                    {isTemplateMenuOpen ? (
                      <div className="batch-template-popover" role="menu" aria-label="选择模板格式">
                        <div className="batch-template-popover__heading">
                          <strong>选择模板格式</strong>
                          <span>下载后可直接填写并导入</span>
                        </div>
                        <button className="batch-template-choice batch-template-choice--txt" type="button" role="menuitem" onClick={() => void downloadBatchPromptTemplate("txt")}>
                          <strong>TXT</strong>
                          <span>纯文本，一行一条提示词</span>
                          <Download size={14} />
                        </button>
                        <button className="batch-template-choice batch-template-choice--csv" type="button" role="menuitem" onClick={() => void downloadBatchPromptTemplate("csv")}>
                          <strong>CSV</strong>
                          <span>表格文件，适合批量编辑</span>
                          <Download size={14} />
                        </button>
                        <button className="batch-template-choice batch-template-choice--xlsx" type="button" role="menuitem" onClick={() => void downloadBatchPromptTemplate("xlsx")}>
                          <strong>XLSX</strong>
                          <span>Excel 模板，带示例表头</span>
                          <Download size={14} />
                        </button>
                      </div>
                    ) : null}
                  </div>
                  <Button variant="secondary" type="button" isLoading={isImportingPrompts} disabled={isImportingPrompts || isSubmitting} onClick={() => promptFileInputRef.current?.click()}>
                    <FolderPlus size={15} />
                    导入文件
                  </Button>
                </div>
                <input
                  ref={promptFileInputRef}
                  type="file"
                  accept=".txt,.csv,.xlsx,.xls,text/plain,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                  hidden
                  disabled={isImportingPrompts || isSubmitting}
                  onChange={importBatchPrompts}
                />
              </div>
          ) : null}

          {config.workType === "batch_generate" ? (
            <>
              <div className="segmented-row segmented-row--compact prompt-mode-toggle" role="radiogroup" aria-label="批量生图模式">
                <button
                  className={batchGenerateMode === "one_per_prompt" ? "is-active" : ""}
                  type="button"
                  role="radio"
                  aria-checked={batchGenerateMode === "one_per_prompt"}
                  onClick={() => setBatchGenerateMode("one_per_prompt")}
                >
                  一图一次
                </button>
                <button
                  className={batchGenerateMode === "multi_output" ? "is-active" : ""}
                  type="button"
                  role="radio"
                  aria-checked={batchGenerateMode === "multi_output"}
                  disabled={!!importedBatch}
                  onClick={() => {
                    setBatchGenerateMode("multi_output");
                    setPrompt((value) => value.split(/\r?\n/).map((line) => line.trim()).find(Boolean) ?? "");
                  }}
                >
                  一词多图
                </button>
              </div>
              {batchGenerateMode === "multi_output" ? (
                <div className="batch-generate-output-count" aria-label="一词多图生成张数">
                  <label htmlFor="batch-generate-output-count">生成张数</label>
                  <input
                    id="batch-generate-output-count"
                    type="number"
                    min={1}
                    max={MAX_BATCH_GENERATE_COUNT}
                    value={batchGenerateOutputCount}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      setBatchGenerateOutputCount(Number.isFinite(next) ? Math.min(Math.max(1, Math.floor(next)), MAX_BATCH_GENERATE_COUNT) : 1);
                    }}
                  />
                  <small>同一条提示词生成多张，最多 {MAX_BATCH_GENERATE_COUNT} 张，按实际张数扣除积分。</small>
                </div>
              ) : null}
            </>
          ) : null}

          {config.workType === "batch_edit" ? (
            <div className="segmented-row segmented-row--compact prompt-mode-toggle" role="radiogroup" aria-label="批量改图提示词模式">
              <button className={usesGroupPrompts ? "is-active" : ""} type="button" role="radio" aria-checked={usesGroupPrompts} disabled={isSubmitting || isGroupLoading} onClick={() => switchBatchEditPromptMode("grouped")}>文件夹任务组</button>
              <button
                className={batchEditPromptMode === "shared" ? "is-active" : ""}
                type="button"
                role="radio"
                aria-checked={batchEditPromptMode === "shared"}
                onClick={() => switchBatchEditPromptMode("shared")}
              >
                统一提示词
              </button>
              <button
                className={batchEditPromptMode === "per_image" ? "is-active" : ""}
                type="button"
                role="radio"
                aria-checked={batchEditPromptMode === "per_image"}
                onClick={() => switchBatchEditPromptMode("per_image")}
              >
                一图一词
              </button>
              <button
                className={batchEditPromptMode === "matrix" ? "is-active" : ""}
                type="button"
                role="radio"
                aria-checked={batchEditPromptMode === "matrix"}
                onClick={() => switchBatchEditPromptMode("matrix")}
              >
                商品套图
              </button>
            </div>
          ) : null}

          {!isLoadingModels && !models.length ? (
            <div className="empty-state">
              <Image size={34} />
              <h3>暂无可用模型</h3>
              <p>请等待后台在该工具类型下发布模型和价格配置。</p>
            </div>
          ) : null}

          {usesGroupPrompts ? <BatchGroupEditor groups={batchGroups} rows={mappedGroupRows} maxInputs={maxInputImages} maxOutputs={batchEditTaskLimit} disabled={isSubmitting} issues={batchGroupIssues} onGroupsChange={setBatchGroups} onRowsChange={setGroupPromptRows} onBusyChange={setIsGroupLoading} onError={setError} /> : null}
          {config.needsUpload && !usesGroupPrompts ? (
            <div className="creation-tool-page__section">
              <div className="creation-tool-page__section-head">
                <span>2</span>
                <div>
                  <strong>添加参考素材</strong>
                  <small>{config.workType === "batch_edit" ? "上传散图，或导入 ZIP 按文件夹分组" : "上传图片或从素材库选择"}</small>
                </div>
              </div>
            <div className="upload-source-panel">
              <label className="file-drop">
                {isUploading || isGroupLoading ? <LoadingIndicator className="spin-icon" size={28} /> : <UploadCloud size={28} />}
                <strong>{isGroupLoading ? "正在读取 ZIP，请稍候…" : uploadedAssets.length ? `已选择 ${uploadedAssets.length} 个素材` : config.workType === "batch_edit" ? "上传图片或 ZIP" : "上传图片素材"}</strong>
                <span>
                  {isVideoTool
                    ? `最多 ${maxInputImages || 1} 张；第 1 张为主图，其余为参考图`
                    : config.workType === "batch_edit"
                      ? usesMatrixPrompts
                        ? `每张商品图套用全部场景；图片数 × 场景数最多 ${batchEditMaxTasks} 个任务`
                        : `最多 ${batchEditMaxTasks} 张；每张图片会创建一条批量改图任务`
                    : "可以上传新图片，也可以从素材库直接选择"}
                </span>
                <input multiple={config.workType === "batch_edit" || maxInputImages !== 1} ref={fileInputRef} type="file" accept={config.workType === "batch_edit" ? "image/*,.zip,application/zip,application/x-zip-compressed" : "image/*"} aria-label={config.workType === "batch_edit" ? "上传批量改图图片或 ZIP" : "上传图片素材"} disabled={isUploading || isGroupLoading} onChange={uploadFiles} />
              </label>
              {config.workType === "batch_edit" ? (
                <>
                  <Button variant="secondary" type="button" disabled={isUploading || isGroupLoading} onClick={() => batchZipInputRef.current?.click()}>
                    <FolderPlus size={16} />
                    导入 ZIP 按文件夹分组
                  </Button>
                  <input ref={batchZipInputRef} type="file" accept=".zip,application/zip,application/x-zip-compressed" hidden aria-label="从默认入口导入 ZIP" disabled={isUploading || isGroupLoading} onChange={uploadFiles} />
                </>
              ) : null}
              <Button variant="secondary" type="button" onClick={() => setIsMaterialPickerOpen(true)}>
                <Image size={16} />
                从素材库选择
              </Button>
            </div>
            </div>
          ) : null}

          {uploadedAssets.length && !usesGroupPrompts ? (
            <div className={config.workType === "batch_edit" ? "asset-grid batch-edit-asset-grid" : "asset-grid"}>
              {uploadedAssets.map((asset, index) => (
                <div className={config.workType === "batch_edit" ? "batch-edit-asset-item" : undefined} key={asset.id}>
                  <figure className="asset-preview-card">
                    {previewErrorAssetIds.includes(asset.id) ? (
                      <div className="asset-preview-card__fallback">图片无法预览</div>
                    ) : (
                      <img
                        src={resolveAssetUrl(asset.url)}
                        alt={`已上传素材 ${asset.id}`}
                        onError={() => setPreviewErrorAssetIds((ids) => (ids.includes(asset.id) ? ids : [...ids, asset.id]))}
                      />
                    )}
                    <span className="asset-preview-card__index">
                      {isVideoTool ? (index === 0 ? "主图" : `参考 ${index}`) : `图片 ${index + 1}`}
                    </span>
                    {config.workType === "batch_edit" ? (
                      <div className="batch-edit-asset-order" aria-label={`调整图片 ${index + 1} 顺序`}>
                        <button type="button" aria-label="上移图片" disabled={index === 0} onClick={() => moveUploadedAsset(asset.id, -1)}><ChevronUp size={14} /></button>
                        <button type="button" aria-label="下移图片" disabled={index === uploadedAssets.length - 1} onClick={() => moveUploadedAsset(asset.id, 1)}><ChevronDown size={14} /></button>
                      </div>
                    ) : null}
                    <button className="asset-preview-card__remove" type="button" aria-label="移除" onClick={() => removeUpload(asset.id)}>
                      <X size={14} />
                    </button>
                    <figcaption>
                      <strong>
                        {config.workType === "batch_edit"
                          ? `图片 ${index + 1}`
                          : isVideoTool
                            ? (index === 0 ? "主图（image）" : `参考图 ${index}`)
                            : `Asset #${asset.id}`}
                      </strong>
                      <span>{asset.width && asset.height ? `${asset.width} x ${asset.height}` : asset.mime_type}</span>
                    </figcaption>
                  </figure>
                  {config.workType === "batch_edit" && batchEditPromptMode === "per_image" ? (
                    <label className="batch-edit-asset-prompt">
                      <span>图片 {index + 1} 的修改指令</span>
                      <textarea
                        value={batchEditPromptsByAssetId[asset.id] ?? ""}
                        onChange={(event) => updateBatchEditPrompt(asset.id, event.target.value.replace(/[\r\n]+/g, " "))}
                        placeholder="例如：换成白底电商主图，保留商品材质"
                        rows={3}
                        aria-label={`图片 ${index + 1} 的修改指令`}
                      />
                    </label>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}

          {config.workType === "batch_edit" ? (
            <div className="batch-edit-summary" aria-live="polite">
              <span>已选择 <strong>{uploadedAssets.length}</strong> / {batchEditMaxTasks} 张图片</span>
              <span>{usesMatrixPrompts ? `${uploadedAssets.length} 张图片 × ${batchGeneratePrompts.length} 个场景 = ${batchEditTaskCount} 个任务` : usesPerImagePrompts ? `已填写 ${uploadedAssets.length - batchEditPromptMissingCount} 张` : "统一提示词将应用到全部图片"}</span>
              <span>{hasBatchEditTaskOverflow ? `超出 ${batchEditTaskOverflow} 个任务，请减少图片或场景` : quote === null ? "预计积分待计算" : `预计消耗 ${estimatedCreditCost ?? 0} 积分`}</span>
            </div>
          ) : null}

          {!usesGroupPrompts ? <div className="creation-tool-page__section">
            <div className="creation-tool-page__section-head">
              <span>{promptStepNumber}</span>
              <div>
                <strong>{isBatchTool ? "填写批量任务" : "描述创作内容"}</strong>
                <small>
                  {isBatchTool
                    ? config.workType === "batch_edit" && usesPerImagePrompts
                      ? "每张图片绑定一条修改指令，提交前会校验完整性"
                      : "提交前会校验图片数量和费用"
                    : "描述画面主体、风格和细节，提交后开始生成"}
                </small>
              </div>
            </div>
          <div className="field-block">
            <span>{promptLabel}</span>
            {config.workType === "text_to_image" ? (
              <div className="batch-generate-output-count" aria-label="一次生成张数">
                <label htmlFor="text-to-image-output-count">生成张数 n</label>
                <input
                  id="text-to-image-output-count"
                  type="number"
                  min={1}
                  max={MAX_STANDARD_OUTPUT_COUNT}
                  value={outputCount}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    setOutputCount(Number.isFinite(next) ? Math.min(Math.max(1, Math.floor(next)), MAX_STANDARD_OUTPUT_COUNT) : 1);
                  }}
                />
                <small>范围 1–{MAX_STANDARD_OUTPUT_COUNT} 张，默认 1 张。</small>
              </div>
            ) : null}
            {usesPerImagePrompts ? (
              <div className="batch-edit-prompt-summary" aria-live="polite">
                <strong>已填写 {uploadedAssets.length - batchEditPromptMissingCount} / {uploadedAssets.length} 张</strong>
                <span>每张图片的修改指令已绑定在上方卡片中，提交时按图片顺序创建任务。</span>
              </div>
            ) : (
              <>
                {importedBatch ? (
                  <div className="batch-edit-prompt-summary" aria-live="polite">
                    <strong>已导入 {importedBatch.prompts.length} 条提示词 · {new Set(importedBatch.folderNames ?? ["生成结果"]).size} 个文件夹</strong>
                    <span>每个【系列名称】单独建文件夹，下方提示词归入该系列，空行自动跳过。提示词原文已保留。</span>
                    <span>首条预览：{importedBatch.prompts[0].slice(0, 240)}{importedBatch.prompts[0].length > 240 ? "…" : ""}</span>
                    <Button variant="secondary" type="button" onClick={() => { setImportedBatch(null); setPrompt(""); }}>清除导入，重新填写</Button>
                  </div>
                ) : <PromptMentionEditor
                  value={prompt}
                  onChange={(value) => setPrompt(
                    config.workType === "batch_generate" && batchGenerateMode === "multi_output"
                      ? value.replace(/[\r\n]+/g, " ")
                      : value,
                  )}
                  placeholder={promptPlaceholder}
                  uploadedAssets={uploadedAssets}
                  enableMentions={config.needsUpload}
                />}

              </>
            )}
            {config.workType === "batch_generate" ? (
              <small className={hasBatchGeneratePromptOverflow ? "field-hint field-hint--error" : "field-hint"} aria-live="polite">
                {hasBatchGeneratePromptOverflow
                  ? `预计生成 ${batchGenerateTaskCount} 张图，超出 ${batchGeneratePromptOverflow} 张；单次最多 ${batchGenerateMaxTasks} 张，请调整后再提交。`
                  : batchGenerateMode === "multi_output"
                    ? `当前为一词多图：1 条提示词 × ${batchGenerateOutputCount} 张，单次最多 ${batchGenerateMaxTasks} 张。`
                    : `已识别 ${batchGeneratePrompts.length} 条提示词，提交后生成 ${batchGenerateTaskCount} 张图；单次最多 ${batchGenerateMaxTasks} 张。`}
              </small>
            ) : null}
            {config.workType === "batch_edit" ? (
              <small className={hasBatchEditPromptMismatch || hasBatchEditTaskOverflow ? "field-hint field-hint--error" : "field-hint"} aria-live="polite">
                {usesMatrixPrompts
                  ? `已选择 ${uploadedAssets.length} 张商品图 × ${batchGeneratePrompts.length} 条场景提示词，共 ${batchEditTaskCount} 个套图任务；最多 ${batchEditMaxTasks} 个。`
                  : batchEditPromptMode === "per_image"
                  ? `已填写 ${uploadedAssets.length - batchEditPromptMissingCount} / ${uploadedAssets.length} 张图片的修改指令；每张图片提交时会对应创建一条任务。`
                  : `已上传 ${uploadedAssets.length} 张图片，提交后会用同一段提示词生成 ${uploadedAssets.length} 张图。`}
              </small>
            ) : null}
          </div>
          </div> : null}

          {groupSubmissionProgress ? <p className="batch-groups__message" role="status">{groupSubmissionProgress}</p> : null}
          <div className="creation-submit-bar">
            <Button className="creation-tool-page__submit" type="button" isLoading={isSubmitting} disabled={!canSubmit || isSubmitting || isImportingPrompts} onClick={submitTask}>
              <Play size={16} />
              {config.submitLabel}
              {estimatedCreditCost !== null && !hasBatchOverflow ? <span>（消耗 {estimatedCreditCost} 积分）</span> : null}
            </Button>
          </div>
        </fieldset>

        <TaskResultPanel
          batchOverview={isBatchTool ? (
              <BatchTaskPanel key={config.workType} workType={config.workType} latestBatchId={latestBatchId}
                onBatchCreated={(result) =>
                  setTasks((current) => [
                    ...result.tasks,
                    ...current.filter((task) => !result.task_ids.includes(task.id)),
                  ])
                }
                tasks={tasks}
                revision={batchRevision}
                onTasksLoaded={(records) =>
                  setTasks((current) => {
                    const updates = new Map(records.map((task) => [task.id, task]));
                    return [
                      ...current.map((task) =>
                        updates.get(task.id) ? { ...task, ...updates.get(task.id)! } : task,
                      ),
                      ...records.filter((task) => !current.some((item) => item.id === task.id)),
                    ];
                  })
                }
                renderTasks={(records) => (
                  <TaskResultCards
                    tasks={records}
                    collectingTaskIds={collectingTaskIds}
                    regeneratingTaskIds={regeneratingTaskIds}
                    now={now}
                    showTextToImageActions={false}
                    onContinueEdit={continueEditingTask}
                    onDelete={setConfirmDeleteTaskId}
                    onDownload={(task) => void downloadTaskOutput(task)}
                    onPreview={setPreviewAsset}
                    onRegenerate={(task) => void regenerateTextToImageTask(task)}
                    onToggleCollection={(task) => void toggleTaskCollection(task)}
                  />
                )}
              />
            ) : undefined}
          tasks={tasks}
          hasMoreHistory={hasMoreHistory}
          isLoadingHistory={isLoadingHistory}
          historyError={historyError}
          onLoadMoreHistory={() => void loadMoreHistory()}
          collectingTaskIds={collectingTaskIds}
          regeneratingTaskIds={regeneratingTaskIds}
          now={now}
          showTextToImageActions={config.workType === "text_to_image"}
          onDelete={setConfirmDeleteTaskId}
          onExport={() => void exportTaskOutputs()}
          onContinueEdit={continueEditingTask}
          onDownload={(task) => void downloadTaskOutput(task)}
          onPreview={setPreviewAsset}
          onRegenerate={(task) => void regenerateTextToImageTask(task)}
          onToggleCollection={(task) => void toggleTaskCollection(task)}
        />
      </section>

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
              <Button variant="danger" type="button" onClick={() => void deleteTask(confirmDeleteTaskId)}>
                删除记录
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {previewAsset ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setPreviewAsset(null)}>
          <div className="image-preview-dialog" role="dialog" aria-modal="true" aria-label={isVideoAsset(previewAsset) ? "视频预览" : "图片预览"}>
            <button type="button" aria-label="关闭预览" onClick={() => setPreviewAsset(null)}>
              <X size={20} />
            </button>
            {isVideoAsset(previewAsset) ? (
              <video
                src={resolveAssetUrl(previewAsset.url)}
                controls
                autoPlay
                playsInline
                onClick={(event) => event.stopPropagation()}
              />
            ) : (
              <img src={resolveAssetUrl(previewAsset.url)} alt="任务结果预览" onClick={(event) => event.stopPropagation()} />
            )}
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
  enableMentions,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  uploadedAssets: ImageAsset[];
  enableMentions: boolean;
}) => {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
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
  const showMentionMenu = enableMentions && Boolean(mentionState);

  useEffect(() => {
    if (!mentionOptions.length) {
      setActiveMentionIndex(0);
      return;
    }
    setActiveMentionIndex((index) => Math.min(index, mentionOptions.length - 1));
  }, [mentionOptions.length]);

  const syncMentionState = (nextValue: string, cursorPosition: number | null) => {
    if (!enableMentions || cursorPosition === null) {
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

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
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

  // Always use a normal selectable textarea. The old transparent+highlight
  // overlay made the last character of the last line hard to select/copy.
  if (!enableMentions) {
    return (
      <textarea
        className="prompt-mention-editor--plain"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        spellCheck={false}
      />
    );
  }

  return (
    <div className={showMentionMenu ? "prompt-mention-editor is-menu-open" : "prompt-mention-editor"}>
      <textarea
        ref={textareaRef}
        className="prompt-mention-editor__input"
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
            <div className="prompt-mention-menu__empty">{uploadedAssets.length ? "没有匹配的图片" : "请先上传图片"}</div>
          )}
        </div>
      ) : null}
    </div>
  );
};

const TaskResultPanel = ({
  batchOverview,
  tasks,
  hasMoreHistory,
  isLoadingHistory,
  historyError,
  onLoadMoreHistory,
  collectingTaskIds,
  regeneratingTaskIds,
  now,
  showTextToImageActions,
  onContinueEdit,
  onDelete,
  onExport,
  onDownload,
  onPreview,
  onRegenerate,
  onToggleCollection,
}: {
  batchOverview?: ReactNode;
  tasks: ImageTask[];
  hasMoreHistory: boolean;
  isLoadingHistory: boolean;
  historyError: string | null;
  onLoadMoreHistory: () => void;
  collectingTaskIds: number[];
  regeneratingTaskIds: number[];
  now: number;
  showTextToImageActions: boolean;
  onContinueEdit: (task: ImageTask) => void;
  onDelete: (taskId: number) => void;
  onExport: () => void;
  onDownload: (task: ImageTask) => void;
  onPreview: (asset: ImageAsset) => void;
  onRegenerate: (task: ImageTask) => void;
  onToggleCollection: (task: ImageTask) => void;
}) => {
  const exportableTaskCount = tasks.filter((task) => task.output_images[0]).length;
  const [visibleTaskCount, setVisibleTaskCount] = useState(TASK_HISTORY_PAGE_SIZE);

  if (batchOverview)
    return (
      <aside className="result-preview-panel">
        <header>
          <div>
            <h2>我的批次</h2>
            <p>展开批次查看具体记录，在批次上下载和重试。</p>
          </div>
        </header>
        {batchOverview}
      </aside>
    );

  return (
  <aside className="result-preview-panel">
    <header>
      <div>
        <h2>我的创作</h2>
        <p>{batchOverview ? "查看整批进度与下载，下面可预览单张结果。" : "展示近期创作，可继续加载更早记录。"}</p>
      </div>
      {!batchOverview ? (
          <button className="task-button task-button--blue" type="button" disabled={!exportableTaskCount} onClick={onExport}>
        <Download size={17} />
        导出已加载{exportableTaskCount ? `（${exportableTaskCount}）` : ""}
      </button>
        ) : null}
    </header>
    {batchOverview}
    {tasks.length ? (
      <TaskResultCards
          tasks={tasks.slice(0, visibleTaskCount)}
          collectingTaskIds={collectingTaskIds}
          regeneratingTaskIds={regeneratingTaskIds}
          now={now}
          showTextToImageActions={showTextToImageActions}
          onContinueEdit={onContinueEdit}
          onDelete={onDelete}
          onDownload={onDownload}
          onPreview={onPreview}
          onRegenerate={onRegenerate}
          onToggleCollection={onToggleCollection}
        />
      ) : isLoadingHistory ? (
        <LoadingArt label="正在加载创作记录" hint="正在整理你的作品，请稍候" compact />
      ) : (
        <div className="empty-state">
          <FileImage size={34} />
          <h3>
            {historyError ? "创作记录加载失败" : "暂无当前类型的任务"}
          </h3>
          <p>
            {hasMoreHistory
              ? "可以继续加载更早的创作记录。"
              : "提交任务后，进度和结果会显示在这里。"}
          </p>
        </div>
      )}
      {tasks.length > visibleTaskCount ? (
        <Button
          type="button"
          variant="secondary"
          fullWidth
          onClick={() => setVisibleTaskCount((count) => count + TASK_HISTORY_PAGE_SIZE)}
        >
          显示更多已加载（{visibleTaskCount}/{tasks.length}）
        </Button>
      ) : null}
      {historyError ? <p role="alert">{historyError}</p> : null}
      {hasMoreHistory || historyError || isLoadingHistory ? (
        <Button
          type="button"
          variant="secondary"
          fullWidth
          isLoading={isLoadingHistory}
          onClick={onLoadMoreHistory}
        >
          {isLoadingHistory ? "正在加载…" : historyError ? "重试加载" : "加载更早记录"}
        </Button>
      ) : null}
    </aside>
  );
};

const TaskResultCards = ({
  tasks,
  collectingTaskIds,
  regeneratingTaskIds,
  now,
  showTextToImageActions,
  onContinueEdit,
  onDelete,
  onDownload,
  onPreview,
  onRegenerate,
  onToggleCollection,
}: {
  tasks: ImageTask[];
  collectingTaskIds: number[];
  regeneratingTaskIds: number[];
  now: number;
  showTextToImageActions: boolean;
  onContinueEdit: (task: ImageTask) => void;
  onDelete: (taskId: number) => void;
  onDownload: (task: ImageTask) => void;
  onPreview: (asset: ImageAsset) => void;
  onRegenerate: (task: ImageTask) => void;
  onToggleCollection: (task: ImageTask) => void;
}) => {
  const [expandedPromptIds, setExpandedPromptIds] = useState<number[]>([]);
  const [clock, setClock] = useState(now);
  const hasActiveTasks = tasks.some((task) =>
    ["pending", "queued", "running"].includes(task.status),
  );
  useEffect(() => {
    if (!hasActiveTasks) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [hasActiveTasks]);
  return (
    <div className="task-list-compact">
      {tasks.map((task) => {
          const output = task.output_images[0];
          const isProcessing = ["pending", "queued", "running"].includes(task.status);
          const isFailed = task.status === "failed" || task.status === "refunded";
          const showTaskEditActions = showTextToImageActions && task.work_type === "text_to_image";

          return (
            <article className="tool-result-card tool-result-card--focused" data-result-state={isFailed ? "failed" : isProcessing ? "processing" : "complete"} key={task.id}>
              <div className="tool-result-card__top">
                <div>
                  <strong>{isFailed ? "本次生成未成功" : isProcessing ? "正在生成作品" : "生成结果"}</strong>
                  <span>{task.model_name || "未命名模型"}</span>
                  <span>{task.task_no}</span>
                  <span>耗时 {formatElapsedTime(getTaskElapsedMs(task, Math.max(now, clock)))}</span>
                </div>
                <span className={`status-badge status-badge--${task.status}`}>
                  {isProcessing ? <LoadingIndicator className="spin-icon" size={14} /> : null}
                  {getImageTaskStatusLabel(task, taskStatusCopy)}
                </span>
              </div>

              <div className="tool-result-card__preview">
                {output ? (
                  <button type="button" onClick={() => onPreview(output)}>
                    {isVideoAsset(output) ? (
                      <video src={resolveAssetUrl(output.url)} muted playsInline preload="metadata" />
                    ) : (
                      <img
                        src={resolveAssetUrl(getAssetPreviewSource(output))}
                        alt="生成结果预览"
                        loading="lazy"
                        decoding="async"
                        onError={(event) => {
                          if (event.currentTarget.dataset.originalFallback === "true") return;
                          event.currentTarget.dataset.originalFallback = "true";
                          event.currentTarget.src = resolveAssetUrl(output.url);
                        }}
                      />
                    )}
                  </button>
                ) : isFailed ? (
                  <div className="tool-result-card__state">
                    <AlertTriangle size={26} />
                    <strong>生成失败</strong>
                    <span>{task.failure_message ?? "任务失败，未返回生成结果。"}</span>
                  </div>
                ) : (
                  <div className="tool-result-card__state">
                    <LoadingArt label={getImageTaskProcessingMessage(task)} hint="完成后，作品将在这里呈现" compact />
                  </div>
                )}
              </div>


              {task.input_group_name ? (
              <div className="tool-result-card__specs" aria-label="任务组"><strong title={task.input_group_path}>{task.input_group_name}</strong>{task.input_group_path && task.input_group_path !== task.input_group_name ? (
                  <span>{task.input_group_path}</span>
                ) : null}<span>{task.input_images.length} 张参考图</span></div>
            ) : null}
              <div className="tool-result-card__specs" aria-label="任务规格">
                <span>{task.resolution || "默认清晰度"}</span>
                <span>{task.aspect_ratio || "默认比例"}</span>
                {task.duration ? <span>{task.duration}s</span> : null}
              </div>

              {(() => {
                const promptText = task.prompt || "（无提示词）";
                const promptExpanded = expandedPromptIds.includes(task.id);
                const promptCollapsible = isPromptCollapsible(task.prompt);
                return (
                  <div className="tool-result-card__prompt">
                    <p className={promptExpanded ? "is-expanded" : undefined} title={promptExpanded || !promptCollapsible ? undefined : task.prompt || undefined}>
                      {promptText}
                    </p>
                    {promptCollapsible ? (
                      <button
                        type="button"
                        className="tool-result-card__prompt-toggle"
                        onClick={() =>
                          setExpandedPromptIds((current) =>
                            current.includes(task.id)
                              ? current.filter((id) => id !== task.id)
                              : [...current, task.id],
                          )
                        }
                      >
                        {promptExpanded ? "收起提示词" : "展开提示词"}
                      </button>
                    ) : null}
                  </div>
                );
              })()}


              <div className="task-actions">
                <button
                  className={task.is_collected ? "task-button task-button--green is-active" : "task-button task-button--green"}
                  type="button"
                  disabled={task.status !== "succeeded" || collectingTaskIds.includes(task.id)}
                  aria-pressed={task.is_collected}
                  onClick={() => onToggleCollection(task)}
                >
                  {collectingTaskIds.includes(task.id) ? (
                  <LoadingIndicator className="spin-icon" size={17} />
                ) : (
                  <FolderPlus size={17} />
                )}
                  {task.is_collected ? "已收藏" : "收藏"}
                </button>
                <button className="task-button task-button--blue" type="button" disabled={!output} onClick={() => output && onPreview(output)}>
                  <FileImage size={17} />
                  预览
                </button>
                <button
                  className="task-button task-button--blue"
                  type="button"
                  disabled={!output}
                  onClick={() => onDownload(task)}
                >
                  <Download size={17} />
                  下载
                </button>
                {showTaskEditActions ? (
                  <>
                    <button
                      className="task-button task-button--orange"
                      type="button"
                      disabled={task.status !== "succeeded" || !output || isVideoAsset(output)}
                      title={output && !isVideoAsset(output) ? "将结果图、原提示词带入图生图重新编辑" : "生成图片后可重新编辑"}
                      onClick={() => onContinueEdit(task)}
                    >
                      <Edit3 size={17} />
                      重新编辑
                    </button>
                    <button
                      className="task-button task-button--cyan"
                      type="button"
                      disabled={isProcessing || regeneratingTaskIds.includes(task.id)}
                      title={isProcessing ? "当前任务完成后可重新生成" : "复用原参数重新生成"}
                      onClick={() => onRegenerate(task)}
                    >
                      {regeneratingTaskIds.includes(task.id) ? (
                      <LoadingIndicator className="spin-icon" size={17} />
                    ) : (
                      <RotateCcw size={17} />
                    )}
                      重新生成
                    </button>
                  </>
                ) : null}
                <button
                  className="task-button task-button--red"
                  type="button"
                  disabled={isProcessing}
                  title={isProcessing ? "生成过程中暂不能删除" : "删除记录"}
                  onClick={() => onDelete(task.id)}
                >
                  <Trash2 size={17} />
                  删除
                </button>
              </div>
            </article>
          );
        })}
      </div>
    );
};
