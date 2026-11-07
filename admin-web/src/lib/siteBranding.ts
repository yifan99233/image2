export const DEFAULT_SITE_ICON_URL = "/image2ai-icon.svg";
export const SITE_ICON_UPDATED_EVENT = "image2:site-icon-updated";

export function resolveSiteIconUrl(value?: string | null) {
  return value?.trim() || DEFAULT_SITE_ICON_URL;
}

export function applySiteIcon(value?: string | null) {
  const iconUrl = resolveSiteIconUrl(value);
  document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]').forEach((link) => {
    link.href = iconUrl;
  });
}

export function publishSiteIcon(value?: string | null) {
  const iconUrl = resolveSiteIconUrl(value);
  applySiteIcon(iconUrl);
  window.dispatchEvent(new CustomEvent<string>(SITE_ICON_UPDATED_EVENT, { detail: iconUrl }));
}
