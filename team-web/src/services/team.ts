import { request } from "./api";

export type TeamSettings = {
  id: number;
  name: string;
  image_history_shared: boolean;
  member_count: number;
  collaboration_enabled: boolean;
  seat_limit: number;
  seats_used: number;
  seats_available: number;
  entitlement_expires_at?: string | null;
  current_role?: "owner" | "admin" | "member" | null;
  site_name: string;
  site_icon_url: string;
};

export type TeamMember = {
  membership_id: number;
  user_id: number;
  username: string;
  nickname?: string | null;
  email: string;
  role: "owner" | "admin" | "member";
  joined_at?: string | null;
};

export type QuotaUsage = {
  quota: number;
  used: number;
  remaining: number | null;
  unlimited: boolean;
  status: string;
};

export type MemberUsage = TeamMember & {
  account_status: string;
  available: boolean;
  balance?: number;
  text?: QuotaUsage;
  image?: QuotaUsage;
  total_used?: number;
};

export type MemberUsagePage = {
  items: MemberUsage[];
  total: number;
  page: number;
  page_size: number;
};

export type QuotaUpdateInput = {
  text_quota: number;
  image_quota: number;
};

export type TeamUsageRecordMember = {
  membership_id: number | null;
  user_id: number | null;
  username: string;
  nickname?: string | null;
  email: string;
  role: TeamMember["role"] | "";
};

export type TeamUsageRecord = {
  id: number | string;
  member: TeamUsageRecordMember;
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

export type TeamUsageRecordPage = {
  items: TeamUsageRecord[];
  total: number;
  page: number;
  page_size: number;
};

export type TeamUsageRecordFilters = {
  memberUserId?: number | null;
  startDate?: string;
  endDate?: string;
};

export type LoginResponse = { access_token: string };

export type TeamConsoleSession = {
  team: TeamSettings;
  permissions: string[];
};

export type TeamInviteLink = {
  invite_url: string;
  expires_at: string;
};

export const teamApi = {
  login: (username: string, password: string) => request<LoginResponse>("/auth/login", { method: "POST", body: { username, password } }),
  getSession: () => request<TeamConsoleSession>("/team-console/session"),
  saveSettings: (input: Pick<TeamSettings, "name" | "image_history_shared">) => request<TeamSettings>("/team-console/settings", { method: "PATCH", body: input }),
  getMembers: () => request<TeamMember[]>("/team-console/members"),
  createInviteLink: () => request<TeamInviteLink>("/team-console/invite-link", { method: "POST" }),
  addMember: (identifier: string, role: "admin" | "member") => request<TeamMember>("/team-console/members", { method: "POST", body: { identifier, role } }),
  updateMemberRole: (membershipId: number, role: "admin" | "member") => request<TeamMember>(`/team-console/members/${membershipId}`, { method: "PATCH", body: { role } }),
  removeMember: (membershipId: number) => request<void>(`/team-console/members/${membershipId}`, { method: "DELETE" }),
  getMyUsage: () => request<MemberUsage>("/team-console/usage/me"),
  getMemberUsage: (page = 1, pageSize = 20, search = "") => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (search.trim()) query.set("search", search.trim());
    return request<MemberUsagePage>(`/team-console/usage/members?${query.toString()}`);
  },
  updateMemberQuotas: (membershipId: number, input: QuotaUpdateInput) =>
    request<MemberUsage>(`/team-console/usage/members/${membershipId}`, { method: "PATCH", body: input }),
  getUsageRecords: (page = 1, pageSize = 20, filters: TeamUsageRecordFilters = {}) => {
    const query = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (filters.memberUserId) query.set("member_user_id", String(filters.memberUserId));
    if (filters.startDate) query.set("start_date", filters.startDate);
    if (filters.endDate) query.set("end_date", filters.endDate);
    return request<TeamUsageRecordPage>(`/team-console/usage/records?${query.toString()}`);
  },
};
