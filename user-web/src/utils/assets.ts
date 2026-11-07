import { appConfig } from "@/config/env";

export const resolveAssetUrl = (url: string) => {
  if (/^https?:\/\//i.test(url) || url.startsWith("blob:") || url.startsWith("data:")) return url;
  if (!url.startsWith("/")) return url;
  return `${appConfig.apiBaseUrl.replace(/\/$/, "")}${url}`;
};
