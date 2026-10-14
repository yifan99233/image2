import { useEffect, useRef, useState, type ChangeEvent } from "react";
import { Download, FolderPlus, UploadCloud, X } from "lucide-react";
import { Button } from "../ui/Button";
import { downloadBlob } from "../../utils/download";
import {
  createGroupPromptTemplate,
  applyCommonGroupPrompt,
  groupImageFiles,
  groupPrompt,
  readGroupPromptFile,
  readGroupZip,
  validateGroupFiles,
  MAX_GROUPS,
  type BatchGroup,
  type GroupPromptRow,
  type CommonGroupPromptMode,
} from "../../utils/batchGroups";

const GroupImage = ({ file }: { file: File }) => {
  const [url, setUrl] = useState("");
  useEffect(() => {
    const preview = URL.createObjectURL(file);
    setUrl(preview);
    return () => URL.revokeObjectURL(preview);
  }, [file]);
  return <img src={url || undefined} alt={file.name} loading="lazy" />;
};

type Props = {
  groups: BatchGroup[];
  rows: GroupPromptRow[];
  maxInputs: number;
  maxOutputs: number;
  disabled: boolean;
  issues: string[];
  onGroupsChange: (groups: BatchGroup[]) => void;
  onRowsChange: (rows: GroupPromptRow[]) => void;
  onBusyChange: (busy: boolean) => void;
  onError: (message: string) => void;
};

export const BatchGroupEditor = ({
  groups,
  rows,
  maxInputs,
  maxOutputs,
  disabled,
  issues,
  onGroupsChange,
  onRowsChange,
  onBusyChange,
  onError,
}: Props) => {
  const directory = useRef<HTMLInputElement>(null);
  const zip = useRef<HTMLInputElement>(null);
  const singleGroup = useRef<HTMLInputElement>(null);
  const prompts = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [commonPrompt, setCommonPrompt] = useState("");
  const [commonPromptMode, setCommonPromptMode] = useState<CommonGroupPromptMode>("supplement");
  const [commonOutputCount, setCommonOutputCount] = useState("1");
  const [groupPage, setGroupPage] = useState(0);
  const [rowPage, setRowPage] = useState(0);
  const [groupSearch, setGroupSearch] = useState("");
  const [onlyIncomplete, setOnlyIncomplete] = useState(false);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  useEffect(() => {
    directory.current?.setAttribute("webkitdirectory", "");
  }, []);
  const run = async (action: () => Promise<void>) => {
    if (disabled || busy) return;
    setBusy(true);
    onBusyChange(true);
    setMessage("");
    try {
      await action();
    } catch (error) {
      onError(error instanceof Error ? error.message : "文件导入失败");
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  };
  const addFiles = (event: ChangeEvent<HTMLInputElement>, mode: "directory" | "zip" | "single") => {
    const files = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = "";
    if (!files.length) return;
    void run(async () => {
      const imported =
        mode === "zip"
          ? await readGroupZip(files[0])
          : groupImageFiles(
              files.map((file) => ({
                file,
                path: mode === "directory" ? file.webkitRelativePath || file.name : file.name,
              })),
              `任务组${groups.length + 1}`,
            );
      const next = [...groups, ...imported.groups];
      if (next.length > MAX_GROUPS) throw new Error(`每批最多 ${MAX_GROUPS} 个任务组`);
      validateGroupFiles(next.flatMap((group) => group.images));
      onGroupsChange(next);
      setMessage(
        `已添加 ${imported.groups.length} 个任务组、${imported.groups.reduce((sum, group) => sum + group.images.length, 0)} 张参考图${imported.skipped ? `；跳过 ${imported.skipped} 个非图片文件` : ""}`,
      );
    });
  };
  const importPrompts = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    void run(async () => {
      const imported = await readGroupPromptFile(file);
      if (rows.length + imported.length > MAX_GROUPS)
        throw new Error(`最多保留 ${MAX_GROUPS} 条导入提示词，请先移除旧行`);
      onRowsChange([...rows, ...imported]);
      const named = imported.filter((row) => row.folder).length;
      setMessage(
        `已导入 ${imported.length} 条提示词${named ? `；${named} 条包含文件夹名，按唯一同名任务组自动匹配` : ""}${named < imported.length ? `；${imported.length - named} 条没有文件夹名，请手动选择任务组` : ""}`,
      );
    });
  };
  const template = (format: "txt" | "csv" | "xlsx") =>
    void run(async () => {
      const result = await createGroupPromptTemplate(
        groups.map((group) => ({ ...group, prompt: groupPrompt(group, rows) })),
        format,
      );
      downloadBlob(result.blob, result.filename);
      setMessage("模板已下载，填写提示词后导入即可按文件夹名匹配");
    });
  const updateGroup = (id: string, patch: Partial<BatchGroup>) =>
    onGroupsChange(groups.map((group) => (group.id === id ? { ...group, ...patch } : group)));
  const updatePrompt = (group: BatchGroup, value: string) => {
    const assigned = rows.filter((row) => row.targetId === group.id);
    if (assigned.length === 1)
      onRowsChange(
        rows.map((row) => (row.id === assigned[0].id ? { ...row, prompt: value } : row)),
      );
    else updateGroup(group.id, { prompt: value });
  };
  const outputCount = groups.reduce((sum, group) => sum + group.outputs, 0);
  const uniformOutputs = Number(commonOutputCount);
  const validUniformOutputs = commonOutputCount.trim() !== "" && Number.isInteger(uniformOutputs) && uniformOutputs >= 1 && uniformOutputs <= 9;
  const uniformTotal = groups.length * uniformOutputs;
  const canApplyUniformOutputs = validUniformOutputs && uniformTotal <= maxOutputs;
  const nameCounts = new Map<string, number>();
  for (const group of groups) {
    const key = group.name.trim().normalize("NFC");
    nameCounts.set(key, (nameCounts.get(key) ?? 0) + 1);
  }
  const hasDuplicateNames = [...nameCounts.values()].some((count) => count > 1);
  const pageSize = 20;
  const filteredGroups = groups.filter((group) => {
    const query = groupSearch.trim().toLocaleLowerCase();
    const matches = !query || `${group.name} ${group.path}`.toLocaleLowerCase().includes(query);
    const incomplete =
      !groupPrompt(group, rows).trim() ||
      !group.images.length ||
      group.images.length > maxInputs ||
      rows.filter((row) => row.targetId === group.id).length > 1 ||
      !Number.isInteger(group.outputs) ||
      group.outputs < 1 ||
      group.outputs > 9;
    return matches && (!onlyIncomplete || incomplete);
  });
  const groupPages = Math.max(1, Math.ceil(filteredGroups.length / pageSize));
  const activeGroupPage = Math.min(groupPage, groupPages - 1);
  const rowPages = Math.max(1, Math.ceil(rows.length / pageSize));
  const activeRowPage = Math.min(rowPage, rowPages - 1);
  return (
    <fieldset className="batch-groups" disabled={disabled || busy}>
      <legend>文件夹任务组</legend>
      <p className="field-hint">
        同一文件夹的多张图片共同作为参考图。导入带文件夹名的 TXT、CSV 或 Excel，即可按名称自动匹配。
      </p>
      <div className="batch-groups__actions">
        <Button type="button" variant="secondary" onClick={() => directory.current?.click()}>
          <FolderPlus size={16} />
          添加文件夹
        </Button>
        <Button type="button" variant="secondary" onClick={() => zip.current?.click()}>
          <UploadCloud size={16} />
          导入 ZIP
        </Button>
        <Button type="button" variant="ghost" onClick={() => singleGroup.current?.click()}>
          散图组成一组
        </Button>
        <input
          ref={directory}
          type="file"
          multiple
          hidden
          onChange={(event) => addFiles(event, "directory")}
          aria-label="选择任务组文件夹"
        />
        <input
          ref={zip}
          type="file"
          accept=".zip,application/zip,application/x-zip-compressed"
          hidden
          onChange={(event) => addFiles(event, "zip")}
          aria-label="选择任务组 ZIP"
        />
        <input
          ref={singleGroup}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          onChange={(event) => addFiles(event, "single")}
          aria-label="选择散图组成任务组"
        />
      </div>
      <div className="batch-groups__actions batch-groups__templates">
        <Button type="button" variant="secondary" onClick={() => prompts.current?.click()}>
          导入任务组提示词
        </Button>
        <Button type="button" variant="ghost" onClick={() => template("xlsx")}>
          <Download size={15} />
          XLSX 模板
        </Button>
        <Button type="button" variant="ghost" onClick={() => template("csv")}>
          CSV 模板
        </Button>
        <Button type="button" variant="ghost" onClick={() => template("txt")}>
          TXT 模板
        </Button>
        <input
          ref={prompts}
          type="file"
          accept=".txt,.csv,.xlsx,.xls"
          hidden
          onChange={importPrompts}
          aria-label="选择任务组提示词文件"
        />
      </div>
      <small className="field-hint">
        模板会填入当前任务组名称。名称完全一致且双方都唯一才会自动匹配；多层同名文件夹请根据路径手动选择。每组最多{" "}
        {maxInputs} 张图，单图 10MB，每批最多 {MAX_GROUPS} 组、生成 {maxOutputs} 张。
        TXT 每行可用“文件夹名 + Tab + 提示词”；仅有提示词时需手动选择任务组。
      </small>
      {busy || message ? (
        <p className="batch-groups__message" role="status">
          {busy ? "正在读取文件，请稍候…" : message}
        </p>
      ) : null}
      {groups.length ? (
        <section className="batch-groups__output-settings" aria-label="统一设置生成张数">
          <div className="batch-groups__output-actions">
            <label>
              统一每组生成张数
              <input type="number" min={1} max={9} step={1} aria-label="统一每组生成张数" value={commonOutputCount} onChange={(event) => setCommonOutputCount(event.target.value)} />
            </label>
            <Button type="button" variant="secondary" disabled={!canApplyUniformOutputs} onClick={() => {
              if (!canApplyUniformOutputs) return;
              onGroupsChange(groups.map((group) => ({ ...group, outputs: uniformOutputs })));
              setMessage(`已将全部 ${groups.length} 个任务组设为每组生成 ${uniformOutputs} 张，共 ${uniformTotal} 张结果图`);
            }}>
              应用到全部 {groups.length} 组
            </Button>
          </div>
          <p className={validUniformOutputs && uniformTotal <= maxOutputs ? "field-hint" : "field-hint field-hint--error"}>
            {validUniformOutputs ? `${groups.length} 组 × ${uniformOutputs} 张 = ${uniformTotal} 张结果图${uniformTotal > maxOutputs ? `，超过单批 ${maxOutputs} 张上限，请减少每组张数` : ""}` : "请输入 1–9 的整数"}
          </p>
          <small className="field-hint">应用到所有页面和筛选隐藏的任务组；应用后仍可逐组修改。</small>
        </section>
      ) : null}
      {hasDuplicateNames ? (
        <p className="field-hint field-hint--error">
          存在同名任务组，不会自动匹配这些名称。可重命名后下载模板，或按路径手动匹配。
        </p>
      ) : null}
      {rows.length ? (
        <section className="batch-groups__mapping" aria-label="提示词匹配关系">
          <strong>
            提示词匹配（{rows.filter((row) => row.targetId).length}/{rows.length}）
          </strong>
          {rows
            .slice(activeRowPage * pageSize, (activeRowPage + 1) * pageSize)
            .map((row, pageIndex) => {
              const index = activeRowPage * pageSize + pageIndex;
              return (
                <div className="batch-groups__mapping-row" key={row.id}>
                  <div>
                    <strong>{row.folder || `TXT 第 ${index + 1} 条`}</strong>
                    <p title={row.prompt}>{row.prompt || "（缺少提示词，请在任务组中补充）"}</p>
                  </div>
                  <label>
                    <span>对应任务组</span>
                    <select
                      aria-label={`提示词 ${index + 1} 对应任务组`}
                      value={row.targetId}
                      onChange={(event) =>
                        onRowsChange(
                          rows.map((other) =>
                            other.id === row.id
                              ? { ...other, targetId: event.target.value, assignment: "manual" }
                              : other,
                          ),
                        )
                      }
                    >
                      <option value="">未匹配 · 请选择</option>
                      {groups.map((group, groupIndex) => (
                        <option key={group.id} value={group.id}>
                          {groupIndex + 1}. {group.name}（{group.path}）
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label={`移除导入提示词 ${index + 1}`}
                    onClick={() => onRowsChange(rows.filter((other) => other.id !== row.id))}
                  >
                    <X size={16} />
                  </Button>
                </div>
              );
            })}
          {rowPages > 1 ? (
            <div className="batch-groups__pagination">
              <Button
                type="button"
                variant="ghost"
                disabled={activeRowPage === 0}
                onClick={() => setRowPage(activeRowPage - 1)}
              >
                上一页提示词
              </Button>
              <span>
                第 {activeRowPage + 1}/{rowPages} 页 · {rows.length} 条
              </span>
              <Button
                type="button"
                variant="ghost"
                disabled={activeRowPage + 1 >= rowPages}
                onClick={() => setRowPage(activeRowPage + 1)}
              >
                下一页提示词
              </Button>
            </div>
          ) : null}
        </section>
      ) : null}
      {groups.length ? (
        <div className="batch-groups__common">
          <label htmlFor="group-common-prompt">共同提示词</label>
          <div className="segmented-row segmented-row--compact prompt-mode-toggle" role="radiogroup" aria-label="共同提示词应用方式">
            {([['overwrite', '覆盖'], ['supplement', '补充'], ['append', '追加']] as const).map(([mode, label]) => (
              <button key={mode} type="button" role="radio" className={commonPromptMode === mode ? "is-active" : ""} aria-checked={commonPromptMode === mode} onClick={() => setCommonPromptMode(mode)}>{label}</button>
            ))}
          </div>
          <p className="field-hint">
            {commonPromptMode === "overwrite" ? "替换所有任务组的原提示词。" : commonPromptMode === "supplement" ? "只填入缺少提示词的任务组，保留已有提示词。" : "在每组原提示词末尾另起一行追加；空缺的组直接填入。"}
            应用于全部任务组，包含其他页面和筛选隐藏的组。
          </p>
          <textarea
            id="group-common-prompt"
            value={commonPrompt}
            onChange={(event) => setCommonPrompt(event.target.value)}
            placeholder={commonPromptMode === "overwrite" ? "输入用于替换全部任务组的新提示词" : commonPromptMode === "append" ? "输入要追加到每组末尾的提示词" : "输入用于补充空缺任务组的提示词"}
            rows={2}
          />
          <Button
            type="button"
            variant="secondary"
            disabled={!commonPrompt.trim()}
            onClick={() => {
              const result = applyCommonGroupPrompt(groups, rows, commonPrompt, commonPromptMode);
              onGroupsChange(result.groups);
              onRowsChange(result.rows);
              setMessage(commonPromptMode === "overwrite" ? `已覆盖全部 ${result.affectedCount} 个任务组的提示词` : commonPromptMode === "append" ? `已为全部 ${result.affectedCount} 个任务组追加提示词` : `已为 ${result.affectedCount} 个缺少提示词的任务组填入共同提示词`);
            }}
          >
            {commonPromptMode === "overwrite" ? `覆盖全部 ${groups.length} 组提示词` : commonPromptMode === "append" ? `追加到全部 ${groups.length} 组末尾` : "填充缺少的提示词"}
          </Button>
        </div>
      ) : (
        <div className="batch-groups__empty">
          例如：商品A文件夹放正面和侧面图，商品B文件夹放商品和包装图，系统会建立两个任务组。
        </div>
      )}
      {groups.length > pageSize ? (
        <div className="batch-groups__filters">
          <label>
            查找任务组
            <input
              aria-label="查找任务组"
              value={groupSearch}
              placeholder="输入文件夹名称或路径"
              onChange={(event) => {
                setGroupSearch(event.target.value);
                setGroupPage(0);
              }}
            />
          </label>
          <label className="batch-groups__filter-toggle">
            <input
              type="checkbox"
              checked={onlyIncomplete}
              onChange={(event) => {
                setOnlyIncomplete(event.target.checked);
                setGroupPage(0);
              }}
            />
            只看待处理
          </label>
          <span>找到 {filteredGroups.length} 组</span>
        </div>
      ) : null}
      <div className="batch-groups__list">
        {filteredGroups
          .slice(activeGroupPage * pageSize, (activeGroupPage + 1) * pageSize)
          .map((group) => {
            const index = groups.indexOf(group);
            return (
              <article
                className="batch-group-card"
                key={group.id}
                aria-label={`任务组 ${index + 1}`}
              >
                <div className="batch-group-card__header">
                  <label>
                    任务组名称
                    <input
                      aria-label={`任务组 ${index + 1} 名称`}
                      value={group.name}
                      maxLength={255}
                      onChange={(event) => updateGroup(group.id, { name: event.target.value })}
                    />
                  </label>
                  <label>
                    生成张数
                    <input
                      aria-label={`任务组 ${index + 1} 生成张数`}
                      type="number"
                      min={1}
                      max={9}
                      value={group.outputs}
                      onChange={(event) =>
                        updateGroup(group.id, { outputs: Number(event.target.value) })
                      }
                    />
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label={`移除任务组 ${index + 1}`}
                    onClick={() => setPendingRemoval(group.id)}
                  >
                    移除组
                  </Button>
                </div>
                <small className="batch-group-card__path">
                  {group.path} · {group.images.length} 张参考图 · 生成 {group.outputs} 张
                </small>
                {pendingRemoval === group.id ? (
                  <div className="batch-group-card__confirm" role="alert">
                    移除后该组图片和已编辑提示词将清除。
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => setPendingRemoval(null)}
                    >
                      保留
                    </Button>
                    <Button
                      type="button"
                      onClick={() => {
                        onGroupsChange(groups.filter((other) => other.id !== group.id));
                        setPendingRemoval(null);
                      }}
                    >
                      确认移除
                    </Button>
                  </div>
                ) : null}
                <div className="batch-group-card__images">
                  {group.images.map((image, imageIndex) => (
                    <figure key={`${image.path}-${imageIndex}`}>
                      <GroupImage file={image.file} />
                      <figcaption title={image.path}>{image.file.name}</figcaption>
                      <button
                        type="button"
                        className="batch-group-card__remove-image"
                        aria-label={`从任务组 ${index + 1} 移除 ${image.file.name}`}
                        onClick={() =>
                          updateGroup(group.id, {
                            images: group.images.filter(
                              (_, currentIndex) => currentIndex !== imageIndex,
                            ),
                          })
                        }
                      >
                        <X size={13} />
                        移除
                      </button>
                      {imageIndex > 0 ? (
                        <button
                          type="button"
                          className="batch-group-card__remove-image"
                          onClick={() =>
                            updateGroup(group.id, {
                              images: [
                                image,
                                ...group.images.filter(
                                  (_, currentIndex) => currentIndex !== imageIndex,
                                ),
                              ],
                            })
                          }
                        >
                          设为首图
                        </button>
                      ) : (
                        <small>首张参考图</small>
                      )}
                    </figure>
                  ))}
                </div>
                <label>
                  本组提示词
                  <textarea
                    aria-label={`任务组 ${index + 1} 提示词`}
                    value={groupPrompt(group, rows)}
                    onChange={(event) => updatePrompt(group, event.target.value)}
                    rows={3}
                    placeholder="描述本组的生成要求，模型会同时参考上方所有图片"
                  />
                </label>
                {rows.filter((row) => row.targetId === group.id).length > 1 ? (
                  <small className="field-hint field-hint--error">
                    提示词冲突：请在匹配关系中移除或重新分配多余行。
                  </small>
                ) : null}
              </article>
            );
          })}
        {groups.length && !filteredGroups.length ? (
          <p className="field-hint">没有符合条件的任务组，请调整查找条件。</p>
        ) : null}
      </div>
      {groupPages > 1 ? (
        <div className="batch-groups__pagination">
          <Button
            type="button"
            variant="secondary"
            disabled={activeGroupPage === 0}
            onClick={() => setGroupPage(activeGroupPage - 1)}
          >
            上一页任务组
          </Button>
          <span>
            第 {activeGroupPage + 1}/{groupPages} 页 · 每页 {pageSize} 组
          </span>
          <Button
            type="button"
            variant="secondary"
            disabled={activeGroupPage + 1 >= groupPages}
            onClick={() => setGroupPage(activeGroupPage + 1)}
          >
            下一页任务组
          </Button>
        </div>
      ) : null}
      <div className="batch-groups__summary" aria-live="polite">
        <strong>
          提交预览：{groups.length} 组 ·{" "}
          {groups.reduce((sum, group) => sum + group.images.length, 0)} 张参考图 · 生成{" "}
          {outputCount} 张
        </strong>
        <small>
          按生成 {outputCount} 张结果图计费；参考图数量不会增加任务数。结果按任务组名称保存和导出。
        </small>
        {groups.length || rows.length ? (
          <ul>
            {issues.slice(0, 6).map((issue, index) => (
              <li key={index}>{issue}</li>
            ))}
            {issues.length > 6 ? <li>另有 {issues.length - 6} 项待处理</li> : null}
          </ul>
        ) : null}
      </div>
    </fieldset>
  );
};
