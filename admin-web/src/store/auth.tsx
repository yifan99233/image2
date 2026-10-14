import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { clearSession, readToken, readUser, writeSession } from "../lib/storage";
import { getCurrentAdmin, login as loginRequest } from "../services/adminApi";
import type { AdminUser } from "../types";

type AuthContextValue = {
  token: string | null;
  user: AdminUser | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [token, setToken] = useState(() => readToken());
  const [user, setUser] = useState<AdminUser | null>(() => readUser());

  const logout = useCallback(() => {
    clearSession();
    setToken(null);
    setUser(null);
    navigate("/login", { replace: true });
  }, [navigate]);

  useEffect(() => {
    const onUnauthorized = () => logout();
    window.addEventListener("admin-web:unauthorized", onUnauthorized);
    return () => window.removeEventListener("admin-web:unauthorized", onUnauthorized);
  }, [logout]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    getCurrentAdmin()
      .then((currentUser) => {
        if (cancelled) return;
        writeSession(token, currentUser);
        setUser(currentUser);
      })
      .catch(() => {
        // Request errors are surfaced by the shared HTTP layer.
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  const login = useCallback(async (username: string, password: string) => {
    const session = await loginRequest(username, password);
    writeSession(session.token, session.user);
    setToken(session.token);
    setUser(session.user);
  }, []);

  const value = useMemo(
    () => ({
      token,
      user,
      isAuthenticated: Boolean(token && user?.is_active),
      login,
      logout,
    }),
    [login, logout, token, user],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return context;
}
