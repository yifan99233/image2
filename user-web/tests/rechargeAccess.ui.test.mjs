import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement as h } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const dom = new JSDOM('<div id="root"></div>', { url: "https://test/billing/recharge" });
for (const key of ["window", "document", "HTMLElement", "Node", "Event", "MouseEvent", "CustomEvent"])
  globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");

await build({
  stdin: {
    contents: 'export { RechargeRoute } from "@/routes/RechargeRoute"; export { Topbar } from "@/components/layout/Topbar";',
    resolveDir: process.cwd(),
  },
  outfile: "node_modules/.tmp/recharge-access-test.mjs",
  bundle: true, format: "esm", platform: "node", packages: "external", jsx: "automatic",
  alias: { "@": process.cwd() + "/src" },
  define: { "import.meta.env": '{"VITE_API_BASE_URL":"https://test"}' },
  plugins: [{
    name: "site-config-fixture",
    setup(builder) {
      builder.onResolve({ filter: /services\/siteConfigStore$/ }, () => ({ path: "site-config", namespace: "fixture" }));
      builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({ contents:
        "export const readCachedSiteConfig = () => globalThis.fixtureSite; export const loadSiteConfig = () => globalThis.fixturePending ?? Promise.resolve(globalThis.fixtureSite);",
      }));
    },
  }],
});
const { RechargeRoute, Topbar } = await import("../node_modules/.tmp/recharge-access-test.mjs");
let root, requests;
globalThis.fetch = async (url, options = {}) => {
  const path = new URL(url).pathname;
  assert.ok(!options.method || options.method === "GET", "rendering must not create orders");
  requests.push(path);
  const data = path === "/recharge/plans"
    ? [{ id: 2, name: "ART 充值档位", amount_cents: 1000, credit_amount: 100, bonus_credit_amount: 0, total_credit_amount: 100 }]
    : { is_enabled: false, balance: 123 };
  return new Response(JSON.stringify({ code: 0, message: "ok", data }), { headers: { "Content-Type": "application/json" } });
};
const site = (key, modules = ["recharge"]) => ({ site_key: key, is_enabled: true, enabled_modules: modules });
async function mount(config, topbar = false, pending = null) {
  globalThis.fixtureSite = config;
  globalThis.fixturePending = pending;
  requests = [];
  root = createRoot(document.getElementById("root"));
  await act(async () => {
    root.render(h(MemoryRouter, { initialEntries: ["/billing/recharge"] }, topbar ? h(Topbar) : h(Routes, null,
      h(Route, { path: "/billing/recharge", element: h(RechargeRoute) }),
      h(Route, { path: "/support", element: h("div", { "data-testid": "support" }, "客服") }),
    )));
  });
}
async function close() { await act(async () => root.unmount()); }

test("art direct recharge route renders its plans", async () => {
  await mount(site("art"));
  assert.match(document.body.textContent, /ART 充值档位/);
  assert.equal(document.querySelector('[data-testid="support"]'), null);
  assert.deepEqual(requests, ["/recharge/plans"]);
  await close();
});

test("main stays on support without requesting recharge plans", async () => {
  await mount(site("main"));
  assert.ok(document.querySelector('[data-testid="support"]'));
  assert.deepEqual(requests, []);
  await close();
});

test("disabled recharge module or disabled site cannot enter recharge", async () => {
  for (const config of [site("art", []), { ...site("art"), is_enabled: false }]) {
    await mount(config);
    assert.ok(document.querySelector('[data-testid="support"]'));
    assert.deepEqual(requests, []);
    await close();
  }
});

test("cold art load waits for config instead of redirecting using main defaults", async () => {
  let resolve;
  await mount(site("main"), false, new Promise((done) => { resolve = done; }));
  assert.match(document.body.textContent, /正在加载充值配置/);
  assert.equal(document.querySelector('[data-testid="support"]'), null);
  assert.deepEqual(requests, []);
  await act(async () => resolve(site("art")));
  assert.match(document.body.textContent, /ART 充值档位/);
  await close();
});

test("desktop and mobile recharge links follow the current site", async () => {
  for (const [key, target] of [["art", "/billing/recharge"], ["ccai", "/billing/recharge"], ["main", "/support"]]) {
    await mount(site(key), true);
    assert.equal(document.querySelector(".credit-pill").getAttribute("href"), target);
    await act(async () => document.querySelector('[aria-label="账户菜单"]').dispatchEvent(new MouseEvent("click", { bubbles: true })));
    const mobileLink = [...document.querySelectorAll('.account-menu__mobile-links a')].find((el) => el.textContent.includes("充值积分"));
    assert.equal(mobileLink.getAttribute("href"), target);
    await close();
  }
});
