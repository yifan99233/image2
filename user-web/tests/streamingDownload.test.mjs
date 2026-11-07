import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';
const source = await readFile(new URL('../public/media-download-worker.js', import.meta.url), 'utf8');
const origin = 'https://magic.shyfai.cn', id = '12345678-1234-1234-1234-123456789abc';
function worker(fetcher) {
  const listeners = {}, messages = [];
  vm.runInNewContext(source, { self: { location: { origin }, addEventListener: (name, fn) => listeners[name] = fn }, URL, Response, Headers, AbortController, setTimeout, clearTimeout, fetch: fetcher });
  const prepare = (overrides = {}) => listeners.message({ origin, data: { id, url: 'https://oss-test.fycsai.com/magic/images/task/0.png', filename: '图片.png', ...overrides }, ports: [{ postMessage: value => messages.push(value), close() {} }] });
  const navigate = (path = '/__media_download__/' + id) => {
    let result;
    listeners.fetch({ request: { url: origin + path }, respondWith: value => result = value });
    return result;
  };
  return { prepare, navigate, messages };
}
test('attachment headers and first bytes arrive before the CDN body finishes', async () => {
  let finish, closed = false;
  const gate = new Promise(resolve => finish = resolve);
  const body = new ReadableStream({ async start(controller) {
    controller.enqueue(new Uint8Array([137, 80, 78, 71]));
    await gate;
    controller.enqueue(new Uint8Array([13, 10, 26, 10]));
    controller.close(); closed = true;
  } });
  const w = worker(async (url, options) => {
    assert.equal(url, 'https://oss-test.fycsai.com/magic/images/task/0.png');
    assert.equal(options.mode, 'cors'); assert.equal(options.credentials, 'omit'); assert.equal(options.cache, 'no-store');
    const response = new Response(body, { headers: { 'Content-Type': 'image/png' } });
    response.blob = () => { throw new Error('must never buffer the image'); };
    return response;
  });
  w.prepare(); assert.equal(w.messages[0].type, 'ready');
  const response = await w.navigate();
  assert.match(response.headers.get('Content-Disposition'), /^attachment; filename\*=UTF-8''/);
  assert.equal(response.headers.get('Content-Type'), 'image/png');
  assert.equal(w.messages.at(-1).type, 'started'); assert.equal(closed, false);
  const reader = response.body.getReader();
  assert.deepEqual([...(await reader.read()).value], [137, 80, 78, 71]);
  finish(); assert.deepEqual([...(await reader.read()).value], [13, 10, 26, 10]);
  assert.equal((await reader.read()).done, true);
});
test('fallback streams; failures are reported before creating an attachment', async () => {
  const urls = [];
  const w = worker(async url => { urls.push(url); if (urls.length === 1) throw new TypeError('CORS'); return new Response('image'); });
  w.prepare({ fallbackUrl: origin + '/image2-assets/example.png' });
  assert.equal((await w.navigate()).status, 200); assert.equal(urls.length, 2);
  const bad = worker(async () => new Response('missing', { status: 404 })); bad.prepare();
  const response = await bad.navigate(); assert.equal(response.status, 502);
  assert.equal(response.headers.has('Content-Disposition'), false); assert.equal(bad.messages.at(-1).type, 'error');
});
test('only download navigation is intercepted and tickets are single use', async () => {
  const w = worker(async () => new Response('image'));
  assert.equal(w.navigate('/api/site/config'), undefined); assert.equal(w.navigate('/create/text-to-image'), undefined);
  w.prepare(); assert.equal((await w.navigate()).status, 200); assert.equal((await w.navigate()).status, 410);
});
test('rejects unsafe schemes and strips filename header/path injection', async () => {
  const w = worker(async () => new Response('image'));
  w.prepare({ url: 'file:///etc/passwd' }); assert.equal(w.messages.at(-1).type, 'error');
  w.prepare({ filename: '../a\r\nX-Injected: true.png' }); const response = await w.navigate();
  assert.equal(response.headers.has('X-Injected'), false);
  assert.doesNotMatch(decodeURIComponent(response.headers.get('Content-Disposition')), /[\r\n/\\]/);
});
