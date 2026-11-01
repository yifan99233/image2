export type AdminRole = "super_admin" | "operator" | "finance" | "model_admin";

export type AdminUser = {
  id: number;
  username: string;
  email: string;
  role: AdminRole;
  system_super_admin: boolean;
  site_id: number;
  site_name?: string;
  is_active: boolean;
  last_login_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  openapi_key?: AdminOpenAPIKey;
};

export type AdminOpenAPIKey = {
  id: number;
  site_id: number;
  name: string;
  key_prefix: string;
  api_key?: string | null;
  scopes: string[];
  is_active: boolean;
  last_used_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type AdminAccountInput = {
  username: string;
  email: string;
  password: string;
  role: AdminRole;
  is_active: boolean;
  create_openapi_key?: boolean;
  openapi_key_name?: string;
  openapi_scopes?: string[];
};

export type AdminAccountUpdateInput = Omit<AdminAccountInput, "password"> & {
  password?: string;
};

export type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export type LoginResponse = {
  token: string;
  user: AdminUser;
};

export type DashboardMetric = {
  key: string;
  label: string;
  value: string;
  trend: string;
  tone: "neutral" | "good" | "warning" | "danger";
};

export type RecentRechargeOrder = {
  order_no: string;
  username: string;
  amount_cents: number;
  credit_amount: number;
  status: RechargeOrderStatus;
  created_at: string;
};

export type RechargeOrderStatus = "pending" | "paid" | "expired" | "cancelled" | "failed";

export type RechargeOrder = {
  id: number;
  order_no: string;
  user_id: number;
  username: string;
  email: string;
  amount_cents: number;
  credit_amount: number;
  bonus_credit_amount: number;
  total_credit_amount: number;
  team_seat_count: number;
  team_duration_days: number;
  status: RechargeOrderStatus;
  payment_provider: string;
  payment_type: string;
  payment_trade_no: string;
  pay_url: string;
  qr_code: string;
  failure_message: string;
  expires_at?: string | null;
  paid_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type RecentFailedModelCall = {
  task_no: string;
  model_name: string;
  username: string;
  latency_ms: number;
  error_message: string;
  created_at: string;
};

export type CreditAlert = {
  id: number;
  title: string;
  detail: string;
  severity: "warning" | "danger";
  created_at: string;
};

export type CustomerOwnerStat = {
  owner_id: number | null;
  owner_name: string;
  customer_count: number;
  paid_customer_count: number;
  paid_order_count: number;
  revenue_cents: number;
};

export type DashboardData = {
  metrics: DashboardMetric[];
  recent_recharge_orders: RecentRechargeOrder[];
  recent_failed_model_calls: RecentFailedModelCall[];
  credit_alerts: CreditAlert[];
  customer_owner_stats: CustomerOwnerStat[];
};

export type SiteConfig = {
  id?: number;
  site_key: string;
  site_name: string;
  site_icon_url: string;
  frontend_url: string;
  admin_url: string;
  is_default: boolean;
  is_enabled: boolean;
  enabled_modules: string[];
  support_qq: string;
  support_wechat: string;
  support_wechat_qrcode_url: string;
  support_email: string;
  homepage_case_carousels: HomepageCaseCarouselItem[][];
  homepage_batch_banners: SiteContentMaterial[];
  lead_case_materials: SiteContentMaterial[];
  opencode_install_video: SiteContentMaterial;
  system_announcement: SystemAnnouncement;
  template_site_id?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type SystemAnnouncement = {
  is_enabled: boolean;
  title: string;
  content: string;
  image_url?: string;
};

export type HomepageCaseCarouselItem = {
  title: string;
  subtitle: string;
  image_url?: string;
  file_url?: string;
  link_url?: string;
  tone?: "blue" | "orange" | "cyan" | "green";
};

export type SiteContentMaterial = {
  title: string;
  subtitle: string;
  file_url?: string;
  cover_url?: string;
  link_url?: string;
  tags?: string[];
  tone?: "blue" | "orange" | "cyan" | "green";
};

export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type VipTier = { id: number; site_id: number; name: string; discount_rate: number; is_active: boolean };
export type CustomerVip = { tier_id: number; name: string; discount_rate: number; is_active: boolean; expires_at: string | null };

export type ManagedUser = {
  site_id?: number;
  vip?: CustomerVip | null;
  id: number;
  username: string;
  email: string;
  phone?: string;
  is_active: boolean;
  is_internal: boolean;
  image_concurrency_limit: number;
  credit_balance: number;
  credit_balance_source?: "authoritative" | "local" | "local_fallback";
  credit_balance_fetched_at?: string | null;
  team_seat_limit?: number;
  lead_module_enabled?: boolean;
  created_at: string;
  last_login_at?: string;
  remark?: string;
  customer_owner_admin_id?: number | null;
  customer_owner_admin_name?: string | null;
};

export type CustomerOwnerOption = {
  id: number;
  username: string;
  email: string;
  role: AdminRole;
};

export type ManagedUserCreditBalance = {
  user_id: number;
  balance: number;
  source: "authoritative" | "local" | "local_fallback";
  fetched_at?: string | null;
};

export type UserFeedbackStatus = "pending" | "processing" | "resolved" | "closed";

export type UserFeedback = {
  id: number;
  user_id: number;
  username: string;
  email: string;
  description: string;
  image_urls: string[];
  status: UserFeedbackStatus;
  admin_remark: string;
  handled_by?: number | null;
  handled_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type UserLeadModule = {
  id?: number;
  user_id?: number;
  is_enabled: boolean;
  enterprise_id?: string;
  enterprise_account?: string;
  credentials_revealed_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type UserLeadModuleInput = {
  is_enabled: boolean;
  enterprise_id: string;
  enterprise_account: string;
  enterprise_password?: string;
};

export type LeadTrialApplicationStatus = "pending" | "processing" | "approved" | "rejected";

export type LeadTrialApplication = {
  id: number;
  user_id: number;
  username: string;
  email: string;
  is_active: boolean;
  is_internal: boolean;
  credit_balance: number;
  lead_module_enabled: boolean;
  business_scope: string;
  keywords: string;
  competitor_accounts: string;
  contact_info: string;
  status: LeadTrialApplicationStatus;
  admin_remark: string;
  handled_by_admin_id?: number | null;
  handled_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type CreditLedger = {
  id: number;
  username: string;
  biz_type: "recharge" | "image_task" | "refund" | "admin_adjustment" | "signin" | "invite";
  change_amount: number;
  balance_after: number;
  related_no?: string;
  reason?: string;
  flag_reason?: string;
  is_flagged: boolean;
  created_at: string;
};

export type SigninRewardConfig = {
  is_enabled: boolean;
  daily_credits: number;
  updated_at?: string | null;
};

export type UserExperienceConfig = {
  max_batch_tasks: number;
  qiniu_storage_enabled: boolean;
  updated_at?: string | null;
};

export type SigninRecord = {
  id: number;
  user_id: number;
  username: string;
  email: string;
  sign_date: string;
  awarded_credits: number;
  streak_days: number;
  created_at: string;
};

export type RechargePlan = {
  id: number;
  name: string;
  amount_cents: number;
  credit_amount: number;
  bonus_credit_amount: number;
  team_seat_count: number;
  team_duration_days: number;
  badge?: string;
  sort_order: number;
  is_recommended: boolean;
  is_active: boolean;
};

export type InviteRewardConfig = {
  is_enabled: boolean;
  valid_user_reward_credits: number;
  recharge_reward_percent: number;
  valid_user_rule: "invited_user_first_paid_recharge" | string;
  valid_user_rule_label: string;
  updated_at?: string | null;
};

export type AgentConfig = {
  is_enabled: boolean;
  image_billing_enabled: boolean;
  base_url: string;
  admin_api_key_masked: string;
  credit_to_agent_rate: number;
  text_group_id?: number | null;
  image_group_id?: number | null;
  key_group_whitelist?: number[];
  create_api_key_path: string;
  user_concurrency: number;
  user_rpm_limit: number;
  updated_at?: string | null;
};

export type AgentConfigInput = Omit<AgentConfig, "admin_api_key_masked" | "updated_at"> & {
  admin_api_key?: string;
};

export type ZPayConfig = {
  is_enabled: boolean;
  pid: string;
  pkey_masked: string;
  api_base: string;
  notify_url: string;
  return_url: string;
  payment_type: "alipay" | "wxpay" | "qqpay" | "bank" | "jdpay";
  payment_mode: "qrcode" | "popup";
  timeout_seconds: number;
  order_expire_minutes: number;
  updated_at?: string | null;
};

export type ZPayConfigInput = Omit<ZPayConfig, "pkey_masked" | "updated_at"> & {
  pkey?: string;
};

export type AgentGroup = {
  id: number;
  name: string;
  platform: string;
  is_active: boolean;
};

export type AgentAccount = {
  id: number;
  user_id: number;
  username: string;
  email: string;
  agent_user_id?: number | null;
  agent_email: string;
  status: "pending" | "active" | "failed";
  failure_message?: string | null;
  text_api_key_masked: string;
  image_api_key_masked: string;
  created_at: string;
};

export type AgentTransfer = {
  id: number;
  username: string;
  email: string;
  credit_amount: number;
  agent_amount: number;
  agent_user_id?: number | null;
  status: "pending" | "succeeded" | "failed";
  failure_message?: string | null;
  created_at: string;
};

export type OpenAgentRelease = {
  id: number;
  site_id: number;
  channel: "prod" | "beta";
  version: string;
  platform: "mac" | "windows" | "linux";
  arch: string;
  file_url: string;
  file_sha512: string;
  file_size: number;
  release_notes: string;
  is_active: boolean;
  is_mandatory: boolean;
  published_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type OpenAgentReleaseInput = Omit<OpenAgentRelease, "id" | "site_id" | "published_at" | "created_at" | "updated_at">;

export type OpenAgentUploadToken = {
  upload_url: string;
  token: string;
  key: string;
  public_url: string;
};

export type MaterialAssetType = "video" | "image" | "file";

export type MaterialAsset = {
  id: number;
  asset_type: MaterialAssetType;
  title: string;
  description: string;
  file_url: string;
  cover_url: string;
  mime_type: string;
  file_size: number;
  sort_order: number;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MaterialAssetInput = Omit<MaterialAsset, "id" | "created_at" | "updated_at">;

export type MaterialUploadToken = OpenAgentUploadToken;

export type ImageSpec = {
  id: number;
  code: string;
  label: string;
  sort_order: number;
  is_active: boolean;
};

export type ImageSpecs = {
  resolutions: ImageSpec[];
  aspect_ratios: ImageSpec[];
  durations: ImageSpec[];
};

export type AdminImageModel = {
  id: number;
  provider_id?: number;
  provider_name: string;
  provider_code?: string;
  capability_type?: "image" | "text" | "video" | "multimodal";
  supports_image_edit?: boolean;
  name: string;
  code: string;
  vendor_model: string;
  work_type: string;
  description?: string;
  base_url?: string;
  access_mode: "api" | "sdk";
  base_url_masked: string;
  api_key_masked: string;
  is_recommended: boolean;
  is_stable: boolean;
  is_new: boolean;
  max_input_images?: number;
  max_output_images?: number;
  concurrency_limit?: number;
  is_active: boolean;
  is_public: boolean;
  sort_order: number;
  supported_resolutions: ImageSpec[];
  supported_aspect_ratios: ImageSpec[];
  supported_durations?: ImageSpec[];
  storage_mode?: "local" | "third_party" | "native";
  timeout_seconds?: number | null;
  disable_retry?: boolean;
};

export type AdminImageModelInput = {
  provider_id?: number;
  provider_name: string;
  provider_code: string;
  base_url: string;
  access_mode: "api" | "sdk";
  api_key: string;
  capability_type: "image" | "text" | "video";
  image_capabilities: Array<"text_to_image" | "image_to_image">;
  video_capabilities: Array<"text_to_video" | "image_to_video">;
  supported_resolution_ids: number[];
  supported_aspect_ratio_ids: number[];
  supported_duration_ids: number[];
  supports_image_edit: boolean;
  name: string;
  code: string;
  vendor_model: string;
  work_type: string;
  description: string;
  is_recommended: boolean;
  is_stable: boolean;
  is_new: boolean;
  max_input_images: number;
  max_output_images: number;
  concurrency_limit: number;
  sort_order: number;
  is_active: boolean;
  is_public: boolean;
  storage_mode?: "local" | "third_party" | "native";
  timeout_seconds?: number | null;
  disable_retry: boolean;
};

export type ModelPrice = {
  quality?: "any" | "low" | "medium" | "high";
  id: number;
  model_id: number;
  model_name: string;
  work_type: string;
  resolution: string;
  aspect_ratio: string;
  output_count: number;
  credit_cost: number;
  fixed_surcharge: number;
  version: number;
  effective_at: string;
  is_active: boolean;
  change_reason: string;
};

export type ModelPriceBatchInput = {
  quality?: "any" | "low" | "medium" | "high";
  model_id: number;
  work_types: string[];
  resolutions: string[];
  aspect_ratios: string[];
  output_count: number;
  price_matrix: Record<string, Record<string, number>>;
  price_entries?: Array<{
    work_type: string;
    resolution: string;
    aspect_ratio: string;
    credit_cost: number;
    fixed_surcharge?: number;
  }>;
  change_reason: string;
};

export type ImageTask = {
  id: number;
  user_id: number;
  task_no: string;
  username: string;
  model_name: string;
  work_type?: string;
  status: "pending" | "queued" | "running" | "succeeded" | "failed" | "refunded";
  credit_cost: number;
  prompt: string;
  failure_message?: string;
  input_image_url?: string | null;
  output_image_url?: string | null;
  is_gallery_featured: boolean;
  gallery_review_status?: "none" | "pending" | "approved" | "rejected";
  deleted_at?: string | null;
  gallery_title?: string | null;
  gallery_sort_order: number;
  gallery_featured_at?: string | null;
  created_at: string;
  worker_started_at?: string | null;
  finished_at?: string;
  queue_duration_seconds?: number | null;
  generation_duration_seconds?: number | null;
  total_duration_seconds?: number | null;
};

export type AuditLog = {
  id: number;
  admin_username: string;
  action: string;
  resource_type: string;
  resource_id: string;
  reason?: string;
  created_at: string;
};
