import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { act, createElement, useState } from "react";

const dom = new JSDOM('<div id="root"></div>', { url: "http://test" });
for (const key of ["window", "document", "HTMLElement", "HTMLInputElement", "Event", "MouseEvent"]) globalThis[key] = dom.window[key];
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { createRoot } = await import("react-dom/client");
await build({ entryPoints: ["src/components/video/VideoDurationPicker.tsx"], outfile: "node_modules/.tmp/video-duration-picker.mjs",
  bundle: true, format: "esm", platform: "node", packages: "external", jsx: "automatic", loader: { ".css": "empty" } });
const { VideoDurationPicker } = await import("../node_modules/.tmp/video-duration-picker.mjs");
const options = [6, 10, 20, 30, 40, 50, 60].map(n => ({ value: String(n), label: `${n} 秒` }));

test("duration buttons select 60 seconds and expose the selection to keyboard/assistive controls", async () => {
  let chosen;
  function Harness() {
    const [value, setValue] = useState("10");
    return createElement(VideoDurationPicker, { options, value, onChange: v => { chosen = v; setValue(v); } });
  }
  const root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(Harness)));
  try {
    const button = [...document.querySelectorAll("button")].find(b => b.textContent === "60 秒");
    await act(async () => button.click());
    assert.equal(chosen, "60");
    assert.equal(button.getAttribute("aria-pressed"), "true");
    assert.equal(document.querySelector("output").textContent, "60 秒");
    assert.equal(document.querySelector('input[type="range"]').value, "6");
    assert.equal(document.querySelector('input[type="range"]').getAttribute("aria-valuetext"), "60 秒");
  } finally { await act(async () => root.unmount()); }
});

test("picker uses only model configured options and prevents selection while disabled", async () => {
  let calls = 0;
  const root = createRoot(document.getElementById("root"));
  await act(async () => root.render(createElement(VideoDurationPicker, { options: options.slice(0, 2), value: "6", disabled: true, onChange: () => calls++ })));
  try {
    assert.deepEqual([...document.querySelectorAll("button")].map(b => b.textContent), ["6 秒", "10 秒"]);
    await act(async () => document.querySelector("button").click());
    assert.equal(calls, 0);
    assert.equal(document.querySelector("fieldset").disabled, true);
  } finally { await act(async () => root.unmount()); }
});
