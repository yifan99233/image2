import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";

const dom = new JSDOM('<title>AI 创作平台</title><link rel="icon"><link rel="apple-touch-icon">', {
  url: "https://magic-aqf.shyfai.cn/",
});
for (const key of ["window", "document", "localStorage", "sessionStorage"]) globalThis[key] = dom.window[key];
await build({
  entryPoints: ["src/services/siteConfigStore.ts"],
  outfile: "node_modules/.tmp/site-branding-test.mjs",
  bundle: true,
  format: "esm",
  platform: "node",
  packages: "external",
  alias: { "@": process.cwd() + "/src" },
  define: { "import.meta.env": '{"VITE_API_BASE_URL":"/api"}' },
});

for (const siteName of ["艾全服", "寻光", "艺源"]) {
  test(`site config sets tab branding for ${siteName}, including recovery and cached loads`, async () => {
    const { loadSiteConfig } = await import(`../node_modules/.tmp/site-branding-test.mjs?site=${encodeURIComponent(siteName)}`);
    globalThis.fetch = async () => { throw new Error("offline"); };
    await loadSiteConfig();
    assert.equal(document.title, "AI 创作平台");

    let requests = 0;
    const config = { site_name: siteName, site_icon_url: "/tenant-logo.png" };
    globalThis.fetch = async (url) => {
      assert.equal(url, "/api/site/config");
      requests += 1;
      return new Response(JSON.stringify({ code: 0, data: config }));
    };
    await Promise.all([loadSiteConfig(), loadSiteConfig()]);
    assert.equal(document.title, siteName);
    for (const link of document.querySelectorAll("link")) assert.equal(link.href, "https://magic-aqf.shyfai.cn/tenant-logo.png");
    document.title = "stale";
    await loadSiteConfig();
    assert.equal(document.title, siteName);
    assert.equal(requests, 1);
  });
}
