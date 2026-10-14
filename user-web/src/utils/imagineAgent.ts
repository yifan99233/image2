import type { ImageModel, ImageTask } from "@/types/api";

/** Commercial use-case → preferred aspect / resolution hints. */
export type UseCasePreset = {
  id: string;
  label: string;
  /** Match user natural language */
  pattern: RegExp;
  aspectRatio: string;
  /** Prefer higher quality when available */
  resolutionPrefer?: "high" | "mid" | "fast";
  media?: "image" | "video" | "any";
};

export const USE_CASE_PRESETS: UseCasePreset[] = [
  {
    id: "xhs_cover",
    label: "小红书封面",
    pattern: /小红书|xhs|red\s*book|种草封面/i,
    aspectRatio: "3:4",
    resolutionPrefer: "high",
  },
  {
    id: "ecom_main",
    label: "电商主图",
    pattern: /电商主图|主图|白底主图|产品主图|方图/i,
    aspectRatio: "1:1",
    resolutionPrefer: "high",
  },
  {
    id: "detail",
    label: "详情长图",
    pattern: /详情图|详情页|长图|卖点图/i,
    aspectRatio: "3:4",
    resolutionPrefer: "high",
  },
  {
    id: "video_cover",
    label: "视频封面",
    pattern: /视频封面|封面图|横版封面|16\s*[:：]\s*9|youtube\s*封面/i,
    aspectRatio: "16:9",
    resolutionPrefer: "high",
  },
  {
    id: "story",
    label: "竖屏故事",
    pattern: /故事|story|reels|抖音封面|9\s*[:：]\s*16|竖屏/i,
    aspectRatio: "9:16",
    resolutionPrefer: "mid",
  },
  {
    id: "poster",
    label: "海报",
    pattern: /海报|活动KV|kv\b|宣传图/i,
    aspectRatio: "3:4",
    resolutionPrefer: "high",
  },
  {
    id: "avatar",
    label: "头像/Logo",
    pattern: /头像|logo|图标|icon/i,
    aspectRatio: "1:1",
    resolutionPrefer: "mid",
  },
  {
    id: "banner",
    label: "横幅 Banner",
    pattern: /banner|横幅|通栏|店招/i,
    aspectRatio: "16:9",
    resolutionPrefer: "mid",
  },
];

export const detectUseCase = (text: string): UseCasePreset | null => {
  const value = (text || "").trim();
  if (!value) return null;
  for (const preset of USE_CASE_PRESETS) {
    if (preset.pattern.test(value)) return preset;
  }
  return null;
};

const ratioScore = (wanted: string, candidate: string) => {
  const parse = (raw: string) => {
    const m = raw.replace(/\s/g, "").match(/^(\d+(?:\.\d+)?)[:：/xX](\d+(?:\.\d+)?)$/);
    if (!m) return null;
    const a = Number(m[1]);
    const b = Number(m[2]);
    if (!a || !b) return null;
    return a / b;
  };
  const w = parse(wanted);
  const c = parse(candidate);
  if (w == null || c == null) return wanted === candidate ? 0 : 99;
  return Math.abs(Math.log(w) - Math.log(c));
};

/** Pick closest supported aspect ratio for a model. */
export const pickClosestAspectRatio = (model: ImageModel | null | undefined, wanted: string, fallback: string) => {
  const options = model?.supported_aspect_ratios ?? [];
  if (!options.length) return fallback || wanted;
  if (options.some((item) => item.value === wanted)) return wanted;
  const ranked = [...options].sort(
    (a, b) => ratioScore(wanted, a.value) - ratioScore(wanted, b.value) || a.value.localeCompare(b.value),
  );
  return ranked[0]?.value || fallback || wanted;
};

export const pickPreferredResolution = (
  model: ImageModel | null | undefined,
  prefer: UseCasePreset["resolutionPrefer"] | undefined,
  fallback: string,
) => {
  const options = model?.supported_resolutions ?? [];
  if (!options.length) return fallback;
  if (options.some((item) => item.value === fallback)) {
    // still allow prefer upgrade
  }
  const values = options.map((item) => item.value);
  const lower = values.map((v) => v.toLowerCase());
  const find = (...keys: string[]) => {
    const idx = lower.findIndex((v) => keys.some((k) => v.includes(k)));
    return idx >= 0 ? values[idx] : null;
  };
  if (prefer === "high") {
    return find("4k", "uhd", "high", "2k", "1080", "1024") || values[values.length - 1] || fallback;
  }
  if (prefer === "fast") {
    return find("fast", "turbo", "512", "768", "low") || values[0] || fallback;
  }
  if (prefer === "mid") {
    return find("2k", "1080", "1024", "standard", "mid") || values[Math.floor(values.length / 2)] || fallback;
  }
  return options.some((item) => item.value === fallback) ? fallback : values[0] || fallback;
};

export type QuickActionId =
  | "cleaner_bg"
  | "sharper"
  | "more_commercial"
  | "more_natural"
  | "same_again"
  | "same_4"
  | "continue_edit"
  | "to_video"
  | "retry_failed";

export type QuickAction = {
  id: QuickActionId;
  label: string;
  /** Natural language prompt fragment for agent/edit */
  prompt?: string;
  /** How many times to recreate (same params) */
  recreateCount?: number;
  requiresSuccess?: boolean;
  requiresFailed?: boolean;
  imageOnly?: boolean;
  videoOnly?: boolean;
};

export const RESULT_QUICK_ACTIONS: QuickAction[] = [
  {
    id: "continue_edit",
    label: "基于此图改",
    prompt: "基于这张图继续修改：",
    requiresSuccess: true,
    imageOnly: true,
  },
  {
    id: "cleaner_bg",
    label: "背景更干净",
    prompt: "保持主体、构图与人物身份不变，只把背景清理得更干净简洁，适合电商/广告使用，光影自然",
    requiresSuccess: true,
    imageOnly: true,
  },
  {
    id: "sharper",
    label: "更清晰",
    prompt: "保持主体与构图不变，提升清晰度与细节质感，边缘锐利但不假，商业摄影质感",
    requiresSuccess: true,
  },
  {
    id: "more_commercial",
    label: "更商业",
    prompt: "保持主体不变，整体更偏商业广告大片：干净构图、高级光影、品牌质感、可投放",
    requiresSuccess: true,
  },
  {
    id: "more_natural",
    label: "更自然",
    prompt: "保持主体不变，画面更自然真实，减少过度磨皮与塑料感，光影柔和",
    requiresSuccess: true,
  },
  {
    id: "same_again",
    label: "同款再来",
    recreateCount: 1,
    requiresSuccess: true,
  },
  {
    id: "same_4",
    label: "再来4张",
    recreateCount: 4,
    requiresSuccess: true,
  },
  {
    id: "to_video",
    label: "转视频",
    prompt: "把这张图做成缓慢推进的短视频，镜头稳定，光影连续",
    requiresSuccess: true,
    imageOnly: true,
  },
  {
    id: "retry_failed",
    label: "重试",
    recreateCount: 1,
    requiresFailed: true,
  },
];

export const classifyFailure = (
  message?: string | null,
): { code: string; label: string; suggestion: string } => {
  const text = (message || "").toLowerCase();
  if (!text) {
    return { code: "unknown", label: "失败", suggestion: "可重试，或换模型后再生成" };
  }
  if (/safety|policy|content|违规|敏感|拒绝|blocked|moderation/.test(text)) {
    return {
      code: "policy",
      label: "内容策略",
      suggestion: "改写提示词，去掉敏感描述后重试",
    };
  }
  if (/timeout|超时|timed?\s*out|deadline/.test(text)) {
    return {
      code: "timeout",
      label: "超时",
      suggestion: "稍后重试，或换更快的模型",
    };
  }
  if (/busy|congest|限流|rate|quota|繁忙|429|capacity/.test(text)) {
    return {
      code: "busy",
      label: "模型繁忙",
      suggestion: "稍后再试，或切换其他可用模型",
    };
  }
  if (/balance|积分|credit|余额不足|insufficient/.test(text)) {
    return {
      code: "credits",
      label: "积分不足",
      suggestion: "充值后再生成，或减少批量条数",
    };
  }
  if (/model|不支持|unsupported|invalid/.test(text)) {
    return {
      code: "model",
      label: "模型/参数",
      suggestion: "检查模型与尺寸参数，或换模型重试",
    };
  }
  return {
    code: "other",
    label: "生成失败",
    suggestion: "可重试；多次失败建议换模型",
  };
};

/** Expand commercial variant matrix from short NL intents. */
export const expandVariantMatrix = (text: string, basePrompt: string, maxCount: number): string[] | null => {
  const value = (text || "").trim();
  if (!value) return null;

  const ecomSet =
    /(电商|主图|套图|一套).{0,12}(图|物料)|白底.{0,6}场景|主图.{0,6}场景|卖点图/.test(value) ||
    /出一套|做一套|物料包/.test(value);
  const variantsWanted =
    /([123456])\s*个?(构图|色调|风格|版本|版)/.exec(value) ||
    /(多构图|多色调|多风格|多版本)/.exec(value);

  if (ecomSet) {
    const subject = basePrompt || "产品";
    const items = [
      `${subject}，纯白背景电商主图，产品居中，柔和棚拍光，高清，无文字`,
      `${subject}，生活场景使用图，自然光，真实环境，突出使用氛围，无文字`,
      `${subject}，卖点展示构图，一侧留白便于后期加文案，商业广告质感，无文字`,
      `${subject}，细节特写，材质纹理清晰，微距质感，高级感，无文字`,
      `${subject}，多角度陈列感，干净背景，品牌目录风格，无文字`,
      `${subject}，节日/活动氛围场景，高级光影，可投放，无文字`,
    ];
    return items.slice(0, Math.max(1, Math.min(maxCount, 6)));
  }

  if (variantsWanted) {
    const nMatch = value.match(/([123456])\s*个?(构图|色调|风格|版本|版)/);
    const n = Math.max(2, Math.min(maxCount, nMatch ? Number(nMatch[1]) || 3 : 3));
    const subject = basePrompt || value;
    if (/色调|风格/.test(value)) {
      const tones = ["清冷青调", "暖金日落", "高饱和潮流", "低饱和莫兰迪", "黑金高级", "明亮清爽"];
      return tones.slice(0, n).map((tone) => `${subject}，${tone}色调，构图稳定，商业可用`);
    }
    const frams = ["正面中景", "45度侧面", "俯视产品特写", "环境场景全景", "人物互动半身", "极简留白构图"];
    return frams.slice(0, n).map((frame) => `${subject}，${frame}，光影专业，高清`);
  }

  return null;
};

export const BULK_CONFIRM_THRESHOLD = 5;

export const formatCredit = (value: number | null | undefined) => {
  if (value == null || Number.isNaN(value)) return "—";
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(1).replace(/\.0$/, "");
};

export const summarizePlanForConfirm = (input: {
  intentLabel: string;
  modelName: string;
  promptCount: number;
  aspectRatio: string;
  resolution: string;
  optimizePrompt?: boolean;
  useCaseLabel?: string | null;
  estimatedCredit?: number | null;
  needsImages?: boolean;
}) => {
  const parts = [
    input.intentLabel,
    `模型 ${input.modelName}`,
    `${input.promptCount} 条`,
    `${input.aspectRatio} · ${input.resolution}`,
    input.optimizePrompt ? "优化提示词" : "不优化提示词",
  ];
  if (input.useCaseLabel) parts.push(input.useCaseLabel);
  if (input.needsImages) parts.push("需参考图");
  if (input.estimatedCredit != null) parts.push(`约 ${formatCredit(input.estimatedCredit)} 积分`);
  return parts.join(" · ");
};

export const isVideoTask = (task: ImageTask) =>
  task.work_type === "text_to_video" || task.work_type === "image_to_video";


/** ---------- Sprint B: multi-turn, style kits, fail model suggest, batch stats ---------- */

export type StyleKit = {
  id: string;
  label: string;
  /** Short chip label */
  short: string;
  description: string;
  /** Appended / merged style guidance (creation only) */
  suffix: string;
  media?: "image" | "video" | "any";
};

/**
 * Curated first-turns for the Agent empty state.  Keeping these in the Agent
 * configuration module makes the suggested workflows easy to tune without
 * coupling product copy to the page component.
 */
export type AgentStarter = {
  id: string;
  label: string;
  description: string;
  prompt: string;
  media?: "image" | "video";
};

export const AGENT_STARTERS: readonly AgentStarter[] = [
  {
    id: "campaign-set",
    label: "一组电商图",
    description: "主图、场景和卖点图",
    prompt: "为这款产品规划一组电商图片：白底主图、使用场景图、卖点特写图。整体风格统一，留出适合后期加文案的空间。",
  },
  {
    id: "reference-edit",
    label: "按参考图改图",
    description: "保留主体，只调整画面",
    prompt: "基于我上传的参考图，保持主体、人物身份和核心构图一致，只按我的要求优化画面。",
  },
  {
    id: "script-storyboard",
    label: "剧本拆分镜",
    description: "上传文档后自动拆镜",
    prompt: "根据我上传的文档拆分成连贯的分镜画面，角色和场景保持一致，并为每个镜头给出可生成的提示词。",
  },
  {
    id: "image-to-video",
    label: "让图片动起来",
    description: "生成稳定的短视频镜头",
    prompt: "基于我上传的图片生成短视频：镜头缓慢推进，主体稳定，光影和动作自然连续。",
    media: "video",
  },
];

export const STYLE_KITS: StyleKit[] = [
  {
    id: "ecom_white",
    label: "电商白底",
    short: "白底",
    description: "产品主图，干净棚拍",
    suffix: "纯白背景，专业棚拍柔光，产品居中，边缘清晰，电商主图质感，无文字无水印",
  },
  {
    id: "lifestyle",
    label: "生活场景",
    short: "场景",
    description: "真实使用氛围",
    suffix: "真实生活场景，自然光，氛围感强，突出使用情境，商业可用，无文字",
  },
  {
    id: "black_gold",
    label: "黑金高级",
    short: "黑金",
    description: "奢侈品牌质感",
    suffix: "黑金高级感，低键奢华光影，质感材质，品牌大片构图，无文字",
  },
  {
    id: "morandi",
    label: "莫兰迪",
    short: "莫兰",
    description: "低饱和柔和",
    suffix: "莫兰迪低饱和配色，柔和光影，高级灰调，干净构图，无文字",
  },
  {
    id: "cyber",
    label: "赛博霓虹",
    short: "赛博",
    description: "科技霓虹夜景",
    suffix: "赛博朋克霓虹，雨夜反光，高对比，科技未来感，电影分镜，无文字",
  },
  {
    id: "film",
    label: "电影质感",
    short: "电影",
    description: "胶片电影光影",
    suffix: "电影级光影，浅景深，胶片质感，叙事构图，色彩电影感，无文字",
  },
  {
    id: "xhs",
    label: "小红书清新",
    short: "种草",
    description: "种草封面风",
    suffix: "小红书种草风，清新明亮，生活感构图，适合竖版封面，画面干净，无文字",
  },
  {
    id: "minimal",
    label: "极简留白",
    short: "极简",
    description: "杂志留白",
    suffix: "极简构图，大面积留白，高级杂志排版感，主体突出，无文字",
  },
];

export const STYLE_KIT_STORAGE_KEY = "imagine.agent.styleKitIds";

export const applyStyleKitsToPrompt = (base: string, kits: StyleKit[]): string => {
  const core = (base || "").trim();
  if (!kits.length) return core;
  const styles = kits.map((k) => k.suffix).join("；");
  if (!core) return styles;
  // Avoid double-appending same kit markers
  if (kits.every((k) => core.includes(k.suffix.slice(0, 8)))) return core;
  return `${core}。风格要求：${styles}`;
};

export type FollowUpResolution = {
  kind: "edit_focus" | "tweak_prompt" | "retry_focus";
  label: string;
  /** Final prompt for generation / plan */
  prompt: string;
  /** Whether to attach focus task output as reference */
  needsFocusImage: boolean;
  /** Prefer image media */
  preferImage: boolean;
};

const FOLLOW_UP_MARKERS =
  /刚才|这张|这幅|上一张|上一轮|上一条|继续改|继续|基于此|基于这|再改|再调|还是这|同一张|同款图/;

const TWEAK_MAP: Array<{ pattern: RegExp; delta: string; label: string }> = [
  { pattern: /更?暗|暗一点|压暗|低调/i, delta: "整体更暗一些，保留主体层次，避免死黑", label: "更暗" },
  { pattern: /更?亮|亮一点|提亮|曝光/i, delta: "整体更亮一些，高光自然，避免过曝", label: "更亮" },
  { pattern: /更?清晰|锐化|更清楚|更细/i, delta: "提升清晰度与细节质感，边缘干净", label: "更清晰" },
  { pattern: /更?模糊|虚化|景深/i, delta: "背景适度虚化，主体更突出", label: "更虚化" },
  { pattern: /更?商业|广告感|大片/i, delta: "更偏商业广告大片：干净构图、高级光影、品牌质感", label: "更商业" },
  { pattern: /更?自然|真实|少磨皮|去塑料/i, delta: "更自然真实，减少过度磨皮与塑料感", label: "更自然" },
  { pattern: /换背景|改背景|背景改|背景换成|背景改为/i, delta: "仅修改背景，主体身份/姿态/服装保持一致", label: "改背景" },
  { pattern: /去文字|去水印|去掉字/i, delta: "去除画面中的文字与水印，保持画面完整", label: "去文字" },
  { pattern: /换色|改色|色调|冷一点|暖一点/i, delta: "调整整体色调以匹配描述，主体不变", label: "调色" },
  { pattern: /再来一张|再来一版|换个构图|换构图/i, delta: "保持主体与风格，更换构图与机位", label: "换构图" },
];

export const isFollowUpIntent = (text: string): boolean => {
  const value = (text || "").trim();
  if (!value) return false;
  if (FOLLOW_UP_MARKERS.test(value)) return true;
  // short tweak without full new subject ("再暗一点")
  if (value.length <= 24 && TWEAK_MAP.some((item) => item.pattern.test(value))) return true;
  if (/^(再|继续|还是).{0,16}$/.test(value) && TWEAK_MAP.some((item) => item.pattern.test(value))) return true;
  return false;
};

export const resolveFollowUp = (
  userText: string,
  focus: { prompt: string; hasOutput: boolean } | null,
): FollowUpResolution | null => {
  const value = (userText || "").trim();
  if (!value || !focus?.prompt) return null;
  if (!isFollowUpIntent(value)) return null;

  const tweaks = TWEAK_MAP.filter((item) => item.pattern.test(value)).map((item) => item);
  const labels = tweaks.map((item) => item.label);
  const deltas = tweaks.map((item) => item.delta);

  // Explicit retry of focus
  if (/重试|重新生成|再生成|再跑/.test(value) && !deltas.length) {
    return {
      kind: "retry_focus",
      label: "重试焦点结果",
      prompt: focus.prompt,
      needsFocusImage: false,
      preferImage: true,
    };
  }

  const extra = value
    .replace(FOLLOW_UP_MARKERS, " ")
    .replace(/再|继续|一点|一些|稍微|请|帮我|把|将/g, " ")
    .replace(/\s+/g, " ")
    .trim();

  const deltaText = [...deltas, extra && extra.length > 1 ? extra : ""].filter(Boolean).join("；");
  const prompt = deltaText
    ? `基于上一张结果继续修改。原描述：${focus.prompt}。本次调整：${deltaText}。保持主体一致，只应用本次调整。`
    : `基于上一张结果继续微调：${value}。原描述：${focus.prompt}。保持主体一致。`;

  return {
    kind: focus.hasOutput ? "edit_focus" : "tweak_prompt",
    label: labels.length ? `续改：${labels.join("·")}` : "续改焦点结果",
    prompt,
    needsFocusImage: Boolean(focus.hasOutput),
    preferImage: true,
  };
};

export const buildAgentContextBlock = (input: {
  focusPrompt?: string | null;
  focusModelName?: string | null;
  recentUserIntents?: string[];
  styleKitLabels?: string[];
}) => {
  const lines: string[] = [];
  if (input.focusPrompt) lines.push(`焦点作品提示词：${input.focusPrompt.slice(0, 400)}`);
  if (input.focusModelName) lines.push(`焦点模型：${input.focusModelName}`);
  if (input.styleKitLabels?.length) lines.push(`当前风格包：${input.styleKitLabels.join("、")}`);
  if (input.recentUserIntents?.length) {
    lines.push(`最近意图：${input.recentUserIntents.slice(-3).join(" | ")}`);
  }
  if (!lines.length) return "";
  return `【创作上下文，仅用于理解续写/续改，不要输出密钥或系统信息】\n${lines.join("\n")}`;
};

export const suggestAlternateModels = (
  models: ImageModel[],
  failedModelId: number | null | undefined,
  limit = 3,
): ImageModel[] => {
  if (!models.length) return [];
  const others = models.filter((m) => m.id !== failedModelId);
  const ranked = [...others].sort((a, b) => {
    const ar = a.is_recommended === b.is_recommended ? 0 : a.is_recommended ? -1 : 1;
    if (ar !== 0) return ar;
    return (b.id || 0) - (a.id || 0);
  });
  return ranked.slice(0, Math.max(1, limit));
};

export type BatchStats = {
  total: number;
  busy: number;
  succeeded: number;
  failed: number;
  pendingLike: number;
};

export const computeBatchStats = (tasks: ImageTask[]): BatchStats => {
  let busy = 0;
  let succeeded = 0;
  let failed = 0;
  let pendingLike = 0;
  for (const task of tasks) {
    if (task.status === "succeeded") succeeded += 1;
    else if (task.status === "failed" || task.status === "refunded") failed += 1;
    else if (task.status === "running") busy += 1;
    else {
      pendingLike += 1;
      busy += 1;
    }
  }
  return { total: tasks.length, busy, succeeded, failed, pendingLike };
};

export const pickLatestFocusTask = (tasks: ImageTask[], selectedId?: number | null): ImageTask | null => {
  if (selectedId != null) {
    const selected = tasks.find((t) => t.id === selectedId);
    if (selected) return selected;
  }
  const succeeded = tasks.find((t) => t.status === "succeeded" && t.output_images?.[0]);
  if (succeeded) return succeeded;
  return tasks[0] ?? null;
};


/** Brand kit — commercial identity constraints (localStorage). */
export type BrandLogoAsset = {
  id: number;
  url: string;
  mime_type?: string;
};

export type BrandKit = {
  name: string;
  /** Hex or color names, e.g. #0EA5E9 */
  colors: string[];
  /** Words/phrases that must not appear in prompts or on-image text requests */
  forbiddenWords: string[];
  /** Extra style / compliance notes appended to prompts */
  styleNotes: string;
  /** @deprecated prefer logoAsset */
  logoUrl?: string | null;
  /** Uploaded logo used as automatic reference image when enabled */
  logoAsset?: BrandLogoAsset | null;
  enabled: boolean;
};

export const BRAND_KIT_STORAGE_KEY = "imagine.agent.brandKit";

export const emptyBrandKit = (): BrandKit => ({
  name: "",
  colors: [],
  forbiddenWords: [],
  styleNotes: "",
  logoUrl: null,
  logoAsset: null,
  enabled: false,
});

const parseLogoAsset = (value: unknown): BrandLogoAsset | null => {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<BrandLogoAsset>;
  const id = Number(raw.id);
  const url = typeof raw.url === "string" ? raw.url : "";
  if (!Number.isFinite(id) || id <= 0 || !url) return null;
  return {
    id,
    url,
    mime_type: typeof raw.mime_type === "string" ? raw.mime_type : undefined,
  };
};

export const loadBrandKit = (): BrandKit => {
  try {
    const raw = localStorage.getItem(BRAND_KIT_STORAGE_KEY);
    if (!raw) return emptyBrandKit();
    const parsed = JSON.parse(raw) as Partial<BrandKit> & { logoAsset?: unknown };
    const logoAsset = parseLogoAsset(parsed.logoAsset);
    const logoUrl =
      logoAsset?.url || (typeof parsed.logoUrl === "string" ? parsed.logoUrl : null);
    return {
      ...emptyBrandKit(),
      name: typeof parsed.name === "string" ? parsed.name : "",
      colors: Array.isArray(parsed.colors)
        ? parsed.colors.filter((c): c is string => typeof c === "string").map((c) => c.trim()).filter(Boolean).slice(0, 8)
        : [],
      forbiddenWords: Array.isArray(parsed.forbiddenWords)
        ? parsed.forbiddenWords
            .filter((w): w is string => typeof w === "string")
            .map((w) => w.trim())
            .filter(Boolean)
            .slice(0, 24)
        : [],
      styleNotes: typeof parsed.styleNotes === "string" ? parsed.styleNotes : "",
      logoUrl,
      logoAsset,
      enabled: Boolean(parsed.enabled),
    };
  } catch {
    return emptyBrandKit();
  }
};

export const saveBrandKit = (kit: BrandKit) => {
  try {
    localStorage.setItem(BRAND_KIT_STORAGE_KEY, JSON.stringify(kit));
  } catch {
    // ignore quota
  }
};

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Apply brand name / colors / notes and strip forbidden words from a prompt. */
export const applyBrandKitToPrompt = (base: string, kit: BrandKit | null | undefined): string => {
  if (!kit?.enabled) return (base || "").trim();
  let text = (base || "").trim();

  for (const word of kit.forbiddenWords) {
    const w = word.trim();
    if (!w) continue;
    try {
      text = text.replace(new RegExp(escapeRegExp(w), "gi"), " ");
    } catch {
      // ignore bad patterns
    }
  }
  text = text.replace(/[ \t]{2,}/g, " ").replace(/\n{3,}/g, "\n\n").trim();

  const parts: string[] = [];
  if (kit.name.trim()) parts.push(`品牌「${kit.name.trim()}」视觉一致`);
  if (kit.colors.length) parts.push(`品牌色优先：${kit.colors.join("、")}`);
  if (kit.styleNotes.trim()) parts.push(kit.styleNotes.trim());
  if (kit.forbiddenWords.length) parts.push(`画面与文案禁止出现：${kit.forbiddenWords.join("、")}`);
  if (kit.logoAsset?.url || kit.logoUrl) parts.push("保留品牌 Logo 识别度与构图留白");
  if (!parts.length) return text;

  const brandBlock = parts.join("；");
  // Avoid double-append when regenerating
  if (text.includes("品牌规范：") || (kit.name && text.includes(`品牌「${kit.name.trim()}」`))) {
    return text || brandBlock;
  }
  return text ? `${text}。品牌规范：${brandBlock}` : `品牌规范：${brandBlock}`;
};

export type StatsRange = "24h" | "7d" | "30d" | "all";

export type CreativeStats = {
  range: StatsRange;
  total: number;
  succeeded: number;
  failed: number;
  busy: number;
  imageCount: number;
  videoCount: number;
  finished: number;
  successRate: number;
  byModel: Array<{ name: string; total: number; succeeded: number; failed: number }>;
};

const isVideoWorkTypeLocal = (workType?: string | null) =>
  Boolean(workType && /video/i.test(workType));

export const filterTasksByRange = (tasks: ImageTask[], range: StatsRange, now = Date.now()): ImageTask[] => {
  if (range === "all") return tasks;
  const windowMs = range === "24h" ? 24 * 3600_000 : range === "7d" ? 7 * 24 * 3600_000 : 30 * 24 * 3600_000;
  return tasks.filter((task) => {
    const ts = new Date(task.created_at).getTime();
    return Number.isFinite(ts) && now - ts <= windowMs;
  });
};

/** Free-form creative stats from local task list (no cost dashboard). */
export const computeCreativeStats = (tasks: ImageTask[], range: StatsRange = "7d"): CreativeStats => {
  const scoped = filterTasksByRange(tasks, range);
  let succeeded = 0;
  let failed = 0;
  let busy = 0;
  let imageCount = 0;
  let videoCount = 0;
  const modelMap = new Map<string, { name: string; total: number; succeeded: number; failed: number }>();

  for (const task of scoped) {
    if (isVideoWorkTypeLocal(task.work_type) || task.output_images?.some((a) => /video/i.test(a.mime_type || a.url || ""))) {
      videoCount += 1;
    } else {
      imageCount += 1;
    }

    const modelName = (task.model_name || "未知模型").trim() || "未知模型";
    const bucket = modelMap.get(modelName) || { name: modelName, total: 0, succeeded: 0, failed: 0 };
    bucket.total += 1;

    if (task.status === "succeeded") {
      succeeded += 1;
      bucket.succeeded += 1;
    } else if (task.status === "failed" || task.status === "refunded") {
      failed += 1;
      bucket.failed += 1;
    } else {
      busy += 1;
    }
    modelMap.set(modelName, bucket);
  }

  const finished = succeeded + failed;
  const successRate = finished > 0 ? Math.round((succeeded / finished) * 1000) / 10 : 0;
  const byModel = [...modelMap.values()].sort(
    (a, b) => b.total - a.total || b.succeeded - a.succeeded || a.name.localeCompare(b.name),
  );

  return {
    range,
    total: scoped.length,
    succeeded,
    failed,
    busy,
    imageCount,
    videoCount,
    finished,
    successRate,
    byModel,
  };
};

export const STATS_RANGE_LABELS: Record<StatsRange, string> = {
  "24h": "近 24 小时",
  "7d": "近 7 天",
  "30d": "近 30 天",
  all: "全部",
};

/** Move an item in a prompt storyboard list. */
export const reorderPrompts = (prompts: string[], from: number, to: number): string[] => {
  if (from === to || from < 0 || to < 0 || from >= prompts.length || to >= prompts.length) return prompts;
  const next = [...prompts];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
};

/** Merge brand logo into input assets (dedupe by id). Logo is appended so user main subject stays first. */
export const mergeBrandLogoAsset = <T extends { id: number }>(
  assets: T[],
  kit: BrandKit | null | undefined,
  logoAsAsset: T | null | undefined,
  maxCount = 8,
): T[] => {
  if (!kit?.enabled || !logoAsAsset?.id) return assets;
  if (assets.some((item) => item.id === logoAsAsset.id)) return assets;
  const limit = Math.max(1, maxCount);
  // Prefer keeping user subject images first; reserve last slot for logo when full.
  if (assets.length < limit) return [...assets, logoAsAsset];
  if (limit === 1) return assets; // keep the single user/subject image
  return [...assets.slice(0, limit - 1), logoAsAsset];
};

export const formatCreativeStatsReply = (stats: CreativeStats): string => {
  const rangeLabel = STATS_RANGE_LABELS[stats.range];
  const topModels = stats.byModel
    .slice(0, 3)
    .map((row) => `${row.name} ${row.succeeded}/${row.total}`)
    .join("；");
  const rate = stats.finished ? `${stats.successRate}%` : "—";
  const lines = [
    `【创作统计 · ${rangeLabel}】`,
    `共 ${stats.total} 条 · 成功 ${stats.succeeded} · 失败 ${stats.failed} · 进行中 ${stats.busy}`,
    `成功率 ${rate} · 图 ${stats.imageCount} / 视频 ${stats.videoCount}`,
  ];
  if (topModels) lines.push(`模型 TOP：${topModels}`);
  return lines.join("\n");
};
