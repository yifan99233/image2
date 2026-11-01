export type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export type ApiErrorPayload = {
  code: number;
  message: string;
  data: null;
};

export type AuthUser = {
  id: number;
  username: string;
  email: string;
  nickname?: string | null;
  avatar_url?: string | null;
  is_active: boolean;
  invited_by_user_id?: number | null;
  created_at?: string | null;
  last_login_at?: string | null;
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

export type ProfileUpdateRequest = {
  email: string;
  nickname?: string | null;
  avatar_url?: string | null;
};

export type CreditBalance = {
  gift_balance: number;
  total_gifted: number;
  balance: number;
  total_recharged: number;
  total_consumed: number;
};

export type ImageAsset = {
  id: number;
  url: string;
  local_url?: string | null;
  r2_url?: string | null;
  r2_expires_at?: string | null;
  thumbnail_url?: string;
  mime_type: string;
  width?: number | null;
  height?: number | null;
  size_bytes: number;
  sha256: string;
  source: "upload" | "generated" | "model_output";
};

export type MaterialFolder = {
  id: number;
  parent_id?: number | null;
  name: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type MaterialAsset = {
  id: number;
  folder_id?: number | null;
  name: string;
  asset: ImageAsset;
  created_at?: string | null;
  updated_at?: string | null;
};

export type UserFeedbackStatus = "pending" | "processing" | "resolved" | "closed";

export type UserFeedback = {
  id: number;
  description: string;
  image_urls: string[];
  status: UserFeedbackStatus;
  admin_remark: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type LoginRequest = {
  username: string;
  password: string;
};

export type RegisterRequest = {
  username: string;
  email: string;
  password: string;
  invite_code?: string;
  referral_token?: string;
  team_invite_token?: string;
};

export type TeamInvitePreview = {
  team_name: string;
  site_name: string;
  expires_at: string;
};

export type LoginResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};

export type PublicKeyResponse = {
  public_key: string;
};

export type ModelOption = {
  value: string;
  label: string;
};

export type ImageModel = {
  id: number;
  name: string;
  code: string;
  work_type: string;
  capability_type?: "image" | "video" | string;
  description: string;
  is_recommended: boolean;
  is_stable: boolean;
  is_new: boolean;
  speed_hint?: string | null;
  risk_hint?: string | null;
  max_input_images: number;
  max_output_images: number;
  images_per_generation?: number;
  storage_mode?: "local" | "third_party" | "native" | string;
  supports_quality?: boolean;
  supports_custom_size?: boolean;
  supports_output_format?: boolean;
  supported_resolutions: ModelOption[];
  supported_aspect_ratios: ModelOption[];
  supported_durations?: ModelOption[];
};

export type ImageTaskStatus = "pending" | "queued" | "running" | "succeeded" | "failed" | "refunded";
export type ImageOutputFormat = "png" | "jpeg" | "webp";

export type ImageQuality = "auto" | "low" | "medium" | "high";
export type ImageTaskProgressStage = ImageTaskStatus | "generating" | "downloading";

export type ImageTask = {
  output_expired_at?: string | null;
  id: number;
  task_no: string;
  batch_id?: string;
  input_group_id?: string;
  input_group_name?: string;
  input_group_path?: string;
  work_type: string;
  model_id: number;
  model_name: string;
  prompt: string;
  resolution: string;
  aspect_ratio: string;
  quality: ImageQuality;
  size?: string | null;
  output_format?: ImageOutputFormat | null;
  duration?: string;
  credit_cost: number;
  status: ImageTaskStatus;
  progress_stage: ImageTaskProgressStage;
  failure_message?: string | null;
  input_images: ImageAsset[];
  output_images: ImageAsset[];
  is_collected: boolean;
  owner_user_id?: number | null;
  owner_name?: string;
  created_at: string;
  worker_started_at?: string | null;
  finished_at?: string | null;
  queue_duration_seconds?: number | null;
  generation_duration_seconds?: number | null;
  total_duration_seconds?: number | null;
};

export type ImageQuote = {
  credit_cost: number;
  pricing?: { base_price: string; discount_rate: string; fixed_surcharge: string; vip_tier_name: string };
};

export type ImageBatchSummary = {
  retry_submission_status?: string;
  retry_submission_error?: string | null;
  submission_status?: string;
  submission_error?: string | null;
  batch_id: string;
  latest_task_id: number;
  created_at: string;
  task_count: number;
  pending_count: number;
  queued_count: number;
  running_count: number;
  succeeded_count: number;
  failed_count: number;
  downloadable_count: number;
  retryable_count: number;
  already_retried_count: number;
  retry_of_batch_id: string | null;
};
export type ImageBatchRetryQuote = {
  batch_id: string;
  task_count: number;
  task_ids: number[];
  total_credit_cost: number;
  quote_token: string;
};
export type ImageBatchPage = { items: ImageBatchSummary[]; has_more: boolean; next_cursor: number | null };
export type ImageBatchSubmission = { batch_id: string; task_count: number; task_ids: number[]; tasks: ImageTask[]; submission_status?: string; submission_error?: string | null };

export type CreateImageTaskRequest = {
  prompts?: string[];
  folder_names?: string[];
  work_type: string;
  batch_id?: string;
  model_id: number;
  prompt: string;
  prompt_mode?: "shared" | "per_image" | "matrix" | "grouped";
  groups?: { group_id: string; group_name: string; group_path?: string; prompt: string; input_image_ids: number[]; output_count: number }[];
  negative_prompt?: string;
  resolution: string;
  aspect_ratio: string;
  quality?: ImageQuality;
  size?: string;
  output_format?: ImageOutputFormat;
  duration?: string;
  input_image_ids: number[];
  input_image_url?: string;
  input_image_urls?: string[];
  output_count: number;
  /** Requested number of variants for batch-compatible image generation. */
  n?: number;
};

export type RechargePlan = {
  id: number;
  name: string;
  amount_cents: number;
  credit_amount: number;
  bonus_credit_amount: number;
  total_credit_amount: number;
  team_seat_count: number;
  team_duration_days: number;
  badge?: string | null;
  is_recommended: boolean;
};

export type RechargeOrder = {
  id: number;
  order_no: string;
  plan_id: number;
  amount_cents: number;
  credit_amount?: number;
  bonus_credit_amount?: number;
  total_credit_amount?: number;
  team_seat_count?: number;
  team_duration_days?: number;
  status: "pending" | "paid" | "expired" | "cancelled" | "failed";
  payment_provider?: string | null;
  payment_type?: string | null;
  payment_trade_no?: string | null;
  pay_url?: string | null;
  qr_code?: string | null;
  qr_code_url?: string | null;
  failure_message?: string | null;
  expires_at?: string | null;
  paid_at?: string | null;
  created_at?: string | null;
};

export type InviteRewardConfig = {
  is_enabled: boolean;
  valid_user_reward_credits: number;
  recharge_reward_percent: number;
  valid_user_rule: "invited_user_first_paid_recharge" | string;
  valid_user_rule_label: string;
  invite_code: string;
  invite_url: string;
};

export type InvitedUser = {
  id: number;
  username: string;
  email: string;
  registered_at: string;
  total_recharged: number;
  is_valid: boolean;
};

export type InviteRewardLedger = {
  id: number;
  amount: number;
  balance_after: number;
  description: string;
  biz_id?: string | null;
  created_at: string;
};

export type InviteSummary = {
  total_invitees: number;
  valid_invitees: number;
  total_reward_credits: number;
  invitees: InvitedUser[];
  rewards: InviteRewardLedger[];
};

export type SigninRecord = {
  id: number;
  sign_date: string;
  awarded_credits: number;
  streak_days: number;
  created_at: string;
};

export type SigninStatus = {
  is_enabled: boolean;
  daily_credits: number;
  today_signed: boolean;
  current_streak: number;
  total_signins: number;
  last_sign_date?: string | null;
  recent_records: SigninRecord[];
};

export type UserExperienceConfig = {
  max_batch_tasks: number;
  batch_upload_max_bytes?: number;
  batch_upload_max_prompt_chars?: number;
  qiniu_storage_enabled?: boolean;
  updated_at?: string | null;
};

export type SigninResult = {
  awarded_credits: number;
  balance_after: number;
  sign_date: string;
  current_streak: number;
};

export type LeadModuleStatus = {
  is_enabled: boolean;
  enterprise_id?: string | null;
  opened_at?: string | null;
  credentials_revealed_at?: string | null;
  can_reveal_credentials: boolean;
};

export type LeadModuleCredentials = {
  enterprise_account: string;
  enterprise_password: string;
  credentials_revealed_at: string;
};

export type LeadTrialApplicationStatus = "pending" | "processing" | "approved" | "rejected";

export type LeadTrialApplication = {
  id: number;
  business_scope: string;
  keywords: string;
  competitor_accounts: string;
  contact_info: string;
  status: LeadTrialApplicationStatus;
  admin_remark: string;
  created_at?: string | null;
  updated_at?: string | null;
};

export type LeadTrialApplicationInput = {
  business_scope: string;
  keywords: string;
  competitor_accounts: string;
  contact_info: string;
};

export type CreditLedgerItem = {
  id: number;
  direction: "credit" | "debit";
  amount: number;
  balance_after: number;
  biz_type: "redemption_gift" | "recharge" | "image_task" | "refund" | "admin_adjustment" | "signin" | "invite" | "agent_transfer" | "agent_transfer_refund";
  description: string;
  payment_amount_cents?: number | null;
  created_at: string;
};

export type OpenCodeBalance = {
  status: "missing" | "pending" | "active" | "failed";
  failure_message?: string | null;
  agent_user_id?: number | null;
  agent_balance: number | null;
  credit_to_agent_rate: number;
  image_billing_enabled: boolean;
  text_api_key?: string | null;
  image_api_key?: string | null;
  api_base_url: string;
};

export type OpenAgentKeyGroup = {
  id: number;
  name: string;
  platform: string;
};

export type OpenAgentKey = {
  id: number;
  key: string;
  name: string;
  group?: OpenAgentKeyGroup | null;
  quota: number;
  quota_used: number;
  rate_limit_5h: number;
  rate_limit_1d: number;
  rate_limit_7d: number;
  usage_5h: number;
  usage_1d: number;
  usage_7d: number;
  reset_5h_at?: string | null;
  reset_1d_at?: string | null;
  reset_7d_at?: string | null;
  status: string;
  expires_at?: string | null;
  created_at: string;
  last_used_at?: string | null;
  last_used_ip?: string | null;
  ip_whitelist: string[];
  ip_blacklist: string[];
  current_concurrency: number;
  max_concurrency: number;
  today_actual_cost: number;
  total_actual_cost: number;
};

export type OpenAgentKeyPage = {
  status: OpenCodeBalance["status"];
  failure_message?: string | null;
  agent_user_id?: number | null;
  agent_balance: number | null;
  can_view_team_balance: boolean;
  api_base_url: string;
  groups: OpenAgentKeyGroup[];
  items: OpenAgentKey[];
  today_used: number;
  total_used: number;
};

export type OpenAgentKeyCreateInput = {
  name: string;
  group_id: number;
  quota: number;
  expires_in_days?: number | null;
  rate_limit_5h: number;
  rate_limit_1d: number;
  rate_limit_7d: number;
  ip_whitelist: string[];
  ip_blacklist: string[];
};

export type OpenAgentKeyUpdateInput = Partial<Omit<OpenAgentKeyCreateInput, "expires_in_days">> & {
  expires_at?: string | null;
  status?: "active" | "inactive";
};

export type OpenCodeLoginResponse = {
  status: OpenCodeBalance["status"];
  agent_user_id?: number | null;
  text_api_key?: string | null;
  image_api_key?: string | null;
};

export type OpenAgentUsageRecord = {
  id: number | string;
  api_key_name: string;
  model: string;
  ip_address: string;
  billing_mode: string;
  tokens: number;
  cost: number;
  first_token_ms?: number | null;
  duration_ms?: number | null;
  created_at: string;
};

export type OpenAgentDownload = {
  key: string;
  platform: "mac" | "windows";
  arch: string;
  label: string;
  package_type: "installer" | "portable";
  version?: string | null;
  file_url?: string | null;
  file_size?: number | null;
  release_notes: string;
  published_at?: string | null;
};

export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type WorkItem = {
  id: number;
  task_id: number;
  work_type?: string;
  aspect_ratio?: string;
  category: string;
  title?: string;
  prompt_snapshot: string;
  cover_asset: ImageAsset;
  input_assets: ImageAsset[];
  output_assets: ImageAsset[];
  is_collected: boolean;
  is_recommended: boolean;
  gallery_review_status?: "none" | "pending" | "approved" | "rejected";
  owner_user_id?: number | null;
  owner_name?: string;
  created_at: string;
};

export type TeamSettings = {
  id: number;
  name: string;
  owner_user_id: number;
  material_library_shared: boolean;
  image_history_shared: boolean;
  member_count: number;
  collaboration_enabled: boolean;
  seat_limit: number;
  seats_used: number;
  seats_available: number;
  entitlement_expires_at?: string | null;
  current_role?: "owner" | "admin" | "member" | string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type TeamOption = TeamSettings & {
  is_active: boolean;
};

export type TeamMember = {
  membership_id: number;
  user_id: number;
  username: string;
  nickname?: string | null;
  email: string;
  avatar_url?: string | null;
  role: "owner" | "admin" | "member" | string;
  joined_at?: string | null;
};
