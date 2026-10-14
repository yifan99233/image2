import { appConfig } from "@/config/env";
import { ApiError } from "@/services/apiError";
import { sessionStorageService } from "@/services/session";
import type { ApiEnvelope, ApiErrorPayload } from "@/types/api";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  skipAuth?: boolean;
  timeoutMs?: number;
};

type FormDataRequestOptions = Omit<RequestInit, "body"> & {
  skipAuth?: boolean;
  timeoutMs?: number;
};

let unauthorizedHandler: (() => void) | null = null;
const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

export const registerUnauthorizedHandler = (handler: () => void) => {
  unauthorizedHandler = handler;
};

const buildUrl = (path: string) => {
  if (/^https?:\/\//.test(path)) {
    return path;
  }

  return `${appConfig.apiBaseUrl}${path.startsWith("/") ? path : `/${path}`}`;
};

export const request = async <T>(path: string, options: RequestOptions = {}): Promise<T> => {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const headers = new Headers(options.headers);
  const token = sessionStorageService.getAccessToken();
  const requestController = new AbortController();
  const timeoutId = window.setTimeout(() => requestController.abort(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
  const callerSignal = options.signal;
  const abortFromCaller = () => requestController.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }

  if (!headers.has("Content-Type") && options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  if (!options.skipAuth && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      ...fetchOptions,
      signal: requestController.signal,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } finally {
    window.clearTimeout(timeoutId);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }

  const payload = (await response.json().catch(() => null)) as
    | ApiEnvelope<T>
    | ApiErrorPayload
    | null;

  if (!response.ok || !payload || payload.code !== 0) {
    const errorPayload: ApiErrorPayload = {
      code: payload?.code ?? response.status,
      message: payload?.message ?? "请求失败，请稍后重试",
      data: null,
    };

    if (response.status === 401) {
      unauthorizedHandler?.();
    }

    throw new ApiError(errorPayload, response.status);
  }

  return (payload as ApiEnvelope<T>).data;
};

export const requestFormData = async <T>(path: string, body: FormData, options: FormDataRequestOptions = {}): Promise<T> => {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const headers = new Headers(options.headers);
  const token = sessionStorageService.getAccessToken();
  const requestController = new AbortController();
  const timeoutId = window.setTimeout(() => requestController.abort(new DOMException("Request timed out", "TimeoutError")), timeoutMs);
  const callerSignal = options.signal;
  const abortFromCaller = () => requestController.abort(callerSignal?.reason);
  if (callerSignal) {
    if (callerSignal.aborted) abortFromCaller();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }

  if (!options.skipAuth && token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path), {
      ...fetchOptions,
      signal: requestController.signal,
      headers,
      body,
    });
  } finally {
    window.clearTimeout(timeoutId);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }

  const payload = (await response.json().catch(() => null)) as
    | ApiEnvelope<T>
    | ApiErrorPayload
    | null;

  if (!response.ok || !payload || payload.code !== 0) {
    const errorPayload: ApiErrorPayload = {
      code: payload?.code ?? response.status,
      message: payload?.message ?? "请求失败，请稍后重试",
      data: null,
    };

    if (response.status === 401) {
      unauthorizedHandler?.();
    }

    throw new ApiError(errorPayload, response.status);
  }

  return (payload as ApiEnvelope<T>).data;
};
