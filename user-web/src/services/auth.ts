import { request } from "@/services/http";
import { encryptPassword } from "@/utils/rsa";
import type { AuthUser, LoginResponse, ProfileUpdateRequest, RegisterRequest, TeamInvitePreview } from "@/types/api";

export const authService = {
  async login(username: string, password: string): Promise<LoginResponse> {
    const publicKey = await request<{ public_key: string }>("/auth/public-key", { skipAuth: true });
    const encryptedPassword = await encryptPassword(password, publicKey.public_key);

    return request<LoginResponse>("/auth/login", {
      method: "POST",
      skipAuth: true,
      body: { username, password: encryptedPassword },
    });
  },

  async exchangeAdminImpersonation(code: string): Promise<LoginResponse> {
    return request<LoginResponse>("/auth/admin-impersonation/exchange", {
      method: "POST",
      skipAuth: true,
      body: { code },
    });
  },

  async register(payload: RegisterRequest): Promise<LoginResponse> {
    const publicKey = await request<{ public_key: string }>("/auth/public-key", { skipAuth: true });
    const encryptedPassword = await encryptPassword(payload.password, publicKey.public_key);

    return request<LoginResponse>("/auth/register", {
      method: "POST",
      skipAuth: true,
      body: { ...payload, password: encryptedPassword },
    });
  },

  async getTeamInvitePreview(token: string): Promise<TeamInvitePreview> {
    const query = new URLSearchParams({ token });
    return request<TeamInvitePreview>(`/auth/team-invite?${query.toString()}`, { skipAuth: true });
  },

  async getCurrentUser(): Promise<AuthUser> {
    return request<AuthUser>("/auth/me");
  },

  async updateProfile(payload: ProfileUpdateRequest): Promise<AuthUser> {
    return request<AuthUser>("/auth/profile", {
      method: "PATCH",
      body: payload,
    });
  },

  async changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const publicKey = await request<{ public_key: string }>("/auth/public-key", { skipAuth: true });
    const [current_password, new_password] = await Promise.all([
      encryptPassword(currentPassword, publicKey.public_key),
      encryptPassword(newPassword, publicKey.public_key),
    ]);

    return request<void>("/auth/password", {
      method: "POST",
      body: { current_password, new_password },
    });
  },
};
