import { request, uploadMultipart } from "./http";
import type {
  AdminImageModel,
  AdminImageModelInput,
  AdminAccountInput,
  AdminAccountUpdateInput,
  AdminUser,
  AgentAccount,
  AgentConfig,
  AgentConfigInput,
  AgentGroup,
  AgentTransfer,
  AuditLog,
  CreditLedger,
  CustomerOwnerOption,
  DashboardData,
  ImageTask,
  ImageSpec,
  ImageSpecs,
  InviteRewardConfig,
  LeadTrialApplication,
  LeadTrialApplicationStatus,
  LoginResponse,
  MaterialAsset,
  MaterialAssetInput,
  MaterialAssetType,
  MaterialUploadToken,
  ManagedUser,
  ManagedUserCreditBalance,
  ModelPrice,
  ModelPriceBatchInput,
  OpenAgentRelease,
  OpenAgentReleaseInput,
  OpenAgentUploadToken,
  PageResult,
  RechargeOrder,
  RechargePlan,
  SigninRecord,
  SigninRewardConfig,
  SiteConfig,
  UserExperienceConfig,
  UserFeedback,
  UserFeedbackStatus,
  UserLeadModule,
  UserLeadModuleInput,
  ZPayConfig,
  ZPayConfigInput,
} from "../types";

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await request<{ access_token: string; admin: LoginResponse["user"] }>("/admin/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  return { token: data.access_token, user: data.admin };
}

export async function getCurrentAdmin(): Promise<AdminUser> {
  return request<AdminUser>("/admin/auth/me");
}

export async function getDashboard(): Promise<DashboardData> {
  return request<DashboardData>("/admin/dashboard/metrics");
}

export async function getPublicSiteConfig(): Promise<SiteConfig> {
  return request<SiteConfig>("/site/config");
}

export async function getSiteConfig(): Promise<SiteConfig> {
  return request<SiteConfig>("/admin/site/config");
}

export async function getSiteConfigs(): Promise<PageResult<SiteConfig>> {
  return request<PageResult<SiteConfig>>("/admin/site/configs");
}

export async function getSiteContentConfigs(): Promise<PageResult<SiteConfig>> {
  return request<PageResult<SiteConfig>>("/admin/site/content-configs");
}

export async function getSiteContentConfig(): Promise<SiteConfig> {
  return request<SiteConfig>("/admin/site/content-config");
}

export async function createSiteConfig(input: SiteConfig): Promise<SiteConfig> {
  return request<SiteConfig>("/admin/site/configs", { method: "POST", body: JSON.stringify(input) });
}

export async function updateSiteConfig(id: number, input: SiteConfig): Promise<SiteConfig> {
  return request<SiteConfig>(`/admin/site/configs/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function updateSiteContentConfig(id: number, input: SiteConfig): Promise<SiteConfig> {
  return request<SiteConfig>(`/admin/site/content-configs/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function updateCurrentSiteContentConfig(input: SiteConfig): Promise<SiteConfig> {
  return request<SiteConfig>("/admin/site/content-config", { method: "PATCH", body: JSON.stringify(input) });
}

export async function saveSiteConfig(input: SiteConfig): Promise<SiteConfig> {
  return request<SiteConfig>("/admin/site/config", { method: "PATCH", body: JSON.stringify(input) });
}

const pageQuery = (query = "", page = 1, pageSize = 20) =>
  `keyword=${encodeURIComponent(query)}&page_no=${page}&page_size=${pageSize}`;

export type RechargePlanFilters = {
  query?: string;
  status?: "all" | "active" | "inactive";
};

export type RechargeOrderFilters = {
  query?: string;
  status?: "all" | RechargeOrder["status"];
};

export type ModelFilters = {
  query?: string;
  provider?: string;
  status?: "all" | "active" | "inactive";
  capabilityType?: "all" | "image" | "text" | "video" | "multimodal";
  workType?: "all" | "text_to_image" | "image_to_image" | "text_to_video" | "image_to_video" | "text";
  tag?: "all" | "recommended" | "stable" | "new";
};

const appendPageParams = (params: URLSearchParams, page: number, pageSize: number) => {
  params.set("page_no", String(page));
  params.set("page_size", String(pageSize));
  return params;
};

export type VipStatus = "all" | "active" | "expired" | "disabled" | "ordinary";

export async function getUsers(query = "", page = 1, pageSize = 20, vipStatus: VipStatus = "all"): Promise<PageResult<ManagedUser>> {
  return request<PageResult<ManagedUser>>(`/admin/users?${pageQuery(query, page, pageSize)}&vip_status=${vipStatus}`);
}

export async function getCustomerOwners(): Promise<CustomerOwnerOption[]> {
  return request<CustomerOwnerOption[]>("/admin/customer-owners");
}

export async function updateUserCustomerOwner(userId: number, ownerAdminId: number | null): Promise<ManagedUser> {
  return request<ManagedUser>(`/admin/users/${userId}/customer-owner`, {
    method: "PATCH",
    body: JSON.stringify({ owner_admin_id: ownerAdminId }),
  });
}

export async function getUserCreditBalance(id: number): Promise<ManagedUserCreditBalance> {
  return request<ManagedUserCreditBalance>(`/admin/users/${id}/credit-balance`);
}

export async function updateUserStatus(id: number, isActive: boolean): Promise<ManagedUser> {
  return request<ManagedUser>(`/admin/users/${id}/status`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) });
}

export async function updateUserTags(id: number, input: Pick<ManagedUser, "is_internal">): Promise<ManagedUser> {
  return request<ManagedUser>(`/admin/users/${id}/tags`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function updateUserImageConcurrency(id: number, imageConcurrencyLimit: number): Promise<ManagedUser> {
  return request<ManagedUser>(`/admin/users/${id}/image-concurrency`, {
    method: "PATCH",
    body: JSON.stringify({ image_concurrency_limit: imageConcurrencyLimit }),
  });
}

export async function resetUserPassword(id: number, newPassword: string): Promise<{ id: number; changed: boolean }> {
  return request<{ id: number; changed: boolean }>(`/admin/users/${id}/password`, {
    method: "PATCH",
    body: JSON.stringify({ new_password: newPassword }),
  });
}

export async function createUserImpersonation(id: number): Promise<{ login_url: string; expires_in_seconds: number }> {
  return request<{ login_url: string; expires_in_seconds: number }>(`/admin/users/${id}/impersonation`, {
    method: "POST",
  });
}

export async function getFeedbacks(query = "", status: "all" | UserFeedbackStatus = "all", page = 1, pageSize = 20): Promise<PageResult<UserFeedback>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", query);
  params.set("status", status);
  return request<PageResult<UserFeedback>>(`/admin/feedbacks?${params.toString()}`);
}

export async function updateFeedback(id: number, status: UserFeedbackStatus, adminRemark: string): Promise<UserFeedback> {
  return request<UserFeedback>(`/admin/feedbacks/${id}`, { method: "PATCH", body: JSON.stringify({ status, admin_remark: adminRemark }) });
}

export async function getLeadTrialApplications(query = "", status: "all" | LeadTrialApplicationStatus = "all", page = 1, pageSize = 20): Promise<PageResult<LeadTrialApplication>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", query);
  params.set("status", status);
  return request<PageResult<LeadTrialApplication>>(`/admin/lead-trial-applications?${params.toString()}`);
}

export async function updateLeadTrialApplication(id: number, status: LeadTrialApplicationStatus, adminRemark: string): Promise<LeadTrialApplication> {
  return request<LeadTrialApplication>(`/admin/lead-trial-applications/${id}`, { method: "PATCH", body: JSON.stringify({ status, admin_remark: adminRemark }) });
}

export async function getUserLeadModule(id: number): Promise<UserLeadModule> {
  return request<UserLeadModule>(`/admin/users/${id}/lead-module`);
}

export async function saveUserLeadModule(id: number, input: UserLeadModuleInput): Promise<UserLeadModule> {
  return request<UserLeadModule>(`/admin/users/${id}/lead-module`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function getAdminAccounts(query = "", page = 1, pageSize = 20): Promise<PageResult<AdminUser>> {
  return request<PageResult<AdminUser>>(`/admin/admin-accounts?${pageQuery(query, page, pageSize)}`);
}

export async function createAdminAccount(input: AdminAccountInput): Promise<AdminUser> {
  return request<AdminUser>("/admin/admin-accounts", { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminAccount(id: number, input: AdminAccountUpdateInput): Promise<AdminUser> {
  return request<AdminUser>(`/admin/admin-accounts/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function updateAdminAccountStatus(id: number, isActive: boolean): Promise<AdminUser> {
  return request<AdminUser>(`/admin/admin-accounts/${id}/status`, { method: "PATCH", body: JSON.stringify({ is_active: isActive }) });
}

export async function adjustUserCredits(id: number, delta: number, reason: string, idempotencyKey: string): Promise<void> {
  return request<void>(`/admin/users/${id}/credit-adjustments`, {
    method: "POST",
    body: JSON.stringify({ delta, reason, idempotency_key: idempotencyKey }),
  });
}

export async function grantUserTeamEntitlement(
  id: number,
  input: { seat_count: number; duration_days: number; reason: string },
): Promise<void> {
  return request<void>(`/admin/users/${id}/team-entitlements`, { method: "POST", body: JSON.stringify(input) });
}

export async function getCreditLedgers(query = "", page = 1, pageSize = 20): Promise<PageResult<CreditLedger>> {
  return request<PageResult<CreditLedger>>(`/admin/credits/ledger?${pageQuery(query, page, pageSize)}`);
}

export async function markLedger(id: number, reason: string): Promise<void> {
  return request<void>(`/admin/credits/ledger/${id}/mark`, { method: "POST", body: JSON.stringify({ reason }) });
}

export async function getSigninRewardConfig(): Promise<SigninRewardConfig> {
  return request<SigninRewardConfig>("/admin/rewards/signin-config");
}

export async function updateSigninRewardConfig(input: SigninRewardConfig): Promise<SigninRewardConfig> {
  return request<SigninRewardConfig>("/admin/rewards/signin-config", { method: "PATCH", body: JSON.stringify(input) });
}

export async function getUserExperienceConfig(): Promise<UserExperienceConfig> {
  return request<UserExperienceConfig>("/admin/user-experience/config");
}

export async function updateUserExperienceConfig(
  input: Pick<UserExperienceConfig, "max_batch_tasks" | "qiniu_storage_enabled">,
): Promise<UserExperienceConfig> {
  return request<UserExperienceConfig>("/admin/user-experience/config", { method: "PATCH", body: JSON.stringify(input) });
}

export async function getSigninRecords(query = "", page = 1, pageSize = 20): Promise<PageResult<SigninRecord>> {
  return request<PageResult<SigninRecord>>(`/admin/rewards/signin-records?${pageQuery(query, page, pageSize)}`);
}

export async function getRechargePlans(filters: RechargePlanFilters = {}, page = 1, pageSize = 20): Promise<PageResult<RechargePlan>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", filters.query ?? "");
  params.set("status", filters.status ?? "all");
  return request<PageResult<RechargePlan>>(`/admin/recharge/plans?${params.toString()}`);
}

export async function getRechargeOrders(filters: RechargeOrderFilters = {}, page = 1, pageSize = 20): Promise<PageResult<RechargeOrder>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", filters.query ?? "");
  params.set("status", filters.status ?? "all");
  return request<PageResult<RechargeOrder>>(`/admin/recharge/orders?${params.toString()}`);
}

export async function saveRechargePlan(plan: Partial<RechargePlan>): Promise<void> {
  const path = plan.id ? `/admin/recharge/plans/${plan.id}` : "/admin/recharge/plans";
  return request<void>(path, { method: plan.id ? "PATCH" : "POST", body: JSON.stringify(plan) });
}

export async function toggleRechargePlan(id: number): Promise<void> {
  return request<void>(`/admin/recharge/plans/${id}/status`, { method: "PATCH" });
}

export async function getInviteRewardConfig(): Promise<InviteRewardConfig> {
  return request<InviteRewardConfig>("/admin/invite/reward-config");
}

export async function saveInviteRewardConfig(input: Pick<InviteRewardConfig, "is_enabled" | "valid_user_reward_credits" | "recharge_reward_percent">): Promise<InviteRewardConfig> {
  return request<InviteRewardConfig>("/admin/invite/reward-config", {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function getAgentConfig(): Promise<AgentConfig> {
  return request<AgentConfig>("/admin/agent/config");
}

export async function saveAgentConfig(input: AgentConfigInput): Promise<AgentConfig> {
  return request<AgentConfig>("/admin/agent/config", { method: "PATCH", body: JSON.stringify(input) });
}

export async function getZPayConfig(): Promise<ZPayConfig> {
  return request<ZPayConfig>("/admin/payment/zpay-config");
}

export async function saveZPayConfig(input: ZPayConfigInput): Promise<ZPayConfig> {
  return request<ZPayConfig>("/admin/payment/zpay-config", { method: "PATCH", body: JSON.stringify(input) });
}

export async function getAgentGroups(input: Pick<AgentConfigInput, "base_url" | "admin_api_key">): Promise<AgentGroup[]> {
  return request<AgentGroup[]>("/admin/agent/groups", { method: "POST", body: JSON.stringify(input) });
}

export async function getAgentAccounts(query = "", page = 1, pageSize = 20): Promise<PageResult<AgentAccount>> {
  return request<PageResult<AgentAccount>>(`/admin/agent/accounts?${pageQuery(query, page, pageSize)}`);
}

export async function getAgentTransfers(query = "", page = 1, pageSize = 20): Promise<PageResult<AgentTransfer>> {
  return request<PageResult<AgentTransfer>>(`/admin/agent/transfers?${pageQuery(query, page, pageSize)}`);
}

export type OpenAgentReleaseFilters = {
  query?: string;
  channel?: "all" | "prod" | "beta";
  platform?: "all" | "mac" | "windows" | "linux";
  arch?: string;
  status?: "all" | "active" | "inactive";
};

export async function getOpenAgentReleases(filters: OpenAgentReleaseFilters = {}, page = 1, pageSize = 20): Promise<PageResult<OpenAgentRelease>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", filters.query ?? "");
  params.set("channel", filters.channel ?? "all");
  params.set("platform", filters.platform ?? "all");
  params.set("arch", filters.arch ?? "all");
  params.set("status", filters.status ?? "all");
  return request<PageResult<OpenAgentRelease>>(`/admin/openagent/releases?${params.toString()}`);
}

export async function createOpenAgentUploadToken(filename: string): Promise<OpenAgentUploadToken> {
  return request<OpenAgentUploadToken>("/admin/openagent/upload-token", {
    method: "POST",
    body: JSON.stringify({ filename }),
  });
}

export async function saveOpenAgentRelease(input: OpenAgentReleaseInput): Promise<OpenAgentRelease> {
  return request<OpenAgentRelease>("/admin/openagent/releases", { method: "POST", body: JSON.stringify(input) });
}

export async function toggleOpenAgentRelease(id: number): Promise<OpenAgentRelease> {
  return request<OpenAgentRelease>(`/admin/openagent/releases/${id}/status`, { method: "PATCH" });
}

export type MaterialFilters = {
  query?: string;
  assetType?: "all" | MaterialAssetType;
  status?: "all" | "active" | "inactive";
};

export async function getMaterials(filters: MaterialFilters = {}, page = 1, pageSize = 20): Promise<PageResult<MaterialAsset>> {
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", filters.query ?? "");
  params.set("asset_type", filters.assetType ?? "all");
  params.set("status", filters.status ?? "all");
  return request<PageResult<MaterialAsset>>(`/admin/materials?${params.toString()}`);
}

export async function createMaterialUploadToken(filename: string, assetType: MaterialAssetType): Promise<MaterialUploadToken> {
  return request<MaterialUploadToken>("/admin/materials/upload-token", { method: "POST", body: JSON.stringify({ filename, asset_type: assetType }) });
}

export type LocalMaterialUpload = {
  public_url: string;
  key: string;
  mime_type: string;
  file_size: number;
};

export async function uploadMaterialLocally(file: File): Promise<LocalMaterialUpload> {
  const body = new FormData();
  body.append("file", file);
  return uploadMultipart<LocalMaterialUpload>("/admin/materials/local-upload", body);
}

export async function saveMaterial(input: MaterialAssetInput, id?: number): Promise<MaterialAsset> {
  return request<MaterialAsset>(id ? `/admin/materials/${id}` : "/admin/materials", { method: id ? "PATCH" : "POST", body: JSON.stringify(input) });
}

export async function toggleMaterial(id: number): Promise<MaterialAsset> {
  return request<MaterialAsset>(`/admin/materials/${id}/status`, { method: "PATCH" });
}

export async function getImageSpecs(): Promise<ImageSpecs> {
  return request<ImageSpecs>("/admin/image-specs");
}

export async function createImageSpec(kind: "resolutions" | "aspect-ratios" | "durations", input: Partial<ImageSpec>): Promise<ImageSpec> {
  return request<ImageSpec>(`/admin/image-specs/${kind}`, { method: "POST", body: JSON.stringify(input) });
}

export async function updateImageSpec(kind: "resolutions" | "aspect-ratios" | "durations", id: number, input: Partial<ImageSpec>): Promise<ImageSpec> {
  return request<ImageSpec>(`/admin/image-specs/${kind}/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

export async function getModels(filters: ModelFilters | string = {}, page = 1, pageSize = 20): Promise<PageResult<AdminImageModel>> {
  const normalizedFilters: ModelFilters = typeof filters === "string" ? { query: filters } : filters;
  const params = appendPageParams(new URLSearchParams(), page, pageSize);
  params.set("keyword", normalizedFilters.query ?? "");
  params.set("provider", normalizedFilters.provider ?? "");
  params.set("status", normalizedFilters.status ?? "all");
  params.set("capability_type", normalizedFilters.capabilityType === "all" ? "" : normalizedFilters.capabilityType ?? "");
  params.set("work_type", normalizedFilters.workType === "all" ? "" : normalizedFilters.workType ?? "");
  params.set("tag", normalizedFilters.tag ?? "all");
  return request<PageResult<AdminImageModel>>(`/admin/models?${params.toString()}`);
}

export async function createModel(input: AdminImageModelInput): Promise<AdminImageModel> {
  return request<AdminImageModel>("/admin/models", { method: "POST", body: JSON.stringify(input) });
}

export async function saveModel(input: AdminImageModelInput, id?: number): Promise<AdminImageModel> {
  return request<AdminImageModel>(id ? `/admin/models/${id}` : "/admin/models", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(input),
  });
}

export async function toggleModel(id: number): Promise<void> {
  return request<void>(`/admin/models/${id}/status`, { method: "PATCH" });
}

export async function deleteModel(id: number): Promise<{ id: number; deleted_price_count: number }> {
  return request<{ id: number; deleted_price_count: number }>(`/admin/models/${id}`, { method: "DELETE" });
}

export async function updateModelVisibility(id: number, isPublic: boolean): Promise<void> {
  return request<void>(`/admin/models/${id}/visibility`, { method: "PATCH", body: JSON.stringify({ is_public: isPublic }) });
}

export async function updateModelSpecs(
  id: number,
  supportedResolutionIds: number[],
  supportedAspectRatioIds: number[],
  supportedDurationIds: number[] = [],
): Promise<AdminImageModel> {
  return request<AdminImageModel>(`/admin/models/${id}/specs`, {
    method: "PATCH",
    body: JSON.stringify({
      supported_resolution_ids: supportedResolutionIds,
      supported_aspect_ratio_ids: supportedAspectRatioIds,
      supported_duration_ids: supportedDurationIds,
    }),
  });
}

export async function runModelTest(id: number, prompt: string) {
  return request<{ status: "succeeded" | "failed"; duration_ms: number; summary: string }>(`/admin/models/${id}/test`, { method: "POST", body: JSON.stringify({ prompt }) });
}


export async function discoverProviderModels(input: {
  base_url: string;
  api_key?: string;
  provider_code?: string;
  provider_name?: string;
  access_mode?: "api" | "sdk";
  provider_id?: number;
}): Promise<{
  status: "succeeded" | "failed";
  summary: string;
  endpoint?: string;
  provider_kind?: string;
  items: Array<{ id: string; name: string }>;
}> {
  return request(`/admin/models/discover`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}


export async function getVipTiers(siteId?: number): Promise<import("../types").VipTier[]> {
  return request(`/admin/vip-tiers${siteId ? `?site_id=${siteId}` : ""}`);
}
export async function saveVipTier(input: { name: string; discount_rate: number; is_active: boolean; reason: string }, id?: number): Promise<{ id: number }> {
  return request(`/admin/vip-tiers${id ? `/${id}` : ""}`, { method: id ? "PUT" : "POST", body: JSON.stringify(input) });
}
export async function assignCustomerVip(userId: number, input: { tier_id: number | null; expires_at: string | null; reason: string }): Promise<void> {
  return request(`/admin/users/${userId}/vip`, { method: "PUT", body: JSON.stringify(input) });
}

export async function getModelPrices(query = "", page = 1, pageSize = 20): Promise<PageResult<ModelPrice>> {
  return request<PageResult<ModelPrice>>(`/admin/model-prices?${pageQuery(query, page, pageSize)}`);
}

export async function getActiveModelPrices(modelId: number): Promise<ModelPrice[]> {
  const pageSize = 100;
  const prices: ModelPrice[] = [];
  let page = 1;
  let total = 0;
  do {
    const result = await request<PageResult<ModelPrice>>(
      `/admin/model-prices?${pageQuery("", page, pageSize)}&model_id=${modelId}&active_only=true`,
    );
    if (!result.items.length) break;
    prices.push(...result.items);
    total = result.total;
    page += 1;
  } while (prices.length < total);
  return prices;
}

export async function createModelPrice(input: Omit<ModelPrice, "id" | "version" | "effective_at" | "is_active" | "model_name">): Promise<void> {
  return request<void>("/admin/model-prices", { method: "POST", body: JSON.stringify(input) });
}

export async function createModelPricesBatch(input: ModelPriceBatchInput): Promise<{ created_count: number; updated_count: number; unchanged_count: number; ids: number[] }> {
  return request<{ created_count: number; updated_count: number; unchanged_count: number; ids: number[] }>("/admin/model-prices/batch", { method: "POST", body: JSON.stringify(input) });
}

export async function toggleModelPrice(id: number): Promise<void> {
  return request<void>(`/admin/model-prices/${id}/status`, { method: "PATCH" });
}

export async function disableModelPricesBatch(input: { price_ids?: number[]; all_active?: boolean }): Promise<{ updated_count: number; ids: number[] }> {
  return request<{ updated_count: number; ids: number[] }>("/admin/model-prices/batch-status", { method: "PATCH", body: JSON.stringify(input) });
}

export type ImageTaskFilters = { status?: "all" | ImageTask["status"]; galleryReviewStatus?: "all" | ImageTask["gallery_review_status"]; username?: string; userId?: number; keyword?: string };
export async function getImageTasks(query = "", page = 1, pageSize = 20, filters: ImageTaskFilters = {}, signal?: AbortSignal): Promise<PageResult<ImageTask>> {
  const params = new URLSearchParams(pageQuery(query, page, pageSize));
  if (filters.status && filters.status !== "all") params.set("status", filters.status);
  if (filters.galleryReviewStatus && filters.galleryReviewStatus !== "all") params.set("gallery_review_status", filters.galleryReviewStatus);
  if (filters.username?.trim()) params.set("username", filters.username.trim());
  if (filters.userId !== undefined) params.set("user_id", String(filters.userId));
  return request<PageResult<ImageTask>>(`/admin/image-tasks?${params}`, { signal });
}

export async function refundTask(id: number, reason: string): Promise<void> {
  return request<void>(`/admin/image-tasks/${id}/refund`, { method: "POST", body: JSON.stringify({ reason }) });
}

export async function retryTask(id: number): Promise<void> {
  return request<void>(`/admin/image-tasks/${id}/retry`, { method: "POST" });
}

export async function toggleTaskGallery(id: number, featured: boolean, reason?: string): Promise<void> {
  return request<void>(`/admin/image-tasks/${id}/gallery`, { method: "PATCH", body: JSON.stringify({ featured, reason }) });
}

export async function getAuditLogs(query = "", page = 1, pageSize = 20): Promise<PageResult<AuditLog>> {
  return request<PageResult<AuditLog>>(`/admin/audit-logs?${pageQuery(query, page, pageSize)}`);
}
