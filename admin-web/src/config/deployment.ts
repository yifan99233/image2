const cleanDomain = (value: string | undefined, fallback: string) =>
  (value?.trim() || fallback).replace(/^\.+|\.+$/g, "");

const cleanBaseUrl = (value: string | undefined, fallback: string) =>
  (value?.trim() || fallback).replace(/\/+$/g, "");

export const siteDomainConfig = {
  frontendRootDomain: cleanDomain(import.meta.env.VITE_SITE_FRONTEND_ROOT_DOMAIN, "shyfai.cn"),
  adminRootDomain: cleanDomain(import.meta.env.VITE_SITE_ADMIN_ROOT_DOMAIN, "shyfai.cn"),
  frontendBaseSubdomain: cleanDomain(import.meta.env.VITE_SITE_FRONTEND_BASE_SUBDOMAIN, "magic"),
  adminBaseSubdomain: cleanDomain(import.meta.env.VITE_SITE_ADMIN_BASE_SUBDOMAIN, "magic-admin"),
} as const;

export const publicFrontendUrl = cleanBaseUrl(
  import.meta.env.VITE_SITE_FRONTEND_URL,
  `https://${siteDomainConfig.frontendBaseSubdomain}.${siteDomainConfig.frontendRootDomain}`,
);

export const zpayDefaultUrls = {
  notify: `${publicFrontendUrl}/api/recharge/zpay/notify`,
  return: `${publicFrontendUrl}/billing/recharge`,
} as const;

const siteDomainKey = (siteKey: string) => {
  const normalized = siteKey
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "site";
};

export const generatedSiteUrls = (siteKey: string) => {
  const domainKey = siteDomainKey(siteKey);
  return {
    frontend_url: `https://${siteDomainConfig.frontendBaseSubdomain}-${domainKey}.${siteDomainConfig.frontendRootDomain}`,
    admin_url: `https://${siteDomainConfig.adminBaseSubdomain}-${domainKey}.${siteDomainConfig.adminRootDomain}`,
  };
};
