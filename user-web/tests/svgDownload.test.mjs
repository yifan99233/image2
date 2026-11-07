import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { transformSync } from "esbuild";

const source = await readFile(new URL("../src/utils/download.ts", import.meta.url), "utf8");
const code = transformSync(source.replace(/^import .*;\n/gm, ""), { loader: "ts", format: "cjs" }).code;

test("SVG downloads use the correct filename for direct and streamed downloads", async () => {
  for (const direct of [true, false]) {
    const downloads = [];
    const sandbox = {
      module: { exports: {} },
      window: { location: { href: "https://app.test/", origin: "https://app.test" } },
      document: { body: { appendChild() {} }, createElement() { return { click() { downloads.push(this.download); }, remove() {} }; } },
      resolveAssetUrl: value => value,
      planDownloadTarget: url => ({ url, canDownloadDirectly: direct }),
      streamBrowserDownload: async (_target, filename) => downloads.push(filename),
    };
    vm.runInNewContext(code, sandbox);
    await sandbox.module.exports.downloadMedia("https://cdn.test/image.svg", "冰雪圣诞", "image/svg+xml");
    await sandbox.module.exports.downloadMedia("https://cdn.test/image.svg", "冰雪圣诞.svg", "image/svg+xml");
    assert.deepEqual(downloads, ["冰雪圣诞.svg", "冰雪圣诞.svg"]);
  }
});
