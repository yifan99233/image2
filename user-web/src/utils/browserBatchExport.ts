import { BlobReader, TextReader, ZipWriter } from "@zip.js/zip.js";

export type ExportItem = { id: number; folder: string; stem: string; url: string; status: string; error: string };
export type ExportPage = { items: ExportItem[]; max_id: number; total: number; has_more: boolean; next_cursor: number; max_image_bytes: number };
export type ExportResult = { id: number; status: "成功" | "失败" | "未完成"; extension: string; error: string };
export type ExportProgress = { processed: number; total: number; succeeded: number; failed: number; pending: number; bytes: number; phase: "images" | "reports" | "done" };
export type ExportSource = {
  page(after: number, maxId: number | undefined, signal: AbortSignal): Promise<ExportPage>;
  report(kind: "full" | "failed", results: ExportResult[], signal: AbortSignal): Promise<ReadableStream<Uint8Array>>;
};

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "图片下载失败";
const extensionOf = async (blob: Blob) => {
  const bytes = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
  const text = new TextDecoder().decode(bytes);
  if (bytes[0] === 137 && text.slice(1, 4) === "PNG") return ".png";
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return ".jpg";
  if (text.startsWith("RIFF") && text.slice(8, 12) === "WEBP") return ".webp";
  if (/^GIF8[79]a/.test(text)) return ".gif";
  if (text.slice(4, 8) === "ftyp" && /avif|avis/.test(text.slice(8))) return ".avif";
  if (text.startsWith("BM")) return ".bmp";
  throw new Error("CDN 返回的内容不是支持的图片格式");
};

async function fetchImage(item: ExportItem, maxBytes: number, signal: AbortSignal, fetcher: typeof fetch) {
  const url = new URL(item.url);
  if (!["https:", "http:"].includes(url.protocol)) throw new Error("图片地址无效");
  for (let attempt = 0; ; attempt++) {
    signal.throwIfAborted();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new Error("图片下载超时")), 120_000);
    const combined = AbortSignal.any([signal, controller.signal]);
    let retryable = true;
    try {
      // No application auth headers, cookies, or server download proxy on CDN requests.
      // Skip non-CORS preview responses already present in the browser cache.
      const response = await fetcher(url.href, { signal: combined, credentials: "omit", mode: "cors", cache: "no-store" });
      if (!response.ok) {
        retryable = [408, 429].includes(response.status) || response.status >= 500;
        await response.body?.cancel();
        throw new Error(`CDN 下载失败（HTTP ${response.status}）`);
      }
      if (!response.body) throw new Error("CDN 返回空文件");
      const reader = response.body.getReader();
      const chunks: Uint8Array<ArrayBuffer>[] = [];
      let size = 0;
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          size += value.byteLength;
          if (size > maxBytes) { retryable = false; throw new Error("单张图片超过下载大小上限"); }
          chunks.push(value as Uint8Array<ArrayBuffer>);
        }
      } catch (error) {
        await reader.cancel().catch(() => {});
        throw error;
      } finally { reader.releaseLock(); }
      const blob = new Blob(chunks);
      retryable = false;
      return { blob, extension: await extensionOf(blob) };
    } catch (error) {
      signal.throwIfAborted();
      if (!retryable || attempt >= 2) throw error;
    } finally { clearTimeout(timer); }
    await new Promise<void>((resolve, reject) => {
      const abort = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, 500 * (attempt + 1));
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) abort();
    });
  }
}

/** Metadata is paged; only a bounded number of individual images are buffered.
 * The archive itself goes to the chosen WritableStream, never a Blob/ArrayBuffer.
 */
export async function writeBrowserBatchExport(target: WritableStream<Uint8Array>, source: ExportSource,
  signal: AbortSignal, progress: (value: ExportProgress) => void, fetcher: typeof fetch = fetch) {
  const controller = new AbortController();
  const combined = AbortSignal.any([signal, controller.signal]);
  const zip = new ZipWriter(target, { zip64: true, level: 0, bufferedWrite: false, useWebWorkers: false });
  const results: ExportResult[] = [], folders = new Set<string>();
  const state: ExportProgress = { processed: 0, total: 0, succeeded: 0, failed: 0, pending: 0, bytes: 0, phase: "images" };
  let cursor = 0, maxId: number | undefined;
  try {
    while (true) {
      combined.throwIfAborted();
      const page = await source.page(cursor, maxId, combined);
      maxId ??= page.max_id;
      if (!page.total || page.total > 20000 || page.max_id !== maxId || (state.total && state.total !== page.total)) throw new Error("批次任务发生变化，请重新下载");
      state.total = page.total;
      progress({ ...state });
      // Target 128 MiB of image payload (or one configured maximum-size image).
      const workers = Math.max(1, Math.min(4, Math.floor(128 * 1024 ** 2 / page.max_image_bytes)));
      const inflight = new Map<number, Promise<{ blob: Blob; extension: string } | { error: string }>>();
      const schedule = (index: number) => {
        const item = page.items[index];
        if (item?.status === "succeeded" && item.url) inflight.set(index, fetchImage(item, page.max_image_bytes, combined, fetcher)
          .catch(error => ({ error: errorMessage(error).slice(0, 512) })));
      };
      for (let i = 0; i < Math.min(workers, page.items.length); i++) schedule(i);
      try {
        for (let i = 0; i < page.items.length; i++) {
          combined.throwIfAborted();
          const item = page.items[i];
          if (item.id <= cursor || item.id > maxId) throw new Error("下载清单顺序错误");
          cursor = item.id;
          if (!folders.has(item.folder)) { await zip.add(item.folder + "/", undefined, { directory: true }); folders.add(item.folder); }
          const result: ExportResult = { id: item.id, status: "成功", extension: "", error: "" };
          if (["pending", "queued", "running"].includes(item.status)) {
            result.status = "未完成"; result.error = "任务尚未完成，请完成后重新下载";
          } else if (item.status !== "succeeded" || !item.url) {
            result.status = "失败"; result.error = (item.error || "任务没有可用的结果图片").slice(0, 512);
          } else {
            const image = await inflight.get(i)!;
            inflight.delete(i);
            combined.throwIfAborted();
            if ("error" in image) { result.status = "失败"; result.error = image.error; }
            else {
              await zip.add(`${item.folder}/${item.stem}${image.extension}`, new BlobReader(image.blob), { signal: combined });
              result.extension = image.extension;
              state.bytes += image.blob.size;
            }
          }
          results.push(result);
          state.processed++;
          if (result.status === "成功") state.succeeded++;
          else if (result.status === "失败") state.failed++;
          else state.pending++;
          progress({ ...state });
          schedule(i + workers);
        }
      } catch (error) {
        controller.abort(error);
        throw error;
      } finally { await Promise.allSettled(inflight.values()); }
      if (!page.has_more) break;
      if (!page.items.length || page.next_cursor !== cursor) throw new Error("下载清单分页错误");
    }
    if (state.processed !== state.total) throw new Error("批次记录已变化，请重新下载");
    state.phase = "reports"; progress({ ...state });
    // The API generates only XLSX metadata. Image bytes never pass through it.
    for (const kind of ["full", "failed"] as const) {
      const stream = await source.report(kind, results, combined);
      await zip.add(kind === "full" ? "完整汇总.xlsx" : "失败汇总.xlsx", stream, { signal: combined });
    }
    const summary = !state.failed && !state.pending ? `全部成功 ${state.succeeded} 张`
      : `成功 ${state.succeeded} 张，失败 ${state.failed} 张${state.pending ? `，未完成 ${state.pending} 张（本次下载快照）` : ""}`;
    await zip.add("结果统计.txt", new TextReader(summary + "\n"), { signal: combined });
    combined.throwIfAborted();
    await zip.close();
    state.phase = "done"; progress({ ...state });
    return state;
  } catch (error) {
    controller.abort(error);
    await target.abort(error).catch(() => {});
    throw error;
  }
}
