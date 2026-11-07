import { CanvasLoading } from "@/components/ui/CanvasLoading";
import { lazy, Suspense, useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { MobileNavigation } from "@/components/layout/MobileNavigation";
import { MOBILE_LAYOUT_QUERY } from "@/hooks/useCreationPanel";
import { Sidebar } from "@/components/layout/Sidebar";
import { SystemAnnouncementModal } from "@/components/layout/SystemAnnouncementModal";
import { Topbar } from "@/components/layout/Topbar";
import { WorkspaceModePrompt } from "@/components/layout/WorkspaceModePrompt";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { useAuthStore } from "@/stores/authStore";

const CanvasWorkspace = lazy(() =>
  import("@/pages/canvas/CanvasWorkspace").then((module) => ({ default: module.CanvasWorkspace })),
);

export const AppLayout = () => {
  const location = useLocation();
  const userId = useAuthStore((state) => state.user?.id);
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);
  const canvasVisible = location.pathname === "/create/canvas";
  const [canvasVisited, setCanvasVisited] = useState(canvasVisible);
  useEffect(() => {
    if (canvasVisible) setCanvasVisited(true);
  }, [canvasVisible]);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isMobileNavigationOpen, setIsMobileNavigationOpen] = useState(false);

  useEffect(() => {
    setIsMobileNavigationOpen(false);
    if (window.matchMedia(MOBILE_LAYOUT_QUERY).matches)
      window.scrollTo({ top: 0, behavior: "instant" });
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobileNavigationOpen) return;
    const navigation = document.getElementById("workspace-navigation");
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    navigation?.querySelector<HTMLButtonElement>(".sidebar__toggle")?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setIsMobileNavigationOpen(false);
      if (event.key !== "Tab" || !navigation) return;
      const focusable = Array.from(
        navigation.querySelectorAll<HTMLElement>("a[href], button"),
      ).filter((element) => element.getClientRects().length > 0);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    const mobileLayout = window.matchMedia(MOBILE_LAYOUT_QUERY);
    const closeOnDesktop = () => {
      if (!mobileLayout.matches) setIsMobileNavigationOpen(false);
    };
    mobileLayout.addEventListener("change", closeOnDesktop);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      mobileLayout.removeEventListener("change", closeOnDesktop);
      window.removeEventListener("keydown", handleKeyDown);
      previousFocus?.focus();
    };
  }, [isMobileNavigationOpen]);

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
    <div
      className={`app-shell app-shell--yiyuan${isMobileNavigationOpen ? " app-shell--nav-open" : ""}`}
    >
      <Sidebar
        collapsed={isSidebarCollapsed && !isMobileNavigationOpen}
        mobileOpen={isMobileNavigationOpen}
        onNavigate={() => setIsMobileNavigationOpen(false)}
        onToggle={() =>
          isMobileNavigationOpen
            ? setIsMobileNavigationOpen(false)
            : setIsSidebarCollapsed((collapsed) => !collapsed)
        }
      />
      {isMobileNavigationOpen && (
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="关闭导航菜单"
          onClick={() => setIsMobileNavigationOpen(false)}
        />
      )}
      <div className="app-shell__main" inert={isMobileNavigationOpen}>
        <Topbar
          navigationOpen={isMobileNavigationOpen}
          onToggleNavigation={() => setIsMobileNavigationOpen((open) => !open)}
        />
        <Outlet />
        {(canvasVisited || canvasVisible) && (
          <Suspense
            fallback={canvasVisible ? <CanvasLoading /> : null}
          >
            <CanvasWorkspace key={userId} visible={canvasVisible} />
          </Suspense>
        )}
      </div>
      <MobileNavigation
        enabledModules={siteConfig.enabled_modules}
        menuOpen={isMobileNavigationOpen}
        onOpenMenu={() => setIsMobileNavigationOpen(true)}
      />
      <WorkspaceModePrompt />
      <SystemAnnouncementModal
        siteConfig={siteConfig}
        announcement={siteConfig.system_announcement}
        userId={userId}
      />
    </div>
  );
};
