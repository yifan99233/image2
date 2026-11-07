import { appConfig } from "@/config/env";
import { request } from "@/services/http";
import { sessionStorageService } from "@/services/session";
import { ApiError } from "@/services/apiError";
import type { ExportPage, ExportProgress } from "@/utils/browserBatchExport";

type SavePicker = (options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<{ createWritable(): Promise<FileSystemWritableFileStream> }>;

async function retryRead<T>(read: () => Promise<T>, signal: AbortSignal): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    try { return await read(); }
    catch (error) {
      signal.throwIfAborted();
      if (attempt >= 2 || (error instanceof ApiError && error.status < 500 && ![408, 429].includes(error.status))) throw error;
      await new Promise<void>((resolve, reject) => {
        const abort = () => { clearTimeout(timer); reject(signal.reason); };
        const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 500 * (attempt + 1));
        signal.addEventListener("abort", abort, { once: true });
        if (signal.aborted) abort();
      });
    }
  }
}

export async function downloadBatchFromCdn(batchId: string, signal: AbortSignal, progress: (value: ExportProgress) => void) {
  const picker = (window as Window & { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
  if (!picker) throw new Error("CDN 直连大文件下载需要电脑端 Chrome 或 Edge，请在这些浏览器中打开本页下载");
  // Must run synchronously in the click handler, before imports or API requests.
  const handle = await picker.call(window, { suggestedName: `批量图片-${batchId.slice(-12)}.zip`,
    types: [{ description: "ZIP 压缩包", accept: { "application/zip": [".zip"] } }] });
  signal.throwIfAborted();
  const { writeBrowserBatchExport } = await import("@/utils/browserBatchExport");
  const target = await handle.createWritable();
  return writeBrowserBatchExport(target, {
    page: (after, maxId, signal) => {
      const params = new URLSearchParams({ batch_id: batchId, after_id: String(after) });
      if (maxId) params.set("max_id", String(maxId));
      return retryRead(() => request<ExportPage>(`/image-tasks/browser-export/items?${params}`, { signal }), signal);
    },
    report: async (kind, results, signal) => {
      return retryRead(async () => {
        const response = await fetch(`${appConfig.apiBaseUrl}/image-tasks/browser-export/reports/${kind}`, {
        method: "POST", signal: AbortSignal.any([signal, AbortSignal.timeout(180_000)]),
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${sessionStorageService.getAccessToken()}` },
        body: JSON.stringify({ batch_id: batchId, results }),
        });
        if (!response.ok || !response.body) throw new ApiError({ code: response.status, message: (await response.json().catch(() => null))?.message || "汇总文件下载失败，请重新下载", data: null }, response.status);
        return response.body;
      }, signal);
    },
  }, signal, progress);
}
