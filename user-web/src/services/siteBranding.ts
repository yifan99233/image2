const DEFAULT_SITE_ICON_URL = "/image2ai-icon.svg";

export function applySiteIcon(value?: string | null) {
  const iconUrl = value?.trim() || DEFAULT_SITE_ICON_URL;
  document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((link) => {
    link.href = iconUrl;
  });
}
