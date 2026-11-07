export type BatchPromptTemplateFormat = "txt" | "csv" | "xlsx";
export type BatchEditPromptMode = "shared" | "per_image" | "matrix" | "grouped";

const MAX_PROMPT_FILE_BYTES = 8 * 1024 * 1024;
const PROMPT_HEADERS = /^(prompt|prompts|提示词|场景提示词|指令|描述)$/i;

export type BatchPromptImport = { prompts: string[]; folderNames?: string[] };
const SERIES_HEADER = /^【[^【】\r\n]+】$/;
export const validatePromptFolder = (name: string) => {
  if (!name || name.length > 120 || new TextEncoder().encode(name).length > 240 || /[<>:"/\\|?*\x00-\x1f]/.test(name) || /[. ]$/.test(name) || /^(\.|\.\.|CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(name)) {
    throw new Error(`文件夹名称不合法：${name.slice(0, 120) || "空名称"}`);
  }
};

/** Named single-column sheets: the first row and later 【series】 rows are folders. */
export const readBatchGenerateFile = async (file: Pick<File, "name" | "size" | "text" | "arrayBuffer">, limit: number): Promise<BatchPromptImport> => {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!["xlsx", "xls", "csv"].includes(extension ?? "")) return { prompts: await readBatchPromptFile(file, limit) };
  if (!file.size || file.size > 64 * 1024 * 1024) throw new Error("提示词文件不能为空或超过 64MB");
  const { read, utils } = await import("xlsx");
  const source = extension === "csv" ? (await file.text()).replace(/^\uFEFF/, "") : new Uint8Array(await file.arrayBuffer());
  if (source instanceof Uint8Array) {
    const signature = Array.from(source.slice(0, 8)).map(v => v.toString(16).padStart(2, "0")).join("");
    if (extension === "xlsx" ? !signature.startsWith("504b0304") : signature !== "d0cf11e0a1b11ae1") throw new Error("文件内容与 Excel 格式不符，请上传有效的 Excel 文件");
  }
  let workbook;
  try { workbook = read(source, { type: extension === "csv" ? "string" : "array", raw: true, sheetRows: 100_001 }); }
  catch { throw new Error("Excel 文件损坏或格式不合法，无法读取提示词"); }
  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  if (!sheet) throw new Error("文件里没有读取到有效提示词");
  const range = utils.decode_range(sheet["!fullref"] || sheet["!ref"] || "A1");
  if (range.e.r >= 100_000 || range.e.c > 100) throw new Error("工作表范围过大，请删除多余的空白行列后导入");
  const rows = utils.sheet_to_json<unknown[]>(sheet, { header: 1, blankrows: true, raw: true, range: { s: { r: 0, c: 0 }, e: range.e } });
  const values = rows.map((row, index) => {
    for (let col = 0; col < row.length; col++) {
      const cell = sheet[utils.encode_cell({ r: index, c: col })];
      if (cell?.f || cell?.t === "e") throw new Error(`第 ${index + 1} 行含公式或错误单元格，请改成提示词原文`);
    }
    return row.map(value => String(value ?? "").trim());
  });
  const nonempty = values.map((row, index) => ({ row, index })).filter(({ row }) => row.some(Boolean));
  if (!nonempty.length) throw new Error("文件里没有读取到有效提示词");
  if (PROMPT_HEADERS.test(nonempty[0].row.filter(Boolean).join(", "))) return { prompts: await readBatchPromptFile(file, limit) };
  if (workbook.SheetNames.slice(1).some(name => Object.entries(workbook.Sheets[name]).some(([key, cell]) => !key.startsWith("!") && (cell.v != null || cell.f)))) {
    throw new Error("系列提示词文件只支持一张有内容的工作表，请合并或拆分后导入");
  }
  const prompts: string[] = [], folderNames: string[] = [];
  let folder = "", count = 0;
  for (const { row, index } of nonempty) {
    if (!row[0] || row.slice(1).some(Boolean)) throw new Error(`第 ${index + 1} 行格式不合法：只允许 A 列填写文件夹名或提示词`);
    const value = row[0];
    if (!folder || SERIES_HEADER.test(value)) {
      if (!SERIES_HEADER.test(value)) throw new Error(`第 ${index + 1} 行应为【文件夹名称】，后面每行填写一条提示词`);
      if (folder && !count) throw new Error(`文件夹 ${folder} 下没有提示词`);
      validatePromptFolder(value);
      folder = value; count = 0;
    } else {
      if (value.length > 100_000) throw new Error(`第 ${index + 1} 行提示词超过 100,000 字符`);
      prompts.push(value); folderNames.push(folder); count++;
    }
  }
  if (!count) throw new Error(`文件夹 ${folder} 下没有提示词`);
  if (prompts.length > limit) throw new Error(`文件共 ${prompts.length} 条提示词，当前单批上限为 ${limit} 条，请调整批量任务上限或拆分文件`);
  return { prompts, folderNames };
};

export const splitBatchPrompts = (text: string) => text.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

export const appendBatchPrompts = (current: string, incoming: string[], limit: number) => {
  const combined = [...splitBatchPrompts(current), ...incoming];
  if (combined.length > limit) throw new Error(`提示词最多 ${limit} 条，合并后共 ${combined.length} 条，请拆分文件后导入`);
  return combined.join("\n");
};

export const readBatchPromptFile = async (file: Pick<File, "name" | "size" | "text" | "arrayBuffer">, limit: number): Promise<string[]> => {
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!["txt", "csv", "xlsx", "xls"].includes(extension ?? "")) throw new Error("仅支持 TXT、CSV、XLSX 或 XLS 文件");
  if (file.size > MAX_PROMPT_FILE_BYTES) throw new Error("提示词文件不能超过 8MB");
  let prompts: string[];
  if (extension === "txt") {
    prompts = splitBatchPrompts(await file.text());
  } else {
    const { read, utils } = await import("xlsx");
    const source = extension === "csv" ? (await file.text()).replace(/^\uFEFF/, "") : await file.arrayBuffer();
    const workbook = read(source, { type: extension === "csv" ? "string" : "array", raw: true });
    const firstSheet = workbook.SheetNames[0];
    const rows = firstSheet ? utils.sheet_to_json<unknown[]>(workbook.Sheets[firstSheet], { header: 1, blankrows: false, raw: false }) : [];
    prompts = rows.map((row) => row.map((cell) => String(cell ?? "").replace(/^\uFEFF/, "").replace(/[\r\n]+/g, " ").trim()).filter(Boolean).join(", ")).filter(Boolean);
    if (prompts[0] && PROMPT_HEADERS.test(prompts[0])) prompts.shift();
  }
  if (!prompts.length) throw new Error("文件里没有读取到有效提示词");
  if (prompts.length > limit) throw new Error(`提示词文件最多包含 ${limit} 条，请拆分后导入`);
  return prompts;
};

export const createBatchPromptTemplate = async (isBatchEdit: boolean, format: BatchPromptTemplateFormat) => {
  const rows = isBatchEdit
    ? [["场景提示词"], ["白底电商主图，保留商品材质、轮廓和 Logo"], ["生活方式场景，商品置于客厅边几，柔和自然光"], ["细节特写，突出纹理、结构和功能，商业摄影"]]
    : [["提示词"], ["白底电商主图，一瓶透明护肤精华，柔和阴影"], ["复古木质餐桌上的陶瓷杯，暖色自然光"], ["户外露营场景中的便携咖啡壶，真实产品摄影"]];
  const filename = `${isBatchEdit ? "magic-商品套图提示词模板" : "magic-批量生图提示词模板"}.${format}`;
  if (format === "txt") return { filename, blob: new Blob([rows.slice(1).map(([value]) => value).join("\n") + "\n"], { type: "text/plain;charset=utf-8" }) };
  if (format === "csv") return { filename, blob: new Blob(["\ufeff" + rows.map(([value]) => `"${value.replaceAll('"', '""')}"`).join("\n") + "\n"], { type: "text/csv;charset=utf-8" }) };
  const { utils, write } = await import("xlsx");
  const sheet = utils.aoa_to_sheet(rows);
  sheet["!cols"] = [{ wch: 72 }];
  const workbook = utils.book_new();
  utils.book_append_sheet(workbook, sheet, isBatchEdit ? "商品套图提示词" : "批量生图提示词");
  const bytes: ArrayBuffer = write(workbook, { bookType: "xlsx", type: "array" });
  return { filename, blob: new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }) };
};
