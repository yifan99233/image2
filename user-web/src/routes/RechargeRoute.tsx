import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { LoadingState } from "@/components/ui/LoadingState";
import { RechargePage } from "@/pages/RechargePage";
import { loadSiteConfig } from "@/services/siteConfigStore";
import type { SiteConfig } from "@/types/api";
import { rechargePath } from "@/utils/rechargeAccess";

export function RechargeRoute() {
  const [siteConfig, setSiteConfig] = useState<SiteConfig | null>(null);

  useEffect(() => {
    let ignore = false;
    void loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => { ignore = true; };
  }, []);

  // Wait for the real site instead of redirecting from the default main config.
  if (!siteConfig) return <LoadingState label="正在加载充值配置…" />;
  if (rechargePath(siteConfig) === "/support") return <Navigate to="/support" replace />;
  return <RechargePage />;
}
