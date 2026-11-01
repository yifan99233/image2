/* Native browser downloads backed by a streaming CDN response. This worker only
 * controls /__media_download__/, never application pages or API requests. */
const pending = new Map();
const downloadPath = '/__media_download__/';
const expiresAfter = 90_000;

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));
self.addEventListener('message', (event) => {
  if (event.origin !== self.location.origin || !event.ports[0]) return;
  const { id, url, fallbackUrl, filename } = event.data || {};
  const port = event.ports[0];
  for (const [key, value] of pending) if (Date.now() - value.created > expiresAfter) pending.delete(key);
  if (!/^[a-f0-9-]{36}$/.test(id || '') || typeof filename !== 'string' || !filename || pending.size >= 128) {
    port.postMessage({ type: 'error', message: '无法准备下载，请重试' });
    return;
  }
  try {
    for (const address of [url, fallbackUrl].filter(Boolean)) {
      const parsed = new URL(address);
      if (!['https:', 'http:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error();
    }
    if (!url) throw new Error();
  } catch {
    port.postMessage({ type: 'error', message: '下载地址无效' });
    return;
  }
  pending.set(id, { url, fallbackUrl, filename, port, created: Date.now() });
  port.postMessage({ type: 'ready' });
});

async function download(item) {
  for (const url of [item.url, item.fallbackUrl].filter(Boolean)) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 30_000);
    try {
      // Preview <img> cache entries may lack CORS headers. Request a fresh stream.
      const response = await fetch(url, {
        mode: 'cors', credentials: 'omit', cache: 'no-store', signal: controller.signal,
      });
      clearTimeout(timeout);
      if (!response.ok || !response.body) {
        await response.body?.cancel();
        continue;
      }
      const filename = item.filename.replace(/[\r\n\x00-\x1f/\\]/g, '_').slice(0, 200);
      const encodedName = encodeURIComponent(filename).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
      const headers = new Headers({
        'Content-Type': response.headers.get('Content-Type') || 'application/octet-stream',
        'Content-Disposition': "attachment; filename*=UTF-8''" + encodedName,
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
      });
      // Do not copy Content-Length: Fetch transparently decompresses encoded
      // responses, and the original compressed size may no longer match.
      item.port.postMessage({ type: 'started' });
      item.port.close();
      return new Response(response.body, { status: 200, headers });
    } catch {
      clearTimeout(timeout);
      // Only fall back before headers/body have been handed to the browser.
    }
  }
  item.port.postMessage({ type: 'error', message: '媒体下载失败，请稍后重试' });
  item.port.close();
  return new Response('下载失败，请返回页面重试', { status: 502 });
}

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin || !url.pathname.startsWith(downloadPath)) return;
  const id = url.pathname.slice(downloadPath.length);
  const item = pending.get(id);
  pending.delete(id);
  event.respondWith(item && Date.now() - item.created <= expiresAfter
    ? download(item)
    : Promise.resolve(new Response('下载链接已失效，请返回页面重新点击下载', { status: 410 })));
});
