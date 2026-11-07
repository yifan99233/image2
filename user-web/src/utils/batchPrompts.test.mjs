import assert from "node:assert/strict";
import test from "node:test";
import { File } from "node:buffer";
import { utils, write } from "xlsx";
import { appendBatchPrompts, createBatchPromptTemplate, readBatchPromptFile, readBatchGenerateFile } from "./batchPrompts.ts";

const workbookFile = (rows) => {
  const book = utils.book_new();
  utils.book_append_sheet(book, utils.aoa_to_sheet(rows), "提示词");
  return new File([write(book, { bookType: "xlsx", type: "array" })], "series.xlsx");
};

test("series headings switch folders, blanks skip, multiline prompts stay intact", async () => {
  const result = await readBatchGenerateFile(workbookFile([
    ["【XMAS-SER-001】"], [], ["first\nkeep the newline"], ["scene with 【text】 inside"],
    ["【XMAS-SER-480】"], [], ["last"], [],
  ]), 3);
  assert.deepEqual(result, { prompts: ["first\nkeep the newline", "scene with 【text】 inside", "last"],
    folderNames: ["【XMAS-SER-001】", "【XMAS-SER-001】", "【XMAS-SER-480】"] });
});

test("named import rejects invalid files atomically", async () => {
  for (const [rows, error] of [
    [[["【folder】", "extra"], ["prompt"]], /只允许 A 列/],
    [[[undefined, "【folder】"], [undefined, "prompt"]], /只允许 A 列/],
    [[["【..\/escape】"], ["prompt"]], /名称不合法/],
    [[["【first】"], ["【second】"], ["prompt"]], /没有提示词/],
    [[["【first】"], ["prompt"], ["【empty】"]], /没有提示词/],
    [[["【folder】"], [{ f: "1+1", v: 2 }]], /公式/],
    [[["【folder】"], ["a"], ["b"]], /当前单批上限/],
    [[["not a heading"], ["prompt"]], /文件夹名称/],
  ]) await assert.rejects(readBatchGenerateFile(workbookFile(rows), 1), error);
  await assert.rejects(readBatchGenerateFile(new File(["not excel"], "bad.xlsx"), 10), /格式不符/);
});

test("20,000 prompts across 1000 folders exclude every heading", async () => {
  const rows = Array.from({ length: 1000 }, (_, i) => [[`【series-${i + 1}】`], ...Array.from({ length: 20 }, (_, j) => [`prompt-${i}-${j}`])]).flat();
  const result = await readBatchGenerateFile(workbookFile(rows), 20000);
  assert.equal(result.prompts.length, 20000);
  assert.equal(new Set(result.folderNames).size, 1000);
  assert.equal(result.folderNames[9580], "【series-480】");
  assert.equal(result.prompts.at(-1), "prompt-999-19");
});

test("TXT imports preserve Chinese text, skip blank lines and remove BOM", async () => {
  const file = new File(["\ufeff 白底商品图\r\n\r\n 客厅场景 \r\n"], "prompts.TXT");
  assert.deepEqual(await readBatchPromptFile(file, 2), ["白底商品图", "客厅场景"]);
});

test("CSV preserves quoted commas and keeps a multiline cell in one task", async () => {
  const file = new File(['\ufeff"提示词"\r\n"白底, 柔和阴影"\r\n"客厅\n自然光"\r\n'], "prompts.csv");
  assert.deepEqual(await readBatchPromptFile(file, 2), ["白底, 柔和阴影", "客厅 自然光"]);
});

for (const bookType of ["xlsx", "xls"]) {
  test(`${bookType.toUpperCase()} imports the first worksheet and excludes its header`, async () => {
    const workbook = utils.book_new();
    utils.book_append_sheet(workbook, utils.aoa_to_sheet([["场景提示词"], ["白底商品"], [], ["细节", "自然光"]]), "提示词");
    utils.book_append_sheet(workbook, utils.aoa_to_sheet([["忽略第二张工作表"]]), "其他");
    const file = new File([write(workbook, { bookType, type: "array" })], `prompts.${bookType}`);
    assert.deepEqual(await readBatchPromptFile(file, 2), ["白底商品", "细节, 自然光"]);
  });
}

for (const format of ["txt", "csv", "xlsx"]) {
  test(`${format.toUpperCase()} templates round-trip into three usable prompts`, async () => {
    for (const isEdit of [false, true]) {
      const template = await createBatchPromptTemplate(isEdit, format);
      const prompts = await readBatchPromptFile(new File([template.blob], template.filename), 3);
      assert.equal(prompts.length, 3);
      assert.match(prompts[0], /白底电商主图/);
      assert.ok(!prompts.includes("提示词") && !prompts.includes("场景提示词"));
    }
  });
}

test("imports reject empty files, unsupported formats and oversized files", async () => {
  await assert.rejects(readBatchPromptFile(new File(["\n\n"], "empty.txt"), 2000), /没有读取到有效提示词/);
  await assert.rejects(readBatchPromptFile(new File(["提示词"], "prompts.pdf"), 2000), /仅支持 TXT/);
  await assert.rejects(readBatchPromptFile({ name: "huge.txt", size: 8 * 1024 * 1024 + 1 }, 2000), /不能超过 8MB/);
});

test("row limits and combined limits prevent partial or excessive imports", async () => {
  const file = new File([Array.from({ length: 2001 }, (_, i) => `提示词${i}`).join("\n")], "too-many.txt");
  await assert.rejects(readBatchPromptFile(file, 2000), /最多包含 2000 条/);
  assert.equal(appendBatchPrompts("已有\n\n", ["新增"], 2), "已有\n新增");
  assert.throws(() => appendBatchPrompts("已有", ["新增1", "新增2"], 2), /合并后共 3 条/);
});
