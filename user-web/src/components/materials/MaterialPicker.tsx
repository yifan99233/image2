import { LoadingState } from "@/components/ui/LoadingState";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronRight, Folder, ImagePlus, Search, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { materialService } from "@/services/materials";
import type { ImageAsset, MaterialAsset, MaterialFolder } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { getAssetPreviewSource } from "@/utils/assetPreview";

type MaterialPickerProps = {
  open: boolean;
  onClose: () => void;
  onSelect: (assets: ImageAsset[]) => void;
};

const MATERIAL_PICKER_PAGE_SIZE = 48;
const MAX_SELECTED_MATERIALS = 200;

/**
 * Creation surfaces use a modal asset browser so selecting materials never
 * resizes or obscures the form and generated-result workspace beneath it.
 */
export function MaterialPicker({ open, onClose, onSelect }: MaterialPickerProps) {
  const [folderStack, setFolderStack] = useState<MaterialFolder[]>([]);
  const [folders, setFolders] = useState<MaterialFolder[]>([]);
  const [materials, setMaterials] = useState<MaterialAsset[]>([]);
  const [selectedMaterials, setSelectedMaterials] = useState<MaterialAsset[]>([]);
  const [keyword, setKeyword] = useState("");
  const [deferredKeyword, setDeferredKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const currentFolder = folderStack.at(-1) ?? null;
  const currentFolderId = currentFolder?.id ?? null;
  const pageCount = Math.max(1, Math.ceil(total / MATERIAL_PICKER_PAGE_SIZE));

  useEffect(() => {
    if (!open) return;
    const timerId = window.setTimeout(() => setDeferredKeyword(keyword.trim()), 250);
    return () => window.clearTimeout(timerId);
  }, [keyword, open]);

  useEffect(() => {
    if (!open) return;
    setPage(1);
  }, [currentFolderId, deferredKeyword, open]);

  useEffect(() => {
    if (!open) return;
    let ignore = false;
    setIsLoading(true);
    setError("");
    Promise.all([
      materialService.getFolders(currentFolderId),
      materialService.getMaterials(currentFolderId, deferredKeyword, page, MATERIAL_PICKER_PAGE_SIZE),
    ])
      .then(([nextFolders, nextMaterials]) => {
        if (ignore) return;
        setFolders(nextFolders);
        setMaterials(nextMaterials.items);
        setTotal(nextMaterials.total);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "素材库加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [currentFolderId, deferredKeyword, open, page]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    const focusTimer = window.setTimeout(() => {
      if (window.matchMedia?.("(hover: hover) and (pointer: fine)")?.matches) {
        searchInputRef.current?.focus();
      }
    }, 0);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.clearTimeout(focusTimer);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onClose, open]);

  const selectedIds = useMemo(() => new Set(selectedMaterials.map((material) => material.id)), [selectedMaterials]);
  const currentPageSelectedCount = useMemo(
    () => materials.filter((material) => selectedIds.has(material.id)).length,
    [materials, selectedIds],
  );
  const allCurrentPageSelected = materials.length > 0 && currentPageSelectedCount === materials.length;

  const openFolder = (folder: MaterialFolder) => {
    setFolderStack((stack) => [...stack, folder]);
    setKeyword("");
    setDeferredKeyword("");
    setPage(1);
  };

  const toggleMaterial = (material: MaterialAsset) => {
    setSelectedMaterials((current) => {
      if (current.some((item) => item.id === material.id)) {
        return current.filter((item) => item.id !== material.id);
      }
      if (current.length >= MAX_SELECTED_MATERIALS) return current;
      return [...current, material];
    });
  };

  const toggleCurrentPage = () => {
    setSelectedMaterials((current) => {
      const pageIds = new Set(materials.map((material) => material.id));
      if (allCurrentPageSelected) return current.filter((material) => !pageIds.has(material.id));

      const selected = [...current];
      const selectedIds = new Set(selected.map((material) => material.id));
      for (const material of materials) {
        if (selected.length >= MAX_SELECTED_MATERIALS) break;
        if (!selectedIds.has(material.id)) {
          selected.push(material);
          selectedIds.add(material.id);
        }
      }
      return selected;
    });
  };

  const confirmSelection = () => {
    if (!selectedMaterials.length) return;
    onSelect(selectedMaterials.map((material) => material.asset));
    setSelectedMaterials([]);
    onClose();
  };

  if (!open) return null;

  return createPortal(
    <div className="material-picker__backdrop" role="presentation" onClick={onClose}>
      <section
        className="material-picker material-picker--dialog"
        role="dialog"
        aria-modal="true"
        aria-label="选择素材"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="material-picker__header">
          <div className="material-picker__title">
            <h2>选择参考图</h2>
            <p>从素材库中选择图片，添加到本次创作</p>
          </div>
          <button type="button" aria-label="关闭素材选择" onClick={onClose}><X size={18} /></button>
        </header>

        <div className="material-picker__toolbar">
          <nav className="material-picker__path" aria-label="素材目录">
            <button type="button" className={!currentFolder ? "is-current" : ""} onClick={() => setFolderStack([])}>全部素材</button>
            {folderStack.map((folder, index) => (
              <span key={folder.id}>
                <ChevronRight size={14} aria-hidden="true" />
                <button
                  type="button"
                  className={index === folderStack.length - 1 ? "is-current" : ""}
                  onClick={() => setFolderStack((stack) => stack.slice(0, index + 1))}
                >
                  {folder.name}
                </button>
              </span>
            ))}
          </nav>
          <label>
            <Search size={16} />
            <input ref={searchInputRef} value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索当前目录" />
          </label>
        </div>

        <div className="material-picker__body">
          <div className="material-picker__content">
            {error ? <div className="list-state list-state--error">{error}</div> : null}
            {isLoading ? (
              <LoadingState label="正在加载素材…" variant="cards" />
            ) : (
              <>
                {folders.length && !deferredKeyword ? (
                  <section className="material-picker__folder-section" aria-label="子目录">
                    <div className="material-picker__section-heading">
                      <span>文件夹</span>
                      <small>{folders.length} 个</small>
                    </div>
                    <div className="material-picker__folder-row">
                    {folders.map((folder) => (
                      <button type="button" key={folder.id} onClick={() => openFolder(folder)}>
                        <Folder size={17} /> {folder.name}
                      </button>
                    ))}
                    </div>
                  </section>
                ) : null}
                {materials.length ? (
                  <div className="material-picker__section-heading material-picker__section-heading--assets">
                    <span>图片素材</span>
                    <small>{total} 张</small>
                    <Button
                      className="material-picker__select-page"
                      variant="ghost"
                      type="button"
                      onClick={toggleCurrentPage}
                      aria-pressed={allCurrentPageSelected}
                    >
                      {allCurrentPageSelected ? "取消全选本页" : "全选本页"}
                    </Button>
                  </div>
                ) : null}
                <div className="material-picker__grid">
                  {materials.map((material) => {
                    const selected = selectedIds.has(material.id);
                    return (
                      <button
                        className={selected ? "material-tile is-selected" : "material-tile"}
                        type="button"
                        key={material.id}
                        aria-pressed={selected}
                        onClick={() => toggleMaterial(material)}
                      >
                        <img src={resolveAssetUrl(getAssetPreviewSource(material.asset))} alt={material.name} loading="lazy" />
                        <span>{material.name}</span>
                        {selected ? <Check className="material-tile__check" size={16} aria-hidden /> : null}
                      </button>
                    );
                  })}
                  {!materials.length ? (
                    <div className="empty-state material-picker__empty"><ImagePlus size={32} /><p>{deferredKeyword ? "没有匹配的素材" : "当前目录暂无素材"}</p><small>{deferredKeyword ? "换个关键词试试" : "先上传图片到素材库，再从这里选择"}</small></div>
                  ) : null}
                </div>
                {total > MATERIAL_PICKER_PAGE_SIZE ? (
                  <div className="material-picker__pagination">
                    <span>第 {page} / {pageCount} 页 · 共 {total} 个素材</span>
                    <div>
                      <Button variant="ghost" type="button" disabled={page <= 1} onClick={() => setPage((current) => current - 1)}>上一页</Button>
                      <Button variant="ghost" type="button" disabled={page >= pageCount} onClick={() => setPage((current) => current + 1)}>下一页</Button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>

        <footer>
          <span className={selectedMaterials.length ? "is-selected" : ""}>已选择 {selectedMaterials.length} / {MAX_SELECTED_MATERIALS} 张图片</span>
          <Button variant="ghost" type="button" onClick={onClose}>取消</Button>
          <Button type="button" disabled={!selectedMaterials.length} onClick={confirmSelection}>添加到创作</Button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
