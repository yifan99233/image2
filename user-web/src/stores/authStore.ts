import { create } from "zustand";
import { authService } from "@/services/auth";
import { sessionStorageService } from "@/services/session";
import type { AuthUser, ProfileUpdateRequest, RegisterRequest } from "@/types/api";

type AuthStatus = "idle" | "checking" | "authenticated" | "anonymous";

type AuthStore = {
  user: AuthUser | null;
  status: AuthStatus;
  loginError: string | null;
  token: string | null;
  initializeSession: () => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  impersonate: (code: string) => Promise<void>;
  register: (payload: RegisterRequest) => Promise<void>;
  updateProfile: (payload: ProfileUpdateRequest) => Promise<AuthUser>;
  logout: () => void;
};

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  status: "idle",
  loginError: null,
  token: sessionStorageService.getAccessToken(),

  async initializeSession() {
    const token = sessionStorageService.getAccessToken();

    if (!token) {
      set({ status: "anonymous", user: null, token: null });
      return;
    }

    set({ status: "checking", token });

    try {
      const user = await authService.getCurrentUser();
      set({ user, status: "authenticated", loginError: null });
    } catch {
      sessionStorageService.clearAccessToken();
      set({ user: null, status: "anonymous", token: null });
    }
  },

  async login(username, password) {
    set({ status: "checking", loginError: null });

    try {
      const loginResponse = await authService.login(username, password);
      sessionStorageService.setAccessToken(loginResponse.access_token);
      set({
        user: loginResponse.user,
        token: loginResponse.access_token,
        status: "authenticated",
        loginError: null,
      });
    } catch (error) {
      set({
        status: "anonymous",
        loginError: error instanceof Error ? error.message : "登录失败，请稍后重试",
      });
      throw error;
    }
  },

  async impersonate(code) {
    sessionStorageService.clearAccessToken();
    set({ user: null, token: null, status: "checking", loginError: null });

    try {
      const loginResponse = await authService.exchangeAdminImpersonation(code);
      sessionStorageService.setAccessToken(loginResponse.access_token);
      set({
        user: loginResponse.user,
        token: loginResponse.access_token,
        status: "authenticated",
        loginError: null,
      });
    } catch (error) {
      set({
        user: null,
        token: null,
        status: "anonymous",
        loginError: error instanceof Error ? error.message : "代登录失败，请重新发起",
      });
      throw error;
    }
  },

  async register(payload) {
    set({ status: "checking", loginError: null });

    try {
      const loginResponse = await authService.register(payload);
      sessionStorageService.setAccessToken(loginResponse.access_token);
      set({
        user: loginResponse.user,
        token: loginResponse.access_token,
        status: "authenticated",
        loginError: null,
      });
    } catch (error) {
      set({
        status: "anonymous",
        loginError: error instanceof Error ? error.message : "注册失败，请稍后重试",
      });
      throw error;
    }
  },

  async updateProfile(payload) {
    const user = await authService.updateProfile(payload);
    set({ user });
    return user;
  },

  logout() {
    sessionStorageService.clearAccessToken();
    set({ user: null, token: null, status: "anonymous", loginError: null });
  },
}));
