import type { SiteConfig } from "@/types/api";

export function rechargePath(site: Pick<SiteConfig, "site_key" | "is_enabled" | "enabled_modules">) {
  // The main site uses customer support; enabled subsites retain online recharge.
  return site.site_key && site.site_key !== "main" && site.is_enabled && site.enabled_modules.includes("recharge")
    ? "/billing/recharge"
    : "/support";
}
