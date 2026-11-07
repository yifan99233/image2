export const MAX_GROUPS = 1000;
export const MAX_GROUP_OUTPUTS = 2000;
export const MAX_GROUP_IMAGES = 10000;
export const MAX_GROUP_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_GROUP_TOTAL_BYTES = 250 * 1024 * 1024;
const IMAGE_EXTENSION = /\.(png|jpe?g|webp)$/i;
export type GroupFile = { file: File; path: string };
export type BatchGroup = {
  id: string;
  name: string;
  path: string;
  images: GroupFile[];
  prompt: string;
  outputs: number;
};
export type GroupPromptRow = {
  id: string;
  folder: string;
  prompt: string;
  targetId: string;
  assignment: "auto" | "manual";
};
export type CommonGroupPromptMode = "overwrite" | "supplement" | "append";
export const folderKey = (name: string) =>
  name
    .replace(/^\uFEFF/, "")
    .trim()
    .normalize("NFC");
const ignoredPath = (path: string) =>
  path.split("/").some((part) => part.startsWith(".") || part === "__MACOSX");

export const validateGroupFiles = (images: GroupFile[]) => {
  if (images.length > MAX_GROUP_IMAGES)
    throw new Error(`每批最多 ${MAX_GROUP_IMAGES} 张参考图，请拆分上传`);
  if (images.reduce((sum, image) => sum + image.file.size, 0) > MAX_GROUP_TOTAL_BYTES)
    throw new Error("参考图总大小不能超过 250MB");
  for (const { file, path } of images) {
    if (file.size > MAX_GROUP_FILE_BYTES) throw new Error(`图片“${path}”超过 10MB`);
    if (!file.size) throw new Error(`图片“${path}”为空文件`);
  }
};

export const groupImageFiles = (files: { file: File; path: string }[], fallbackName = "任务组") => {
  if (
    files.some(
      ({ path }) => path.replaceAll("\\", "/").split("/").includes("..") || path.startsWith("/"),
    )
  )
    throw new Error("文件包中包含无效路径");
  const images = files.filter(({ path }) => IMAGE_EXTENSION.test(path) && !ignoredPath(path));
  if (!images.length) throw new Error("没有找到 PNG、JPG 或 WEBP 图片");
  validateGroupFiles(images);
  const paths = images.map((image) => image.path);
  if (new Set(paths).size !== paths.length)
    throw new Error("同一任务组中存在重复文件路径，请检查文件包");
  const folders = new Map<string, GroupFile[]>();
  for (const image of images) {
    const parts = image.path.replaceAll("\\", "/").split("/");
    if (parts.some((part) => part === "..") || image.path.startsWith("/"))
      throw new Error("文件包中包含无效路径");
    const parent = parts.slice(0, -1).join("/") || fallbackName;
    folders.set(parent, [...(folders.get(parent) ?? []), image]);
  }
  if (folders.size > MAX_GROUPS) throw new Error(`每批最多 ${MAX_GROUPS} 个任务组`);
  return {
    groups: [...folders].map(
      ([path, groupImages]): BatchGroup => ({
        id: crypto.randomUUID(),
        name: path.split("/").pop() || fallbackName,
        path,
        images: groupImages,
        prompt: "",
        outputs: 1,
      }),
    ),
    skipped: files.length - images.length,
  };
};

// Streaming inflation enforces actual bytes, including ZIPs with false size
// headers. No archive member is written to disk or automatically executed.
export const readGroupZip = async (file: File) => {
  if (file.size > 100 * 1024 * 1024) throw new Error("ZIP 文件不能超过 100MB，请拆分上传");
  const { Unzip, UnzipInflate } = await import("fflate");
  const packed = new Uint8Array(await file.arrayBuffer());
  const files: { file: File; path: string }[] = [];
  let total = 0;
  let members = 0;
  let skipped = 0;
  const paths = new Set<string>();
  let failure: Error | null = null;
  const archive = new Unzip((entry) => {
    if (++members > 20000) throw new Error("ZIP 中的文件过多，请拆分上传");
    if (entry.name.replaceAll("\\", "/").split("/").includes("..") || entry.name.startsWith("/"))
      throw new Error("文件包中包含无效路径");
    if (entry.name.endsWith("/") || ignoredPath(entry.name)) return;
    if (!IMAGE_EXTENSION.test(entry.name)) {
      skipped++;
      return;
    }
    if (paths.has(entry.name)) throw new Error("ZIP 中存在重复文件路径，请检查文件包");
    paths.add(entry.name);
    if (files.length >= MAX_GROUP_IMAGES || (entry.originalSize ?? 0) > MAX_GROUP_FILE_BYTES)
      throw new Error("ZIP 中的图片数量或单图大小超过限制");
    let received = 0;
    const chunks: Uint8Array<ArrayBuffer>[] = [];
    entry.ondata = (error, bytes, final) => {
      if (failure) return;
      if (error) {
        failure = new Error("ZIP 解压失败，请检查文件是否损坏或加密");
        return;
      }
      received += bytes.length;
      total += bytes.length;
      if (received > MAX_GROUP_FILE_BYTES || total > MAX_GROUP_TOTAL_BYTES) {
        failure = new Error("ZIP 解压后的图片超过大小限制（单图 10MB、总计 250MB）");
        entry.terminate();
        return;
      }
      chunks.push(new Uint8Array(bytes));
      if (final) {
        const name = entry.name.split("/").pop() || "image.png";
        const type = /\.webp$/i.test(name)
          ? "image/webp"
          : /\.png$/i.test(name)
            ? "image/png"
            : "image/jpeg";
        files.push({ file: new File(chunks, name, { type }), path: entry.name });
      }
    };
    entry.start();
  });
  archive.register(UnzipInflate);
  try {
    // Yield between chunks so large archives do not freeze form controls.
    for (let offset = 0; offset < packed.length; offset += 64 * 1024) {
      archive.push(
        packed.subarray(offset, offset + 64 * 1024),
        offset + 64 * 1024 >= packed.length,
      );
      if (failure) throw failure;
      if (offset % (1024 * 1024) === 0) await new Promise((resolve) => setTimeout(resolve, 0));
    }
    if (paths.size !== files.length) throw new Error("ZIP 解压未完成，请检查文件是否损坏");
    const result = groupImageFiles(files, file.name.replace(/\.zip$/i, ""));
    return { ...result, skipped: result.skipped + skipped };
  } catch (error) {
    throw (
      failure ??
      (error instanceof Error && /限制|过多|超过|无效|找到|为空/.test(error.message)
        ? error
        : new Error("ZIP 解压失败，请检查文件是否损坏或加密"))
    );
  }
};

export const matchGroupPromptRows = (rows: GroupPromptRow[], groups: BatchGroup[]) => {
  const groupIds = new Set(groups.map((group) => group.id));
  const byName = new Map<string, BatchGroup[]>();
  const rowCounts = new Map<string, number>();
  for (const group of groups) {
    const key = folderKey(group.name);
    byName.set(key, [...(byName.get(key) ?? []), group]);
  }
  for (const row of rows) {
    const key = folderKey(row.folder);
    rowCounts.set(key, (rowCounts.get(key) ?? 0) + 1);
  }
  return rows.map((row) => {
    if (row.assignment === "manual")
      return { ...row, targetId: groupIds.has(row.targetId) ? row.targetId : "" };
    const key = folderKey(row.folder);
    const candidates = key ? (byName.get(key) ?? []) : [];
    return {
      ...row,
      targetId: candidates.length === 1 && rowCounts.get(key) === 1 ? candidates[0].id : "",
    };
  });
};

export const groupPrompt = (group: BatchGroup, rows: GroupPromptRow[]) => {
  const assigned = rows.filter((row) => row.targetId === group.id);
  return assigned.length === 1 ? assigned[0].prompt : group.prompt;
};

export const applyCommonGroupPrompt = (
  groups: BatchGroup[], rows: GroupPromptRow[], prompt: string, mode: CommonGroupPromptMode,
) => {
  const addition = prompt.trim();
  if (!addition) return { groups, rows, affectedCount: 0 };
  const assigned = new Map<string, GroupPromptRow[]>();
  for (const row of rows) assigned.set(row.targetId, [...(assigned.get(row.targetId) ?? []), row]);
  const affected = new Set<string>();
  const transform = (current: string) => mode === "append" && current.trim() ? `${current.trimEnd()}\n${addition}` : addition;
  const nextGroups = groups.map((group) => {
    const groupRows = assigned.get(group.id) ?? [];
    const current = groupRows.length === 1 ? groupRows[0].prompt : group.prompt;
    const hasPrompt = current.trim() || (groupRows.length > 1 && groupRows.some((row) => row.prompt.trim()));
    if (mode === "supplement" && hasPrompt) return group;
    affected.add(group.id);
    return { ...group, prompt: transform(current) };
  });
  const nextRows = rows.map((row) => affected.has(row.targetId) ? { ...row, prompt: transform(row.prompt) } : row);
  return { groups: nextGroups, rows: nextRows, affectedCount: affected.size };
};

export const groupIssues = (groups: BatchGroup[], rows: GroupPromptRow[], maxInputs: number) => {
  const issues: string[] = [];
  if (!groups.length) issues.push("请先添加文件夹或任务组");
  if (groups.length > MAX_GROUPS) issues.push(`最多 ${MAX_GROUPS} 个任务组`);
  const unmatched = rows.filter((row) => !groups.some((group) => group.id === row.targetId)).length;
  if (unmatched) issues.push(`${unmatched} 条提示词尚未匹配，请选择任务组或移除该行`);
  let promptChars = 0;
  for (const group of groups) {
    const assigned = rows.filter((row) => row.targetId === group.id);
    if (group.path.length > 1024) issues.push("任务组文件夹路径过长");
    if (!folderKey(group.name) || group.name.trim().length > 255)
      issues.push("任务组名称须为 1–255 个字符");
    if (assigned.length > 1) issues.push(`“${group.name}”匹配到多条提示词，请保留一条`);
    if (!groupPrompt(group, rows).trim()) issues.push(`“${group.name}”缺少提示词`);
    promptChars += groupPrompt(group, rows).length;
    if (!group.images.length || group.images.length > maxInputs)
      issues.push(`“${group.name}”须包含 1–${maxInputs} 张参考图`);
    if (!Number.isInteger(group.outputs) || group.outputs < 1 || group.outputs > 9)
      issues.push("每组生成张数须为 1–9 的整数");
  }
  if (promptChars > 1_000_000) issues.push("提示词总量过大，请拆分提交");
  if (groups.reduce((sum, group) => sum + group.outputs, 0) > MAX_GROUP_OUTPUTS)
    issues.push(`单批最多生成 ${MAX_GROUP_OUTPUTS} 张图`);
  try {
    validateGroupFiles(groups.flatMap((group) => group.images));
  } catch (error) {
    issues.push((error as Error).message);
  }
  return issues;
};

export const readGroupPromptFile = async (
  file: Pick<File, "name" | "size" | "text" | "arrayBuffer">,
): Promise<GroupPromptRow[]> => {
  if (file.size > 8 * 1024 * 1024) throw new Error("提示词文件不能超过 8MB");
  const extension = file.name.split(".").pop()?.toLowerCase();
  let values: { folder: string; prompt: string }[];
  if (extension === "txt") {
    const lines = (await file.text()).replace(/^\uFEFF/, "").split(/\r?\n/);
    values = lines.flatMap((line) => {
      if (!line.trim()) return [];
      const tab = line.indexOf("\t");
      if (tab >= 0) {
        const folder = folderKey(line.slice(0, tab));
        let prompt = line.slice(tab + 1).trim();
        // Quoted template cells preserve line breaks and tabs within one TXT record.
        if (prompt.startsWith('"')) {
          try {
            const decoded: unknown = JSON.parse(prompt);
            if (typeof decoded === "string") prompt = decoded.trim();
          } catch { /* Plain prompt text may contain quotes. */ }
        }
        if (/^(文件夹名|文件夹名称|任务组名称|folder|folder_name)$/i.test(folder) && /^(提示词|prompt)$/i.test(prompt)) return [];
        return [{ folder, prompt }];
      }
      const prompt = line.trim();
      // Older test kits explicitly name the folder at the start of the prompt.
      // Do not infer names from order or from incidental mentions within the text.
      const named = prompt.match(/^(?:本任务对应)?(?:文件夹|任务组)(?:名称|名)?\s*[:：]?\s*(?:“([^”]+)”|"([^"]+)"|「([^」]+)」)/);
      return [{ folder: named ? folderKey(named[1] || named[2] || named[3]) : "", prompt }];
    }).filter((row) => row.folder || row.prompt);
  } else if (["csv", "xlsx", "xls"].includes(extension || "")) {
    const { read, utils } = await import("xlsx");
    const workbook = read(
      extension === "csv" ? (await file.text()).replace(/^\uFEFF/, "") : await file.arrayBuffer(),
      { type: extension === "csv" ? "string" : "array", raw: true },
    );
    const sheet = workbook.SheetNames[0];
    const rows = sheet
      ? utils.sheet_to_json<unknown[]>(workbook.Sheets[sheet], {
          header: 1,
          blankrows: false,
          raw: false,
        })
      : [];
    const header = rows.shift()?.map((cell) => folderKey(String(cell ?? ""))) ?? [];
    const folderIndex = header.findIndex((cell) =>
      /^(文件夹名|文件夹名称|任务组名称|folder|folder_name)$/i.test(cell),
    );
    const promptIndex = header.findIndex((cell) => /^(提示词|prompt)$/i.test(cell));
    if (folderIndex < 0 || promptIndex < 0)
      throw new Error("表格须包含“文件夹名”和“提示词”两列表头，请下载任务组模板");
    values = rows
      .map((row) => ({
        folder: folderKey(String(row[folderIndex] ?? "")),
        prompt: String(row[promptIndex] ?? "").trim(),
      }))
      .filter((row) => row.folder || row.prompt);
  } else throw new Error("仅支持 TXT、CSV、XLSX 或 XLS 文件");
  if (!values.length) throw new Error("文件里没有提示词");
  if (values.length > MAX_GROUPS) throw new Error(`每批最多导入 ${MAX_GROUPS} 条提示词`);
  return values.map((row) => ({
    ...row,
    id: crypto.randomUUID(),
    targetId: "",
    assignment: "auto",
  }));
};

export const createGroupPromptTemplate = async (groups: BatchGroup[], format: "txt" | "csv" | "xlsx") => {
  const rows = [
    ["文件夹名", "提示词"],
    ...(groups.length
      ? groups.map((group) => [group.name, group.prompt])
      : [
          ["商品A", "白底电商主图，结合组内全部参考图，保留商品形状和材质"],
          ["商品B", "生活方式场景，结合组内全部参考图，柔和自然光"],
        ]),
  ];
  const filename = `magic-文件夹任务组提示词模板.${format}`;
  if (format === "txt") return {
    filename,
    blob: new Blob(["\ufeff" + rows.map(([folder, prompt]) => `${folder}\t${JSON.stringify(prompt)}`).join("\r\n")], { type: "text/plain;charset=utf-8" }),
  };
  if (format === "csv")
    return {
      filename,
      blob: new Blob(
        [
          "\ufeff" +
            rows
              .map((row) => row.map((cell) => `"${cell.replaceAll('"', '""')}"`).join(","))
              .join("\r\n"),
        ],
        { type: "text/csv;charset=utf-8" },
      ),
    };
  const { utils, write } = await import("xlsx");
  const sheet = utils.aoa_to_sheet(rows);
  sheet["!cols"] = [{ wch: 24 }, { wch: 72 }];
  const workbook = utils.book_new();
  utils.book_append_sheet(workbook, sheet, "任务组提示词");
  return {
    filename,
    blob: new Blob([write(workbook, { bookType: "xlsx", type: "array" })], {
      type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }),
  };
};
