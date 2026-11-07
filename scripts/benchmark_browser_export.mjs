// node --experimental-strip-types scripts/benchmark_browser_export.mjs /path/to/fixture.png
// Exercises the shipped browser ZIP writer against local HTTP, not paid generation.
import { createServer } from "node:http";
import { createWriteStream, readFileSync, mkdtempSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Writable } from "node:stream";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { writeBrowserBatchExport } from "../user-web/src/utils/browserBatchExport.ts";

const require = createRequire(new URL("../user-web/package.json", import.meta.url));
const XLSX = require("xlsx");
const png = readFileSync(process.argv[2]);
const count = Number(process.argv[3] || 20000);
const directory = mkdtempSync(join(tmpdir(), "browser-zip-benchmark-"));
const archivePath = join(directory, "images.zip");
const server = createServer((_request, response) => {
  response.writeHead(200, { "Content-Type": "image/png", "Content-Length": png.length, "Access-Control-Allow-Origin": "*" });
  response.end(png);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;
const report = failed => {
  const workbook = XLSX.utils.book_new();
  const rows = [["任务", "状态", "提示词"], ...(!failed ? Array.from({ length: count }, (_, i) => [i + 1, "成功", `完整提示词 ${i + 1}`]) : [])];
  XLSX.utils.book_append_sheet(workbook, XLSX.utils.aoa_to_sheet(rows), "汇总");
  return XLSX.write(workbook, { type: "buffer", bookType: "xlsx", compression: true });
};
const full = report(false), failed = report(true);
let active = 0, peak = 0, pages = 0, firstByte;
const started = performance.now();
let previous = started, maxLag = 0;
const heartbeat = setInterval(() => { const now = performance.now(); maxLag = Math.max(maxLag, now - previous - 20); previous = now; }, 20);
try {
  const fileWriter = Writable.toWeb(createWriteStream(archivePath));
  const file = fileWriter.getWriter();
  const output = new WritableStream({ write(chunk) { firstByte ??= performance.now() - started; return file.write(chunk); }, close() { return file.close(); }, abort(error) { return file.abort(error); } });
  const result = await writeBrowserBatchExport(output, {
    page: async after => {
      pages++;
      return { items: Array.from({ length: Math.min(200, count - after) }, (_, offset) => {
        const id = after + offset + 1;
        return { id, folder: `【XMAS-SER-${Math.floor((id - 1) / 20) + 1}】`, stem: String(id), url: `${base}/${id}.png`, status: "succeeded", error: "" };
      }), total: count, max_id: count, max_image_bytes: 64 * 1024 ** 2, next_cursor: Math.min(count, after + 200), has_more: after + 200 < count };
    },
    report: async kind => new Blob([kind === "full" ? full : failed]).stream(),
  }, new AbortController().signal, () => {}, async (...args) => {
    active++; peak = Math.max(peak, active);
    try { return await fetch(...args); } finally { active--; }
  });
  const elapsed = performance.now() - started;
  clearInterval(heartbeat);
  const verification = JSON.parse(execFileSync("python3", ["-c", `import sys,json,zipfile
with zipfile.ZipFile(sys.argv[1]) as z:
 assert z.testzip() is None
 names=z.namelist()
 count=int(sys.argv[2])
 assert sum(n.endswith('.png') for n in names)==count
 assert sum(n.endswith('/') for n in names)==(count+19)//20
 assert len(names)==count+(count+19)//20+3
 assert z.read('结果统计.txt').decode()==f'全部成功 {count} 张\\n'
 print(json.dumps({'crc_verified':True,'entries':len(names)}))`, archivePath, String(count)], { encoding: "utf8" }));
  console.log(JSON.stringify({ images: count, folders: Math.ceil(count / 20), zip_bytes: statSync(archivePath).size,
    seconds: +(elapsed / 1000).toFixed(2), first_byte_ms: +firstByte.toFixed(2), peak_rss_mib: +(process.resourceUsage().maxRSS / 1024).toFixed(2),
    max_event_loop_lag_ms: +maxLag.toFixed(2), peak_cdn_requests: peak, metadata_pages: pages,
    succeeded: result.succeeded, failed: result.failed, ...verification, scope: "browser export code in Node; local HTTP fixtures, no production CDN throughput claim" }));
} finally {
  clearInterval(heartbeat);
  server.closeAllConnections(); server.close();
  rmSync(directory, { recursive: true, force: true });
}
