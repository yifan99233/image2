import { LoadingArt } from "./LoadingArt";
import { useState } from "react";
import { readCachedSiteConfig } from "@/services/siteConfigStore";

export function SessionLoading() {
  const [site] = useState(readCachedSiteConfig);
  return (
    <main className="session-loading" aria-busy="true">
      <div className="session-loading__content">
        <div className="session-loading__brand"><img src={site.site_icon_url || "/image2ai-icon.svg"} alt="" onError={(event) => { if (event.currentTarget.getAttribute("src") !== "/image2ai-icon.svg") event.currentTarget.src = "/image2ai-icon.svg"; }} /><span>{site.site_name}</span></div>
        <LoadingArt label="正在连接你的创作空间" hint="让灵感，慢慢铺展开" />
      </div>
    </main>
  );
}
