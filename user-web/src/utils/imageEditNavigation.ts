import type { ImageAsset } from "@/types/api";

export type ImageEditNavigationState = {
  imageEditSourceAsset: ImageAsset;
  imageEditReferenceAssets?: ImageAsset[];
  imageEditPrompt?: string;
};

const isImageAsset = (asset: unknown): asset is ImageAsset => (
  asset !== null
  && typeof asset === "object"
  && "id" in asset
  && "url" in asset
  && "mime_type" in asset
  && typeof asset.id === "number"
  && typeof asset.url === "string"
  && typeof asset.mime_type === "string"
);

export const mergeImageEditAssets = (
  sourceAsset: ImageAsset,
  referenceAssets: ImageAsset[] = [],
): ImageAsset[] => {
  const seenUrls = new Set<string>();
  return [sourceAsset, ...referenceAssets].filter((asset) => {
    if (!isImageAsset(asset) || !asset.url || seenUrls.has(asset.url)) return false;
    seenUrls.add(asset.url);
    return true;
  });
};

export const createImageEditNavigationState = (
  asset: ImageAsset,
  referenceAssets: ImageAsset[] = [],
  prompt = "",
): ImageEditNavigationState => ({
  imageEditSourceAsset: asset,
  imageEditReferenceAssets: mergeImageEditAssets(asset, referenceAssets).slice(1),
  imageEditPrompt: prompt.trim() || undefined,
});

export const readImageEditAssets = (state: unknown): ImageAsset[] => {
  if (!state || typeof state !== "object" || !("imageEditSourceAsset" in state)) {
    return [];
  }
  const sourceAsset = state.imageEditSourceAsset;
  if (!isImageAsset(sourceAsset)) return [];
  const referenceAssets = "imageEditReferenceAssets" in state && Array.isArray(state.imageEditReferenceAssets)
    ? state.imageEditReferenceAssets.filter(isImageAsset)
    : [];
  return mergeImageEditAssets(sourceAsset, referenceAssets);
};

export const readImageEditSourceAsset = (state: unknown): ImageAsset | null =>
  readImageEditAssets(state)[0] ?? null;

export const readImageEditPrompt = (state: unknown): string => {
  if (!state || typeof state !== "object" || !("imageEditPrompt" in state)) return "";
  const prompt = state.imageEditPrompt;
  return typeof prompt === "string" ? prompt : "";
};
