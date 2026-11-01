import { resolveAssetUrl } from "@/utils/assets";
import { planDownloadTarget } from "@/utils/downloadTarget";
import { streamBrowserDownload } from "@/utils/streamingDownload";

const extensionByMime: Record<string, string> = {
  "image/jpeg": "jpg",
  "image/png": "png",
  "image/webp": "webp",
  "video/mp4": "mp4",
  "video/webm": "webm",
  "video/quicktime": "mov",
  "video/x-m4v": "m4v",
};

const withMediaExtension = (fileName: string, mimeType?: string) => {
  if (/\.(jpe?g|png|webp|mp4|webm|mov|m4v)$/i.test(fileName)) return fileName;
  const extension = mimeType ? extensionByMime[mimeType] : undefined;
  const fallback = mimeType?.startsWith("video/") ? "mp4" : "png";
  return `${fileName}.${extension ?? fallback}`;
};

export const downloadImage = async (url: string, fileName: string, mimeType?: string) => {
  return downloadMedia(url, fileName, mimeType);
};

const resolveDownloadTarget = (url: string) => {
  const resolvedUrl = resolveAssetUrl(url);
  return planDownloadTarget(resolvedUrl, window.location.href, window.location.origin);
};

export const downloadMedia = async (url: string, fileName: string, mimeType?: string) => {
  const target = resolveDownloadTarget(url);
  if (!target.canDownloadDirectly) {
    await streamBrowserDownload(target, withMediaExtension(fileName, mimeType));
    return;
  }

  const link = document.createElement("a");
  link.href = target.url;
  link.download = withMediaExtension(fileName, mimeType);
  document.body.appendChild(link);
  link.click();
  link.remove();
};

export const downloadBlob = (blob: Blob, fileName: string) => {
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Let the browser start consuming the object URL before releasing it. This
  // matters for large ZIP exports, where an immediate revoke can cancel the
  // download in Safari and some Chromium versions.
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
};

export const startBrowserDownload = (url: string) => {
  const link = document.createElement("a");
  link.href = url;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
};
