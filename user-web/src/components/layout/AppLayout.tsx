import { lazy, Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { SystemAnnouncementModal } from "@/components/layout/SystemAnnouncementModal";
import { Topbar } from "@/components/layout/Topbar";
import { WorkspaceModePrompt } from "@/components/layout/WorkspaceModePrompt";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { useAuthStore } from "@/stores/authStore";

const CanvasWorkspace = lazy(() => import("@/pages/canvas/CanvasWorkspace").then((module) => ({ default: module.CanvasWorkspace })));

export const AppLayout = () => {
  const location = useLocation();
  const userId = useAuthStore((state) => state.user?.id);
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);
  const canvasVisible = location.pathname === "/create/canvas";
  const [canvasVisited, setCanvasVisited] = useState(canvasVisible);
  useEffect(() => { if (canvasVisible) setCanvasVisited(true); }, [canvasVisible]);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  useEffect(() => {
    const collapse = () => setIsSidebarCollapsed(true);
    window.addEventListener("image2:collapse-sidebar", collapse);
    return () => window.removeEventListener("image2:collapse-sidebar", collapse);
  }, []);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  return (
    <div className="app-shell app-shell--yiyuan">
      <Sidebar
        collapsed={isSidebarCollapsed}
        onToggle={() => setIsSidebarCollapsed((collapsed) => !collapsed)}
      />
      <div className="app-shell__main">
        <Topbar />
        <Outlet />
        {(canvasVisited || canvasVisible) && <Suspense fallback={canvasVisible ? <div className="list-state">正在加载画布…</div> : null}>
          <CanvasWorkspace key={userId} visible={canvasVisible} />
        </Suspense>}
      </div>
      <WorkspaceModePrompt />
      <SystemAnnouncementModal siteConfig={siteConfig} announcement={siteConfig.system_announcement} userId={userId} />
    </div>
  );
};
