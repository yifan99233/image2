import { clearSession, readToken } from "../lib/storage";
import type { ApiEnvelope } from "../types";

const API_BASE_URL = import.meta.env.VITE_ADMIN_API_BASE_URL ?? "http://localhost:8001";

type RequestErrorEventDetail = {
  status: number;
  message: string;
  code?: number;
  data?: unknown;
  path: string;
};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public code?: number,
    public data?: unknown,
  ) {
    super(message);
  }
}

function notifyRequestError(detail: RequestErrorEventDetail) {
  window.dispatchEvent(new CustomEvent<RequestErrorEventDetail>("admin-web:request-error", { detail }));
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = readToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...options.headers,
      },
    });
  } catch (error) {
    if (options.signal?.aborted) throw error;
    const message = error instanceof Error ? error.message : "网络连接失败";
    notifyRequestError({ status: 0, message, path });
    throw new ApiError(0, message);
  }

  if (response.status === 401) {
    clearSession();
    window.dispatchEvent(new CustomEvent("admin-web:unauthorized"));
    throw new ApiError(401, "登录已过期");
  }

  const payload = (await response.json().catch(() => null)) as ApiEnvelope<T> | null;
  if (!payload || !response.ok || payload.code !== 0) {
    const message = payload?.message ?? "请求失败，请稍后重试";
    notifyRequestError({ status: response.status, message, code: payload?.code, data: payload?.data, path });
    throw new ApiError(response.status, message, payload?.code, payload?.data);
  }

  return payload.data;
}

export async function uploadMultipart<T>(path: string, body: FormData): Promise<T> {
  const token = readToken();
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      body,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "网络连接失败";
    notifyRequestError({ status: 0, message, path });
    throw new ApiError(0, message);
  }

  if (response.status === 401) {
    clearSession();
    window.dispatchEvent(new CustomEvent("admin-web:unauthorized"));
    throw new ApiError(401, "登录已过期");
  }

  const payload = (await response.json().catch(() => null)) as ApiEnvelope<T> | null;
  if (!payload || !response.ok || payload.code !== 0) {
    const message = payload?.message ?? "上传失败，请稍后重试";
    notifyRequestError({ status: response.status, message, code: payload?.code, data: payload?.data, path });
    throw new ApiError(response.status, message, payload?.code, payload?.data);
  }

  return payload.data;
}
