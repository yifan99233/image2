import type { AdminUser } from "../types";

const TOKEN_KEY = "image2_admin_token";
const USER_KEY = "image2_admin_user";

export function readToken() {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function writeSession(token: string, user: AdminUser) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function readUser(): AdminUser | null {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;

  try {
    return JSON.parse(raw) as AdminUser;
  } catch {
    clearSession();
    return null;
  }
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}
