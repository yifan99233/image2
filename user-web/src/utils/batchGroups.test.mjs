import assert from "node:assert/strict";
import test from "node:test";
import { File } from "node:buffer";
import { zipSync, strToU8 } from "fflate";
import { utils, write } from "xlsx";
import {
  groupImageFiles,
  readGroupZip,
  matchGroupPromptRows,
  groupPrompt,
  groupIssues,
  readGroupPromptFile,
  createGroupPromptTemplate,
  applyCommonGroupPrompt,
} from "./batchGroups.ts";
const image = (path) => ({
  file: new File(["image"], path.split("/").pop(), { type: "image/png" }),
  path,
});
const folderGroups = () =>
  groupImageFiles([
    image("包/商品A/正面.png"),
    image("包/商品A/侧面.png"),
    image("包/商品B/包装.png"),
  ]).groups;
const row = (folder, prompt = "提示词") => ({
  id: crypto.randomUUID(),
  folder,
  prompt,
  targetId: "",
  assignment: "auto",
});

for (const mode of ["overwrite", "supplement", "append"]) test(`common ${mode} updates effective imported and manual prompts while retaining unmatched rows and source inputs`, () => {
  const groups=folderGroups();
  groups[0].prompt="旧草稿";
  groups[1].prompt="手写B";
  groups.push({...groups[1],id:"group-c",name:"商品C",path:"包/商品C",prompt:""});
  const rows=[{...row("商品A","导入A"),targetId:groups[0].id,assignment:"manual"},{...row("商品C",""),targetId:"group-c"},row("其他","未匹配行")];
  const before=JSON.stringify([groups,rows]);
  const result=applyCommonGroupPrompt(groups,rows,"  新公共  ",mode);
  const expected=mode==="overwrite" ? ["新公共","新公共","新公共"] : mode==="append" ? ["导入A\n新公共","手写B\n新公共","新公共"] : ["导入A","手写B","新公共"];
  assert.deepEqual(result.groups.map(g=>groupPrompt(g,result.rows)),expected);
  assert.equal(result.affectedCount,mode==="supplement" ? 1 : 3);
  assert.equal(result.rows[2],rows[2]);
  assert.deepEqual(result.rows.map(r=>[r.id,r.folder,r.targetId,r.assignment]),rows.map(r=>[r.id,r.folder,r.targetId,r.assignment]));
  assert.equal(result.groups[0].images,groups[0].images);
  assert.equal(result.groups[0].outputs,groups[0].outputs);
  assert.equal(JSON.stringify([groups,rows]),before);
});
test("common prompts preserve unresolved mapping conflicts and ignore empty applications", () => {
  const groups=folderGroups();
  const rows=[{...row("A","第一条"),targetId:groups[0].id},{...row("B","第二条"),targetId:groups[0].id}];
  const appended=applyCommonGroupPrompt(groups,rows,"末尾","append");
  assert.deepEqual(appended.rows.map(r=>r.prompt),["第一条\n末尾","第二条\n末尾"]);
  assert.match(groupIssues(appended.groups,appended.rows,8).join(),/多条提示词/);
  const overwritten=applyCommonGroupPrompt(groups,rows,"统一","overwrite");
  assert.deepEqual(overwritten.rows.map(r=>r.prompt),["统一","统一"]);
  assert.match(groupIssues(overwritten.groups,overwritten.rows,8).join(),/多条提示词/);
  const supplemented=applyCommonGroupPrompt(groups,rows,"统一","supplement");
  assert.equal(supplemented.groups[0],groups[0]);
  assert.equal(supplemented.rows[0],rows[0]);
  const empty=applyCommonGroupPrompt(groups,rows," \n ","overwrite");
  assert.equal(empty.groups,groups);
  assert.equal(empty.rows,rows);
  assert.equal(empty.affectedCount,0);
});

test("folder structure keeps all references in each parent, ignores metadata and never merges same basenames", () => {
  const { groups, skipped } = groupImageFiles([
    image("包/A/正面.png"),
    image("包/A/侧面.png"),
    image("包/嵌套/A/正面.png"),
    image("包/__MACOSX/x.png"),
    image("包/A/note.txt"),
  ]);
  assert.deepEqual(
    groups.map((g) => [g.name, g.path, g.images.length]),
    [
      ["A", "包/A", 2],
      ["A", "包/嵌套/A", 1],
    ],
  );
  assert.equal(skipped, 2);
  assert.notEqual(groups[0].id, groups[1].id);
});
test("ZIP supports Unicode folder names, nested directories and multiple references", async () => {
  const packed = zipSync({
    "包/商品A/正面.png": strToU8("front"),
    "包/商品A/侧面.png": strToU8("side"),
    "包/商品B/包装.jpg": strToU8("pack"),
    "包/readme.txt": strToU8("ignore"),
  });
  const result = await readGroupZip(new File([packed], "素材.zip"));
  assert.deepEqual(
    result.groups.map((g) => [g.name, g.images.map((i) => i.file.name)]),
    [
      ["商品A", ["正面.png", "侧面.png"]],
      ["商品B", ["包装.jpg"]],
    ],
  );
  assert.equal(result.skipped, 1);
  assert.equal(await result.groups[0].images[1].file.text(), "side");
});
test("ZIP and direct inputs reject corrupt archives, traversal, empty and oversized images", async () => {
  await assert.rejects(readGroupZip(new File(["invalid"], "bad.zip")), /ZIP|找到/);
  await assert.rejects(
    readGroupZip(new File([zipSync({ "../bad.png": strToU8("bad") })], "bad.zip")),
    /无效路径/,
  );
  await assert.rejects(
    readGroupZip(
      new File([zipSync({ "a.png": new Uint8Array(10 * 1024 * 1024 + 1) })], "huge.zip"),
    ),
    /超过|限制/,
  );
  assert.throws(
    () => groupImageFiles([{ file: new File([], "empty.png"), path: "empty.png" }]),
    /为空/,
  );
});
test("name matching does not use upload order and normalizes Unicode, while retaining multiline prompts", async () => {
  const groups = folderGroups();
  const rows = await readGroupPromptFile(
    new File(['文件夹名,提示词\n商品B,"柔光, 客厅\n保留包装"\n商品A,白底'], "p.csv"),
  );
  const matched = matchGroupPromptRows(rows, groups);
  assert.equal(matched[0].targetId, groups[1].id);
  assert.equal(matched[1].targetId, groups[0].id);
  assert.equal(groupPrompt(groups[1], matched), "柔光, 客厅\n保留包装");
  assert.deepEqual(groupIssues(groups, matched, 8), []);
  groups[0].name = "é";
  assert.equal(matchGroupPromptRows([row("e\u0301")], groups)[0].targetId, groups[0].id);
});
test("duplicate folders, duplicate prompt keys, unmatched names and unnamed TXT cannot auto-bind", async () => {
  const groups = folderGroups();
  groups.push({ ...groups[0], id: crypto.randomUUID(), path: "另包/商品A" });
  const rows = matchGroupPromptRows(
    [row("商品A"), row("商品B"), row("商品B"), row("不存在")],
    groups,
  );
  assert.ok(rows.every((r) => !r.targetId));
  const txt = await readGroupPromptFile(new File(["第一条\n第二条"], "p.txt"));
  assert.ok(matchGroupPromptRows(txt, groups).every((r) => !r.targetId));
  assert.match(groupIssues(groups, rows, 8).join(","), /尚未匹配/);
});
test("manual selection resolves ambiguities, conflicts block submission, rename re-matches auto rows", () => {
  const groups = folderGroups();
  let rows = matchGroupPromptRows([row("商品A")], groups);
  groups[0].name = "改名";
  assert.equal(matchGroupPromptRows(rows, groups)[0].targetId, "");
  rows = rows.map((r) => ({ ...r, targetId: groups[0].id, assignment: "manual" }));
  assert.equal(matchGroupPromptRows(rows, groups)[0].targetId, groups[0].id);
  rows.push({ ...row("其他"), targetId: groups[0].id, assignment: "manual" });
  assert.match(groupIssues(groups, rows, 8).join(","), /多条提示词/);
  assert.equal(matchGroupPromptRows(rows, groups.slice(1))[0].targetId, "");
});
test("outputs rather than reference count determine tasks, validates model limits and 2000-output ceiling", () => {
  const groups = folderGroups().map((g) => ({ ...g, prompt: "test", outputs: 2 }));
  assert.deepEqual(groupIssues(groups, [], 2), []);
  assert.match(groupIssues(groups, [], 1).join(","), /1–1 张参考图/);
  assert.match(groupIssues([{ ...groups[0], outputs: 1.5 }], [], 8).join(","), /整数/);
  const many = Array.from({ length: 223 }, (_, i) => ({ ...groups[0], id: String(i), outputs: 9 }));
  assert.match(groupIssues(many, [], 8).join(","), /最多生成 2000/);
});
for (const format of ["txt", "csv", "xlsx"])
  test(`current-folder ${format} templates round-trip names and prompts`, async () => {
    const groups = folderGroups().map((g) => ({ ...g, prompt: "一段,提示词\n第二行" }));
    const template = await createGroupPromptTemplate(groups, format);
    const imported = await readGroupPromptFile(new File([template.blob], template.filename));
    assert.deepEqual(
      imported.map((r) => [r.folder, r.prompt]),
      groups.map((g) => [g.name, g.prompt]),
    );
  });
test("named TXT matches exact folder names from tab columns or explicit folder prefixes, independently of order", async () => {
  const groups = folderGroups();
  const txt = '\ufeff文件夹名\t提示词\r\n商品B\t客厅包装\r\n本任务对应文件夹“商品A”，商品编号 001。保留颜色\r\n';
  const imported = await readGroupPromptFile(new File([txt], "p.txt"));
  assert.deepEqual(imported.map(r=>r.folder), ["商品B", "商品A"]);
  const matched = matchGroupPromptRows(imported, groups);
  assert.deepEqual(matched.map(r=>r.targetId), [groups[1].id, groups[0].id]);
  assert.equal(groupPrompt(groups[0],matched), '本任务对应文件夹“商品A”，商品编号 001。保留颜色');
  assert.deepEqual(groupIssues(groups,matched,2), []);
});
test("unnamed TXT never infers folder names from order or incidental mentions; ambiguous names still require manual selection", async () => {
  const groups = folderGroups();
  const imported = await readGroupPromptFile(new File(['请参考文件夹“商品A”中的色彩\n白底图\n商品A\t柔光\n商品A\t保留颜色\n不存在\t主图'],"p.txt"));
  assert.deepEqual(imported.map(r=>r.folder), ["", "", "商品A", "商品A", "不存在"]);
  assert.ok(matchGroupPromptRows(imported, groups).every(r=>!r.targetId));
});
test("XLS imports named columns independent of column order; wrong and blank tables are rejected", async () => {
  const book = utils.book_new();
  utils.book_append_sheet(
    book,
    utils.aoa_to_sheet([
      ["提示词", "文件夹名"],
      ["白底", "商品A"],
    ]),
    "p",
  );
  const imported = await readGroupPromptFile(
    new File([write(book, { type: "array", bookType: "xls" })], "p.xls"),
  );
  assert.deepEqual(
    imported.map((r) => [r.folder, r.prompt]),
    [["商品A", "白底"]],
  );
  await assert.rejects(readGroupPromptFile(new File(["提示词\n白底"], "bad.csv")), /两列表头/);
  await assert.rejects(
    readGroupPromptFile(new File(["文件夹名,提示词\n"], "blank.csv")),
    /没有提示词/,
  );
  await assert.rejects(
    readGroupPromptFile({ name: "huge.xlsx", size: 8 * 1024 * 1024 + 1 }),
    /8MB/,
  );
});
