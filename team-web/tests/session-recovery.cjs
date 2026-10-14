// Run with Playwright available in Node's module path and TEAM_WEB_TEST_URL
// pointing to a running team-web Vite server. All API calls are intercepted.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    const base = process.env.TEAM_WEB_TEST_URL || 'http://127.0.0.1:54183';
    const key = 'image2:team-web:access-token';
    let mode = 'expired';
    let authSeen = false;
    await page.addInitScript(key => localStorage.setItem(key, 'expired-token'), key);
    await page.route('**/sqcm/api/**', async route => {
      const req = route.request();
      const path = new URL(req.url()).pathname;
      let status = 200;
      let data;
      let message = 'ok';
      if (path.endsWith('/auth/login')) data = { access_token: 'fresh-token' };
      else if (mode === 'expired') { status = 401; message = '令牌无效或已过期'; }
      else if (mode === 'denied') { status = 403; message = '没有团队权限'; }
      else if (path.endsWith('/session')) {
        authSeen = req.headers().authorization === 'Bearer fresh-token';
        data = { team: { id: 1, name: 'Test team', site_name: 'Test', current_role: 'owner', member_count: 0, seat_limit: 10, seats_used: 0, seats_available: 10, collaboration_enabled: true }, permissions: ['members:view'] };
      } else data = [];
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify({ code: status === 200 ? 0 : status * 100, message, data }) });
    });
    await page.goto(`${base}/sqcm/`);
    await page.getByRole('button', { name: '登录团队管理中心', exact: true }).waitFor();
    assert.equal(await page.evaluate(key => localStorage.getItem(key), key), null);
    mode = 'ok';
    await page.getByLabel('账号', { exact: true }).fill('test');
    await page.getByLabel('密码', { exact: true }).fill('test-password');
    await page.getByRole('button', { name: '登录团队管理中心', exact: true }).click();
    await page.getByRole('button', { name: '退出', exact: true }).waitFor();
    assert.ok(authSeen, 'relogin sends the fresh bearer credential');
    // A 401 from any later screen must return to login, without a page reload.
    mode = 'expired';
    await page.getByRole('button', { name: '额度与用量', exact: true }).click();
    await page.getByRole('button', { name: '登录团队管理中心', exact: true }).waitFor();
    mode = 'denied';
    await page.getByLabel('账号', { exact: true }).fill('test');
    await page.getByLabel('密码', { exact: true }).fill('test-password');
    await page.getByRole('button', { name: '登录团队管理中心', exact: true }).click();
    await page.getByRole('heading', { name: '当前账号无法进入团队中心' }).waitFor();
    assert.equal(await page.evaluate(key => localStorage.getItem(key), key), 'fresh-token');
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.getByRole('button', { name: '登录团队管理中心', exact: true }).waitFor();
    console.log('PASS: expired session recovery, relogin bearer header, later 401, preserved 403, logout');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
