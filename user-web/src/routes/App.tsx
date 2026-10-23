import { LoadingState } from "@/components/ui/LoadingState";
import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppLayout } from "@/components/layout/AppLayout";
import { ProtectedRoute } from "@/routes/ProtectedRoute";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { AdminImpersonationPage } from "@/pages/AdminImpersonationPage";
import { WorkbenchPage } from "@/pages/WorkbenchPage";
import { MaterialLibraryPage } from "@/pages/MaterialLibraryPage";
import { WorksPage } from "@/pages/WorksPage";
import { AccountProfilePage, AccountSettingsPage } from "@/pages/AccountPages";
import { CreditsLedgerPage } from "@/pages/CreditsLedgerPage";
import { TeamSettingsPage } from "@/pages/TeamPage";
import { PlaceholderPage } from "@/pages/PlaceholderPage";
import {
  CreativeToolPage,
  DashboardPage,
  DeveloperApiPage,
  FeedbackPage,
  GalleryPage,
  InvitePage,
  LeadModulePage,
  LicensePage,
  OpenAgentInstallPage,
  OpenAgentKeysPage,
  OpenAgentUsagePage,
  ProductToolPage,
  SigninPage,
  SupportPage,
} from "@/pages/AdditionalPages";
import { useAuthStore } from "@/stores/authStore";
import { useThemeStore } from "@/stores/themeStore";

const GrokImaginePage = lazy(() =>
  import("@/pages/tools/GrokImaginePage").then((module) => ({ default: module.GrokImaginePage })),
);

export const App = () => {
  const initializeSession = useAuthStore((state) => state.initializeSession);
  const themeMode = useThemeStore((state) => state.themeMode);
  const location = useLocation();
  const isAdminLogin = location.pathname === "/admin-login";

  useEffect(() => {
    if (isAdminLogin) return;
    void initializeSession();
  }, [initializeSession, isAdminLogin]);

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
  }, [themeMode]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/r/:referralToken" element={<RegisterPage />} />
      <Route path="/admin-login" element={<AdminImpersonationPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<AppLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/gallery" element={<GalleryPage />} />
          <Route
            path="/create/imagine"
            element={
              <Suspense fallback={<LoadingState label="正在加载创作工作台…" variant="cards" />}>
                <GrokImaginePage />
              </Suspense>
            }
          />
          <Route path="/create/canvas" element={null} />
          <Route path="/create/edit" element={<WorkbenchPage />} />
          <Route path="/create/text-to-image" element={<CreativeToolPage mode="text-to-image" />} />
          <Route path="/create/text-to-video" element={<CreativeToolPage mode="text-to-video" />} />
          <Route path="/create/image-to-video" element={<CreativeToolPage mode="image-to-video" />} />
          <Route path="/create/batch-generate" element={<CreativeToolPage mode="batch-generate" />} />
          <Route path="/create/batch-edit" element={<CreativeToolPage mode="batch-edit" />} />
          <Route path="/materials" element={<MaterialLibraryPage />} />
          <Route path="/works" element={<WorksPage />} />
          <Route path="/leads" element={<LeadModulePage />} />
          <Route path="/account/profile" element={<AccountProfilePage />} />
          <Route path="/account/settings" element={<AccountSettingsPage />} />
          <Route path="/credits/ledger" element={<CreditsLedgerPage />} />
          <Route path="/billing/recharge" element={<Navigate to="/support" replace />} />
          <Route path="/team" element={<TeamSettingsPage />} />
          <Route path="/product/try-on" element={<ProductToolPage mode="try-on" />} />
          <Route path="/product/multi-view" element={<ProductToolPage mode="multi-view" />} />
          <Route path="/product/pose" element={<ProductToolPage mode="pose" />} />
          <Route path="/product/ootd" element={<ProductToolPage mode="ootd" />} />
          <Route path="/product/background" element={<ProductToolPage mode="background" />} />
          <Route path="/product/scene" element={<ProductToolPage mode="scene" />} />
          <Route path="/support" element={<SupportPage />} />
          <Route path="/feedback" element={<FeedbackPage />} />
          <Route path="/rewards/signin" element={<SigninPage />} />
          <Route path="/rewards/invite" element={<InvitePage />} />
          <Route path="/opencode/install" element={<OpenAgentInstallPage />} />
          <Route path="/opencode/keys" element={<OpenAgentKeysPage />} />
          <Route path="/opencode/usage" element={<OpenAgentUsagePage />} />
          <Route path="/developer/api" element={<DeveloperApiPage />} />
          <Route path="/developer/openclaw" element={<DeveloperApiPage />} />
          <Route path="/license" element={<LicensePage />} />
          <Route path="/billing/license" element={<LicensePage />} />
          <Route path="*" element={<PlaceholderPage />} />
        </Route>
      </Route>
    </Routes>
  );
};
