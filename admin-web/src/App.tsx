import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { RedemptionCodesPage } from "./pages/RedemptionCodesPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { VipTiersPage, VipCustomersPage } from "./pages/management/VipPages";
import { CustomerUsersPage } from "./pages/management/CustomerUsersPage";
import { AnnouncementsPage } from "./pages/AnnouncementsPage";
import {
  AuditLogsPage,
  AgentPage,
  CreditsPage,
  FeedbacksPage,
  ImageSpecsPage,
  InviteRewardPage,
  LeadApplicationsPage,
  MaterialsPage,
  ModelPricesPage,
  ModelsPage,
  OpenAgentReleasesPage,
  RechargeOrdersPage,
  RechargePlansPage,
  SigninRewardsPage,
  SiteConfigPage,
  SiteContentPage,
  TasksPage,
  UserExperiencePage,
  UsersPage,
  ZPayConfigPage,
} from "./pages/ManagementPages";
import { useThemeMode } from "./store/theme";

export function App() {
  const themeMode = useThemeMode();

  useEffect(() => {
    document.documentElement.dataset.theme = themeMode;
  }, [themeMode]);

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="site-config" element={<SiteConfigPage />} />
        <Route path="announcements" element={<AnnouncementsPage />} />
        <Route path="site-content" element={<SiteContentPage />} />
        <Route path="admin-accounts" element={<UsersPage />} />
        <Route path="users" element={<CustomerUsersPage />} />
        <Route path="vip-tiers" element={<VipTiersPage />} />
        <Route path="vip-customers" element={<VipCustomersPage />} />
        <Route path="lead-applications" element={<LeadApplicationsPage />} />
        <Route path="feedbacks" element={<FeedbacksPage />} />
        <Route path="credits" element={<CreditsPage />} />
        <Route path="signin-rewards" element={<SigninRewardsPage />} />
        <Route path="invite-reward" element={<InviteRewardPage />} />
        <Route path="payment/zpay" element={<ZPayConfigPage />} />
        <Route path="user-experience" element={<UserExperiencePage />} />
        <Route path="agent" element={<AgentPage />} />
        <Route path="openagent-releases" element={<OpenAgentReleasesPage />} />
        <Route path="recharge-orders" element={<RechargeOrdersPage />} />
        <Route path="redemption-codes" element={<RedemptionCodesPage />} />
        <Route path="recharge-plans" element={<RechargePlansPage />} />
        <Route path="image-specs" element={<ImageSpecsPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="model-prices" element={<ModelPricesPage />} />
        <Route path="materials" element={<MaterialsPage />} />
        <Route path="tasks" element={<TasksPage />} />
        <Route path="audit-logs" element={<AuditLogsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
