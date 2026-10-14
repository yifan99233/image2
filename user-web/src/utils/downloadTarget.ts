export type DownloadTarget = {
  url: string;
  canDownloadDirectly: boolean;
  fallbackUrl?: string;
};

type DownloadResponse = {
  ok: boolean;
  blob: () => Promise<Blob>;
};

type DownloadFetcher = (url: string) => Promise<DownloadResponse>;

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
  const canDownloadDirectly = new URL(normalizedUrl, pageHref).origin === pageOrigin;

  return {
    url: normalizedUrl,
    canDownloadDirectly,
    ...(!canDownloadDirectly && isSharedAsset
      ? { fallbackUrl: `${pageOrigin}${parsedUrl.pathname}${parsedUrl.search}` }
      : {}),
  };
};

export const fetchDownloadBlob = async (
  target: DownloadTarget,
  fetcher: DownloadFetcher = fetch,
): Promise<Blob> => {
  try {
    const response = await fetcher(target.url);
    if (response.ok) return response.blob();
  } catch {
    // A legacy asset host may not allow cross-origin reads. Fall back to the
    // current site's shared MinIO proxy when the object path is compatible.
  }

  if (target.fallbackUrl) {
    try {
      const fallbackResponse = await fetcher(target.fallbackUrl);
      if (fallbackResponse.ok) return fallbackResponse.blob();
    } catch {
      // Use the same user-facing failure for network and HTTP errors.
    }
  }

  throw new Error("媒体下载失败，请稍后重试");
};
