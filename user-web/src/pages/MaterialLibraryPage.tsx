import { LoadingState } from "@/components/ui/LoadingState";
import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, Folder, FolderOpen, HardDrive, ImagePlus, Pencil, Plus, Search, UploadCloud, X, Zap } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { materialService, type MaterialUploadMode } from "@/services/materials";
import type { MaterialAsset, MaterialFolder } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { getAssetPreviewSource } from "@/utils/assetPreview";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";

const MATERIAL_PAGE_SIZE = 48;
const MAX_UPLOAD_SIZE = 10 * 1024 * 1024;

const formatFileSize = (bytes: number) => {
  if (!Number.isFinite(bytes) || bytes <= 0) return "—";
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

/** Asset workspace: directories, gallery and optional inspector are separate
 * regions, preventing folders and files from competing in the same grid. */
export function MaterialLibraryPage() {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderNameInputRef = useRef<HTMLInputElement>(null);
  const [folderStack, setFolderStack] = useState<MaterialFolder[]>([]);
  const [folders, setFolders] = useState<MaterialFolder[]>([]);
  const [materials, setMaterials] = useState<MaterialAsset[]>([]);
  const [selectedMaterialId, setSelectedMaterialId] = useState<number | null>(null);
  const [isRenamingMaterial, setIsRenamingMaterial] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [isSavingMaterial, setIsSavingMaterial] = useState(false);
  const [isFolderDialogOpen, setIsFolderDialogOpen] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [folderNameError, setFolderNameError] = useState("");
  const [keyword, setKeyword] = useState("");
  const [deferredKeyword, setDeferredKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isCreatingFolder, setIsCreatingFolder] = useState(false);
  const [error, setError] = useState("");
  const [uploadMode, setUploadMode] = useState<MaterialUploadMode>("local");
  const [cdnCreditCost, setCdnCreditCost] = useState(1);
  const currentFolder = folderStack.at(-1) ?? null;
  const currentFolderId = currentFolder?.id ?? null;
  const pageCount = Math.max(1, Math.ceil(total / MATERIAL_PAGE_SIZE));
  const selectedMaterial = useMemo(
    () => materials.find((material) => material.id === selectedMaterialId) ?? null,
    [materials, selectedMaterialId],
  );

  useEffect(() => {
    const timerId = window.setTimeout(() => setDeferredKeyword(keyword.trim()), 250);
    return () => window.clearTimeout(timerId);
  }, [keyword]);

  useEffect(() => {
    setPage(1);
  }, [currentFolderId, deferredKeyword]);

  useEffect(() => {
    let ignore = false;
    void materialService.getUploadOptions()
      .then((options) => {
        if (ignore) return;
        setUploadMode(options.default_mode);
        setCdnCreditCost(Math.max(0, options.cdn_credit_cost));
      })
      .catch(() => {
        // Keep the safe local default if an older server does not expose options yet.
      });
    return () => {
      ignore = true;
    };
  }, []);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const [nextFolders, nextMaterials] = await Promise.all([
        materialService.getFolders(currentFolderId),
        materialService.getMaterials(currentFolderId, deferredKeyword, page, MATERIAL_PAGE_SIZE),
      ]);
      setFolders(nextFolders);
      setMaterials(nextMaterials.items);
      setTotal(nextMaterials.total);
      setSelectedMaterialId((current) =>
        nextMaterials.items.some((material) => material.id === current) ? current : null,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材库加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [currentFolderId, deferredKeyword, page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!isFolderDialogOpen) return;
    const focusTimer = window.setTimeout(() => folderNameInputRef.current?.focus(), 0);
    return () => window.clearTimeout(focusTimer);
  }, [isFolderDialogOpen]);

  useEffect(() => {
    if (!selectedMaterial) {
      setIsRenamingMaterial(false);
      setNameDraft("");
      return;
    }
    if (!isRenamingMaterial) setNameDraft(selectedMaterial.name);
  }, [isRenamingMaterial, selectedMaterial]);

  const navigateToFolder = (folder: MaterialFolder | null, stack?: MaterialFolder[]) => {
    setFolderStack(stack ?? (folder ? [...folderStack, folder] : []));
    setKeyword("");
    setDeferredKeyword("");
    setSelectedMaterialId(null);
    setPage(1);
  };

  const openFolderDialog = () => {
    setFolderName("");
    setFolderNameError("");
    setIsFolderDialogOpen(true);
  };

  const closeFolderDialog = () => {
    if (isCreatingFolder) return;
    setIsFolderDialogOpen(false);
    setFolderName("");
    setFolderNameError("");
  };

  const createFolder = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextName = folderName.trim();
    if (!nextName) {
      setFolderNameError("请输入目录名称");
      return;
    }
    setIsCreatingFolder(true);
    setFolderNameError("");
    setError("");
    try {
      const folder = await materialService.createFolder(nextName, currentFolderId);
      setFolders((items) => [...items, folder]);
      setIsFolderDialogOpen(false);
      setFolderName("");
    } catch (err) {
      setFolderNameError(err instanceof Error ? err.message : "目录创建失败");
    } finally {
      setIsCreatingFolder(false);
    }
  };

  const upload = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    const oversizedFile = files.find((file) => file.size > MAX_UPLOAD_SIZE);
    if (oversizedFile) {
      setError(`图片“${oversizedFile.name}”超过 10MB，请压缩后再上传`);
      return;
    }
    setIsUploading(true);
    setError("");
    try {
      const uploaded = await materialService.uploadMaterials(files, currentFolderId, uploadMode);
      setPage(1);
      setMaterials((items) => [...uploaded, ...items].slice(0, MATERIAL_PAGE_SIZE));
      setTotal((current) => current + uploaded.length);
      if (uploadMode === "cdn") notifyCreditBalanceChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材上传失败");
    } finally {
      setIsUploading(false);
    }
  };

  const saveMaterialName = async () => {
    if (!selectedMaterial || isSavingMaterial) return;
    const nextName = nameDraft.trim();
    if (!nextName || nextName === selectedMaterial.name) {
      setIsRenamingMaterial(false);
      setNameDraft(selectedMaterial.name);
      return;
    }
    setIsSavingMaterial(true);
    setError("");
    try {
      const saved = await materialService.updateMaterial(selectedMaterial.id, {
        name: nextName,
        folder_id: selectedMaterial.folder_id ?? null,
      });
      setMaterials((items) => items.map((item) => (item.id === saved.id ? saved : item)));
      setIsRenamingMaterial(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材名称保存失败");
    } finally {
      setIsSavingMaterial(false);
    }
  };

  const selectMaterial = (material: MaterialAsset) => {
    setSelectedMaterialId(material.id);
    setIsRenamingMaterial(false);
  };

  return (
    <main className="page-surface material-library-page material-workspace">
      <header className="page-header material-workspace__header">
        <div>
          <p className="material-workspace__eyebrow">团队资产</p>
          <h1>素材库</h1>
          <p>在同一个工作区管理目录、素材和创作参考图。</p>
        </div>
        <div className="material-library-actions">
          <Button variant="secondary" type="button" onClick={openFolderDialog}><Plus size={16} />新建目录</Button>
          <div className="material-upload-settings" aria-label="素材上传方式">
            <span className="material-upload-settings__label">上传方式</span>
            <div className="material-upload-settings__options" role="radiogroup" aria-label="选择素材上传方式">
              <label className={uploadMode === "local" ? "material-upload-option is-selected" : "material-upload-option"}>
                <input
                  type="radio"
                  name="material-upload-mode"
                  value="local"
                  checked={uploadMode === "local"}
                  disabled={isUploading}
                  onChange={() => setUploadMode("local")}
                />
                <HardDrive size={14} />
                <span>本地上传</span>
                <small>免费</small>
              </label>
              <label className={uploadMode === "cdn" ? "material-upload-option is-selected material-upload-option--cdn" : "material-upload-option material-upload-option--cdn"}>
                <input
                  type="radio"
                  name="material-upload-mode"
                  value="cdn"
                  checked={uploadMode === "cdn"}
                  disabled={isUploading}
                  onChange={() => setUploadMode("cdn")}
                />
                <Zap size={14} />
                <span>CDN 加速</span>
                <small>每张 {cdnCreditCost} 积分</small>
              </label>
            </div>
            <p className="material-upload-settings__hint">
              {uploadMode === "local"
                ? "默认使用本地存储，不扣积分。"
                : `CDN 加速上传按成功图片计费，每张 ${cdnCreditCost} 积分。`}
            </p>
          </div>
          <Button type="button" isLoading={isUploading} onClick={() => fileInputRef.current?.click()}>
            <UploadCloud size={16} />{uploadMode === "cdn" ? "上传素材（CDN）" : "上传素材"}
          </Button>
          <input ref={fileInputRef} className="visually-hidden" type="file" multiple accept="image/*" onChange={upload} />
        </div>
      </header>

      <section className={`material-workspace__body ${selectedMaterial ? "has-inspector" : ""}`}>
        <aside className="material-workspace__folders" aria-label="素材目录">
          <div className="material-workspace__folders-head">
            <strong>目录</strong>
            {currentFolder ? <button type="button" onClick={() => navigateToFolder(null)} title="回到全部素材">全部</button> : null}
          </div>
          <button
            type="button"
            className={!currentFolder ? "is-active" : ""}
            onClick={() => navigateToFolder(null)}
          >
            <FolderOpen size={17} /> 全部素材
          </button>
          {folderStack.map((folder, index) => (
            <button
              type="button"
              key={folder.id}
              className={index === folderStack.length - 1 ? "is-active" : ""}
              onClick={() => navigateToFolder(folder, folderStack.slice(0, index + 1))}
            >
              <ChevronLeft size={14} /> {folder.name}
            </button>
          ))}
          {folders.length ? <span className="material-workspace__folder-caption">当前目录</span> : null}
          {folders.map((folder) => (
            <button type="button" key={folder.id} onClick={() => navigateToFolder(folder)}>
              <Folder size={17} /> {folder.name}
            </button>
          ))}
        </aside>

        <section className="material-workspace__content" aria-label="素材列表">
          <div className="material-workspace__content-head">
            <div>
              <p>{folderStack.length ? folderStack.map((folder) => folder.name).join(" / ") : "全部素材"}</p>
              <strong>{deferredKeyword ? `“${deferredKeyword}” 的搜索结果` : "素材"}</strong>
            </div>
            <label className="material-workspace__search">
              <Search size={16} />
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索当前目录" />
            </label>
          </div>

          {error ? <div className="list-state list-state--error">{error}</div> : null}
          {isLoading ? (
            <LoadingState label="正在加载素材库…" variant="cards" />
          ) : (
            <>
              {folders.length && !deferredKeyword ? (
                <div className="material-workspace__subfolders" aria-label="子目录">
                  {folders.map((folder) => (
                    <button type="button" key={folder.id} onClick={() => navigateToFolder(folder)}>
                      <Folder size={18} />
                      <span>{folder.name}</span>
                    </button>
                  ))}
                </div>
              ) : null}
              <div className="material-workspace__grid">
                {materials.map((material) => (
                  <button
                    type="button"
                    key={material.id}
                    className={material.id === selectedMaterialId ? "material-asset-card is-selected" : "material-asset-card"}
                    onClick={() => selectMaterial(material)}
                  >
                    <img src={resolveAssetUrl(getAssetPreviewSource(material.asset))} alt={material.name} loading="lazy" />
                    <span>{material.name}</span>
                    <small>{material.asset.width && material.asset.height ? `${material.asset.width} × ${material.asset.height}` : material.asset.mime_type}</small>
                  </button>
                ))}
                {!folders.length && !materials.length ? (
                  <div className="empty-state material-workspace__empty"><ImagePlus size={34} /><h3>{deferredKeyword ? "没有匹配的素材" : "当前目录暂无素材"}</h3><p>{deferredKeyword ? "试试更短的关键词，或返回上级目录。" : "上传图片或新建目录开始整理素材。"}</p></div>
                ) : null}
              </div>
              {total > MATERIAL_PAGE_SIZE ? (
                <div className="material-workspace__pagination">
                  <span>第 {page} / {pageCount} 页 · 共 {total} 个素材</span>
                  <div>
                    <Button variant="ghost" type="button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button>
                    <Button variant="ghost" type="button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>下一页</Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </section>

        {selectedMaterial ? (
          <aside className="material-workspace__inspector" aria-label="素材详情">
            <img src={resolveAssetUrl(getAssetPreviewSource(selectedMaterial.asset))} alt={selectedMaterial.name} />
            <div className="material-workspace__inspector-head">
              <strong>素材详情</strong>
              <button type="button" onClick={() => setSelectedMaterialId(null)} aria-label="关闭素材详情"><X size={16} /></button>
            </div>
            {isRenamingMaterial ? (
              <div className="material-workspace__rename">
                <input
                  value={nameDraft}
                  autoFocus
                  disabled={isSavingMaterial}
                  onChange={(event) => setNameDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void saveMaterialName();
                    if (event.key === "Escape") setIsRenamingMaterial(false);
                  }}
                />
                <Button type="button" isLoading={isSavingMaterial} onClick={() => void saveMaterialName()}>保存名称</Button>
                <Button variant="ghost" type="button" disabled={isSavingMaterial} onClick={() => setIsRenamingMaterial(false)}>取消</Button>
              </div>
            ) : (
              <div className="material-workspace__inspector-name">
                <strong>{selectedMaterial.name}</strong>
                <button type="button" onClick={() => setIsRenamingMaterial(true)} aria-label="重命名素材"><Pencil size={15} /></button>
              </div>
            )}
            <dl>
              <div><dt>尺寸</dt><dd>{selectedMaterial.asset.width && selectedMaterial.asset.height ? `${selectedMaterial.asset.width} × ${selectedMaterial.asset.height}` : "未知"}</dd></div>
              <div><dt>格式</dt><dd>{selectedMaterial.asset.mime_type || "未知"}</dd></div>
              <div><dt>大小</dt><dd>{formatFileSize(selectedMaterial.asset.size_bytes)}</dd></div>
            </dl>
          </aside>
        ) : null}
      </section>

      {isFolderDialogOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeFolderDialog}>
          <form className="folder-dialog" role="dialog" aria-modal="true" aria-labelledby="folder-dialog-title" onSubmit={createFolder} onClick={(event) => event.stopPropagation()}>
            <header>
              <div>
                <h2 id="folder-dialog-title">新建目录</h2>
                <p>{currentFolder ? `在“${currentFolder.name}”中创建子目录` : "在素材库根目录创建目录"}</p>
              </div>
              <button type="button" onClick={closeFolderDialog} aria-label="关闭新建目录弹窗" disabled={isCreatingFolder}><X size={18} /></button>
            </header>
            <label className="folder-dialog__field">
              <span>目录名称</span>
              <input
                ref={folderNameInputRef}
                value={folderName}
                maxLength={160}
                onChange={(event) => {
                  setFolderName(event.target.value);
                  if (folderNameError) setFolderNameError("");
                }}
                placeholder="例如：产品图、灵感参考"
                aria-invalid={Boolean(folderNameError)}
              />
            </label>
            {folderNameError ? <p className="folder-dialog__error">{folderNameError}</p> : null}
            <div className="dialog-actions">
              <Button variant="ghost" type="button" onClick={closeFolderDialog} disabled={isCreatingFolder}>取消</Button>
              <Button type="submit" isLoading={isCreatingFolder}>创建目录</Button>
            </div>
          </form>
        </div>
      ) : null}
    </main>
  );
}
