import { LoadingIndicator } from "@/components/ui/LoadingIndicator";
import { useCallback, useEffect, useMemo, useRef, useState, type ChangeEvent, type CSSProperties, type DragEvent, type FormEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { createPortal } from "react-dom";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  BarChart3,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clapperboard,
  Download,
  FileText,
  FolderPlus,
  History,
  Image as ImageIcon,
  Mic,
  MessageSquare,
  MicOff,
  Package,
  Palette,
  Plus,
  RefreshCw,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  UploadCloud,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MaterialPicker } from "@/components/materials/MaterialPicker";
import { ModelPicker } from "@/components/models/ModelPicker";
import { DEFAULT_IMAGE_QUALITY } from "@/constants/imageGeneration";
import { imageTaskService } from "@/services/imageTasks";
import { modelService } from "@/services/models";
import { promptService, type AgentDocument, type AgentPlan } from "@/services/prompt";
import { uxService, DEFAULT_MAX_BATCH_TASKS } from "@/services/ux";
import { uploadService } from "@/services/uploads";
import type { ImageAsset, ImageModel, ImageTask } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import { downloadMedia, startBrowserDownload } from "@/utils/download";
import { mergeImageEditAssets } from "@/utils/imageEditNavigation";
import { getImageTaskStatusLabel } from "@/utils/imageTaskStatus";
import { formatElapsedTime, getTaskElapsedMs } from "@/utils/time";
import { readToolPreference, resolveToolPreference, writeToolPreference } from "@/utils/toolPreferences";
import {
  BULK_CONFIRM_THRESHOLD,
  AGENT_STARTERS,
  STATS_RANGE_LABELS,
  STYLE_KITS,
  STYLE_KIT_STORAGE_KEY,
  applyBrandKitToPrompt,
  applyStyleKitsToPrompt,
  classifyFailure,
  computeBatchStats,
  computeCreativeStats,
  detectUseCase,
  emptyBrandKit,
  expandVariantMatrix,
  formatCredit,
  isFollowUpIntent,
  loadBrandKit,
  mergeBrandLogoAsset,
  pickClosestAspectRatio,
  pickLatestFocusTask,
  pickPreferredResolution,
  resolveFollowUp,
  saveBrandKit,
  summarizePlanForConfirm,
  type BrandKit,
  type StatsRange,
} from "@/utils/imagineAgent";
import {
  buildMaterialRedrawPrompts,
  isMaterialLibraryBatchIntent,
  resolveMaterialBatchSelection,
} from "@/utils/imagineAgentMaterials";
import {
  appendSessionMessage,
  bindTasksToSession,
  buildSessionContextBlock,
  createAndActivateSession,
  deleteSession,
  deriveSessionTitleFromIntent,
  formatSessionTime,
  getActiveSession,
  loadAgentSessionStore,
  loadSessionFeedOnly,
  renameSession,
  saveAgentSessionStore,
  saveSessionFeedOnly,
  upsertSession,
  type AgentSession,
  type AgentSessionStore,
} from "@/utils/imagineAgentSessions";
import { isVideoAsset } from "@/pages/shared/mediaConfig";
import { getAssetPreviewSource } from "@/utils/assetPreview";


type BrowserSpeechRecognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: ((this: BrowserSpeechRecognition, ev: Event) => void) | null;
  onend: ((this: BrowserSpeechRecognition, ev: Event) => void) | null;
  onerror: ((this: BrowserSpeechRecognition, ev: Event & { error?: string }) => void) | null;
  onresult: ((this: BrowserSpeechRecognition, ev: BrowserSpeechRecognitionEvent) => void) | null;
};

type BrowserSpeechRecognitionEvent = {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
};

type BrowserSpeechRecognitionCtor = new () => BrowserSpeechRecognition;

const getSpeechRecognitionCtor = (): BrowserSpeechRecognitionCtor | null => {
  if (typeof window === "undefined") return null;
  const w = window as Window & {
    SpeechRecognition?: BrowserSpeechRecognitionCtor;
    webkitSpeechRecognition?: BrowserSpeechRecognitionCtor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

export type ImagineMediaKind = "image" | "video";
export type ImagineCreateMode = "direct" | "agent";

type Props = {
  /** Optional initial media kind. Default image. */
  initialMedia?: ImagineMediaKind;
  /** When true, start expecting reference images (video image-to-video entry). */
  preferImageInput?: boolean;
};

const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;
const DEFAULT_MAX_INPUT_IMAGES = 7;
const DOCUMENT_PLAN_MAX_PROMPTS = 100;
const TASK_PAGE_SIZE = 80;
const PREVIEW_THUMBNAIL_RADIUS = 10;

const mediaMeta: Record<
  ImagineMediaKind,
  { title: string; hint: string; path: string; icon: typeof ImageIcon }
> = {
  image: {
    title: "图片",
    hint: "描述画面，或上传参考图进行编辑",
    path: "/create/imagine",
    icon: ImageIcon,
  },
  video: {
    title: "视频",
    hint: "文生视频，或上传参考图生成动态短片",
    path: "/create/imagine?media=video",
    icon: Clapperboard,
  },
};

const taskStatusCopy: Record<ImageTask["status"], string> = {
  pending: "等待中",
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  refunded: "已退款",
};

const VIDEO_WORK_TYPES = ["text_to_video", "image_to_video"];
const BUSY_TASK_STATUSES = new Set<ImageTask["status"]>(["pending", "queued", "running"]);
const PROMPT_COLLAPSE_CHARS = 72;

const hasSamePollingState = (current: ImageTask, updated: ImageTask) =>
  current.status === updated.status &&
  current.progress_stage === updated.progress_stage &&
  current.failure_message === updated.failure_message &&
  current.finished_at === updated.finished_at &&
  current.worker_started_at === updated.worker_started_at &&
  current.output_images.length === updated.output_images.length &&
  current.output_images.every((asset, index) => asset.url === updated.output_images[index]?.url);

const isVideoWorkType = (workType: string) => VIDEO_WORK_TYPES.includes(workType);

const isPromptCollapsible = (prompt?: string | null) => {
  if (!prompt) return false;
  return prompt.length > PROMPT_COLLAPSE_CHARS || prompt.includes("\n");
};

/** Pseudo progress while polling (backend has no percent field). */
const estimateTaskProgress = (task: ImageTask, now: number): number => {
  if (task.status === "succeeded") return 100;
  if (task.status === "failed" || task.status === "refunded") return 0;
  if (task.progress_stage === "downloading") return 97;

  const createdAt = new Date(task.created_at).getTime();
  const createdMs = Number.isNaN(createdAt) ? now : createdAt;
  const sinceCreateSec = Math.max(0, (now - createdMs) / 1000);

  if (task.status === "pending") {
    return Math.min(10, 3 + sinceCreateSec * 0.45);
  }

  if (task.status === "queued") {
    return Math.min(28, 12 + sinceCreateSec * 0.28);
  }

  // running: time-based ease toward ~95% until success
  const elapsedMs = getTaskElapsedMs(task, now);
  const elapsedSec = (elapsedMs ?? Math.max(0, sinceCreateSec - (task.queue_duration_seconds ?? 0))) / 1000;
  const isVideo = isVideoWorkType(task.work_type);
  const durationSec = Number(task.duration) || (isVideo ? 6 : 0);
  const estimatedSec = isVideo
    ? Math.max(50, Math.min(200, durationSec * 14 + 36))
    : 30;
  const ratio = Math.min(1, elapsedSec / estimatedSec);
  const eased = 1 - (1 - ratio) ** 1.35;
  // After estimate, crawl slowly to 98% so the bar doesn't look frozen forever.
  if (elapsedSec > estimatedSec) {
    const overtime = elapsedSec - estimatedSec;
    return Math.min(98, 95 + Math.min(3, overtime / 60));
  }
  return Math.min(95, Math.round((30 + eased * 65) * 10) / 10);
};

const getAspectRatioStyle = (value: string): CSSProperties => {
  const [width, height] = value.split(":").map(Number);
  if (!width || !height || width <= 0 || height <= 0) {
    return { "--aspect-preview-height": "14px", "--aspect-preview-width": "14px" } as CSSProperties;
  }
  const maxWidth = 22;
  const maxHeight = 14;
  const scale = Math.min(maxWidth / width, maxHeight / height);
  return {
    "--aspect-preview-height": `${Math.max(8, height * scale)}px`,
    "--aspect-preview-width": `${Math.max(8, width * scale)}px`,
  } as CSSProperties;
};


const FAILED_TASK_STATUSES = new Set<ImageTask["status"]>(["failed", "refunded"]);

type RetryFailedScopeMode = "recent_batch" | "recent_n";

type RetryFailedDraft = {
  mode: RetryFailedScopeMode;
  recentCount: number;
  sourceText: string;
};

/** Agent / bulk run waiting for explicit user confirm. */
type PendingExecution = {
  source: "agent" | "direct_bulk";
  plan: AgentPlan | null;
  prompts: string[];
  modelId: number;
  modelName: string;
  resolution: string;
  aspectRatio: string;
  duration?: string;
  workType: string;
  inputAssets: ImageAsset[];
  /** When set (same length as prompts), each task uses its own reference image(s). */
  perTaskAssets?: ImageAsset[][];
  estimatedCredit: number | null;
  useCaseLabel?: string | null;
  optimizePrompt: boolean;
  summary: string;
  materialBatch?: {
    folderLabel: string;
    totalAvailable: number;
    selectedCount: number;
    thumbUrls: string[];
    editPrompt: string;
  } | null;
};

const isFailedTask = (task: ImageTask) => FAILED_TASK_STATUSES.has(task.status);
const isRetryableFailedTask = (task: ImageTask) =>
  isFailedTask(task) && !/(内容策略|content\s*policy|safety\s*policy)/i.test(task.failure_message || "");

const FAILURE_MESSAGE_COLLAPSE_THRESHOLD = 120;

const clusterRecentFailedBatch = (failed: ImageTask[], maxCount: number) => {
  if (!failed.length) return [] as ImageTask[];
  // tasks list is newest-first in this page.
  const newestTs = new Date(failed[0].created_at).getTime();
  const windowMs = 30 * 60 * 1000;
  const clustered = failed.filter((task) => {
    const ts = new Date(task.created_at).getTime();
    return Number.isFinite(ts) && Math.abs(ts - newestTs) <= windowMs;
  });
  return (clustered.length ? clustered : failed).slice(0, Math.max(1, maxCount));
};

const pickFailedTasksByScope = (
  failed: ImageTask[],
  mode: RetryFailedScopeMode,
  recentCount: number,
  maxCount: number,
) => {
  const limit = Math.max(1, Math.min(maxCount, recentCount || 1));
  if (mode === "recent_n") return failed.slice(0, limit);
  return clusterRecentFailedBatch(failed, Math.max(1, maxCount));
};

const normalizeModelKey = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/[\s_\-·•]+/g, "")
    .replace(/(模型|model)$/i, "");

/** Match NL model hint (e.g. 即梦) against catalog from GET /models. */
const matchModelByHint = (items: ImageModel[], hint?: string | null): ImageModel | null => {
  const key = normalizeModelKey(hint || "");
  if (!key || !items.length) return null;
  const scored = items
    .map((model) => {
      const nameK = normalizeModelKey(model.name || "");
      const codeK = normalizeModelKey(model.code || "");
      const descK = normalizeModelKey(model.description || "");
      let score = 0;
      if (key === nameK || key === codeK) score = 100;
      else if (nameK.includes(key) || key.includes(nameK)) score = 80;
      else if (codeK.includes(key) || key.includes(codeK)) score = 70;
      else if (descK.includes(key)) score = 50;
      return { model, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || b.model.id - a.model.id);
  return scored[0]?.model ?? null;
};

const extractModelHintFromText = (text: string): string | null => {
  const value = text.trim();
  if (!value) return null;
  const patterns = [
    /(?:用|使用|换成|换到|切换到|选用|采用)\s*([A-Za-z0-9\u4e00-\u9fff·_-]{1,32}?)\s*(?:的)?(?:图片|图像|视频|生图|绘画)?\s*模型/i,
    /模型\s*[：:为是]\s*([A-Za-z0-9\u4e00-\u9fff·_-]{1,32})/i,
    /([A-Za-z0-9\u4e00-\u9fff·_-]{1,32})\s*模型\s*(?:来|去|帮|给)?/i,
  ];
  for (const pattern of patterns) {
    const match = value.match(pattern);
    const hint = (match?.[1] || "").trim().replace(/[的了吧呀啊，,。]/g, "");
    if (hint && !["图片", "图像", "视频", "生成", "当前", "这个", "默认"].includes(hint)) return hint;
  }
  return null;
};

const buildRecreatePayload = (
  task: ImageTask,
  overrides?: { modelId?: number; prompt?: string },
): { payload: import("@/types/api").CreateImageTaskRequest; assets: ImageAsset[] } => {
  const assets = task.input_images ?? [];
  const workType = task.work_type?.startsWith("batch_")
    ? assets.length
      ? "image_to_image"
      : isVideoWorkType(task.work_type)
        ? "text_to_video"
        : "text_to_image"
    : task.work_type || (assets.length ? "image_to_image" : "text_to_image");
  // Normalize batch work types to single recreate.
  let normalized = workType;
  if (normalized === "batch_generate") normalized = "text_to_image";
  if (normalized === "batch_edit") normalized = assets.length ? "image_to_image" : "text_to_image";
  return {
    payload: {
      work_type: normalized,
      model_id: overrides?.modelId ?? task.model_id,
      prompt: overrides?.prompt ?? task.prompt,
      resolution: task.resolution,
      aspect_ratio: task.aspect_ratio,
      duration: task.duration || undefined,
      input_image_ids: assets.map((asset) => asset.id),
      output_count: 1,
    },
    assets,
  };
};

const resolveWorkType = (media: ImagineMediaKind, hasImages: boolean) => {
  if (media === "image") return hasImages ? "image_edit" : "text_to_image";
  return hasImages ? "image_to_video" : "text_to_video";
};

export const GrokImaginePage = ({ initialMedia = "image", preferImageInput = false }: Props) => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const assetDragDepthRef = useRef(0);
  const docInputRef = useRef<HTMLInputElement | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);
  const loadMoreSentinelRef = useRef<HTMLDivElement | null>(null);
  const speechRecognitionRef = useRef<BrowserSpeechRecognition | null>(null);
  const voiceBasePromptRef = useRef("");
  const voiceFinalPromptRef = useRef("");
  const composerPromptRef = useRef<HTMLTextAreaElement | null>(null);

  const mediaFromQuery = searchParams.get("media") === "video" ? "video" : initialMedia;

  useEffect(() => {
    window.dispatchEvent(new Event("image2:collapse-sidebar"));
  }, []);

  const [media, setMedia] = useState<ImagineMediaKind>(() => mediaFromQuery);
  const [models, setModels] = useState<ImageModel[]>([]);
  const [isPlanningAgent, setIsPlanningAgent] = useState(false);
  const [textModels, setTextModels] = useState<ImageModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<number | null>(null);
  const [selectedTextModelId, setSelectedTextModelId] = useState<number | null>(null);
  const [uploadedAssets, setUploadedAssets] = useState<ImageAsset[]>([]);
  const [isDraggingAssets, setIsDraggingAssets] = useState(false);
  /** Local object-URL previews while upload is in-flight (not yet server assets). */
  const [pendingUploadPreviews, setPendingUploadPreviews] = useState<string[]>([]);
  const [prompt, setPrompt] = useState("");
  const [resolution, setResolution] = useState("");
  const [aspectRatio, setAspectRatio] = useState("");
  const [duration, setDuration] = useState("");
  const [quote, setQuote] = useState<number | null>(null);
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [hasMoreTasks, setHasMoreTasks] = useState(false);
  const [isLoadingMoreTasks, setIsLoadingMoreTasks] = useState(false);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isMaterialPickerOpen, setIsMaterialPickerOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [previewAsset, setPreviewAsset] = useState<ImageAsset | null>(null);
  const [previewSourceAsset, setPreviewSourceAsset] = useState<ImageAsset | null>(null);
  const [isDownloadingPreview, setIsDownloadingPreview] = useState(false);
  // Imagine is the comprehensive Agent entry. Direct generation remains
  // available from its dedicated routes, while a temporary mode switch here
  // can still serve experienced users during the current visit.
  const [createMode, setCreateMode] = useState<ImagineCreateMode>("agent");
  const [agentPlanPrompt, setAgentPlanPrompt] = useState<string | null>(null);
  const [agentDocuments, setAgentDocuments] = useState<AgentDocument[]>([]);
  const [agentPlan, setAgentPlan] = useState<AgentPlan | null>(null);
  const [agentPlanningStatus, setAgentPlanningStatus] = useState<string | null>(null);
  const [isParsingDocument, setIsParsingDocument] = useState(false);
  const [maxBatchTasks, setMaxBatchTasks] = useState(DEFAULT_MAX_BATCH_TASKS);
  const [retryFailedDraft, setRetryFailedDraft] = useState<RetryFailedDraft | null>(null);
  const [deleteTaskIds, setDeleteTaskIds] = useState<number[] | null>(null);
  const [pendingExecution, setPendingExecution] = useState<PendingExecution | null>(null);
  const [pendingQuoteLoading, setPendingQuoteLoading] = useState(false);
  const [activeStyleKitIds, setActiveStyleKitIds] = useState<string[]>(() => {
    try {
      const raw = localStorage.getItem(STYLE_KIT_STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
    } catch {
      return [];
    }
  });
  const [recentAgentIntents, setRecentAgentIntents] = useState<string[]>([]);
  const [brandKit, setBrandKit] = useState<BrandKit>(() => loadBrandKit());
  const [showBrandKit, setShowBrandKit] = useState(false);
  const [statsRange, setStatsRange] = useState<StatsRange>("7d");
  const [showStats, setShowStats] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [isUploadingBrandLogo, setIsUploadingBrandLogo] = useState(false);
  const [agentHistoryReply, setAgentHistoryReply] = useState<string | null>(null);
  const brandLogoInputRef = useRef<HTMLInputElement | null>(null);
  const [sessionStore, setSessionStore] = useState<AgentSessionStore>(() => loadAgentSessionStore());
  const [showSessionPanel, setShowSessionPanel] = useState(false);
  const [sessionFeedOnly, setSessionFeedOnly] = useState(() => loadSessionFeedOnly());
  const [editingSessionTitle, setEditingSessionTitle] = useState(false);
  const [sessionTitleDraft, setSessionTitleDraft] = useState("");
  const [isSessionThreadOpen, setIsSessionThreadOpen] = useState(false);
  const [showAllSessionMessages, setShowAllSessionMessages] = useState(false);
  const [isComposerSettingsOpen, setIsComposerSettingsOpen] = useState(false);
  const [isCreativePreferencesOpen, setIsCreativePreferencesOpen] = useState(false);
  const [isAttachmentTrayOpen, setIsAttachmentTrayOpen] = useState(false);
  const skipNextSessionHydrateRef = useRef(false);
  const [feedFilter, setFeedFilter] = useState<"all" | "busy" | "succeeded" | "failed">("all");
  const [isVoiceListening, setIsVoiceListening] = useState(false);
  const [speechSupported] = useState(() => Boolean(getSpeechRecognitionCtor()));
  const [openMenu, setOpenMenu] = useState<"textModel" | "ratio" | "resolution" | "duration" | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [expandedPromptIds, setExpandedPromptIds] = useState<number[]>([]);
  const [expandedFailureIds, setExpandedFailureIds] = useState<number[]>([]);

  const selectedModel = useMemo(
    () => models.find((model) => model.id === selectedModelId) ?? null,
    [models, selectedModelId],
  );

  const selectedTextModel = useMemo(
    () => textModels.find((model) => model.id === selectedTextModelId) ?? null,
    [textModels, selectedTextModelId],
  );

  const isAgentMode = createMode === "agent";

  useEffect(() => {
    document.body.classList.add("is-imagine-page");
    return () => document.body.classList.remove("is-imagine-page");
  }, []);

  useEffect(() => {
    if (!isAgentMode) return;
    let ignore = false;
    uxService
      .getConfig()
      .then((cfg) => {
        if (ignore) return;
        const next = Number(cfg.max_batch_tasks);
        setMaxBatchTasks(Number.isFinite(next) && next >= 1 ? Math.floor(next) : DEFAULT_MAX_BATCH_TASKS);
      })
      .catch(() => {
        if (!ignore) setMaxBatchTasks(DEFAULT_MAX_BATCH_TASKS);
      });
    return () => {
      ignore = true;
    };
  }, [isAgentMode]);

  const isVideoMode = media === "video";
  const hasImages = uploadedAssets.length > 0;
  /** Uploading in progress — must not submit as text-to-image while refs are pending. */
  const hasPendingUploads = isUploading || pendingUploadPreviews.length > 0;
  const hasImagesOrPending = hasImages || hasPendingUploads;
  // While images are uploading, treat as image-edit / image-to-video for model prefs & UI.
  const effectiveWorkType = resolveWorkType(media, hasImagesOrPending);
  const maxInputImages =
    selectedModel?.max_input_images ?? (effectiveWorkType === "text_to_image" ? DEFAULT_MAX_INPUT_IMAGES : DEFAULT_MAX_INPUT_IMAGES);
  // Keep the attachment entry point available before an image-edit model is
  // selected. Once a reference image is uploaded, the model catalog switches
  // to the corresponding image-to-image or image-to-video capability.
  const canAttachImages = true;
  const remainingSlots = Math.max(
    0,
    (maxInputImages || DEFAULT_MAX_INPUT_IMAGES) - uploadedAssets.length - pendingUploadPreviews.length,
  );
  const needsUpload = Boolean(preferImageInput && isVideoMode);

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? tasks[0] ?? null,
    [tasks, selectedTaskId],
  );

  useEffect(() => {
    setMedia(mediaFromQuery);
  }, [mediaFromQuery]);

  useEffect(() => {
    try {
      window.localStorage.setItem("image2.imagine.createMode", createMode);
    } catch {
      // ignore storage failures
    }
  }, [createMode]);

  useEffect(() => {
    if (!error) return;
    const timerId = window.setTimeout(() => setError(null), 5000);
    return () => window.clearTimeout(timerId);
  }, [error]);

  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(null), 2800);
    return () => window.clearTimeout(timerId);
  }, [notice]);

  useEffect(() => {
    if (!previewAsset) return;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setPreviewAsset(null);
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [previewAsset]);

  useEffect(() => {
    if (!previewAsset) setPreviewSourceAsset(null);
  }, [previewAsset]);

  // Close menus on outside click.
  useEffect(() => {
    if (!openMenu) return;
    const onPointer = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target?.closest?.(".gi-menu, .gi-pill-btn")) setOpenMenu(null);
    };
    window.addEventListener("mousedown", onPointer);
    return () => window.removeEventListener("mousedown", onPointer);
  }, [openMenu]);

  // Load models for current media + attachment state.
  // Agent mode: also pull sibling image work_types so NL model match (e.g. 即梦) sees full catalog.
  useEffect(() => {
    let ignore = false;
    setIsLoadingModels(true);
    const requestWorkType = resolveWorkType(media, hasImagesOrPending || Boolean(preferImageInput && media === "video"));
    const siblingWorkType =
      media === "image"
        ? hasImages
          ? "text_to_image"
          : "image_edit"
        : hasImages
          ? "text_to_video"
          : "image_to_video";

    const load = async () => {
      const primary = await modelService.getModels(requestWorkType);
      let merged = primary;
      if (createMode === "agent") {
        try {
          const sibling = await modelService.getModels(siblingWorkType);
          const seen = new Set(primary.map((item) => item.id));
          merged = [...primary];
          for (const item of sibling) {
            if (!seen.has(item.id)) {
              seen.add(item.id);
              merged.push(item);
            }
          }
        } catch {
          // keep primary list
        }
      }
      return merged;
    };

    load()
      .then((items) => {
        if (ignore) return;
        setModels(items);
        const preference = resolveToolPreference(items, readToolPreference(requestWorkType));
        setSelectedModelId(preference.modelId);
        setResolution(preference.resolution);
        setAspectRatio(preference.aspectRatio);
        setDuration(preference.duration);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [media, preferImageInput, hasImagesOrPending ? "with-image" : "no-image", createMode]);

  useEffect(() => {
    if (!isAgentMode) return;
    let ignore = false;
    modelService
      .getModels("prompt_optimize")
      .then((items) => {
        if (ignore) return;
        setTextModels(items);
        setSelectedTextModelId(items[0]?.id ?? null);
      })
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, [isAgentMode]);

  useEffect(() => {
    if (!selectedModelId || !resolution || !aspectRatio) return;
    if (isVideoMode && !duration) return;
    writeToolPreference(effectiveWorkType, {
      modelId: selectedModelId,
      resolution,
      aspectRatio,
      duration,
      quality: DEFAULT_IMAGE_QUALITY,
    });
  }, [selectedModelId, resolution, aspectRatio, duration, effectiveWorkType, isVideoMode]);

  useEffect(() => {
    let ignore = false;
    imageTaskService
      .getTasks({ limit: TASK_PAGE_SIZE })
      .then((items) => {
        if (ignore) return;
        setTasks(items);
        setHasMoreTasks(items.length === TASK_PAGE_SIZE);
        if (items[0]) setSelectedTaskId((current) => current ?? items[0].id);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "任务记录加载失败");
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    const activeTaskIds = tasks
      .filter((task) => ["pending", "queued", "running"].includes(task.status))
      .map((task) => task.id);
    if (!activeTaskIds.length) return;
    const timerId = window.setInterval(() => {
      void imageTaskService.getTaskStatuses(activeTaskIds)
        .then((updatedTasks) => {
          const updatesById = new Map(updatedTasks.map((task) => [task.id, task]));
          setTasks((current) => {
            let changed = false;
            const next = current.map((task) => {
              const updated = updatesById.get(task.id);
              if (!updated || hasSamePollingState(task, updated)) return task;
              changed = true;
              return updated;
            });
            return changed ? next : current;
          });
          if (updatedTasks.some((task) => ["succeeded", "failed", "refunded"].includes(task.status))) {
            notifyCreditBalanceChanged();
          }
        })
        .catch(() => undefined);
    }, 1600);
    return () => window.clearInterval(timerId);
  }, [tasks]);

  const loadMoreTasks = useCallback(async () => {
    if (isLoadingMoreTasks || !hasMoreTasks) return;
    const beforeId = tasks.reduce((oldest, task) => Math.min(oldest, task.id), Number.POSITIVE_INFINITY);
    if (!Number.isFinite(beforeId)) return;
    setIsLoadingMoreTasks(true);
    try {
      const items = await imageTaskService.getTasks({ limit: TASK_PAGE_SIZE, beforeId });
      setTasks((current) => {
        const knownIds = new Set(current.map((task) => task.id));
        return [...current, ...items.filter((task) => !knownIds.has(task.id))];
      });
      setHasMoreTasks(items.length === TASK_PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更早的任务加载失败");
    } finally {
      setIsLoadingMoreTasks(false);
    }
  }, [hasMoreTasks, isLoadingMoreTasks, tasks]);

  useEffect(() => {
    const sentinel = loadMoreSentinelRef.current;
    const scrollRoot = feedRef.current;
    if (!sentinel || !scrollRoot || !hasMoreTasks || isLoadingMoreTasks) return;
    if (!("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMoreTasks();
      },
      { root: scrollRoot, rootMargin: "800px 0px", threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMoreTasks, isLoadingMoreTasks, loadMoreTasks]);

  useEffect(() => {
    if (!selectedModel || !resolution || !aspectRatio) return;
    if (isVideoMode && !duration) return;
    let ignore = false;
    modelService
      .quote(selectedModel.id, effectiveWorkType, resolution, aspectRatio, 1, isVideoMode ? duration : undefined)
      .then((nextQuote) => {
        if (!ignore) setQuote(nextQuote.credit_cost);
      })
      .catch(() => {
        if (!ignore) setQuote(null);
      });
    return () => {
      ignore = true;
    };
  }, [resolution, aspectRatio, duration, selectedModel, effectiveWorkType, isVideoMode]);

  const isImageFile = (file: File) => {
    if (file.type.startsWith("image/")) return true;
    return /\.(jpe?g|png|webp|gif|bmp|heic|heif)$/i.test(file.name);
  };

  const isAgentDocumentFile = (file: File) => {
    const lower = file.name.toLowerCase();
    if (
      lower.endsWith(".txt") ||
      lower.endsWith(".md") ||
      lower.endsWith(".markdown") ||
      lower.endsWith(".pdf") ||
      lower.endsWith(".docx") ||
      lower.endsWith(".csv") ||
      lower.endsWith(".json") ||
      lower.endsWith(".html") ||
      lower.endsWith(".htm") ||
      lower.endsWith(".rtf")
    ) {
      return true;
    }
    // Old .doc is detected so we can show a clearer backend/frontend message.
    if (lower.endsWith(".doc")) return true;
    const mime = (file.type || "").toLowerCase();
    return (
      mime === "application/pdf" ||
      mime === "text/plain" ||
      mime === "text/markdown" ||
      mime === "text/x-markdown" ||
      mime === "text/csv" ||
      mime === "application/csv" ||
      mime === "application/json" ||
      mime === "text/html" ||
      mime === "application/rtf" ||
      mime === "text/rtf" ||
      mime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
      mime === "application/msword"
    );
  };

  const canAcceptComposerDrop =
    (isAgentMode && !isParsingDocument && agentDocuments.length < 5) ||
    (canAttachImages && !isUploading && remainingSlots > 0);

  const uploadImageFiles = async (incoming: File[]) => {
    if (!incoming.length || !canAttachImages) return;
    if (isUploading) {
      setNotice("上一批图片还在上传中，请稍候再添加");
      return;
    }

    const imageFiles = incoming.filter(isImageFile);
    if (!imageFiles.length) {
      setError(
        isAgentMode
          ? "未识别到图片。文档请拖入 TXT/MD/PDF/DOCX 等（或点「文档」），参考图请用 JPG/PNG/WEBP"
          : "请拖入或选择图片文件（JPG / PNG / WEBP）",
      );
      return;
    }

    const limit = maxInputImages || DEFAULT_MAX_INPUT_IMAGES;
    const nextFiles = imageFiles.slice(0, Math.max(0, limit - uploadedAssets.length));
    if (!nextFiles.length) {
      setError(`当前模型最多支持 ${limit} 张输入图`);
      return;
    }

    const oversizedFile = nextFiles.find((file) => file.size > MAX_UPLOAD_SIZE);
    if (oversizedFile) {
      setError(`图片“${oversizedFile.name}”超过 10MB，请压缩后再上传`);
      return;
    }

    const previews = nextFiles.map((file) => URL.createObjectURL(file));
    setPendingUploadPreviews(previews);
    setIsUploading(true);
    setError(null);
    setNotice(`正在上传 ${nextFiles.length} 张参考图…上传完成前请勿发送，避免误走文生图`);
    try {
      const assets = await Promise.all(nextFiles.map((file) => uploadService.uploadImage(file)));
      setUploadedAssets((current) => [...current, ...assets].slice(0, limit));
      const skippedNonImage = incoming.length - imageFiles.length;
      const skippedByLimit = imageFiles.length - nextFiles.length;
      if (skippedByLimit > 0) {
        setNotice(`已按上限上传 ${nextFiles.length} 张（最多 ${limit} 张）· 可发送图生图`);
      } else if (skippedNonImage > 0) {
        setNotice(`已上传 ${nextFiles.length} 张参考图（忽略 ${skippedNonImage} 个非图片）· 可发送图生图`);
      } else {
        setNotice(`参考图已就绪（${nextFiles.length} 张）· 现在发送会走图生图`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片上传失败");
      setNotice(null);
    } finally {
      previews.forEach((url) => URL.revokeObjectURL(url));
      setPendingUploadPreviews([]);
      setIsUploading(false);
    }
  };

  const uploadFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    await uploadImageFiles(files);
  };

  const onAssetDragEnter = (event: DragEvent<HTMLElement>) => {
    if (!canAcceptComposerDrop) return;
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    assetDragDepthRef.current += 1;
    setIsDraggingAssets(true);
  };

  const onAssetDragOver = (event: DragEvent<HTMLElement>) => {
    if (!canAcceptComposerDrop) return;
    if (![...event.dataTransfer.types].includes("Files")) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = "copy";
    if (!isDraggingAssets) setIsDraggingAssets(true);
  };

  const onAssetDragLeave = (event: DragEvent<HTMLElement>) => {
    if (!canAcceptComposerDrop && !isDraggingAssets) return;
    event.preventDefault();
    event.stopPropagation();
    assetDragDepthRef.current = Math.max(0, assetDragDepthRef.current - 1);
    if (assetDragDepthRef.current === 0) setIsDraggingAssets(false);
  };

  const onAssetDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    event.stopPropagation();
    assetDragDepthRef.current = 0;
    setIsDraggingAssets(false);
    const files = Array.from(event.dataTransfer.files ?? []);
    if (!files.length) return;

    const docs = isAgentMode ? files.filter(isAgentDocumentFile) : [];
    const images = files.filter(isImageFile);

    if (docs.length) {
      void parseAgentDocumentFiles(docs);
    }

    if (images.length) {
      if (!canAttachImages) {
        if (!docs.length) setError("当前模式不支持参考图");
      } else if (remainingSlots <= 0) {
        if (!docs.length) setError(`当前模型最多支持 ${maxInputImages || DEFAULT_MAX_INPUT_IMAGES} 张输入图`);
        else setNotice(`文档已处理；参考图已满（最多 ${maxInputImages || DEFAULT_MAX_INPUT_IMAGES} 张）`);
      } else if (isUploading) {
        if (!docs.length) setNotice("上一批图片还在上传中，请稍候再添加");
        else setNotice("文档解析中…参考图仍在上传，请稍候再拖图");
      } else {
        void uploadImageFiles(images);
      }
      return;
    }

    if (!docs.length) {
      setError(
        isAgentMode
          ? "请拖入图片（JPG/PNG/WEBP）或文档（TXT/MD/PDF/DOCX 等）"
          : "请拖入或选择图片文件（JPG / PNG / WEBP）",
      );
    }
  };

  const addMaterialAssets = (assets: ImageAsset[]) => {
    if (!canAttachImages) return;
    const limit = maxInputImages || DEFAULT_MAX_INPUT_IMAGES;
    setUploadedAssets((current) => {
      const existingIds = new Set(current.map((asset) => asset.id));
      const merged = [...current];
      for (const asset of assets) {
        if (existingIds.has(asset.id)) continue;
        if (merged.length >= limit) break;
        merged.push(asset);
      }
      return merged;
    });
  };

  const removeUpload = (assetId: number) => {
    setUploadedAssets((current) => current.filter((asset) => asset.id !== assetId));
  };

  const agentDocumentText = useMemo(
    () => agentDocuments.map((doc) => `【${doc.name}】\n${doc.text}`).join("\n\n"),
    [agentDocuments],
  );

  const parseAgentDocumentFiles = async (incoming: File[]) => {
    if (!isAgentMode || !incoming.length) return;
    if (isParsingDocument) {
      setNotice("文档还在解析中，请稍候再添加");
      return;
    }
    const files = incoming.filter(isAgentDocumentFile);
    if (!files.length) {
      setError("不支持的文档类型（支持 TXT / MD / PDF / DOCX / CSV / JSON / HTML / RTF）");
      return;
    }
    if (agentDocuments.length >= 5) {
      setError("最多载入 5 个文档，请先移除部分文档");
      return;
    }
    setIsParsingDocument(true);
    setError(null);
    setNotice(`正在解析 ${files.length} 个文档…`);
    try {
      const parsed: AgentDocument[] = [];
      for (const file of files) {
        if (file.size > 8 * 1024 * 1024) {
          throw new Error(`文件过大：${file.name}（最大 8MB）`);
        }
        parsed.push(await promptService.extractDocument(file));
      }
      setAgentDocuments((current) => {
        const merged = [...current];
        for (const doc of parsed) {
          if (merged.some((item) => item.name === doc.name && item.char_count === doc.char_count)) continue;
          if (merged.length >= 5) break;
          merged.push(doc);
        }
        return merged.slice(0, 5);
      });
      setAgentPlan(null);
      setNotice(`已解析 ${parsed.length} 个文档，可直接描述意图生成（支持剧本分镜 / 多提示词）`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "文档解析失败");
      setNotice(null);
    } finally {
      setIsParsingDocument(false);
    }
  };

  const uploadAgentDocuments = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    await parseAgentDocumentFiles(files);
  };

  const removeAgentDocument = (docId: string) => {
    setAgentDocuments((current) => current.filter((doc) => doc.id !== docId));
    setAgentPlan(null);
  };

  const intentLabel = (intent?: string) => {
    switch (intent) {
      case "script_to_images":
        return "剧本/分镜生图";
      case "multi_prompts":
        return "多提示词批量";
      case "image_edit_plan":
        return "参考图改图计划";
      case "material_library_batch":
        return "素材库批量重绘";
      case "retry_failed":
        return "重试失败任务";
      case "refused":
        return "已拒绝（安全边界）";
      case "single_prompt":
        return "单条创作";
      default:
        return intent || "创作计划";
    }
  };

  const stopVoiceInput = (opts?: { abort?: boolean }) => {
    const recognition = speechRecognitionRef.current;
    if (!recognition) {
      setIsVoiceListening(false);
      return;
    }
    try {
      if (opts?.abort) recognition.abort();
      else recognition.stop();
    } catch {
      // ignore stop race
    }
    speechRecognitionRef.current = null;
    setIsVoiceListening(false);
  };

  const startVoiceInput = () => {
    const Ctor = getSpeechRecognitionCtor();
    if (!Ctor) {
      setError("当前浏览器不支持语音输入，请使用 Chrome / Edge，或直接打字");
      return;
    }
    if (isSubmitting || isPlanningAgent || isParsingDocument) return;

    stopVoiceInput({ abort: true });
    const recognition = new Ctor();
    recognition.lang = "zh-CN";
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    voiceBasePromptRef.current = prompt.trim();
    voiceFinalPromptRef.current = prompt.trim();
    speechRecognitionRef.current = recognition;

    recognition.onstart = () => {
      setIsVoiceListening(true);
      setError(null);
      setNotice(isAgentMode ? "正在听你说意图… 说完点麦克风结束" : "正在语音输入…");
    };

    recognition.onresult = (event) => {
      let finalChunk = "";
      let interimChunk = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const piece = event.results[i]?.[0]?.transcript?.trim() ?? "";
        if (!piece) continue;
        if (event.results[i].isFinal) finalChunk += `${piece} `;
        else interimChunk += `${piece} `;
      }
      if (finalChunk.trim()) {
        const merged = [voiceFinalPromptRef.current, finalChunk.trim()].filter(Boolean).join(voiceFinalPromptRef.current ? " " : "");
        voiceFinalPromptRef.current = merged.trim();
      }
      const display = [voiceFinalPromptRef.current || voiceBasePromptRef.current, interimChunk.trim()]
        .filter(Boolean)
        .join(voiceFinalPromptRef.current || voiceBasePromptRef.current ? " " : "")
        .trim();
      setPrompt(display);
      if (agentPlanPrompt && display !== agentPlanPrompt) {
        setAgentPlanPrompt(null);
      }
    };

    recognition.onerror = (event) => {
      const code = event.error || "";
      if (code === "aborted") return;
      if (code === "no-speech") {
        setNotice("没有听清，请靠近麦克风再说一次");
        return;
      }
      if (code === "not-allowed" || code === "service-not-allowed") {
        setError("麦克风权限被拒绝，请在浏览器设置中允许后重试");
      } else if (code === "network") {
        setError("语音识别网络异常，请检查网络后重试");
      } else {
        setError(`语音输入失败${code ? `：${code}` : ""}`);
      }
      setIsVoiceListening(false);
    };

    recognition.onend = () => {
      // If user didn't manually stop and browser auto-ended, keep UI consistent.
      if (speechRecognitionRef.current === recognition) {
        speechRecognitionRef.current = null;
      }
      setIsVoiceListening(false);
      const finalText = (voiceFinalPromptRef.current || prompt).trim();
      if (finalText) {
        setPrompt(finalText);
        setNotice(isAgentMode ? "语音意图已写入，可继续补充或直接生成" : "语音已写入输入框");
      }
    };

    try {
      recognition.start();
    } catch (err) {
      setIsVoiceListening(false);
      speechRecognitionRef.current = null;
      setError(err instanceof Error ? err.message : "无法启动语音输入");
    }
  };

  const toggleVoiceInput = () => {
    if (isVoiceListening) {
      stopVoiceInput();
      return;
    }
    startVoiceInput();
  };

  useEffect(() => {
    return () => {
      try {
        speechRecognitionRef.current?.abort();
      } catch {
        // ignore
      }
      speechRecognitionRef.current = null;
    };
  }, []);

  const recreateTasksFromSources = async (
    sources: ImageTask[],
    overrides?: { modelId?: number },
  ) => {
    if (!sources.length) {
      throw new Error("没有可重新生成的任务");
    }
    const limited = sources.slice(0, maxBatchTasks);
    const created: ImageTask[] = [];
    for (const source of limited) {
      const { payload, assets } = buildRecreatePayload(source, { modelId: overrides?.modelId });
      const task = await imageTaskService.createTask(payload, assets);
      created.push(task);
    }
    if (isAgentMode && created.length) {
      const taskIds = created.map((task) => task.id);
      patchActiveSession((session) =>
        appendSessionMessage(bindTasksToSession(session, taskIds), {
          role: "agent",
          content: created.length > 1 ? `已基于现有作品提交 ${created.length} 个同款任务` : "已基于现有作品提交同款任务",
        }),
      );
    }
    setTasks((current) => [...created, ...current]);
    setSelectedTaskId(created[0]?.id ?? null);
    setFeedFilter("all");
    notifyCreditBalanceChanged();
    feedRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    return created;
  };

  const retryAllFailedInFeed = async () => {
    if (!retryableFailedTasks.length || isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    if (isAgentMode) {
      setAgentPlanningStatus("正在读取你的创作意图与当前会话上下文…");
    }
    try {
      const created = await recreateTasksFromSources(retryableFailedTasks.slice(0, maxBatchTasks));
      setNotice(`已重试 ${created.length} 条失败任务`);
      setFeedFilter("busy");
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量重试失败");
    } finally {
      setIsSubmitting(false);
    }
  };


  const activeStyleKits = useMemo(
    () => STYLE_KITS.filter((kit) => activeStyleKitIds.includes(kit.id)),
    [activeStyleKitIds],
  );

  useEffect(() => {
    try {
      localStorage.setItem(STYLE_KIT_STORAGE_KEY, JSON.stringify(activeStyleKitIds));
    } catch {
      // ignore quota
    }
  }, [activeStyleKitIds]);

  useEffect(() => {
    saveBrandKit(brandKit);
  }, [brandKit]);

  const activeSession = useMemo(() => getActiveSession(sessionStore), [sessionStore]);

  const persistSessionStore = (next: AgentSessionStore) => {
    setSessionStore(next);
    saveAgentSessionStore(next);
  };

  const patchActiveSession = (updater: (session: AgentSession) => AgentSession) => {
    setSessionStore((current) => {
      const active = getActiveSession(current);
      const nextSession = updater(active);
      const next = upsertSession(current, nextSession);
      // keep activeId from upsertSession
      saveAgentSessionStore(next);
      return next;
    });
  };

  const flushUiIntoActiveSession = (base?: AgentSessionStore) => {
    const current = base || sessionStore;
    const active = getActiveSession(current);
    const nextSession: AgentSession = {
      ...active,
      documents: agentDocuments,
      recentIntents: recentAgentIntents,
      focusTaskId: selectedTaskId,
      textModelId: selectedTextModelId,
      styleKitIds: activeStyleKitIds,
      draftPrompt: prompt,
      updatedAt: new Date().toISOString(),
    };
    const next = upsertSession({ ...current, activeId: active.id }, nextSession);
    saveAgentSessionStore(next);
    return next;
  };

  const hydrateFromSession = (session: AgentSession, options?: { notice?: string | null }) => {
    // Always restore session-scoped fields, including empty arrays, so nothing leaks from previous session UI.
    setAgentDocuments(session.documents || []);
    setRecentAgentIntents(session.recentIntents || []);
    setSelectedTaskId(session.focusTaskId);
    setActiveStyleKitIds(Array.isArray(session.styleKitIds) ? session.styleKitIds : []);
    if (session.textModelId != null) setSelectedTextModelId(session.textModelId);
    setPrompt(session.draftPrompt || "");
    // Reference uploads are working memory for the current session only.
    setUploadedAssets([]);
    setAgentPlan(null);
    setAgentPlanPrompt(null);
    setPendingExecution(null);
    setPendingQuoteLoading(false);
    setRetryFailedDraft(null);
    setFeedFilter("all");
    setError(null);
    if (options?.notice === null) {
      // caller sets notice
    } else {
      setNotice(options?.notice ?? `已切换到会话「${session.title}」· 上下文已隔离`);
    }
  };

  const switchAgentSession = (sessionId: string) => {
    if (sessionId === activeSession.id) {
      setShowSessionPanel(false);
      return;
    }
    const flushed = flushUiIntoActiveSession();
    const target = flushed.sessions.find((s) => s.id === sessionId);
    if (!target) return;
    skipNextSessionHydrateRef.current = true;
    const next = { ...flushed, activeId: sessionId };
    persistSessionStore(next);
    hydrateFromSession(target);
    setShowSessionPanel(false);
  };

  const createAgentSession = () => {
    const flushed = flushUiIntoActiveSession();
    const { store, session } = createAndActivateSession(flushed);
    skipNextSessionHydrateRef.current = true;
    persistSessionStore(store);
    hydrateFromSession(session, { notice: `已新建会话「${session.title}」· 空白上下文` });
    setShowSessionPanel(false);
  };

  const removeAgentSession = (sessionId: string) => {
    const flushed = flushUiIntoActiveSession();
    const next = deleteSession(flushed, sessionId);
    const active = getActiveSession(next);
    skipNextSessionHydrateRef.current = true;
    persistSessionStore(next);
    hydrateFromSession(active, { notice: "会话已删除，上下文不会串到其他会话" });
  };

  const commitSessionTitle = () => {
    const title = sessionTitleDraft.trim();
    if (!title) {
      setEditingSessionTitle(false);
      return;
    }
    const next = renameSession(sessionStore, activeSession.id, title);
    persistSessionStore(next);
    setEditingSessionTitle(false);
  };

  // Hydrate UI once when entering Agent mode (prevent empty state wiping stored session).
  useEffect(() => {
    if (!isAgentMode) return;
    skipNextSessionHydrateRef.current = true;
    const session = getActiveSession(sessionStore);
    setAgentDocuments(session.documents || []);
    setRecentAgentIntents(session.recentIntents || []);
    setSelectedTaskId(session.focusTaskId);
    setActiveStyleKitIds(Array.isArray(session.styleKitIds) ? session.styleKitIds : []);
    if (session.textModelId != null) setSelectedTextModelId(session.textModelId);
    if (typeof session.draftPrompt === "string") setPrompt(session.draftPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAgentMode]);

  // Persist feed scope preference
  useEffect(() => {
    saveSessionFeedOnly(sessionFeedOnly);
  }, [sessionFeedOnly]);

  // Keep lightweight session fields in sync (docs / intents / focus / style / text model / draft)
  useEffect(() => {
    if (!isAgentMode) return;
    if (skipNextSessionHydrateRef.current) {
      skipNextSessionHydrateRef.current = false;
      return;
    }
    patchActiveSession((session) => ({
      ...session,
      documents: agentDocuments,
      recentIntents: recentAgentIntents,
      focusTaskId: selectedTaskId,
      textModelId: selectedTextModelId,
      styleKitIds: activeStyleKitIds,
      draftPrompt: prompt,
    }));
  }, [isAgentMode, agentDocuments, recentAgentIntents, selectedTaskId, selectedTextModelId, activeStyleKitIds, prompt]);

  const agentScopedTasks = useMemo(() => {
    return tasks;
  }, [tasks]);

  const failedTasks = useMemo(() => {
    const pool = isAgentMode && sessionFeedOnly ? agentScopedTasks : tasks;
    return pool.filter(isFailedTask);
  }, [isAgentMode, sessionFeedOnly, agentScopedTasks, tasks]);
  const retryableFailedTasks = useMemo(() => failedTasks.filter(isRetryableFailedTask), [failedTasks]);

  const batchStats = useMemo(() => computeBatchStats(agentScopedTasks), [agentScopedTasks]);
  const creativeStats = useMemo(
    () => computeCreativeStats(isAgentMode && sessionFeedOnly ? agentScopedTasks : tasks, statsRange),
    [isAgentMode, sessionFeedOnly, agentScopedTasks, tasks, statsRange],
  );

  const filteredTasks = useMemo(() => {
    const pool = agentScopedTasks;
    if (feedFilter === "all") return pool;
    if (feedFilter === "succeeded") return pool.filter((t) => t.status === "succeeded");
    if (feedFilter === "failed") return pool.filter(isFailedTask);
    return pool.filter((t) => BUSY_TASK_STATUSES.has(t.status));
  }, [feedFilter, agentScopedTasks]);

  const exportableTaskIds = useMemo(() => {
    const pool = feedFilter === "succeeded" || feedFilter === "all" ? filteredTasks : agentScopedTasks;
    return pool.filter((t) => t.status === "succeeded" && t.output_images?.[0]).map((t) => t.id);
  }, [feedFilter, filteredTasks, agentScopedTasks]);

  // Focus must stay inside the active session when session-only mode is on.
  const focusTask = useMemo(() => {
    const pool =
      isAgentMode && sessionFeedOnly && activeSession.taskIds.length
        ? agentScopedTasks
        : isAgentMode && activeSession.taskIds.length
          ? // still prefer session tasks for multi-turn even if viewing all
            (() => {
              const idSet = new Set(activeSession.taskIds);
              const scoped = tasks.filter((t) => idSet.has(t.id));
              return scoped.length ? scoped : tasks;
            })()
          : tasks;
    return pickLatestFocusTask(pool, selectedTaskId);
  }, [isAgentMode, sessionFeedOnly, activeSession.taskIds, agentScopedTasks, tasks, selectedTaskId]);

  const toggleStyleKit = (kitId: string) => {
    setActiveStyleKitIds((current) =>
      current.includes(kitId) ? current.filter((id) => id !== kitId) : [...current, kitId].slice(-4),
    );
  };

  const enrichPromptWithKits = (base: string) =>
    applyBrandKitToPrompt(applyStyleKitsToPrompt(base, activeStyleKits), brandKit);

  const updateBrandKit = (patch: Partial<BrandKit>) => {
    setBrandKit((current) => ({ ...current, ...patch }));
  };

  const exportSucceededPack = async () => {
    const ids = exportableTaskIds;
    if (!ids.length || isExporting) return;
    setIsExporting(true);
    setError(null);
    try {
      const downloadUrl = await imageTaskService.createExportDownloadUrl(ids);
      startBrowserDownload(downloadUrl);
      setNotice(`已导出 ${ids.length} 条成功素材包`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setIsExporting(false);
    }
  };

  const brandLogoAsImageAsset = useMemo((): ImageAsset | null => {
    const logo = brandKit.logoAsset;
    if (!logo?.id || !logo.url) return null;
    return {
      id: logo.id,
      url: logo.url,
      mime_type: logo.mime_type || "image/png",
      size_bytes: 0,
      sha256: "",
      source: "upload",
    };
  }, [brandKit.logoAsset]);

  const uploadBrandLogo = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setError("品牌 Logo 请上传图片文件");
      return;
    }
    setIsUploadingBrandLogo(true);
    setError(null);
    try {
      const asset = await uploadService.uploadImage(file);
      updateBrandKit({
        logoAsset: { id: asset.id, url: asset.url, mime_type: asset.mime_type },
        logoUrl: asset.url,
        enabled: true,
      });
      setNotice("品牌 Logo 已上传，开启规范后会自动作为参考图");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Logo 上传失败");
    } finally {
      setIsUploadingBrandLogo(false);
    }
  };

  const clearBrandLogo = () => {
    updateBrandKit({ logoAsset: null, logoUrl: null });
    setNotice("已移除品牌 Logo");
  };

  const pushAgentIntent = (intent: string) => {
    const value = intent.trim();
    if (!value) return;
    setRecentAgentIntents((current) => [...current.filter((item) => item !== value), value].slice(-6));
    if (!isAgentMode) return;
    patchActiveSession((session) => {
      let next = appendSessionMessage(session, {
        role: "user",
        content: value,
        kind: "intent",
      });
      next = {
        ...next,
        recentIntents: [...next.recentIntents.filter((item) => item !== value), value].slice(-8),
      };
      // Auto-title only for default-ish titles
      if (/^会话\s*\d+$/.test(next.title) || next.title === "新会话" || next.title === "未命名会话") {
        next = { ...next, title: deriveSessionTitleFromIntent(value, next.title) };
      }
      return next;
    });
  };

  const pushAgentMessage = (
    content: string,
    kind: "plan" | "stats" | "notice" | "confirm" | "error" = "notice",
    meta?: { planIntent?: string; promptCount?: number; taskIds?: number[] },
  ) => {
    if (!isAgentMode || !content.trim()) return;
    patchActiveSession((session) =>
      appendSessionMessage(session, {
        role: kind === "error" ? "system" : "agent",
        content: content.trim(),
        kind,
        meta,
      }),
    );
  };

  const retryPreviewTasks = useMemo(() => {
    if (!retryFailedDraft) return [] as ImageTask[];
    return pickFailedTasksByScope(
      retryableFailedTasks,
      retryFailedDraft.mode,
      retryFailedDraft.recentCount,
      maxBatchTasks,
    );
  }, [maxBatchTasks, retryFailedDraft, retryableFailedTasks]);

  const confirmRetryFailedTasks = async () => {
    if (!retryFailedDraft) return;
    const sources = pickFailedTasksByScope(
      retryableFailedTasks,
      retryFailedDraft.mode,
      retryFailedDraft.recentCount,
      maxBatchTasks,
    );
    if (!sources.length) {
      setError("当前范围没有失败任务");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      const scopeLabel =
        retryFailedDraft.mode === "recent_batch"
          ? `最近一批（${sources.length} 条）`
          : `最近 ${sources.length} 条`;
      setNotice(`正在重试${scopeLabel}失败任务…`);
      setAgentPlan({
        intent: "retry_failed",
        summary: `确认范围：${scopeLabel}`,
        prompts: sources.map((task) => task.prompt),
      });
      const modelHint = extractModelHintFromText(retryFailedDraft.sourceText || prompt);
      const overrideModel = matchModelByHint(models, modelHint);
      if (overrideModel) {
        setSelectedModelId(overrideModel.id);
      }
      const created = await recreateTasksFromSources(
        sources,
        overrideModel ? { modelId: overrideModel.id } : undefined,
      );
      setNotice(
        `已重新提交 ${created.length} 个失败任务（${scopeLabel}${
          overrideModel ? ` · 模型 ${overrideModel.name}` : " · 沿用历史任务模型"
        }）`,
      );
      setRetryFailedDraft(null);
      setPrompt("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const estimateTotalCredit = async (
    modelId: number,
    workType: string,
    res: string,
    ratio: string,
    count: number,
    dur?: string,
  ) => {
    if (count <= 0) return null;
    try {
      const unit = await modelService.quote(modelId, workType, res, ratio, 1, dur);
      const cost = Number(unit.credit_cost);
      if (Number.isNaN(cost)) return null;
      return cost * count;
    } catch {
      return null;
    }
  };

  const executePromptBatch = async (input: {
    prompts: string[];
    model: ImageModel;
    resolution: string;
    aspectRatio: string;
    duration?: string;
    assets: ImageAsset[];
    /** Parallel to prompts: each task uses its own input assets (material library redraw). */
    perTaskAssets?: ImageAsset[][];
    workType: string;
    plan?: AgentPlan | null;
  }) => {
    const promptsToRun = [...input.prompts].map((item) => item.trim()).filter(Boolean);
    if (!promptsToRun.length) throw new Error("没有可执行的提示词");

    let created: ImageTask[] = [];
    const batchId = `batch-${crypto.randomUUID()}`;
    const isVideoWork = isVideoWorkType(input.workType) || media === "video";
    const perTask =
      input.perTaskAssets && input.perTaskAssets.length
        ? input.perTaskAssets.slice(0, promptsToRun.length)
        : null;

    if (perTask && perTask.length === promptsToRun.length) {
      for (let i = 0; i < promptsToRun.length; i += 1) {
        const item = promptsToRun[i];
        const assets = perTask[i]?.length ? perTask[i] : input.assets;
        const task = await imageTaskService.createTask(
          {
            work_type: input.workType,
            batch_id: batchId,
            model_id: input.model.id,
            prompt: item,
            resolution: input.resolution,
            aspect_ratio: input.aspectRatio,
            duration: isVideoWork ? input.duration : undefined,
            input_image_ids: assets.map((asset) => asset.id),
            output_count: 1,
          },
          assets,
        );
        created.push(task);
      }
    } else if (promptsToRun.length === 1) {
      const task = await imageTaskService.createTask(
        {
          work_type: input.workType,
          batch_id: batchId,
          model_id: input.model.id,
          prompt: promptsToRun[0],
          resolution: input.resolution,
          aspect_ratio: input.aspectRatio,
          duration: isVideoWork ? input.duration : undefined,
          input_image_ids: input.assets.map((asset) => asset.id),
          output_count: 1,
        },
        input.assets,
      );
      created = [task];
    } else if (!isVideoWork && input.assets.length === 0) {
      for (let start = 0; start < promptsToRun.length; start += maxBatchTasks) {
        const promptGroup = promptsToRun.slice(start, start + maxBatchTasks);
        const batchCreated = await imageTaskService.createBatchTasks(
          {
            work_type: "batch_generate",
            batch_id: batchId,
            model_id: input.model.id,
            prompt: promptGroup.join("\n"),
            resolution: input.resolution,
            aspect_ratio: input.aspectRatio,
            input_image_ids: [],
            output_count: 1,
          },
          [],
        );
        created.push(...batchCreated);
      }
    } else {
      for (const item of promptsToRun) {
        const task = await imageTaskService.createTask(
          {
            work_type: input.workType,
            batch_id: batchId,
            model_id: input.model.id,
            prompt: item,
            resolution: input.resolution,
            aspect_ratio: input.aspectRatio,
            duration: isVideoWork ? input.duration : undefined,
            input_image_ids: input.assets.map((asset) => asset.id),
            output_count: 1,
          },
          input.assets,
        );
        created.push(task);
      }
    }

    setTasks((current) => [...created, ...current]);
    setSelectedTaskId(created[0]?.id ?? null);
    // The task payload already contains these asset IDs. Start the next creation
    // from a clean compose state only after every task has been accepted.
    setUploadedAssets([]);
    setIsAttachmentTrayOpen(false);
    setPrompt("");
    setAgentPlanPrompt(null);
    setAgentPlan(null);
    if (isAgentMode && created.length) {
      const ids = created.map((item) => item.id);
      patchActiveSession((session) => {
        let next = bindTasksToSession(session, ids);
        next = { ...next, draftPrompt: "" };
        next = appendSessionMessage(next, {
          role: "agent",
          content:
            created.length > 1
              ? `已提交 ${created.length} 个任务到本会话${input.plan ? `（${intentLabel(input.plan.intent)}）` : ""}`
              : "已提交生成任务到本会话",
          kind: "confirm",
          meta: { taskIds: ids, promptCount: created.length, planIntent: input.plan?.intent },
        });
        return next;
      });
    }
    setNotice(
      created.length > 1
        ? `已提交 ${created.length} 个任务${input.plan ? `（${intentLabel(input.plan.intent)}）` : ""}${isAgentMode ? " · 已绑定当前会话" : ""}`
        : isAgentMode
          ? "Agent 已提交生成任务（绑定当前会话）…"
          : "已提交，正在生成…",
    );
    notifyCreditBalanceChanged();
    feedRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    return created;
  };

  const cancelPendingExecution = () => {
    setPendingExecution(null);
    setPendingQuoteLoading(false);
    setNotice("已取消本次计划");
  };

  const confirmPendingExecution = async () => {
    if (!pendingExecution || isSubmitting) return;
    const model = models.find((item) => item.id === pendingExecution.modelId);
    if (!model) {
      setError("计划中的模型不可用，请重新规划");
      return;
    }
    const prompts = pendingExecution.prompts.map((item) => item.trim()).filter(Boolean);
    if (!prompts.length) {
      setError("分镜提示词不能为空，请至少保留 1 条");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      setNotice(
        prompts.length > 1
          ? `确认执行：正在提交 ${prompts.length} 条任务…`
          : "确认执行：正在提交任务…",
      );
      await executePromptBatch({
        prompts,
        model,
        resolution: pendingExecution.resolution,
        aspectRatio: pendingExecution.aspectRatio,
        duration: pendingExecution.duration,
        assets: pendingExecution.inputAssets,
        perTaskAssets: pendingExecution.perTaskAssets,
        workType: pendingExecution.workType,
        plan: pendingExecution.plan,
      });
      setPendingExecution(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务提交失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const buildPendingFromPlan = async (input: {
    source: PendingExecution["source"];
    plan: AgentPlan | null;
    prompts: string[];
    model: ImageModel;
    resolution: string;
    aspectRatio: string;
    duration?: string;
    assets: ImageAsset[];
    perTaskAssets?: ImageAsset[][];
    workType: string;
    useCaseLabel?: string | null;
    optimizePrompt: boolean;
    materialBatch?: PendingExecution["materialBatch"];
  }) => {
    setPendingQuoteLoading(true);
    try {
      const estimatedCredit = await estimateTotalCredit(
        input.model.id,
        input.workType,
        input.resolution,
        input.aspectRatio,
        input.prompts.length,
        input.duration,
      );
      const summary = summarizePlanForConfirm({
        intentLabel: input.plan ? intentLabel(input.plan.intent) : input.source === "direct_bulk" ? "批量生成" : "生成",
        modelName: input.model.name,
        promptCount: input.prompts.length,
        aspectRatio: input.aspectRatio,
        resolution: input.resolution,
        optimizePrompt: input.optimizePrompt,
        useCaseLabel: input.useCaseLabel,
        estimatedCredit,
        needsImages: Boolean(input.plan?.needs_images || input.perTaskAssets?.length),
      });
      const pending: PendingExecution = {
        source: input.source,
        plan: input.plan,
        prompts: input.prompts,
        modelId: input.model.id,
        modelName: input.model.name,
        resolution: input.resolution,
        aspectRatio: input.aspectRatio,
        duration: input.duration,
        workType: input.workType,
        inputAssets: input.assets,
        perTaskAssets: input.perTaskAssets,
        estimatedCredit,
        useCaseLabel: input.useCaseLabel,
        optimizePrompt: input.optimizePrompt,
        summary,
        materialBatch: input.materialBatch ?? null,
      };
      setPendingExecution(pending);
      const readyMsg =
        input.source === "agent"
          ? `计划已就绪，请确认后生成（${input.prompts.length} 条${estimatedCredit != null ? ` · 约 ${formatCredit(estimatedCredit)} 积分` : ""}）`
          : `批量任务需确认：${input.prompts.length} 条${estimatedCredit != null ? ` · 约 ${formatCredit(estimatedCredit)} 积分` : ""}`;
      setNotice(readyMsg);
      if (isAgentMode) {
        pushAgentMessage(
          `${input.plan?.summary || readyMsg} · 分镜 ${input.prompts.length} 条 · ${input.model.name}`,
          "plan",
          {
            planIntent: input.plan?.intent,
            promptCount: input.prompts.length,
          },
        );
        patchActiveSession((session) => ({
          ...session,
          lastPlanSummary: (input.plan?.summary || readyMsg).slice(0, 500),
        }));
      }
      return pending;
    } finally {
      setPendingQuoteLoading(false);
    }
  };

  const submitTask = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!selectedModel || !resolution || !aspectRatio) return;
    if (isVideoMode && !duration) return;
    if (pendingExecution) {
      setNotice("已有待确认计划，请先确认生成或取消");
      return;
    }
    // Critical: never submit while reference images are still uploading — otherwise
    // work type falls back to text_to_image / text_to_video with empty input_image_ids.
    if (isUploading || pendingUploadPreviews.length > 0) {
      setError("参考图还在上传中，请等上传完成后再发送（避免误走文生图）");
      setNotice("上传完成后会提示「参考图已就绪」，再点生成即可走图生图");
      return;
    }

    if (needsUpload && !uploadedAssets.length) {
      setError(isVideoMode ? "图生视频请至少上传 1 张参考图" : "图生图需要至少 1 张参考图");
      return;
    }

    // Agent: material library bulk redraw (folder / keyword / recent)
    if (
      isAgentMode &&
      !agentDocumentText.trim() &&
      isMaterialLibraryBatchIntent(prompt) &&
      media === "image"
    ) {
      if (!selectedModel) {
        setError("请先选择生成模型（图生图能力）");
        return;
      }
      pushAgentIntent(prompt.trim());
      setIsSubmitting(true);
      setError(null);
      setNotice("正在从素材库解析文件夹与图片…");
      try {
        const selection = await resolveMaterialBatchSelection(prompt, maxBatchTasks);
        const editPrompt = enrichPromptWithKits(selection.intent.editPrompt);
        const prompts = buildMaterialRedrawPrompts(selection.materials, editPrompt, enrichPromptWithKits);
        const perTaskAssets = selection.assets.map((asset) => [asset]);
        let plan: AgentPlan = {
          intent: "material_library_batch",
          summary: `素材库「${selection.folderPathLabel}」批量重绘 ${selection.appliedLimit} 张${
            selection.truncated ? `（库内约 ${selection.totalAvailable} 张，已按上限截取）` : ""
          } · ${selection.intent.editPrompt.slice(0, 80)}`,
          prompts,
          optimize_prompt: false,
          needs_images: true,
          model_id: selectedModel.id,
          model_name: selectedModel.name,
          notes: selection.truncated
            ? `truncated_to_${selection.appliedLimit}_of_${selection.totalAvailable}`
            : `full_${selection.appliedLimit}`,
        };
        setAgentPlan(plan);
        setAgentPlanPrompt(prompts[0] || editPrompt);
        setUploadedAssets(selection.assets.slice(0, Math.min(4, selection.assets.length)));
        // Enrich plan summary for session message (buildPendingFromPlan logs it).
        plan = {
          ...plan,
          summary:
            `已从「${selection.folderPathLabel}」载入 ${selection.appliedLimit} 张准备重绘` +
            (selection.truncated ? `（库内约 ${selection.totalAvailable}，上限 ${maxBatchTasks}）` : "") +
            ` · ${selection.intent.editPrompt.slice(0, 100)}`,
        };
        setAgentPlan(plan);
        await buildPendingFromPlan({
          source: "agent",
          plan,
          prompts,
          model: selectedModel,
          resolution,
          aspectRatio,
          assets: selection.assets.slice(0, 1),
          perTaskAssets,
          workType: "image_to_image",
          useCaseLabel: "素材库批量重绘",
          optimizePrompt: false,
          materialBatch: {
            folderLabel: selection.folderPathLabel,
            totalAvailable: selection.totalAvailable,
            selectedCount: selection.appliedLimit,
            thumbUrls: selection.assets.slice(0, 8).map((a) => a.url),
            editPrompt: selection.intent.editPrompt,
          },
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "素材库批量计划失败");
        setNotice(null);
      } finally {
        setIsSubmitting(false);
      }
      return;
    }

    const hasIntent = Boolean(prompt.trim() || agentDocumentText.trim());
    if (!hasIntent) {
      setError(isAgentMode ? "请描述创作意图，或上传文档（TXT/MD/PDF/DOCX 等）；失败任务可说「把失败的重新生成」" : "请输入提示词");
      return;
    }
    if (isAgentMode && !selectedTextModelId) {
      setError("Agent 模式请先选择文本模型");
      return;
    }
    const limit = maxInputImages || DEFAULT_MAX_INPUT_IMAGES;
    if (uploadedAssets.length > limit) {
      setError(`当前模型最多支持 ${limit} 张输入图`);
      return;
    }

    setIsSubmitting(true);
    setError(null);
    try {
      let promptsToRun: string[] = [prompt.trim()].filter(Boolean);
      let plan: AgentPlan | null = null;
      let generationModel = selectedModel;
      let generationResolution = resolution;
      let generationAspectRatio = aspectRatio;
      let generationDuration = duration;
      let useCaseLabel: string | null = null;
      let optimizePrompt = false;

      const intentCorpus = [prompt, agentDocumentText].filter(Boolean).join("\n");
      pushAgentIntent(prompt.trim());

      // Sprint B: multi-turn follow-up local fast path ("刚才那张再暗一点")
      let followUpApplied = false;
      let workingAssets = uploadedAssets;
      let workingPrompt = prompt.trim();

      // Brand logo auto-reference when规范 enabled
      if (brandKit.enabled && brandLogoAsImageAsset) {
        workingAssets = mergeBrandLogoAsset(
          workingAssets,
          brandKit,
          brandLogoAsImageAsset,
          maxInputImages || DEFAULT_MAX_INPUT_IMAGES,
        );
      }

      if (isAgentMode && !agentDocumentText.trim() && focusTask) {
        const follow = resolveFollowUp(workingPrompt, {
          prompt: focusTask.prompt || "",
          hasOutput: Boolean(focusTask.output_images?.[0]),
        });
        if (follow) {
          followUpApplied = true;
          workingPrompt = follow.prompt;
          if (follow.needsFocusImage && focusTask.output_images?.[0]) {
            workingAssets = [focusTask.output_images[0]];
            if (brandKit.enabled && brandLogoAsImageAsset) {
              workingAssets = mergeBrandLogoAsset(
                workingAssets,
                brandKit,
                brandLogoAsImageAsset,
                maxInputImages || DEFAULT_MAX_INPUT_IMAGES,
              );
            }
            setUploadedAssets(workingAssets);
          }
          setNotice(`识别多轮续改：${follow.label}`);
        }
      }

      const styleEnrichedSeed = enrichPromptWithKits(workingPrompt);
      const contextBlock = isAgentMode
        ? buildSessionContextBlock({
            session: {
              ...activeSession,
              // Always use live UI state for the active session (including empty) to avoid cross-session ghosts.
              recentIntents: recentAgentIntents,
              documents: agentDocuments,
              styleKitIds: activeStyleKitIds,
              textModelId: selectedTextModelId,
              focusTaskId: selectedTaskId,
              draftPrompt: prompt,
            },
            focusPrompt: focusTask?.prompt,
            focusModelName: focusTask?.model_name,
            styleKitLabels: activeStyleKits.map((k) => k.label),
            brandLabel: brandKit.enabled
              ? brandKit.name || (brandKit.logoAsset ? "Logo参考" : "已开启")
              : null,
          })
        : "";

      if (isAgentMode && selectedTextModelId) {
        const planningMessage = followUpApplied ? "正在按多轮上下文整理续改要求…" : "正在识别意图、文档与参考图，规划任务…";
        setNotice(`Agent ${planningMessage}`);
        setAgentPlanningStatus(planningMessage);
        setIsPlanningAgent(true);
        try {
          plan = await promptService.agentPlanStream({

            modelId: selectedTextModelId,
            prompt: workingPrompt,
            sessionContext: contextBlock,
            documentText: agentDocumentText,
            media,
            hasImages: workingAssets.length > 0,
            maxPrompts: agentDocumentText.trim() ? DOCUMENT_PLAN_MAX_PROMPTS : maxBatchTasks,
            availableModels: models.map((item) => ({
              id: item.id,
              name: item.name,
              code: item.code,
              work_type: item.work_type,
              capability_type: item.capability_type,
              description: item.description,
            })),
          }, {
            onStatus: (message) => {
              setAgentPlanningStatus(message);
              setNotice(`Agent ${message}`);
            },
          });
          setAgentPlanningStatus("计划已返回，正在匹配模型与生成参数…");
          setAgentPlan(plan);
          if (!plan) {
            throw new Error("Agent 未返回计划");
          }
          const resolvedPlan = plan;
          if (resolvedPlan.intent === "delete_tasks") {
            const limit = Math.max(1, Math.min(maxBatchTasks, Number(resolvedPlan.delete_query?.limit) || maxBatchTasks));
            const candidates = failedTasks.slice(0, limit);
            if (!candidates.length) throw new Error("当前范围没有失败任务可删除。");
            setDeleteTaskIds(candidates.map((task) => task.id));
            setAgentPlan(null);
            setAgentPlanPrompt(null);
            setNotice(`已定位 ${candidates.length} 条失败任务，确认后将逻辑删除。`);
            return;
          }
          if (resolvedPlan.intent === "retry_failed") {
            if (!retryableFailedTasks.length) {
              throw new Error("没有可自动重试的失败任务；内容策略拦截需要先修改提示词，不能原样重提。");
            }
            const retryQuery = resolvedPlan.retry_query;
            setRetryFailedDraft({
              mode: retryQuery?.scope === "recent_n" ? "recent_n" : "recent_batch",
              recentCount: Math.max(1, Math.min(maxBatchTasks, Number(retryQuery?.limit) || maxBatchTasks)),
              sourceText: workingPrompt,
            });
            setAgentPlan(null);
            setAgentPlanPrompt(null);
            setNotice("已定位失败任务，请核对真实任务列表后确认重新提交。");
            return;
          }
          if (resolvedPlan.intent === "query_own_creation_history") {
            const reply = resolvedPlan.history_reply || "当前没有可展示的创作记录。";
            setAgentHistoryReply(reply);
            setAgentPlan(null);
            setAgentPlanPrompt(null);
            setNotice(reply);
            pushAgentMessage(reply, "notice");
            return;
          }
          if (resolvedPlan.intent === "document_split_review") {
            setAgentPlanPrompt(null);
            throw new Error(resolvedPlan.summary || "文档未识别到可拆分的多条画面描述，未创建任务");
          }
          if (resolvedPlan.intent === "refused" || resolvedPlan.refused || (!(resolvedPlan.prompts || []).length && resolvedPlan.notes === "safety_refusal")) {
            const reason = resolvedPlan.summary || "请求超出创作范围，已拒绝";
            setAgentPlanPrompt(null);
            setNotice(null);
            throw new Error(reason);
          }

          // Layer 1: apply generation model selected by Agent (catalog match).
          let activeModel = selectedModel;
          const hinted =
            (resolvedPlan.model_id ? models.find((item) => item.id === resolvedPlan.model_id) : null) ||
            matchModelByHint(models, resolvedPlan.model_hint) ||
            matchModelByHint(models, extractModelHintFromText(prompt));
          if (hinted) {
            activeModel = hinted;
            setSelectedModelId(hinted.id);
            if (hinted.supported_resolutions?.length && !hinted.supported_resolutions.some((item) => item.value === generationResolution)) {
              generationResolution = hinted.supported_resolutions[0]?.value || generationResolution;
              setResolution(generationResolution);
            }
            if (hinted.supported_aspect_ratios?.length && !hinted.supported_aspect_ratios.some((item) => item.value === generationAspectRatio)) {
              generationAspectRatio = hinted.supported_aspect_ratios[0]?.value || generationAspectRatio;
              setAspectRatio(generationAspectRatio);
            }
            if (
              isVideoMode &&
              hinted.supported_durations?.length &&
              !hinted.supported_durations.some((item) => item.value === generationDuration)
            ) {
              generationDuration = hinted.supported_durations[0]?.value || generationDuration;
              setDuration(generationDuration);
            }
          } else if (resolvedPlan.model_hint) {
            setNotice(`未在当前列表找到模型「${resolvedPlan.model_hint}」，将使用 ${selectedModel?.name || "当前模型"}`);
          }

          // Layer 2: image-edit requires reference images.
          if (resolvedPlan.needs_images && !workingAssets.length) {
            throw new Error("该任务需要参考图，请先上传图片或选中一张已生成结果后再试");
          }

          promptsToRun = (resolvedPlan.prompts || []).map((item) => item.trim()).filter(Boolean);
          optimizePrompt = Boolean(resolvedPlan.optimize_prompt);

          const requestedTaskCount = Number(resolvedPlan.task_count || promptsToRun.length);
          if (resolvedPlan.reuse_prompt && promptsToRun.length === 1 && Number.isFinite(requestedTaskCount)) {
            promptsToRun = Array.from(
              { length: Math.max(1, Math.min(maxBatchTasks, Math.floor(requestedTaskCount))) },
              () => promptsToRun[0],
            );
          }

          if (followUpApplied && (!promptsToRun.length || (promptsToRun.length === 1 && promptsToRun[0].length < 8))) {
            promptsToRun = [styleEnrichedSeed || workingPrompt];
          }

          if (activeStyleKits.length || brandKit.enabled) {
            promptsToRun = promptsToRun.map((item) => enrichPromptWithKits(item));
          }

          // Commercial variant matrix (e.g. 出一套电商图 / 3个构图)
          const matrix = expandVariantMatrix(intentCorpus, promptsToRun[0] || workingPrompt, maxBatchTasks);
          if (matrix && matrix.length > promptsToRun.length) {
            promptsToRun = matrix;
            if (plan) {
              plan = { ...plan, prompts: matrix, summary: `${plan.summary || ""}${plan.summary ? " · " : ""}已扩展商业变体 ${matrix.length} 条`.trim() };
              setAgentPlan(plan);
            }
          }

          // Use-case → preferred aspect / resolution
          const useCase = detectUseCase(intentCorpus);
          if (useCase) {
            useCaseLabel = useCase.label;
            generationAspectRatio = pickClosestAspectRatio(activeModel, useCase.aspectRatio, generationAspectRatio);
            generationResolution = pickPreferredResolution(activeModel, useCase.resolutionPrefer, generationResolution);
            setAspectRatio(generationAspectRatio);
            setResolution(generationResolution);
          }

          setAgentPlanPrompt(promptsToRun.join("\n"));
          if (promptsToRun.length === 1) {
            setPrompt(promptsToRun[0]);
          }
          generationModel = activeModel || generationModel;
        } finally {
          setIsPlanningAgent(false);
        }
      } else {
        setAgentPlan(null);
        setAgentPlanPrompt(null);
        // Direct mode sends the complete prompt verbatim as one generation task.
        // Newlines are prompt structure, not an implicit request for a batch.
        const useCase = detectUseCase(prompt);
        if (useCase) {
          useCaseLabel = useCase.label;
          generationAspectRatio = pickClosestAspectRatio(selectedModel, useCase.aspectRatio, generationAspectRatio);
          generationResolution = pickPreferredResolution(selectedModel, useCase.resolutionPrefer, generationResolution);
          setAspectRatio(generationAspectRatio);
          setResolution(generationResolution);
        }
      }

      if (!generationModel) {
        throw new Error("请先选择生成模型");
      }
      if (!promptsToRun.length) {
        throw new Error(isAgentMode ? "Agent 未产出可用提示词" : "请输入提示词");
      }
      const assetsForRun = workingAssets.length ? workingAssets : uploadedAssets;
      const nextWorkType = resolveWorkType(media, assetsForRun.length > 0);
      const needsConfirm = isAgentMode || promptsToRun.length >= BULK_CONFIRM_THRESHOLD;

      if (!isAgentMode && (activeStyleKits.length || brandKit.enabled)) {
        promptsToRun = promptsToRun.map((item) => enrichPromptWithKits(item));
      }

      if (needsConfirm) {
        // Planning phase only — never auto execute for Agent / large bulk
        setIsSubmitting(false);
        await buildPendingFromPlan({
          source: isAgentMode ? "agent" : "direct_bulk",
          plan,
          prompts: promptsToRun,
          model: generationModel,
          resolution: generationResolution,
          aspectRatio: generationAspectRatio,
          duration: isVideoMode ? generationDuration : undefined,
          assets: assetsForRun,
          workType: nextWorkType,
          useCaseLabel: useCaseLabel || (activeStyleKits[0]?.label ?? null),
          optimizePrompt,
        });
        return;
      }

      await executePromptBatch({
        prompts: promptsToRun,
        model: generationModel,
        resolution: generationResolution,
        aspectRatio: generationAspectRatio,
        duration: isVideoMode ? generationDuration : undefined,
        assets: assetsForRun,
        workType: nextWorkType,
        plan,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "任务提交失败");
    } finally {
      setIsSubmitting(false);
      setIsPlanningAgent(false);
      setAgentPlanningStatus(null);
    }
  };

  const onPromptKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void submitTask();
    }
  };

  const switchMedia = (next: ImagineMediaKind) => {
    if (next === media) return;
    setMedia(next);
    setOpenMenu(null);
    // Stay on the new Imagine page; only update query-friendly path under /create/imagine
    navigate(next === "video" ? "/create/imagine?media=video" : "/create/imagine", { replace: true });
  };

  const materialBatchReady =
    isAgentMode &&
    media === "image" &&
    !agentDocumentText.trim() &&
    isMaterialLibraryBatchIntent(prompt);
  const multiTurnReady =
    isAgentMode &&
    Boolean(focusTask) &&
    !agentDocumentText.trim() &&
    isFollowUpIntent(prompt);
  const canSubmit =
    Boolean(
      selectedModel && resolution && aspectRatio && !isSubmitting && !isPlanningAgent && !isParsingDocument && !isLoadingModels && !pendingQuoteLoading && !isUploading,
    ) &&
    Boolean(
        prompt.trim() ||
        (isAgentMode && agentDocumentText.trim()) ||
        materialBatchReady,
    ) &&
    (!isVideoMode ||
      Boolean(duration) ||
      multiTurnReady ||
      materialBatchReady) &&
    (!isAgentMode ||
      Boolean(selectedTextModelId) ||
      multiTurnReady ||
      materialBatchReady) &&
    !pendingExecution &&
    !isSubmitting &&
    !isUploading &&
    pendingUploadPreviews.length === 0;


  const heroOutput = selectedTask?.output_images[0] ?? null;
  const isBusy = selectedTask ? BUSY_TASK_STATUSES.has(selectedTask.status) : false;
  const previewTask = previewAsset
    ? tasks.find((task) => task.output_images.some((asset) => asset.url === previewAsset.url)) ?? selectedTask
    : null;
  const previewScopeTasks = useMemo(() => {
    if (!previewAsset) return [];
    const visibleTasksWithResults = filteredTasks.filter((task) => task.output_images.length > 0);
    const currentIsVisible = visibleTasksWithResults.some((task) =>
      task.output_images.some((asset) => asset.url === previewAsset.url),
    );
    return currentIsVisible
      ? visibleTasksWithResults
      : tasks.filter((task) => task.output_images.length > 0);
  }, [filteredTasks, previewAsset, tasks]);
  const previewAssets = useMemo(
    () => previewScopeTasks.flatMap((task) => task.output_images),
    [previewScopeTasks],
  );
  const previewAssetIndex = previewAssets.findIndex((asset) => asset.url === previewAsset?.url);
  const previewThumbnailEntries = useMemo(() => {
    if (!previewAssets.length) return [];
    const center = Math.max(0, previewAssetIndex);
    const start = Math.max(0, center - PREVIEW_THUMBNAIL_RADIUS);
    const end = Math.min(previewAssets.length, center + PREVIEW_THUMBNAIL_RADIUS + 1);
    return previewAssets.slice(start, end).map((asset, offset) => ({ asset, index: start + offset }));
  }, [previewAssetIndex, previewAssets]);
  const openPreviewAsset = useCallback((asset: ImageAsset) => {
    setPreviewSourceAsset(null);
    setPreviewAsset(asset);
    const ownerTask = tasks.find((task) => task.output_images.some((output) => output.url === asset.url));
    if (ownerTask) setSelectedTaskId(ownerTask.id);
  }, [tasks]);
  const selectPreviewOffset = (offset: number) => {
    if (previewAssets.length < 2 || previewAssetIndex < 0) return;
    const nextIndex = (previewAssetIndex + offset + previewAssets.length) % previewAssets.length;
    openPreviewAsset(previewAssets[nextIndex]);
  };

  const downloadPreviewAsset = async () => {
    if (!previewAsset || isDownloadingPreview) return;
    setIsDownloadingPreview(true);
    setError(null);
    setNotice("正在准备下载…");
    try {
      await downloadMedia(previewAsset.url, "image2ai-preview", previewAsset.mime_type);
      setNotice("下载已开始，请在浏览器下载记录中查看");
    } catch (downloadError) {
      setNotice(null);
      setError(downloadError instanceof Error ? downloadError.message : "下载失败");
    } finally {
      setIsDownloadingPreview(false);
    }
  };

  useEffect(() => {
    if (!previewAsset || previewAssets.length < 2) return;
    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        const nextIndex = (previewAssetIndex - 1 + previewAssets.length) % previewAssets.length;
        openPreviewAsset(previewAssets[nextIndex]);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        const nextIndex = (previewAssetIndex + 1) % previewAssets.length;
        openPreviewAsset(previewAssets[nextIndex]);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [openPreviewAsset, previewAsset, previewAssets, previewAssetIndex]);

  const ratioOptions = selectedModel?.supported_aspect_ratios ?? [];
  const resolutionOptions = selectedModel?.supported_resolutions ?? [];
  const durationOptions = selectedModel?.supported_durations ?? [];

  const selectGenerationModel = (nextModel: ImageModel) => {
    const supportsResolution = nextModel.supported_resolutions.some((option) => option.value === resolution);
    const supportsAspectRatio = nextModel.supported_aspect_ratios.some((option) => option.value === aspectRatio);
    const supportsDuration = nextModel.supported_durations?.some((option) => option.value === duration) ?? !isVideoMode;
    const nextResolution = supportsResolution ? resolution : nextModel.supported_resolutions[0]?.value ?? "";
    const nextAspectRatio = supportsAspectRatio ? aspectRatio : nextModel.supported_aspect_ratios[0]?.value ?? "";
    const nextDuration = supportsDuration ? duration : nextModel.supported_durations?.[0]?.value ?? "";
    const adjustedFields = [
      nextResolution !== resolution ? "清晰度" : "",
      nextAspectRatio !== aspectRatio ? "画幅" : "",
      isVideoMode && nextDuration !== duration ? "时长" : "",
    ].filter(Boolean);

    setSelectedModelId(nextModel.id);
    setResolution(nextResolution);
    setAspectRatio(nextAspectRatio);
    setDuration(nextDuration);
    setOpenMenu(null);
    const imageLimitExceeded = uploadedAssets.length > nextModel.max_input_images;
    if (adjustedFields.length || imageLimitExceeded) {
      const messages = [
        adjustedFields.length ? `已调整${adjustedFields.join("、")}以兼容该模型` : "",
        imageLimitExceeded ? `当前 ${uploadedAssets.length} 张参考图超过该模型的 ${nextModel.max_input_images} 张上限` : "",
      ].filter(Boolean);
      setNotice(`已切换至 ${nextModel.name}，${messages.join("；")}`);
    }
  };

  return (
    <main className="gi-page">
      <div className="gi-ambient" aria-hidden />

      {/* Top brand strip — minimal like Grok */}
      <header className="gi-top">
        <div className="gi-brand">
          {isAgentMode ? <Bot size={16} /> : <Sparkles size={16} />}
          <span>{isAgentMode ? "Imagine Agent" : "Imagine"}</span>
        </div>
        {isAgentMode ? (
          <div className="gi-session-bar" aria-label="Agent 会话">
            <button
              type="button"
              className={`gi-session-bar__current ${showSessionPanel ? "is-open" : ""}`}
              onClick={() => {
                setShowSessionPanel((open) => !open);
                setIsSessionThreadOpen(false);
              }}
              title="切换会话 · 会话间上下文隔离"
            >
              <History size={14} />
              <span className="gi-session-bar__title">{activeSession.title}</span>
              <em>{activeSession.messages.length} 轮 · {activeSession.taskIds.length} 任务</em>
              <ChevronDown size={14} />
            </button>
            <button type="button" className="gi-session-bar__new" onClick={createAgentSession} title="新建会话">
              <Plus size={14} />
              新会话
            </button>
            <button
              type="button"
              className={`gi-session-bar__context ${isSessionThreadOpen ? "is-open" : ""}`}
              onClick={() => {
                setIsSessionThreadOpen((open) => !open);
                setShowSessionPanel(false);
                setShowAllSessionMessages(false);
              }}
              aria-expanded={isSessionThreadOpen}
              title="查看当前会话的上下文记录"
            >
              <MessageSquare size={14} />
              上下文
            </button>
            <label
              className={`gi-session-bar__scope ${sessionFeedOnly ? "is-on" : ""}`}
              title={sessionFeedOnly ? "结果流仅显示本会话绑定任务" : "结果流显示账号全部历史（对话上下文仍仅本会话）"}
            >
              <input
                type="checkbox"
                checked={sessionFeedOnly}
                onChange={(e) => setSessionFeedOnly(e.target.checked)}
              />
              {sessionFeedOnly ? "仅本会话" : "全部历史"}
            </label>
          </div>
        ) : null}
        <div className="gi-top__meta">
          {selectedModel ? <span className="gi-chip-soft">{selectedModel.name}</span> : null}
          {activeStyleKits.length ? (
            <span className="gi-chip-soft">风格 {activeStyleKits.map((k) => k.short).join("·")}</span>
          ) : null}
          {brandKit.enabled ? (
            <span className="gi-chip-soft" title={brandKit.name || "品牌规范"}>
              品牌 {brandKit.name || "规范开"}
            </span>
          ) : null}
          {isAgentMode && focusTask?.status === "succeeded" ? (
            <span className="gi-chip-soft" title="多轮续改将基于此结果">续改焦点就绪</span>
          ) : null}
          {pendingExecution?.estimatedCredit != null ? (
            <span className="gi-chip-soft gi-chip-soft--cost">
              计划约 {formatCredit(pendingExecution.estimatedCredit)} 积分
            </span>
          ) : quote !== null ? (
            <span className="gi-chip-soft gi-chip-soft--cost">{quote} 积分/条</span>
          ) : null}
        </div>
      </header>

      {(error || notice) && (
        <div className={`gi-toast ${error ? "is-error" : "is-ok"}`} role="status">
          {error ?? notice}
        </div>
      )}

      {isAgentMode && showSessionPanel ? (
        <div className="gi-session-panel" role="dialog" aria-label="会话列表">
          <div className="gi-session-panel__head">
            <strong>
              <MessageSquare size={14} style={{ marginRight: 6, verticalAlign: "-2px" }} />
              Agent 会话
            </strong>
            <span>每个会话独立：对话 / 文档 / 草稿 / 风格包 / 任务绑定；传给 Agent 仅当前会话</span>
            <button type="button" className="gi-session-panel__close" onClick={() => setShowSessionPanel(false)}>
              <X size={14} />
            </button>
          </div>
          <div className="gi-session-panel__actions">
            <Button type="button" onClick={createAgentSession}>
              <Plus size={14} /> 新建会话
            </Button>
          </div>
          <ul className="gi-session-list">
            {sessionStore.sessions.map((session) => {
              const active = session.id === activeSession.id;
              return (
                <li key={session.id} className={active ? "is-active" : ""}>
                  <button type="button" className="gi-session-list__main" onClick={() => switchAgentSession(session.id)}>
                    <strong>{session.title}</strong>
                    <em>
                      {formatSessionTime(session.updatedAt)} · {session.messages.length} 轮 · {session.taskIds.length}{" "}
                      任务
                      {session.documents.length ? ` · 文档 ${session.documents.length}` : ""}
                    </em>
                  </button>
                  <button
                    type="button"
                    className="gi-session-list__del"
                    title="删除会话"
                    onClick={() => {
                      if (sessionStore.sessions.length <= 1) {
                        setNotice("至少保留一个会话");
                        return;
                      }
                      if (window.confirm(`删除会话「${session.title}」？仅清除本地会话上下文，不会删除已生成素材文件。`)) {
                        removeAgentSession(session.id);
                      }
                    }}
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}

      {isAgentMode && isSessionThreadOpen ? (
        <div className="gi-session-thread" aria-label="当前会话上下文">
          <div className="gi-session-thread__head">
            {editingSessionTitle ? (
              <form
                className="gi-session-thread__rename"
                onSubmit={(e) => {
                  e.preventDefault();
                  commitSessionTitle();
                }}
              >
                <input
                  value={sessionTitleDraft}
                  onChange={(e) => setSessionTitleDraft(e.target.value)}
                  maxLength={40}
                  autoFocus
                  onBlur={commitSessionTitle}
                />
              </form>
            ) : (
              <button
                type="button"
                className="gi-session-thread__title"
                onClick={() => {
                  setSessionTitleDraft(activeSession.title);
                  setEditingSessionTitle(true);
                }}
                title="重命名会话"
              >
                {activeSession.title}
              </button>
            )}
            <span>
              隔离：意图 / 文档 / 草稿 / 风格包 / 焦点
              {sessionFeedOnly ? " · 结果仅本会话" : " · 结果看全部历史（上下文仍不串）"}
            </span>
            {activeSession.messages.length > 6 ? (
              <button
                type="button"
                className="gi-session-thread__show-all"
                onClick={() => setShowAllSessionMessages((showAll) => !showAll)}
              >
                {showAllSessionMessages ? "仅看最近" : `查看全部 ${activeSession.messages.length} 条`}
              </button>
            ) : null}
            <button
              type="button"
              className="gi-session-thread__close"
              onClick={() => setIsSessionThreadOpen(false)}
              aria-label="关闭上下文"
              title="关闭上下文"
            >
              <X size={14} />
            </button>
          </div>
          {activeSession.messages.length ? (
            <ol className="gi-session-thread__list">
              {(showAllSessionMessages ? activeSession.messages : activeSession.messages.slice(-6)).map((msg) => (
                <li key={msg.id} className={`is-${msg.role}`}>
                  <em>{msg.role === "user" ? "你" : msg.role === "agent" ? "Agent" : "系统"}</em>
                  <p title={msg.content}>{msg.content}</p>
                </li>
              ))}
            </ol>
          ) : (
            <p className="gi-session-thread__empty">本会话还没有记录。描述意图或上传文档后，对话会留在此会话内。</p>
          )}
        </div>
      ) : null}

      {/* Main feed / canvas */}
      <section className="gi-feed" ref={feedRef} aria-label="生成结果">
        {agentScopedTasks.length ? (
          <div className="gi-batch-bar" role="status">
            <div className="gi-batch-bar__stats">
              <button type="button" className={feedFilter === "all" ? "is-active" : ""} onClick={() => setFeedFilter("all")}>
                全部 {batchStats.total}
              </button>
              <button type="button" className={feedFilter === "busy" ? "is-active" : ""} onClick={() => setFeedFilter("busy")}>
                进行中 {batchStats.busy}
              </button>
              <button type="button" className={feedFilter === "succeeded" ? "is-active" : ""} onClick={() => setFeedFilter("succeeded")}>
                成功 {batchStats.succeeded}
              </button>
              <button type="button" className={feedFilter === "failed" ? "is-active" : ""} onClick={() => setFeedFilter("failed")}>
                失败 {batchStats.failed}
              </button>
            </div>
            <div className="gi-batch-bar__actions">
              {focusTask ? (
                <span className="gi-batch-bar__focus" title={focusTask.prompt}>
                  焦点：{(focusTask.prompt || "未命名").slice(0, 18)}
                  {(focusTask.prompt || "").length > 18 ? "…" : ""}
                </span>
              ) : null}
              <button
                type="button"
                className={`gi-batch-bar__retry ${showStats ? "is-active" : ""}`}
                onClick={() => setShowStats((v) => !v)}
                title="创作统计"
              >
                <BarChart3 size={13} />
                统计
              </button>
              <button
                type="button"
                className="gi-batch-bar__retry"
                disabled={!exportableTaskIds.length || isExporting}
                onClick={() => void exportSucceededPack()}
                title={feedFilter === "succeeded" ? "导出当前筛选的成功结果" : "导出成功结果素材包"}
              >
                {isExporting ? <LoadingIndicator size={13} className="spin-icon" /> : <Package size={13} />}
                导出({exportableTaskIds.length})
              </button>
              {batchStats.failed > 0 ? (
                <button
                  type="button"
                  className="gi-batch-bar__retry"
                  disabled={isSubmitting}
                  onClick={() => void retryAllFailedInFeed()}
                >
                  <RefreshCw size={13} />
                  重试失败({Math.min(batchStats.failed, maxBatchTasks)})
                </button>
              ) : null}
            </div>
          </div>
        ) : null}

        {(agentScopedTasks.length || tasks.length) && showStats ? (
          <div className="gi-stats-panel" role="region" aria-label="创作统计">
            <div className="gi-stats-panel__head">
              <strong>
                <BarChart3 size={14} style={{ marginRight: 6, verticalAlign: "-2px" }} />
                我的创作统计
              </strong>
              <div className="gi-stats-panel__ranges">
                {(Object.keys(STATS_RANGE_LABELS) as StatsRange[]).map((range) => (
                  <button
                    key={range}
                    type="button"
                    className={statsRange === range ? "is-active" : ""}
                    onClick={() => setStatsRange(range)}
                  >
                    {STATS_RANGE_LABELS[range]}
                  </button>
                ))}
              </div>
              <button type="button" className="gi-stats-panel__close" onClick={() => setShowStats(false)} aria-label="关闭统计">
                <X size={14} />
              </button>
            </div>
            <div className="gi-stats-panel__grid">
              <div className="gi-stats-card">
                <em>总计</em>
                <strong>{creativeStats.total}</strong>
              </div>
              <div className="gi-stats-card is-ok">
                <em>成功</em>
                <strong>{creativeStats.succeeded}</strong>
              </div>
              <div className="gi-stats-card is-bad">
                <em>失败</em>
                <strong>{creativeStats.failed}</strong>
              </div>
              <div className="gi-stats-card">
                <em>进行中</em>
                <strong>{creativeStats.busy}</strong>
              </div>
              <div className="gi-stats-card">
                <em>成功率</em>
                <strong>{creativeStats.finished ? `${creativeStats.successRate}%` : "—"}</strong>
              </div>
              <div className="gi-stats-card">
                <em>图 / 视频</em>
                <strong>
                  {creativeStats.imageCount}
                  <span className="gi-stats-card__sep">/</span>
                  {creativeStats.videoCount}
                </strong>
              </div>
            </div>
            {creativeStats.byModel.length ? (
              <div className="gi-stats-models">
                <span className="gi-stats-models__label">按模型</span>
                <ul>
                  {creativeStats.byModel.slice(0, 8).map((row) => (
                    <li key={row.name}>
                      <span title={row.name}>{row.name}</span>
                      <em>
                        {row.succeeded}/{row.total}
                        {row.failed ? ` · 失败 ${row.failed}` : ""}
                      </em>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="gi-stats-panel__empty">该时间范围内暂无记录</p>
            )}
          </div>
        ) : null}
        {!agentScopedTasks.length ? (
          <div className="gi-empty">
            <div className="gi-empty__orb">
              <Sparkles size={28} />
            </div>
            <h1>{isAgentMode ? "Agent Imagine" : "Imagine anything"}</h1>
            <p>
              {isAgentMode
                ? sessionFeedOnly
                  ? "当前会话还没有绑定任务。描述意图开始创作；切换会话不会带上其他会话上下文。"
                  : "用自然语言描述意图，Agent 会先用文本模型构思提示词，再调用生成模型完成创作"
                : mediaMeta[media].hint}
            </p>
            {isAgentMode ? (
              <div className="gi-agent-starters" aria-label="常用创作任务">
                <div className="gi-agent-starters__head">
                  <strong>从一个任务开始</strong>
                  <span>描述需求后，Agent 会先给出可编辑的生成计划</span>
                </div>
                <div className="gi-agent-starters__grid">
                  {AGENT_STARTERS.filter((starter) => !starter.media || starter.media === media).map((starter) => (
                    <button
                      key={starter.id}
                      type="button"
                      className="gi-agent-starter"
                      onClick={() => {
                        if (starter.media && starter.media !== media) switchMedia(starter.media);
                        setPrompt(starter.prompt);
                        setAgentPlan(null);
                        setAgentPlanPrompt(null);
                      }}
                    >
                      <strong>{starter.label}</strong>
                      <span>{starter.description}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="gi-empty__tips">
                <span>试试：赛博朋克雨夜街头，霓虹倒影</span>
                <span>或上传参考图，描述你想改的部分</span>
              </div>
            )}
          </div>
        ) : !filteredTasks.length ? (
          <div className="gi-empty gi-empty--filter">
            <p>当前筛选下没有任务</p>
            <button type="button" className="gi-chip-action" onClick={() => setFeedFilter("all")}>
              查看全部
            </button>
          </div>
        ) : (
          <div className="gi-masonry">
            {filteredTasks.map((task) => {
              const renderNow = Date.now();
              const output = task.output_images[0];
              const active = task.id === selectedTask?.id;
              const busy = BUSY_TASK_STATUSES.has(task.status);
              const progress = busy ? estimateTaskProgress(task, renderNow) : task.status === "succeeded" ? 100 : 0;
              const progressLabel = `${Math.round(progress)}%`;
              const promptText = task.prompt || "（无提示词）";
              const promptExpanded = expandedPromptIds.includes(task.id);
              const promptCollapsible = isPromptCollapsible(task.prompt);
              const failInfo = isFailedTask(task) ? classifyFailure(task.failure_message) : null;
              const failureMessage = task.failure_message?.trim() || "生成失败，请稍后重试";
              const failureExpanded = expandedFailureIds.includes(task.id);
              const failureCollapsible = failureMessage.length > FAILURE_MESSAGE_COLLAPSE_THRESHOLD;
              return (
                <article
                  key={task.id}
                  className={`gi-card ${active ? "is-active" : ""} ${busy ? "is-busy" : ""}`}
                  onClick={() => setSelectedTaskId(task.id)}
                >
                  <div
                    className={`gi-card__media ${output ? "is-previewable" : ""}`}
                    role={output ? "button" : undefined}
                    tabIndex={output ? 0 : undefined}
                    aria-label={output ? (isVideoAsset(output) ? "预览视频" : "预览图片") : undefined}
                    onClick={(event) => {
                      if (!output) return;
                      event.stopPropagation();
                      setSelectedTaskId(task.id);
                      setPreviewAsset(output);
                    }}
                    onKeyDown={(event: ReactKeyboardEvent<HTMLDivElement>) => {
                      if (!output) return;
                      if (event.key !== "Enter" && event.key !== " ") return;
                      event.preventDefault();
                      event.stopPropagation();
                      setSelectedTaskId(task.id);
                      setPreviewAsset(output);
                    }}
                    onMouseEnter={(event) => {
                      if (!output || !isVideoAsset(output)) return;
                      const video = event.currentTarget.querySelector("video");
                      if (video) void video.play().catch(() => undefined);
                    }}
                    onMouseLeave={(event) => {
                      if (!output || !isVideoAsset(output)) return;
                      const video = event.currentTarget.querySelector("video");
                      if (!video) return;
                      video.pause();
                      video.currentTime = 0;
                    }}
                  >
                    {output ? (
                      isVideoAsset(output) ? (
                        <video
                          src={resolveAssetUrl(output.url)}
                          muted
                          playsInline
                          loop
                        />
                      ) : (
                        <img
                          src={resolveAssetUrl(getAssetPreviewSource(output))}
                          alt={task.prompt}
                          loading="lazy"
                          decoding="async"
                          fetchPriority="low"
                          onError={(event) => {
                            if (event.currentTarget.dataset.originalFallback === "true") return;
                            event.currentTarget.dataset.originalFallback = "true";
                            event.currentTarget.src = resolveAssetUrl(output.url);
                          }}
                        />
                      )
                    ) : (
                      <div className="gi-card__placeholder">
                        {busy ? <LoadingIndicator className="spin-icon" size={22} /> : <ImageIcon size={22} />}
                        <span>{getImageTaskStatusLabel(task, taskStatusCopy)}</span>
                        {busy ? <strong className="gi-card__placeholder-pct">{progressLabel}</strong> : null}
                      </div>
                    )}
                    {busy ? (
                      <div className="gi-card__progress" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)} aria-label={`${getImageTaskStatusLabel(task, taskStatusCopy)} ${progressLabel}`}>
                        <div className="gi-card__progress-meta">
                          <span>
                            {getImageTaskStatusLabel(task, taskStatusCopy)}
                            {progress >= 95 ? " · 即将完成" : ""} · {progressLabel}
                          </span>
                          <span>{formatElapsedTime(getTaskElapsedMs(task, renderNow))}</span>
                        </div>
                        <div className="gi-card__progress-track">
                          <div
                            className={`gi-card__progress-fill ${task.status === "running" ? "is-running" : "is-wait"}`}
                            style={{ width: `${Math.max(4, progress)}%` }}
                          />
                        </div>
                      </div>
                    ) : null}
                  </div>
                  <div className="gi-card__body">
                    <div className="gi-card__prompt">
                      <p className={promptExpanded ? "is-expanded" : undefined} title={promptExpanded || !promptCollapsible ? undefined : task.prompt || undefined}>
                        {promptText}
                      </p>
                      {promptCollapsible ? (
                        <button
                          type="button"
                          className="gi-card__prompt-toggle"
                          onClick={(event) => {
                            event.stopPropagation();
                            setExpandedPromptIds((current) =>
                              current.includes(task.id)
                                ? current.filter((id) => id !== task.id)
                                : [...current, task.id],
                            );
                          }}
                        >
                          {promptExpanded ? "收起" : "展开"}
                        </button>
                      ) : null}
                    </div>
                    <div className="gi-card__meta">
                      <span>{task.model_name}</span>
                      <span className="gi-card__meta-tag gi-card__meta-tag--resolution">{task.resolution || "默认清晰度"}</span>
                      {task.duration ? <span>{task.duration}s</span> : null}
                      <span>{task.aspect_ratio}</span>
                    </div>
                    {failInfo && isFailedTask(task) ? (
                      <div className="gi-card__error-block" role="alert">
                        <p className="gi-card__error-hint">
                          {failInfo.label} · {failInfo.suggestion}
                        </p>
                        <div className="gi-card__failure-reason">
                          <span className="gi-card__failure-label">失败原因</span>
                          <p className={failureExpanded ? "is-expanded" : undefined} title={failureExpanded || !failureCollapsible ? undefined : failureMessage}>
                            {failureMessage}
                          </p>
                          {failureCollapsible ? (
                            <button
                              type="button"
                              onClick={(event) => {
                                event.stopPropagation();
                                setExpandedFailureIds((current) =>
                                  current.includes(task.id)
                                    ? current.filter((id) => id !== task.id)
                                    : [...current, task.id],
                                );
                              }}
                            >
                              {failureExpanded ? "收起原因" : "查看完整原因"}
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </article>
              );
            })}
          </div>
        )}
        {tasks.length && hasMoreTasks ? (
          <div className="gi-load-more" ref={loadMoreSentinelRef}>
            <button type="button" onClick={() => void loadMoreTasks()} disabled={isLoadingMoreTasks}>
              {isLoadingMoreTasks ? <LoadingIndicator size={15} className="spin-icon" /> : <History size={15} />}
              {isLoadingMoreTasks ? "正在加载…" : "继续加载"}
            </button>
            <span>{isLoadingMoreTasks ? "正在读取更早的任务" : `下滑自动加载 · 已加载 ${tasks.length} 条`}</span>
          </div>
        ) : null}
      </section>

      {/* Floating Grok-style composer */}
      <div className="gi-dock">
        <form
          className={`gi-composer ${isDraggingAssets ? "is-dragover" : ""}`}
          onSubmit={(e) => void submitTask(e)}
          onDragEnter={onAssetDragEnter}
          onDragOver={onAssetDragOver}
          onDragLeave={onAssetDragLeave}
          onDrop={onAssetDrop}
        >
          {isDraggingAssets && canAcceptComposerDrop ? (
            <div className="gi-composer__drop-overlay" aria-hidden>
              <UploadCloud size={22} />
              <strong>{isAgentMode ? "松开即可添加文件" : "松开即可上传参考图"}</strong>
              <span>
                {isAgentMode
                  ? `文档 TXT/MD/PDF/DOCX 等（还可 ${Math.max(0, 5 - agentDocuments.length)} 个） · 参考图 JPG/PNG/WEBP（还可 ${remainingSlots} 张）`
                  : `还可添加 ${remainingSlots} 张 · JPG/PNG/WEBP · 单张 ≤10MB`}
              </span>
            </div>
          ) : null}
          {/* Attachments */}
          {(hasImagesOrPending || agentDocuments.length > 0 || isAttachmentTrayOpen) && (
            <div className={`gi-attach ${isAttachmentTrayOpen ? "is-open" : ""}`}>
              {isAgentMode
                ? agentDocuments.map((doc) => (
                    <div className="gi-thumb gi-thumb--doc" key={doc.id} title={doc.name}>
                      <div className="gi-thumb__doc">
                        <FileText size={16} />
                        <span>{doc.name}</span>
                        <em>{doc.char_count} 字</em>
                      </div>
                      <button type="button" className="gi-thumb__x" onClick={() => removeAgentDocument(doc.id)} aria-label="移除文档">
                        <X size={12} />
                      </button>
                    </div>
                  ))
                : null}
              {uploadedAssets.map((asset, index) => (
                <div className="gi-thumb" key={asset.id}>
                  <img src={resolveAssetUrl(asset.url)} alt={`参考图 ${index + 1}`} />
                  {index === 0 ? <span className="gi-thumb__badge">主图</span> : <span className="gi-thumb__badge gi-thumb__badge--ref">参考</span>}
                  <button type="button" className="gi-thumb__x" onClick={() => removeUpload(asset.id)} aria-label="移除">
                    <X size={12} />
                  </button>
                </div>
              ))}
              {pendingUploadPreviews.map((previewUrl, index) => (
                <div className="gi-thumb gi-thumb--pending" key={`pending-upload-${index}-${previewUrl}`} title="上传中…">
                  <img src={previewUrl} alt={`上传中 ${index + 1}`} />
                  <span className="gi-thumb__badge gi-thumb__badge--pending">上传中</span>
                  <div className="gi-thumb__pending-mask" aria-hidden>
                    <LoadingIndicator className="spin-icon" size={16} />
                  </div>
                </div>
              ))}
              {isAttachmentTrayOpen && remainingSlots > 0 ? (
                <>
                  <button
                    type="button"
                    className={`gi-thumb gi-thumb--add ${isDraggingAssets ? "is-dragover" : ""}`}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isUploading}
                    title="点击选择，或直接拖拽图片到此处"
                  >
                    {isUploading ? <LoadingIndicator className="spin-icon" size={16} /> : <UploadCloud size={16} />}
                    <span>{isUploading ? "上传中" : "拖拽/上传"}</span>
                  </button>
                  <button type="button" className="gi-thumb gi-thumb--add" onClick={() => setIsMaterialPickerOpen(true)}>
                    <FolderPlus size={16} />
                    <span>素材</span>
                  </button>
                </>
              ) : null}
              {isAttachmentTrayOpen && isAgentMode ? (
                <button
                  type="button"
                  className="gi-thumb gi-thumb--add"
                  onClick={() => docInputRef.current?.click()}
                  disabled={isParsingDocument || agentDocuments.length >= 5}
                  title="上传剧本/提示词文档：TXT MD PDF DOCX CSV JSON HTML RTF"
                >
                  {isParsingDocument ? <LoadingIndicator className="spin-icon" size={16} /> : <FileText size={16} />}
                  <span>文档</span>
                </button>
              ) : null}
              {hasPendingUploads ? (
                <p className="gi-attach__hint gi-attach__hint--warn">参考图上传中…完成后才会按图生图发送，请稍候</p>
              ) : null}
            </div>
          )}

          <div className={`gi-composer__advanced ${isCreativePreferencesOpen ? "is-open" : ""}`}>
          <div className="gi-style-kits" aria-label="风格包">
              <div className="gi-style-kits__head">
                <Palette size={13} />
                <strong>风格包</strong>
                <span>可多选，会注入到生成提示词</span>
                {activeStyleKitIds.length ? (
                  <button type="button" className="gi-style-kits__clear" onClick={() => setActiveStyleKitIds([])}>
                    清空
                  </button>
                ) : null}
              </div>
              <div className="gi-style-kits__list">
                {STYLE_KITS.map((kit) => {
                  const on = activeStyleKitIds.includes(kit.id);
                  return (
                    <button
                      key={kit.id}
                      type="button"
                      className={`gi-style-chip ${on ? "is-active" : ""}`}
                      title={kit.description}
                      onClick={() => toggleStyleKit(kit.id)}
                    >
                      {kit.short}
                    </button>
                  );
                })}
              </div>
            </div>

          <div className="gi-brand-kit" aria-label="品牌规范">
            <div className="gi-brand-kit__head">
              <Shield size={13} />
              <strong>品牌规范</strong>
              <span>名称 / 品牌色 / 禁词 · 开启后自动注入</span>
              <label className="gi-brand-kit__toggle">
                <input
                  type="checkbox"
                  checked={brandKit.enabled}
                  onChange={(e) => updateBrandKit({ enabled: e.target.checked })}
                />
                {brandKit.enabled ? "已开启" : "关闭"}
              </label>
              <button type="button" className="gi-style-kits__clear" onClick={() => setShowBrandKit((v) => !v)}>
                {showBrandKit ? "收起" : "编辑"}
              </button>
            </div>
            {showBrandKit ? (
              <div className="gi-brand-kit__body">
                <label>
                  <span>品牌名</span>
                  <input
                    type="text"
                    value={brandKit.name}
                    placeholder="例如：青湖旅拍"
                    maxLength={40}
                    onChange={(e) => updateBrandKit({ name: e.target.value })}
                  />
                </label>
                <label>
                  <span>品牌色</span>
                  <input
                    type="text"
                    value={brandKit.colors.join(", ")}
                    placeholder="#0EA5E9, 米白, 藏青"
                    onChange={(e) =>
                      updateBrandKit({
                        colors: e.target.value
                          .split(/[,，、]/)
                          .map((c) => c.trim())
                          .filter(Boolean)
                          .slice(0, 8),
                      })
                    }
                  />
                </label>
                <label>
                  <span>禁用词</span>
                  <input
                    type="text"
                    value={brandKit.forbiddenWords.join(", ")}
                    placeholder="低价, 竞品名, 夸张功效"
                    onChange={(e) =>
                      updateBrandKit({
                        forbiddenWords: e.target.value
                          .split(/[,，、]/)
                          .map((w) => w.trim())
                          .filter(Boolean)
                          .slice(0, 24),
                      })
                    }
                  />
                </label>
                <div className="gi-brand-kit__logo">
                  <span>品牌 Logo</span>
                  <div className="gi-brand-kit__logo-row">
                    {brandKit.logoAsset?.url || brandKit.logoUrl ? (
                      <button
                        type="button"
                        className="gi-brand-kit__logo-preview"
                        onClick={() =>
                          setPreviewAsset(
                            brandLogoAsImageAsset || {
                              id: brandKit.logoAsset?.id || 0,
                              url: brandKit.logoAsset?.url || brandKit.logoUrl || "",
                              mime_type: brandKit.logoAsset?.mime_type || "image/png",
                              size_bytes: 0,
                              sha256: "",
                              source: "upload",
                            },
                          )
                        }
                        title="预览 Logo"
                      >
                        <img src={resolveAssetUrl(brandKit.logoAsset?.url || brandKit.logoUrl || "")} alt="品牌 Logo" />
                      </button>
                    ) : (
                      <div className="gi-brand-kit__logo-empty">未上传</div>
                    )}
                    <div className="gi-brand-kit__logo-actions">
                      <button
                        type="button"
                        className="gi-style-kits__clear"
                        disabled={isUploadingBrandLogo}
                        onClick={() => brandLogoInputRef.current?.click()}
                      >
                        {isUploadingBrandLogo ? "上传中…" : brandKit.logoAsset ? "更换 Logo" : "上传 Logo"}
                      </button>
                      {brandKit.logoAsset ? (
                        <button type="button" className="gi-style-kits__clear" onClick={clearBrandLogo}>
                          移除
                        </button>
                      ) : null}
                      <em>开启规范后自动加入参考图（主体图优先）</em>
                    </div>
                  </div>
                  <input
                    ref={brandLogoInputRef}
                    type="file"
                    accept="image/*"
                    hidden
                    onChange={(e) => void uploadBrandLogo(e)}
                  />
                </div>
                <label className="gi-brand-kit__notes">
                  <span>风格备注</span>
                  <textarea
                    value={brandKit.styleNotes}
                    placeholder="例如：干净高级感，留白充足，不要夸张滤镜"
                    rows={2}
                    maxLength={240}
                    onChange={(e) => updateBrandKit({ styleNotes: e.target.value })}
                  />
                </label>
                <div className="gi-brand-kit__actions">
                  <button
                    type="button"
                    className="gi-style-kits__clear"
                    onClick={() => {
                      setBrandKit(emptyBrandKit());
                      setNotice("品牌规范已重置");
                    }}
                  >
                    重置
                  </button>
                  {brandKit.enabled ? (
                    <em>写入提示词{brandKit.logoAsset ? " · Logo 作参考图" : ""}</em>
                  ) : (
                    <em>开启后才会影响生成</em>
                  )}
                </div>
              </div>
            ) : brandKit.enabled && (brandKit.name || brandKit.colors.length || brandKit.forbiddenWords.length || brandKit.logoAsset) ? (
              <p className="gi-brand-kit__summary">
                {[
                  brandKit.name && `「${brandKit.name}」`,
                  brandKit.colors.length ? `色 ${brandKit.colors.slice(0, 3).join("/")}` : "",
                  brandKit.forbiddenWords.length ? `禁 ${brandKit.forbiddenWords.length} 词` : "",
                  brandKit.logoAsset ? "含 Logo" : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            ) : null}
          </div>
          </div>


          <div className={`gi-prompt ${isVoiceListening ? "is-listening" : ""}`}>
            {canAttachImages || isAgentMode ? (
              <button
                type="button"
                className={`gi-attach-trigger ${isAttachmentTrayOpen ? "is-open" : ""} ${hasImagesOrPending || agentDocuments.length ? "has-items" : ""} ${isDraggingAssets ? "is-dragover" : ""}`}
                onClick={() => setIsAttachmentTrayOpen((open) => !open)}
                disabled={isUploading || (!isAgentMode && remainingSlots <= 0)}
                title="添加参考图、素材或文档"
                aria-label="添加参考图、素材或文档"
              >
                <Plus size={24} strokeWidth={2} />
                <span className="gi-attach-trigger__label">
                  添加
                  {hasImagesOrPending ? ` ${uploadedAssets.length + pendingUploadPreviews.length}` : ""}
                </span>
                {hasImagesOrPending || agentDocuments.length ? (
                  <span className="gi-attach-trigger__count" aria-hidden>
                    {uploadedAssets.length + pendingUploadPreviews.length + agentDocuments.length}
                  </span>
                ) : null}
              </button>
            ) : null}
            <textarea
              ref={composerPromptRef}
              value={prompt}
              onChange={(e) => {
                setPrompt(e.target.value);
                if (agentPlanPrompt && e.target.value !== agentPlanPrompt) {
                  setAgentPlanPrompt(null);
                }
              }}
              onKeyDown={onPromptKeyDown}
              placeholder={
                isAgentMode
                  ? agentDocuments.length
                    ? "可语音或打字补充：风格、画幅偏好、角色一致性要求…"
                    : isVideoMode
                      ? hasImages
                        ? "点麦克风说出镜头/氛围意图，或上传分镜文档"
                        : "点麦克风直接说视频意图，或上传分镜/剧本"
                      : hasImages
                        ? "说意图或续改：如「背景改青海湖」；也可说「刚才那张再暗一点」"
                        : "说意图批量生图，或续改：如「刚才那张再商业一点」；可上传文档"
                  : isVideoMode
                    ? hasImages
                      ? "描述镜头运动、氛围与细节…"
                      : "描述你想生成的视频…"
                    : hasImages
                      ? "描述如何修改或延展这张图…"
                      : "描述你想生成的画面…"
              }
              rows={2}
            />
            {speechSupported ? (
              <button
                type="button"
                className={`gi-voice-btn ${isVoiceListening ? "is-listening" : ""} ${isAgentMode ? "is-agent" : ""}`}
                onClick={toggleVoiceInput}
                disabled={isSubmitting || isPlanningAgent || isParsingDocument}
                aria-pressed={isVoiceListening}
                title={
                  isVoiceListening
                    ? "停止语音输入"
                    : isAgentMode
                      ? "语音输入意图（中文）"
                      : "语音输入提示词（中文）"
                }
              >
                {isVoiceListening ? <MicOff size={16} /> : <Mic size={16} />}
                <span>{isVoiceListening ? "结束" : "语音"}</span>
              </button>
            ) : isAgentMode ? (
              <span className="gi-voice-fallback" title="当前浏览器不支持语音识别">
                语音不可用
              </span>
            ) : null}
            {isVoiceListening ? <p className="gi-voice-hint">正在聆听… 说完点「结束」</p> : null}
          </div>

          <div className="gi-toolbar">
            <div className="gi-toolbar__left">
              {/* Image | Video toggle — Grok core */}
              <div className="gi-seg" role="tablist" aria-label="媒体类型">
                <button
                  type="button"
                  role="tab"
                  aria-selected={media === "image"}
                  className={media === "image" ? "is-active" : ""}
                  onClick={() => switchMedia("image")}
                >
                  <ImageIcon size={14} />
                  图片
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={media === "video"}
                  className={media === "video" ? "is-active" : ""}
                  onClick={() => switchMedia("video")}
                >
                  <Clapperboard size={14} />
                  视频
                </button>
              </div>

              <div className="gi-seg gi-seg--mode" role="tablist" aria-label="创作模式">
                <button
                  type="button"
                  role="tab"
                  aria-selected={!isAgentMode}
                  className={!isAgentMode ? "is-active" : ""}
                  onClick={() => {
                    if (isAgentMode) {
                      // Persist current session draft/docs before leaving Agent mode.
                      const next = flushUiIntoActiveSession();
                      persistSessionStore(next);
                    }
                    setCreateMode("direct");
                    setPendingExecution(null);
                    setOpenMenu(null);
                  }}
                  title="直接输入提示词生成"
                >
                  直接
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={isAgentMode}
                  className={isAgentMode ? "is-active" : ""}
                  onClick={() => {
                    if (!isAgentMode) {
                      // Agent hydration restores its persisted draft. Transfer
                      // the complete Direct composer value first so entering
                      // Agent never replaces newer lines with a stale draft.
                      const next = flushUiIntoActiveSession();
                      persistSessionStore(next);
                    }
                    setCreateMode("agent");
                    setPendingExecution(null);
                    setOpenMenu(null);
                  }}
                  title="Agent 多会话隔离 · 先规划再确认生成"
                >
                  <Bot size={14} />
                  Agent
                </button>
              </div>

              <ModelPicker
                models={models}
                selectedModelId={selectedModelId}
                onChange={selectGenerationModel}
                isLoading={isLoadingModels}
                triggerClassName="gi-pill-btn gi-model-picker-trigger"
              />

              <button
                type="button"
                className={`gi-pill-btn gi-toolbar__settings ${isComposerSettingsOpen ? "is-open" : ""}`}
                onClick={() => setIsComposerSettingsOpen((open) => !open)}
                aria-expanded={isComposerSettingsOpen}
                title="调整文本模型、画幅、清晰度和视频时长"
              >
                <SlidersHorizontal size={14} />
                <span>参数</span>
                <ChevronDown size={14} />
              </button>

              <button
                type="button"
                className={`gi-pill-btn gi-composer__advanced-toggle ${isCreativePreferencesOpen ? "is-open" : ""}`}
                onClick={() => setIsCreativePreferencesOpen((open) => !open)}
                aria-expanded={isCreativePreferencesOpen}
              >
                <Palette size={14} />
                <span>
                  偏好
                  {activeStyleKitIds.length ? ` ${activeStyleKitIds.length}` : ""}
                  {brandKit.enabled ? " · 品牌" : ""}
                </span>
                <ChevronDown size={14} />
              </button>

              {isComposerSettingsOpen ? <div className="gi-toolbar__advanced">
              {/* Text model is only needed for Agent planning. */}
              {isAgentMode && textModels.length ? (
                <div className="gi-menu-wrap">
                  <button
                    type="button"
                    className={`gi-pill-btn ${openMenu === "textModel" ? "is-open" : ""} ${isAgentMode ? "is-required" : ""}`}
                    onClick={() => setOpenMenu((v) => (v === "textModel" ? null : "textModel"))}
                    title="Agent 文本模型（必选）"
                  >
                    <Bot size={14} />
                    <span className="gi-pill-btn__label">
                      {selectedTextModel?.name ?? "文本模型"}
                    </span>
                    <ChevronDown size={14} />
                  </button>
                  {openMenu === "textModel" ? (
                    <div className="gi-menu" role="listbox">
                      {textModels.map((model) => (
                        <button
                          key={model.id}
                          type="button"
                          role="option"
                          aria-selected={model.id === selectedTextModelId}
                          className={model.id === selectedTextModelId ? "is-active" : ""}
                          onClick={() => {
                            setSelectedTextModelId(model.id);
                            setOpenMenu(null);
                          }}
                        >
                          <strong>{model.name}</strong>
                          <span>Agent 推理模型</span>
                        </button>
                      ))}
                      {!textModels.length ? <p className="gi-menu__empty">暂无文本模型</p> : null}
                    </div>
                  ) : null}
                </div>
              ) : isAgentMode ? (
                <span className="gi-pill-btn gi-pill-btn--warn" title="未配置可用文本模型">
                  <Bot size={14} />
                  无文本模型
                </span>
              ) : null}

              {/* Aspect ratio */}
              <div className="gi-menu-wrap">
                <button
                  type="button"
                  className={`gi-pill-btn ${openMenu === "ratio" ? "is-open" : ""}`}
                  onClick={() => setOpenMenu((v) => (v === "ratio" ? null : "ratio"))}
                >
                  <span className="gi-ratio-icon" style={getAspectRatioStyle(aspectRatio || "1:1")} />
                  <span>{aspectRatio || "比例"}</span>
                  <ChevronDown size={14} />
                </button>
                {openMenu === "ratio" ? (
                  <div className="gi-menu gi-menu--grid" role="listbox">
                    {ratioOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        role="option"
                        aria-selected={option.value === aspectRatio}
                        className={option.value === aspectRatio ? "is-active" : ""}
                        onClick={() => {
                          setAspectRatio(option.value);
                          setOpenMenu(null);
                        }}
                      >
                        <span className="gi-ratio-icon" style={getAspectRatioStyle(option.value)} />
                        {option.label || option.value}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              {/* Resolution */}
              <div className="gi-menu-wrap">
                <button
                  type="button"
                  className={`gi-pill-btn ${openMenu === "resolution" ? "is-open" : ""}`}
                  onClick={() => setOpenMenu((v) => (v === "resolution" ? null : "resolution"))}
                >
                  <span>{resolution || "画质"}</span>
                  <ChevronDown size={14} />
                </button>
                {openMenu === "resolution" ? (
                  <div className="gi-menu" role="listbox">
                    {resolutionOptions.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        role="option"
                        aria-selected={option.value === resolution}
                        className={option.value === resolution ? "is-active" : ""}
                        onClick={() => {
                          setResolution(option.value);
                          setOpenMenu(null);
                        }}
                      >
                        {option.label || option.value}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              {/* Duration (video) */}
              {isVideoMode ? (
                <div className="gi-menu-wrap">
                  <button
                    type="button"
                    className={`gi-pill-btn ${openMenu === "duration" ? "is-open" : ""}`}
                    onClick={() => setOpenMenu((v) => (v === "duration" ? null : "duration"))}
                  >
                    <span>{duration ? `${duration}s` : "时长"}</span>
                    <ChevronDown size={14} />
                  </button>
                  {openMenu === "duration" ? (
                    <div className="gi-menu" role="listbox">
                      {durationOptions.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          role="option"
                          aria-selected={option.value === duration}
                          className={option.value === duration ? "is-active" : ""}
                          onClick={() => {
                            setDuration(option.value);
                            setOpenMenu(null);
                          }}
                        >
                          {option.label || `${option.value}s`}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              </div> : null}
            </div>

            <div className="gi-toolbar__right">
              <Button
                type="submit"
                className="gi-make"
                disabled={!canSubmit}
                title={
                  isUploading || pendingUploadPreviews.length
                    ? "参考图上传中，完成后才能发送（避免误走文生图）"
                    : undefined
                }
              >
                {isUploading || pendingUploadPreviews.length ? (
                  <LoadingIndicator className="spin-icon" size={16} />
                ) : isSubmitting || isPlanningAgent || isBusy || pendingQuoteLoading ? (
                  <LoadingIndicator className="spin-icon" size={16} />
                ) : isAgentMode ? (
                  <Bot size={16} />
                ) : isVideoMode ? (
                  <Clapperboard size={16} />
                ) : (
                  <Sparkles size={16} />
                )}
                {isUploading || pendingUploadPreviews.length
                  ? "上传中…"
                  : pendingExecution
                    ? "已有待确认计划"
                    : isAgentMode && isSubmitting
                      ? "Agent 分析中…"
                    : isAgentMode
                      ? isVideoMode
                        ? "Agent 规划视频"
                        : "Agent 规划"
                      : isVideoMode
                        ? "生成视频"
                        : "生成"}
                {!pendingExecution && !isUploading && !pendingUploadPreviews.length && quote !== null ? <em>{quote}</em> : null}
              </Button>
            </div>
          </div>

          {agentHistoryReply ? (
            <div className="gi-agent-plan gi-agent-plan--compact" role="status" aria-label="创作查询结果">
              <div className="gi-agent-plan__head">
                <strong>创作查询结果</strong>
                <button type="button" className="gi-style-kits__clear" onClick={() => setAgentHistoryReply(null)}>
                  关闭
                </button>
              </div>
              <p className="gi-agent-plan__summary">{agentHistoryReply}</p>
            </div>
          ) : null}

          {isAgentMode && isSubmitting && !pendingExecution && agentPlanningStatus ? (
            <div className="gi-agent-planning" role="status" aria-live="polite">
              <LoadingIndicator className="spin-icon" size={18} />
              <div>
                <strong>Agent 正在规划</strong>
                <span>{agentPlanningStatus}</span>
              </div>
            </div>
          ) : null}

          {pendingExecution ? (
            <div className="gi-agent-plan gi-pending-exec" role="region" aria-label="待确认执行计划">
              <div className="gi-pending-exec__review">
                <div>
                  <span>Agent 已理解</span>
                  <strong>{pendingExecution.plan?.summary || `准备执行 ${pendingExecution.prompts.length} 个任务`}</strong>
                </div>
                <em>
                  {pendingExecution.prompts.length} {isVideoMode ? "条视频" : "张图片"}
                  {pendingExecution.estimatedCredit != null ? ` · ${formatCredit(pendingExecution.estimatedCredit)} 积分` : ""}
                </em>
              </div>
              {pendingExecution.inputAssets.length || pendingExecution.perTaskAssets?.length ? (
                <p className="gi-pending-exec__reference">已使用参考图，Agent 会基于它完成本次任务。</p>
              ) : null}
              <section className="gi-pending-exec__tasks" aria-label="待执行任务列表">
                <div>
                  <strong>待执行任务</strong>
                  <span>以下内容将原样提交</span>
                </div>
                <ol className="gi-agent-plan__list">
                  {pendingExecution.prompts.map((taskPrompt, index) => (
                    <li key={`${index}-${taskPrompt}`}>{taskPrompt}</li>
                  ))}
                </ol>
              </section>
              <div className="gi-pending-exec__actions">
                <Button type="button" variant="secondary" onClick={cancelPendingExecution} disabled={isSubmitting}>
                  返回修改
                </Button>
                <Button type="button" onClick={() => void confirmPendingExecution()} disabled={isSubmitting || pendingQuoteLoading}>
                  {isSubmitting ? (
                    <>
                      <LoadingIndicator className="spin-icon" size={14} /> 提交中…
                    </>
                  ) : (
                    <>
                      <Check size={14} /> 开始执行
                      {pendingExecution.estimatedCredit != null ? <em>{formatCredit(pendingExecution.estimatedCredit)}</em> : null}
                    </>
                  )}
                </Button>
              </div>
            </div>
          ) : isAgentMode && agentPlan ? (
            <div className="gi-agent-plan gi-agent-plan--compact" title={agentPlan.summary || undefined}>
              <div className="gi-agent-plan__head">
                <strong>{intentLabel(agentPlan.intent)}</strong>
                <span>{agentPlan.prompts.length} 条任务</span>
              </div>
              {agentPlan.summary ? <p className="gi-agent-plan__summary">{agentPlan.summary}</p> : null}
            </div>
          ) : isAgentMode && agentPlanPrompt ? (
            <div className="gi-agent-plan gi-agent-plan--compact" title={agentPlanPrompt}>
              <strong>Agent 已更新提示词</strong>
            </div>
          ) : null}

          {needsUpload && !uploadedAssets.length ? (
            <p className="gi-hint">请先上传至少 1 张参考图</p>
          ) : isAgentMode ? (
            <p className="gi-hint gi-hint--muted">Agent：创作任务确认执行，历史查询直接返回 · 单次最多 {maxBatchTasks} 条{!selectedTextModelId ? " · 请先选择文本模型" : ""}</p>
          ) : (
            <p className="gi-hint gi-hint--muted">⌘/Ctrl + Enter 快速生成 · 多图图生图/视频已支持</p>
          )}

          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={(e) => void uploadFiles(e)}
          />
          <input
            ref={docInputRef}
            type="file"
            accept=".txt,.md,.markdown,.pdf,.docx,.csv,.json,.html,.htm,.rtf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/csv,application/json,text/html,application/rtf"
            multiple
            hidden
            onChange={(e) => void uploadAgentDocuments(e)}
          />
        </form>
      </div>

      {/* Hero lightbox strip for selected result (optional large view) */}
      {heroOutput && selectedTask?.status === "succeeded" ? (
        <button type="button" className="gi-fab-preview" onClick={() => setPreviewAsset(heroOutput)} title="大图预览">
          查看大图
        </button>
      ) : null}

      <MaterialPicker
        open={isMaterialPickerOpen}
        onClose={() => setIsMaterialPickerOpen(false)}
        onSelect={(assets) => {
          addMaterialAssets(assets);
          setIsMaterialPickerOpen(false);
        }}
      />

      {retryFailedDraft ? (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-dialog gi-retry-dialog" role="dialog" aria-modal="true" aria-label="确认失败重试范围">
            <h3>确认重试范围</h3>
            <p>
              当前共有 <strong>{failedTasks.length}</strong> 条失败/已退款任务。不会直接重跑全部，请选择范围：
            </p>
            <div className="gi-retry-scope">
              <label className={retryFailedDraft.mode === "recent_batch" ? "is-active" : ""}>
                <input
                  type="radio"
                  name="retry-scope"
                  checked={retryFailedDraft.mode === "recent_batch"}
                  onChange={() => setRetryFailedDraft((current) => current ? { ...current, mode: "recent_batch" } : current)}
                />
                <span>
                  <strong>最近一批失败</strong>
                  <em>按最近 30 分钟聚类，约 {clusterRecentFailedBatch(failedTasks, maxBatchTasks).length} 条</em>
                </span>
              </label>
              <label className={retryFailedDraft.mode === "recent_n" ? "is-active" : ""}>
                <input
                  type="radio"
                  name="retry-scope"
                  checked={retryFailedDraft.mode === "recent_n"}
                  onChange={() => setRetryFailedDraft((current) => current ? { ...current, mode: "recent_n" } : current)}
                />
                <span>
                  <strong>最近 N 条失败</strong>
                  <em>从最新失败任务往前取</em>
                </span>
              </label>
              {retryFailedDraft.mode === "recent_n" ? (
                <div className="gi-retry-count">
                  <span>条数</span>
                  <input
                    type="number"
                    min={1}
                    max={maxBatchTasks}
                    value={retryFailedDraft.recentCount}
                    onChange={(event) => {
                      const next = Number(event.target.value);
                      setRetryFailedDraft((current) =>
                        current
                          ? {
                              ...current,
                              recentCount: Math.max(1, Math.min(maxBatchTasks, Number.isFinite(next) ? Math.floor(next) : 1)),
                            }
                          : current,
                      );
                    }}
                  />
                  <div className="gi-retry-count__chips">
                    {[1, 3, 5, 10].filter((n) => n <= maxBatchTasks).map((n) => (
                      <button
                        key={n}
                        type="button"
                        className={retryFailedDraft.recentCount === n ? "is-active" : ""}
                        onClick={() => setRetryFailedDraft((current) => (current ? { ...current, recentCount: n, mode: "recent_n" } : current))}
                      >
                        {n}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
            <div className="gi-retry-preview">
              <strong>将重试 {retryPreviewTasks.length} 条</strong>
              <ol>
                {retryPreviewTasks.slice(0, 6).map((task) => (
                  <li key={task.id} title={task.prompt}>
                    {task.prompt.length > 48 ? `${task.prompt.slice(0, 48)}…` : task.prompt}
                  </li>
                ))}
              </ol>
              {retryPreviewTasks.length > 6 ? <p>还有 {retryPreviewTasks.length - 6} 条未展开</p> : null}
            </div>
            <div className="dialog-actions">
              <Button variant="secondary" type="button" onClick={() => setRetryFailedDraft(null)} disabled={isSubmitting}>
                取消
              </Button>
              <Button type="button" onClick={() => void confirmRetryFailedTasks()} disabled={isSubmitting || retryPreviewTasks.length === 0}>
                {isSubmitting ? "提交中…" : `确认重试 ${retryPreviewTasks.length} 条`}
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {deleteTaskIds?.length ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setDeleteTaskIds(null)}>
          <div className="confirm-dialog gi-retry-dialog" role="dialog" aria-modal="true" aria-label="确认删除失败任务" onClick={(event) => event.stopPropagation()}>
            <h3>确认逻辑删除 {deleteTaskIds.length} 条失败任务？</h3>
            <p>任务会从当前列表隐藏；此操作由受权限约束的 MCP 删除工具调用现有删除接口完成。</p>
            <div className="dialog-actions">
              <Button type="button" variant="secondary" onClick={() => setDeleteTaskIds(null)} disabled={isSubmitting}>取消</Button>
              <Button
                type="button"
                variant="danger"
                disabled={isSubmitting}
                onClick={() => {
                  const taskIds = [...deleteTaskIds];
                  setIsSubmitting(true);
                  void Promise.all(taskIds.map((taskId) => imageTaskService.deleteTask(taskId)))
                    .then(() => {
                      setTasks((current) => current.filter((task) => !taskIds.includes(task.id)));
                      setDeleteTaskIds(null);
                      setNotice(`已逻辑删除 ${taskIds.length} 条失败任务`);
                    })
                    .catch((error) => setError(error instanceof Error ? error.message : "删除任务失败"))
                    .finally(() => setIsSubmitting(false));
                }}
              >
                确认删除
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {previewAsset
        ? createPortal(
            <div className="modal-backdrop gi-preview-backdrop" role="presentation" onClick={() => setPreviewAsset(null)}>
              <section
                className="image-preview-dialog gi-preview"
                role="dialog"
                aria-modal="true"
                aria-label={isVideoAsset(previewAsset) ? "视频预览" : "图片预览"}
                onClick={(e) => e.stopPropagation()}
              >
                <aside className="gi-preview__thumbs" aria-label="结果缩略图">
                  <button type="button" className="gi-preview__back" onClick={() => setPreviewAsset(null)} aria-label="关闭预览">
                    <ArrowLeft size={18} />
                  </button>
                  {previewThumbnailEntries.map(({ asset, index }) => (
                    <button
                      className={asset.url === previewAsset.url ? "is-active" : undefined}
                      key={`${asset.url}-${index}`}
                      type="button"
                      onClick={() => openPreviewAsset(asset)}
                    >
                      <img
                        src={resolveAssetUrl(getAssetPreviewSource(asset))}
                        alt={`结果图 ${index + 1}`}
                        loading="lazy"
                        decoding="async"
                        onError={(event) => {
                          if (event.currentTarget.dataset.originalFallback === "true") return;
                          event.currentTarget.dataset.originalFallback = "true";
                          event.currentTarget.src = resolveAssetUrl(asset.url);
                        }}
                      />
                    </button>
                  ))}
                </aside>
                <div className="gi-preview__canvas">
                  {isVideoAsset(previewSourceAsset ?? previewAsset) ? (
                    <video src={resolveAssetUrl((previewSourceAsset ?? previewAsset).url)} controls autoPlay playsInline />
                  ) : (
                    <img src={resolveAssetUrl((previewSourceAsset ?? previewAsset).url)} alt={previewSourceAsset ? "原图预览" : "结果预览"} />
                  )}
                  {previewAssets.length > 1 ? (
                    <>
                      <button
                        type="button"
                        className="gi-preview__step gi-preview__step--prev"
                        onClick={() => selectPreviewOffset(-1)}
                        aria-label="上一张"
                        title="上一张（←）"
                      >
                        <ChevronLeft size={21} />
                      </button>
                      <button
                        type="button"
                        className="gi-preview__step gi-preview__step--next"
                        onClick={() => selectPreviewOffset(1)}
                        aria-label="下一张"
                        title="下一张（→）"
                      >
                        <ChevronRight size={21} />
                      </button>
                    </>
                  ) : null}
                </div>
                <aside className="gi-preview__actions">
                  <div className="gi-preview__meta">
                    <strong>{previewTask?.model_name || "当前模型"}</strong>
                    <span>
                      {previewAssetIndex >= 0 ? `作品 ${previewAssetIndex + 1} / ${previewAssets.length} · ` : ""}
                      {previewTask?.resolution || "默认分辨率"} · {previewTask?.aspect_ratio || "默认比例"}
                    </span>
                    {previewTask?.input_images?.length ? (
                      <div className="gi-preview__source">
                        <b>原图</b>
                        <div>
                          {previewTask.input_images.map((asset) => (
                            <button
                              key={asset.id}
                              type="button"
                              className={`gi-preview__source-item ${previewSourceAsset?.url === asset.url ? "is-active" : ""}`}
                              onClick={() => setPreviewSourceAsset(asset)}
                              title="在当前预览中查看原图"
                            >
                              <img src={resolveAssetUrl(asset.url)} alt="参考原图" />
                            </button>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    <div className="gi-preview__prompt">
                      <b>提示词</b>
                      <p>{previewTask?.prompt || "暂无提示词"}</p>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setPreviewAsset(null);
                      setCreateMode("direct");
                      switchMedia("image");
                      const editAssets = mergeImageEditAssets(previewAsset, previewTask?.input_images ?? []);
                      setUploadedAssets(editAssets);
                      setIsAttachmentTrayOpen(true);
                      setNotice(
                        editAssets.length > 1
                          ? `已载入结果图和 ${editAssets.length - 1} 张原始参考图，可继续编辑`
                          : "已载入结果图，可继续编辑",
                      );
                    }}
                  >
                    <ImageIcon size={17} /> 继续编辑
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (!previewTask) return;
                      setPreviewAsset(null);
                      setCreateMode("direct");
                      switchMedia(previewTask.work_type.includes("video") ? "video" : "image");
                      setUploadedAssets(previewTask.input_images);
                      setIsAttachmentTrayOpen(true);
                      setPrompt(previewTask.prompt);
                      setNotice("已将提示词和参考图重新放入输入框");
                    }}
                  >
                    <RefreshCw size={17} /> 重新生成
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (!previewTask) return;
                      void recreateTasksFromSources([previewTask]).catch((error) => setError(error instanceof Error ? error.message : "提交失败"));
                    }}
                  >
                    <Sparkles size={17} /> 再抽一张
                  </button>
                  <button
                    type="button"
                    onClick={() => void downloadPreviewAsset()}
                    disabled={isDownloadingPreview}
                  >
                    {isDownloadingPreview ? (
                      <LoadingIndicator size={17} className="spin" />
                    ) : (
                      <Download size={17} />
                    )}
                    {isDownloadingPreview ? "下载中…" : "下载图片"}
                  </button>
                </aside>
              </section>
            </div>,
            document.body,
          )
        : null}
    </main>
  );
};
