const TEAM_TOKEN_KEY = "image2:team-web:access-token";
const TEAM_SESSION_EVENT = "image2:team-web:session-change";

function siteKeyFromLocation(): string {
  const pathSegment = window.location.pathname.split("/").filter(Boolean)[0] ?? "";
  if (pathSegment && pathSegment !== "login") return pathSegment;

  const redirect = new URLSearchParams(window.location.search).get("redirect") ?? "";
  if (!redirect.startsWith("/")) return "";
  return redirect.split("?")[0].split("/").filter(Boolean)[0] ?? "";
}

const candidateSiteKey = siteKeyFromLocation();
export const teamSiteKey = /^[A-Za-z0-9_-]{1,64}$/.test(candidateSiteKey) ? candidateSiteKey : "";
export const teamConsolePath = teamSiteKey ? `/${encodeURIComponent(teamSiteKey)}/` : "/";
const apiBaseUrl = import.meta.env.VITE_TEAM_API_BASE_URL ?? (teamSiteKey ? `/${encodeURIComponent(teamSiteKey)}/api` : "/api");

type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export class TeamApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

export const teamSession = {
  get: () => window.localStorage.getItem(TEAM_TOKEN_KEY),
  set: (token: string) => {
    window.localStorage.setItem(TEAM_TOKEN_KEY, token);
    window.dispatchEvent(new Event(TEAM_SESSION_EVENT));
  },
  clear: () => {
    window.localStorage.removeItem(TEAM_TOKEN_KEY);
    window.dispatchEvent(new Event(TEAM_SESSION_EVENT));
  },
  subscribe: (onChange: () => void) => {
    const onStorage = (event: StorageEvent) => {
      if (event.storageArea === window.localStorage && (event.key === TEAM_TOKEN_KEY || event.key === null)) onChange();
    };
    window.addEventListener(TEAM_SESSION_EVENT, onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(TEAM_SESSION_EVENT, onChange);
      window.removeEventListener("storage", onStorage);
    };
  },
};

export async function request<T>(path: string, options: Omit<RequestInit, "body"> & { body?: unknown } = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = teamSession.get();
  if (options.body !== undefined) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const payload = (await response.json().catch(() => null)) as ApiEnvelope<T> | { message?: string } | null;
  if (!response.ok || !payload || !("code" in payload) || payload.code !== 0) {
    // A late response from an old session must not clear a newly logged-in one.
    if (response.status === 401 && token === teamSession.get()) teamSession.clear();
    throw new TeamApiError(payload && "message" in payload && payload.message ? payload.message : "请求失败，请稍后重试", response.status);
  }
  return payload.data;
}
