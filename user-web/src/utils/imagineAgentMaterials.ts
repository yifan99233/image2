import { materialService } from "@/services/materials";
import type { ImageAsset, MaterialAsset, MaterialFolder } from "@/types/api";

export type MaterialBatchMode = "folder" | "keyword" | "recent_all";

export type MaterialBatchIntent = {
  /** Folder name query extracted from NL, if any. */
  folderQuery: string | null;
  /** Material name keyword filter, if any. */
  keyword: string | null;
  /** Edit / redraw instruction for each image. */
  editPrompt: string;
  /** Optional max count from NL (e.g. 前20张). */
  limit: number | null;
  mode: MaterialBatchMode;
  raw: string;
};

export type MaterialBatchSelection = {
  intent: MaterialBatchIntent;
  folder: MaterialFolder | null;
  folderPathLabel: string;
  materials: MaterialAsset[];
  assets: ImageAsset[];
  totalAvailable: number;
  truncated: boolean;
  appliedLimit: number;
};

const QUOTE_NAME =
  /[「『《“"']([^「『《“"'\n]{1,40})[」』》”"']/;

/** True when user wants bulk redraw / restyle of material library images. */
export const isMaterialLibraryBatchIntent = (text: string): boolean => {
  const value = (text || "").trim();
  if (!value) return false;
  const mentionsLibrary =
    /素材库|素材夹|素材文件夹|素材目录|我的素材|素材分组|素材合集/.test(value) ||
    (/文件夹|目录/.test(value) && /素材|图片|照片|图集/.test(value));
  if (!mentionsLibrary) return false;
  const wantsBatchAction =
    /重绘|重新画|重新生成|再画|批量|统一|全部|所有|逐张|一张张|改成|换成|改成|改为|改成|按.{0,20}(要求|风格|提示)|风格化|换背景|改背景|重做|翻新|出一套/.test(
      value,
    );
  return wantsBatchAction;
};

const stripNoise = (value: string) =>
  value
    .replace(/[，。！？、,.!?;；:\n\r]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();

/**
 * Parse NL like:
 * - 把我素材库「产品图」文件夹的图片按极简白底重绘
 * - 将素材库 春季主图 的图全部改成青海湖背景
 * - 素材库最近 20 张统一重绘成赛博朋克
 */
export const parseMaterialLibraryBatchIntent = (text: string): MaterialBatchIntent | null => {
  if (!isMaterialLibraryBatchIntent(text)) return null;
  const raw = text.trim();
  let folderQuery: string | null = null;
  let keyword: string | null = null;
  let mode: MaterialBatchMode = "folder";

  const quoted = raw.match(QUOTE_NAME);
  if (quoted?.[1]) {
    folderQuery = quoted[1].trim();
  }

  if (!folderQuery) {
    const folderPatterns = [
      /素材库(?:里的|中的|的)?\s*[「『《“"']?([^\s「『《“"'」』》”"']{1,30})[」』》”"']?\s*(?:文件夹|目录|分组|合集)/,
      /(?:文件夹|目录|分组|合集)\s*[「『《“"']?([^\s「『《“"'」』》”"']{1,30})[」』》”"']?/,
      /素材库\s*[「『《“"']?([^\s「『《“"'」』》”"']{1,30})[」』》”"']?\s*(?:里的|中的|的)?\s*(?:图片|照片|素材|图)?/,
    ];
    for (const re of folderPatterns) {
      const m = raw.match(re);
      if (m?.[1] && !/最近|全部|所有|图片|照片|素材|图/.test(m[1])) {
        folderQuery = m[1].trim();
        break;
      }
    }
  }

  if (/最近/.test(raw) && !folderQuery) {
    mode = "recent_all";
  } else if (!folderQuery && /关键词|名称包含|叫|名为|搜索/.test(raw)) {
    mode = "keyword";
    const km =
      raw.match(/(?:关键词|名称包含|名为|叫)\s*[「『《“"']?([^\s「『《“"'」』》”"']{1,30})/) ||
      raw.match(/搜索\s*[「『《“"']?([^\s「『《“"'」』》”"']{1,30})/);
    keyword = km?.[1]?.trim() || null;
  } else if (!folderQuery) {
    // No folder named → try treat residual as keyword under root+walk later
    mode = "recent_all";
  } else {
    mode = "folder";
  }

  let limit: number | null = null;
  const limitMatch =
    raw.match(/(?:最近|前|最多|取|只要)\s*(\d{1,3})\s*张/) ||
    raw.match(/(\d{1,3})\s*张(?:图|图片|素材|照片)?/);
  if (limitMatch) {
    const n = Number(limitMatch[1]);
    if (Number.isFinite(n) && n > 0) limit = Math.floor(n);
  }

  // Extract edit instruction: after 按/改成/换成/重绘成/统一...
  let editPrompt = "";
  const editPatterns = [
    /(?:按照?|按)\s*(.+?)(?:重绘|重新画|重新生成|再画|批量|统一|全部|生成|$)/,
    /(?:重绘|重新画|重新生成|再画|改成|改为|换成|换为|画成|做成|风格化成?|统一成?)\s*[：:]?\s*(.+)$/,
    /要求[是为：:]\s*(.+)$/,
  ];
  for (const re of editPatterns) {
    const m = raw.match(re);
    if (m?.[1]) {
      editPrompt = stripNoise(m[1]);
      if (editPrompt.length >= 2) break;
    }
  }
  if (!editPrompt || editPrompt.length < 2) {
    // Fallback: remove library/folder scaffolding, keep rest as instruction
    editPrompt = stripNoise(
      raw
        .replace(/素材库|素材夹|素材文件夹|素材目录|我的素材|素材分组|素材合集/g, " ")
        .replace(/文件夹|目录|分组|合集/g, " ")
        .replace(QUOTE_NAME, " ")
        .replace(/(?:最近|前|最多|取|只要)\s*\d{1,3}\s*张/g, " ")
        .replace(/\d{1,3}\s*张(?:图|图片|素材|照片)?/g, " ")
        .replace(/(把|将|给|帮我|请|一下|所有|全部|统一|批量|逐张)/g, " "),
    );
  }
  // Clean leftover folder name from edit prompt
  if (folderQuery) {
    editPrompt = stripNoise(editPrompt.replace(folderQuery, " "));
  }
  if (!editPrompt || editPrompt.length < 2) {
    editPrompt = "保持主体清晰，整体画质提升，商业可用";
  }

  // Soft defaults for pure library mentions
  if (editPrompt.length > 500) editPrompt = editPrompt.slice(0, 500);

  return {
    folderQuery,
    keyword,
    editPrompt,
    limit,
    mode,
    raw,
  };
};

const scoreFolderName = (name: string, query: string): number => {
  const a = name.trim().toLowerCase();
  const b = query.trim().toLowerCase();
  if (!a || !b) return 0;
  if (a === b) return 100;
  if (a.includes(b) || b.includes(a)) return 80;
  // simple char overlap
  let hit = 0;
  for (const ch of b) if (a.includes(ch)) hit += 1;
  return Math.round((hit / Math.max(b.length, 1)) * 40);
};

/** BFS folder tree (bounded) and pick best name match. */
export const findMaterialFolderByName = async (
  query: string,
  options?: { maxNodes?: number; maxDepth?: number },
): Promise<{ folder: MaterialFolder; path: string[] } | null> => {
  const q = query.trim();
  if (!q) return null;
  const maxNodes = options?.maxNodes ?? 200;
  const maxDepth = options?.maxDepth ?? 5;

  type Node = { folder: MaterialFolder | null; path: string[]; depth: number };
  const queue: Node[] = [{ folder: null, path: [], depth: 0 }];
  let best: { folder: MaterialFolder; path: string[]; score: number } | null = null;
  let visited = 0;

  while (queue.length && visited < maxNodes) {
    const cur = queue.shift()!;
    if (cur.depth > maxDepth) continue;
    const children = await materialService.getFolders(cur.folder?.id ?? null);
    for (const child of children) {
      visited += 1;
      if (visited > maxNodes) break;
      const path = [...cur.path, child.name];
      const score = scoreFolderName(child.name, q);
      if (score > 0 && (!best || score > best.score)) {
        best = { folder: child, path, score };
      }
      if (cur.depth + 1 <= maxDepth) {
        queue.push({ folder: child, path, depth: cur.depth + 1 });
      }
    }
  }

  if (!best || best.score < 40) return null;
  return { folder: best.folder, path: best.path };
};

/** Load materials for a folder (or root-only when folderId null), paginated up to limit. */
export const loadMaterialAssetsPaged = async (input: {
  folderId?: number | null;
  keyword?: string;
  limit: number;
}): Promise<{ materials: MaterialAsset[]; total: number }> => {
  const limit = Math.max(1, Math.min(200, input.limit));
  const pageSize = 80;
  let page = 1;
  let total = 0;
  const materials: MaterialAsset[] = [];

  while (materials.length < limit) {
    const res = await materialService.getMaterials(
      input.folderId ?? null,
      input.keyword || "",
      page,
      pageSize,
    );
    total = Number(res.total) || 0;
    const items = res.items || [];
    if (!items.length) break;
    for (const item of items) {
      materials.push(item);
      if (materials.length >= limit) break;
    }
    if (items.length < pageSize) break;
    if (materials.length >= total && total > 0) break;
    page += 1;
    if (page > 20) break;
  }

  return { materials, total: total || materials.length };
};

/**
 * Walk shallow subfolders and collect materials until limit.
 * Used when user says "全部" but assets live in nested folders.
 */
export const loadMaterialsDeepFromFolder = async (input: {
  rootFolderId: number | null;
  keyword?: string;
  limit: number;
  maxFolders?: number;
}): Promise<{ materials: MaterialAsset[]; total: number }> => {
  const limit = Math.max(1, input.limit);
  const maxFolders = input.maxFolders ?? 40;
  const materials: MaterialAsset[] = [];
  let totalEstimate = 0;

  // include root folder materials first
  const root = await loadMaterialAssetsPaged({
    folderId: input.rootFolderId,
    keyword: input.keyword,
    limit,
  });
  materials.push(...root.materials);
  totalEstimate += root.total;
  if (materials.length >= limit) {
    return { materials: materials.slice(0, limit), total: totalEstimate };
  }

  // BFS children
  type Q = { id: number | null; depth: number };
  const queue: Q[] = [{ id: input.rootFolderId, depth: 0 }];
  let folderVisits = 0;
  const seen = new Set<string>();

  while (queue.length && materials.length < limit && folderVisits < maxFolders) {
    const cur = queue.shift()!;
    const children = await materialService.getFolders(cur.id);
    for (const child of children) {
      folderVisits += 1;
      if (folderVisits > maxFolders) break;
      const key = String(child.id);
      if (seen.has(key)) continue;
      seen.add(key);
      const page = await loadMaterialAssetsPaged({
        folderId: child.id,
        keyword: input.keyword,
        limit: limit - materials.length,
      });
      materials.push(...page.materials);
      totalEstimate += page.total;
      if (materials.length >= limit) break;
      if (cur.depth < 3) queue.push({ id: child.id, depth: cur.depth + 1 });
    }
  }

  // de-dupe by material id
  const uniq: MaterialAsset[] = [];
  const ids = new Set<number>();
  for (const m of materials) {
    if (ids.has(m.id)) continue;
    ids.add(m.id);
    uniq.push(m);
    if (uniq.length >= limit) break;
  }
  return { materials: uniq, total: Math.max(totalEstimate, uniq.length) };
};

/** Resolve NL intent → concrete material list (capped). */
export const resolveMaterialBatchSelection = async (
  text: string,
  maxBatchTasks: number,
): Promise<MaterialBatchSelection> => {
  const intent = parseMaterialLibraryBatchIntent(text);
  if (!intent) {
    throw new Error("未能识别素材库批量意图");
  }
  const cap = Math.max(1, maxBatchTasks);
  const wanted = Math.max(1, Math.min(cap, intent.limit || cap));

  let folder: MaterialFolder | null = null;
  let folderPathLabel = "素材库";
  let materials: MaterialAsset[] = [];
  let totalAvailable = 0;

  if (intent.mode === "folder" && intent.folderQuery) {
    const hit = await findMaterialFolderByName(intent.folderQuery);
    if (!hit) {
      // fallback: keyword search in root+deep
      const deep = await loadMaterialsDeepFromFolder({
        rootFolderId: null,
        keyword: intent.folderQuery,
        limit: wanted,
      });
      materials = deep.materials;
      totalAvailable = deep.total;
      folderPathLabel = `关键词「${intent.folderQuery}」`;
      if (!materials.length) {
        throw new Error(`未找到名为「${intent.folderQuery}」的素材文件夹，也没有匹配的素材名称`);
      }
    } else {
      folder = hit.folder;
      folderPathLabel = hit.path.join(" / ") || hit.folder.name;
      const deep = await loadMaterialsDeepFromFolder({
        rootFolderId: hit.folder.id,
        keyword: intent.keyword || "",
        limit: wanted,
      });
      materials = deep.materials;
      totalAvailable = deep.total;
    }
  } else if (intent.mode === "keyword" && intent.keyword) {
    const deep = await loadMaterialsDeepFromFolder({
      rootFolderId: null,
      keyword: intent.keyword,
      limit: wanted,
    });
    materials = deep.materials;
    totalAvailable = deep.total;
    folderPathLabel = `关键词「${intent.keyword}」`;
  } else {
    // recent_all: walk library shallow-deep and take newest pages from each folder
    const deep = await loadMaterialsDeepFromFolder({
      rootFolderId: null,
      keyword: intent.keyword || "",
      limit: wanted,
    });
    materials = deep.materials;
    totalAvailable = deep.total;
    folderPathLabel = "素材库（多级汇总）";
  }

  if (!materials.length) {
    throw new Error("目标范围内没有可用素材图片");
  }

  const sliced = materials.slice(0, wanted);
  const assets = sliced.map((m) => m.asset).filter(Boolean);
  if (!assets.length) {
    throw new Error("素材缺少可用图片资源");
  }

  return {
    intent,
    folder,
    folderPathLabel,
    materials: sliced,
    assets,
    totalAvailable: Math.max(totalAvailable, materials.length),
    truncated: totalAvailable > sliced.length || materials.length > sliced.length,
    appliedLimit: sliced.length,
  };
};

/** Build one redraw prompt per material (same instruction, optional name anchor). */
export const buildMaterialRedrawPrompts = (
  materials: MaterialAsset[],
  editPrompt: string,
  enrich?: (prompt: string) => string,
): string[] => {
  const base = (editPrompt || "").trim() || "保持主体清晰，整体画质提升";
  return materials.map((m) => {
    const nameHint = m.name ? `（原素材：${m.name.slice(0, 40)}）` : "";
    const prompt = `基于参考图重绘${nameHint}：${base}。保持主体可识别，构图完整，细节清晰，商业可用。`;
    return enrich ? enrich(prompt) : prompt;
  });
};
