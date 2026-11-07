import type { DownloadTarget } from './downloadTarget';

async function downloadWorker(): Promise<ServiceWorker> {
  if (!window.isSecureContext || !('serviceWorker' in navigator)) {
    throw new Error('当前浏览器不支持流式下载，请使用最新版 Chrome、Edge 或 Safari');
  }
  const registration = await navigator.serviceWorker.register('/media-download-worker.js', {
    scope: '/__media_download__/', updateViaCache: 'none',
  });
  if (!registration.installing && !registration.waiting && registration.active?.state === 'activated') return registration.active;
  const worker = registration.installing || registration.waiting || registration.active;
  if (!worker) throw new Error('下载组件启动失败，请刷新后重试');
  return new Promise<ServiceWorker>((resolve, reject) => {
    const cleanup = () => { clearTimeout(timeout); worker.removeEventListener('statechange', changed); };
    const changed = () => {
      if (worker.state === 'activated') { cleanup(); resolve(worker); }
      else if (worker.state === 'redundant') { cleanup(); reject(new Error('下载组件启动失败，请刷新后重试')); }
    };
    const timeout = window.setTimeout(() => { cleanup(); reject(new Error('下载组件启动超时，请重试')); }, 15_000);
    worker.addEventListener('statechange', changed);
    changed();
  });
}

export async function streamBrowserDownload(target: DownloadTarget, filename: string): Promise<void> {
  const worker = await downloadWorker();
  const id = crypto.randomUUID();
  const frame = document.createElement('iframe');
  frame.hidden = true;
  frame.title = '媒体下载';
  const channel = new MessageChannel();
  return new Promise<void>((resolve, reject) => {
    const cleanup = () => { clearTimeout(timeout); channel.port1.close(); };
    const timeout = window.setTimeout(() => {
      cleanup(); frame.remove(); reject(new Error('下载启动超时，请重试'));
    }, 45_000);
    channel.port1.onmessage = ({ data }) => {
      if (data.type === 'ready') {
        // A navigation (not an <a download> fetch) is handled by the worker.
        // Content-Disposition makes the browser own the download immediately.
        frame.src = `/__media_download__/${id}`;
        document.body.appendChild(frame);
      } else if (data.type === 'started') {
        cleanup();
        // Keep the navigation alive until the browser has consumed its headers.
        window.setTimeout(() => frame.remove(), 60_000);
        resolve();
      } else if (data.type === 'error') {
        cleanup(); frame.remove(); reject(new Error(data.message || '媒体下载失败，请稍后重试'));
      }
    };
    worker.postMessage({ id, url: target.url, fallbackUrl: target.fallbackUrl, filename }, [channel.port2]);
  });
}
