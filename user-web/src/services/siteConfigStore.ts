import { defaultSiteConfig, siteService } from "@/services/site";
import type { SiteConfig } from "@/types/api";
import { applySiteBranding } from "@/services/siteBranding";

let cachedSiteConfig: SiteConfig | null = null;
let pendingSiteConfig: Promise<SiteConfig> | null = null;

export function readCachedSiteConfig() {
  return cachedSiteConfig ?? defaultSiteConfig;
}

export async function loadSiteConfig() {
  if (cachedSiteConfig) {
    applySiteBranding(cachedSiteConfig);
    return cachedSiteConfig;
  }
  if (!pendingSiteConfig) {
    pendingSiteConfig = siteService
      .getConfig()
      .then((config) => {
        cachedSiteConfig = config;
        applySiteBranding(config);
        return config;
      })
      .catch(() => {
        applySiteBranding();
        return defaultSiteConfig;
      })
      .finally(() => {
        pendingSiteConfig = null;
      });
  }
  return pendingSiteConfig;
}
