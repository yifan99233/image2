import assert from 'node:assert/strict';
import test from 'node:test';
const { planDownloadTarget, fetchDownloadBlob } = await import('./downloadTarget.ts');
const origin = 'https://magic.shyfai.com', page = origin + '/create/imagine';
test('same-origin assets use the native direct link', () => {
  assert.deepEqual(planDownloadTarget(origin + '/image2-assets/test.png', page, origin), { url: origin + '/image2-assets/test.png', canDownloadDirectly: true });
});
test('legacy shared assets are normalized to the current origin', () => {
  assert.deepEqual(planDownloadTarget('https://magic-old.shyfai.com/image2-assets/test.png?v=1', page, origin), { url: origin + '/image2-assets/test.png?v=1', canDownloadDirectly: true });
});
test('external shared CDN keeps its URL and legacy fallback', () => {
  const url = 'https://openagent-cdn.shyfai.cn/image2-assets/test.png?v=1';
  assert.deepEqual(planDownloadTarget(url, page, origin), { url, canDownloadDirectly: false, fallbackUrl: origin + '/image2-assets/test.png?v=1' });
});
test('ADX2 CDN stays direct to its original host, never a Magic relay', () => {
  const url = 'https://oss-test.fycsai.com/magic/images/task/0.png';
  assert.deepEqual(planDownloadTarget(url, page, origin), { url, canDownloadDirectly: false });
});
test('data and blob media need no remote download worker', () => {
  for (const url of ['data:image/png;base64,aGVsbG8=', 'blob:' + origin + '/1234']) assert.equal(planDownloadTarget(url, page, origin).canDownloadDirectly, true);
});


test('cutout reads fresh CORS bytes without reusing the preview cache', async () => {
  const calls = [], blob = new Blob(['mask'], {type: 'image/png'});
  const result = await fetchDownloadBlob({url: 'https://cdn.test/mask.png', canDownloadDirectly: false}, async (url, options) => {
    calls.push({url, options}); return {ok: true, blob: async () => blob};
  });
  assert.equal(result, blob);
  assert.deepEqual(calls, [{url: 'https://cdn.test/mask.png', options: {mode: 'cors', credentials: 'omit', cache: 'no-store'}}]);
});
test('cutout falls back after a failed body read and reports total download failure', async () => {
  const target = {url: 'https://cdn.test/mask.png', fallbackUrl: origin + '/image2-assets/mask.png', canDownloadDirectly: false};
  const calls = [], blob = new Blob(['mask']);
  assert.equal(await fetchDownloadBlob(target, async url => {
    calls.push(url); return {ok: true, blob: async () => {if (url === target.url) throw new Error('read failed'); return blob;}};
  }), blob);
  assert.deepEqual(calls, [target.url, target.fallbackUrl]);
  await assert.rejects(fetchDownloadBlob(target, async () => ({ok: false})), /媒体下载失败/);
});
