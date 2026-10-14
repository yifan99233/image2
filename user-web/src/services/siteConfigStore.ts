import { defaultSiteConfig, siteService } from "@/services/site";
import type { SiteConfig } from "@/types/api";
import { applySiteIcon } from "@/services/siteBranding";

let cachedSiteConfig: SiteConfig | null = null;
let pendingSiteConfig: Promise<SiteConfig> | null = null;

export function readCachedSiteConfig() {
  return cachedSiteConfig ?? defaultSiteConfig;
}

export async function loadSiteConfig() {
  if (cachedSiteConfig) return cachedSiteConfig;
  if (!pendingSiteConfig) {
    pendingSiteConfig = siteService
      .getConfig()
      .then((config) => {
        cachedSiteConfig = config;
        applySiteIcon(config.site_icon_url);
        return config;
      })
      .catch(() => {
        applySiteIcon(defaultSiteConfig.site_icon_url);
        return defaultSiteConfig;
      })
      .finally(() => {
        pendingSiteConfig = null;
      });
  }
  return pendingSiteConfig;
}
