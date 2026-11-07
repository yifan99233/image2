const DEFAULT_SITE_ICON_URL = "/image2ai-icon.svg";

export function applySiteBranding(config?: { site_name?: string | null; site_icon_url?: string | null }) {
  document.title = config?.site_name?.trim() || "AI 创作平台";
  applySiteIcon(config?.site_icon_url);
}

export function applySiteIcon(value?: string | null) {
  const iconUrl = value?.trim() || DEFAULT_SITE_ICON_URL;
  document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((link) => {
    link.href = iconUrl;
  });
}
