const DEFAULT_SITE_NAME = "艺源";

export function adminBrandName(siteName?: string | null): string {
  const normalized = siteName?.trim() || DEFAULT_SITE_NAME;
  return normalized.endsWith("后台") ? normalized : `${normalized}后台`;
}
