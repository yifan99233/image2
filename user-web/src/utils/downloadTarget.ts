export type DownloadTarget = {
  url: string;
  canDownloadDirectly: boolean;
  fallbackUrl?: string;
};

export const planDownloadTarget = (
  resolvedUrl: string,
  pageHref: string,
  pageOrigin: string,
): DownloadTarget => {
  const parsedUrl = new URL(resolvedUrl, pageHref);
  const isSharedAsset = parsedUrl.pathname.startsWith("/image2-assets/");
  const isLegacyMagicAsset = isSharedAsset && parsedUrl.hostname?.endsWith("shyfai.com");
  const normalizedUrl = isLegacyMagicAsset && parsedUrl.origin !== pageOrigin
    ? `${pageOrigin}${parsedUrl.pathname}${parsedUrl.search}`
    : parsedUrl.toString();
  const canDownloadDirectly = ["blob:", "data:"].includes(parsedUrl.protocol) || new URL(normalizedUrl, pageHref).origin === pageOrigin;

  return {
    url: normalizedUrl,
    canDownloadDirectly,
    ...(!canDownloadDirectly && isSharedAsset
      ? { fallbackUrl: `${pageOrigin}${parsedUrl.pathname}${parsedUrl.search}` }
      : {}),
  };
};

// Canvas composition needs readable image bytes; user downloads stay streamed.
type DownloadResponse = {
  ok: boolean;
  blob: () => Promise<Blob>;
};

type DownloadFetcher = (url: string, options?: RequestInit) => Promise<DownloadResponse>;

// Preview <img> responses may be cached without CORS headers. A download must
// make a fresh CORS request instead of reusing that opaque preview response.
const CDN_DOWNLOAD_OPTIONS = {
  mode: "cors",
  credentials: "omit",
  cache: "no-store",
} as const;

export const fetchDownloadBlob = async (
  target: DownloadTarget,
  fetcher: DownloadFetcher = fetch,
): Promise<Blob> => {
  try {
    const response = await fetcher(target.url, CDN_DOWNLOAD_OPTIONS);
    if (response.ok) return await response.blob();
  } catch {
    // A legacy asset host may not allow cross-origin reads. Fall back to the
    // current site's shared MinIO proxy when the object path is compatible.
  }

  if (target.fallbackUrl) {
    try {
      const fallbackResponse = await fetcher(target.fallbackUrl, CDN_DOWNLOAD_OPTIONS);
      if (fallbackResponse.ok) return await fallbackResponse.blob();
    } catch {
      // Use the same user-facing failure for network and HTTP errors.
    }
  }

  throw new Error("媒体下载失败，请稍后重试");
};
