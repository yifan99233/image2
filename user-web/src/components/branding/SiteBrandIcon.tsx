import { useEffect, useState } from "react";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";

type SiteBrandIconProps = {
  className?: string;
};

export const SiteBrandIcon = ({ className }: SiteBrandIconProps) => {
  const [iconUrl, setIconUrl] = useState(readCachedSiteConfig().site_icon_url);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setIconUrl(config.site_icon_url);
    });
    return () => {
      ignore = true;
    };
  }, []);

  return <img className={className} src={iconUrl || "/image2ai-icon.svg"} alt="" />;
};
