import type { SiteContentMaterial } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";

export const isVideoUrl = (value?: string) => /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(value || "");

export const isVideoMime = (value?: string | null) => Boolean(value && value.toLowerCase().startsWith("video/"));

export const isVideoAsset = (asset?: { url?: string; mime_type?: string | null } | null) => {
  if (!asset) return false;
  if (isVideoMime(asset.mime_type)) return true;
  return isVideoUrl(asset.url);
};

export const hasConfiguredVideo = (item: SiteContentMaterial) => isVideoUrl(resolveAssetUrl(item.file_url || ""));

export const hasConfiguredMaterial = (item: SiteContentMaterial) => Boolean((item.file_url || "").trim() || (item.cover_url || "").trim());
