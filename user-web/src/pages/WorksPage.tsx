import { LoadingIndicator } from "@/components/ui/LoadingIndicator";
import { LoadingState } from "@/components/ui/LoadingState";
import { ExpandablePrompt } from "@/components/ui/ExpandablePrompt";
import { useEffect, useMemo, useState } from "react";
import { Download, Eye, FolderPlus, Search, Star, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { workService } from "@/services/works";
import { imageTaskService } from "@/services/imageTasks";
import { startBrowserDownload } from "@/utils/download";
import type { WorkItem } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { isVideoAsset } from "@/pages/shared/mediaConfig";
import { downloadImage } from "@/utils/download";

const categories = ["全部", "AI 创作", "营销素材", "图片处理", "创意玩法"];
const statusFilters = ["全部", "已收藏", "未收藏", "待审核", "已公开", "未通过", "未公开"];

const formatWorkTime = (value: string) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

export const WorksPage = () => {
  const [works, setWorks] = useState<WorkItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [category, setCategory] = useState("全部");
  const [status, setStatus] = useState("全部");
  const [keyword, setKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [previewWork, setPreviewWork] = useState<WorkItem | null>(null);
  const [updatingWorkIds, setUpdatingWorkIds] = useState<number[]>([]);

  useEffect(() => {
    let ignore = false;
    setIsLoading(true);
    workService
      .getWorks({ limit: 80 })
      .then((items) => {
        if (!ignore) {
          setWorks(items);
          setError(null);
        }
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "作品加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!previewWork) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewWork(null);
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [previewWork]);

  const filteredWorks = useMemo(
    () =>
      works.filter((work) => {
        const categoryMatched = category === "全部" || work.category === category;
        const statusMatched =
          status === "全部" ||
          (status === "已收藏" && work.is_collected) ||
          (status === "未收藏" && !work.is_collected) ||
          (status === "已公开" && work.is_recommended) ||
          (status === "待审核" && work.gallery_review_status === "pending") ||
          (status === "未通过" && work.gallery_review_status === "rejected") ||
          (status === "未公开" && !work.is_recommended);
        const keywordMatched = !keyword || work.prompt_snapshot.toLowerCase().includes(keyword.toLowerCase());
        return categoryMatched && statusMatched && keywordMatched;
      }),
    [category, keyword, status, works],
  );

  const toggleSelect = (workId: number) => {
    setSelectedIds((ids) => (ids.includes(workId) ? ids.filter((id) => id !== workId) : [...ids, workId]));
  };

  const updateWork = async (work: WorkItem, patch: Partial<Pick<WorkItem, "is_collected" | "is_recommended">>) => {
    setUpdatingWorkIds((ids) => [...ids, work.id]);
    try {
      const next = await workService.updateWork(work.id, patch);
      setWorks((items) => items.map((item) => (item.id === work.id ? next : item)));
    } catch (err) {
      setWorks((items) => items.map((item) => (item.id === work.id ? work : item)));
      setError(err instanceof Error ? err.message : "作品状态更新失败");
    } finally {
      setUpdatingWorkIds((ids) => ids.filter((id) => id !== work.id));
    }
  };

  const deleteWork = async (workId: number) => {
    await workService.deleteWork(workId);
    setWorks((items) => items.filter((item) => item.id !== workId));
    setSelectedIds((ids) => ids.filter((id) => id !== workId));
    setPendingDeleteId(null);
  };

  const downloadWork = async (work: WorkItem) => {
    try {
      if (work.output_assets.length > 1) {
        startBrowserDownload(await imageTaskService.createExportDownloadUrl([work.task_id]));
      } else {
        await downloadImage(work.cover_asset.url, `image2ai-work-${work.id}`, work.cover_asset.mime_type);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片下载失败，请稍后重试");
    }
  };

  return (
    <main className="page-surface works-page">
      <header className="page-header">
        <div>
          <h1>我的作品</h1>
          <p>管理生成结果和收藏内容。提交到创作广场的作品需经管理员审核，通过后才会公开展示。</p>
        </div>
        <div className="page-actions">
          <Button variant="secondary" type="button" disabled={!selectedIds.length}>
            <FolderPlus size={17} />
            批量收藏
          </Button>
          <Button type="button" disabled={!selectedIds.length}>
            <Download size={17} />
            批量下载
          </Button>
        </div>
      </header>

      <section className="work-layout">
        <aside className="filter-sidebar" aria-label="作品分类">
          {categories.map((item) => (
            <button className={item === category ? "is-active" : undefined} key={item} type="button" aria-pressed={item === category} onClick={() => setCategory(item)}>
              {item}
            </button>
          ))}
        </aside>

        <div className="work-content">
          <div className="filter-toolbar">
            <div className="search-field">
              <Search size={17} />
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索提示词" aria-label="搜索作品提示词" />
            </div>
            <div className="segmented-row segmented-row--compact">
              {statusFilters.map((item) => (
                <button className={item === status ? "is-active" : undefined} key={item} type="button" aria-pressed={item === status} onClick={() => setStatus(item)}>
                  {item}
                </button>
              ))}
            </div>
          </div>

          {isLoading ? <LoadingState label="正在加载作品…" variant="cards" /> : null}
          {error ? <div className="list-state list-state--error">{error}</div> : null}
          {!isLoading && !error && filteredWorks.length === 0 ? (
            <div className="empty-state">
              <Eye size={34} />
              <h3>没有匹配的作品</h3>
              <p>调整筛选条件，或回到工作台创建新的图片结果。</p>
            </div>
          ) : null}

          <div className="work-grid">
            {filteredWorks.map((work) => (
              <article className="work-card" key={work.id}>
                <label className="work-card__select">
                  <input checked={selectedIds.includes(work.id)} type="checkbox" onChange={() => toggleSelect(work.id)} />
                </label>
                <button className="work-card__preview" type="button" onClick={() => setPreviewWork(work)}>
                  {isVideoAsset(work.cover_asset) ? (
                    <video src={resolveAssetUrl(work.cover_asset.url)} muted playsInline preload="metadata" />
                  ) : (
                    <img src={resolveAssetUrl(work.cover_asset.url)} alt="作品缩略图" loading="lazy" />
                  )}
                </button>
                <div className="work-card__body">
                  <div className="work-card__meta">
                    <span>{work.category}</span>
                    <span>{work.is_recommended ? "已公开" : work.gallery_review_status === "pending" ? "待审核" : work.gallery_review_status === "rejected" ? "审核未通过／已下架" : "未公开"}</span>
                    {work.owner_name ? <span>{work.owner_name}</span> : null}
                    <time dateTime={work.created_at} title={work.created_at}>
                      {formatWorkTime(work.created_at)}
                    </time>
                  </div>
                  <ExpandablePrompt text={work.prompt_snapshot} />
                  <div className="work-card__actions">
                    <button type="button" aria-label="下载" onClick={() => void downloadWork(work)}>
                      <Download size={16} />
                    </button>
                    <button className={work.is_collected ? "is-active" : undefined} type="button" aria-label={work.is_collected ? "取消收藏" : "收藏"} aria-pressed={work.is_collected} title={work.is_collected ? "取消收藏" : "收藏到我的筛选"} disabled={updatingWorkIds.includes(work.id)} onClick={() => void updateWork(work, { is_collected: !work.is_collected })}>
                      {updatingWorkIds.includes(work.id) ? <LoadingIndicator className="spin-icon" size={16} /> : <FolderPlus size={16} />}
                    </button>
                    <button className={work.is_recommended || work.gallery_review_status === "pending" ? "is-active" : undefined} type="button" aria-label={work.is_recommended ? "取消公开展示" : work.gallery_review_status === "pending" ? "撤回审核" : "提交广场审核"} title={work.is_recommended ? "从公开展示移除" : work.gallery_review_status === "pending" ? "撤回审核申请" : "提交到创作广场，审核通过后公开"} disabled={updatingWorkIds.includes(work.id)} onClick={() => void updateWork(work, { is_recommended: !(work.is_recommended || work.gallery_review_status === "pending") })}>
                      <Star size={16} />
                    </button>
                    <button className="danger-icon" type="button" aria-label="删除" onClick={() => setPendingDeleteId(work.id)}>
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {pendingDeleteId ? (
        <div className="modal-backdrop" role="presentation">
          <div className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="work-delete-title">
            <div className="dialog-icon dialog-icon--danger">
              <Trash2 size={22} />
            </div>
            <h2 id="work-delete-title">删除这个作品</h2>
            <p>作品会从当前列表移除，批量选择状态也会同步更新。此操作不会删除你已下载的本地文件。</p>
            <div className="dialog-actions">
              <Button variant="ghost" type="button" onClick={() => setPendingDeleteId(null)}>
                取消
              </Button>
              <Button variant="danger" type="button" onClick={() => void deleteWork(pendingDeleteId)}>
                删除作品
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {previewWork ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setPreviewWork(null)}>
          <div className="image-preview-dialog" role="dialog" aria-modal="true" aria-label="图片预览">
            <button type="button" aria-label="关闭预览" onClick={() => setPreviewWork(null)}>
              <X size={20} />
            </button>
            {isVideoAsset(previewWork.cover_asset) ? (
              <video src={resolveAssetUrl(previewWork.cover_asset.url)} controls autoPlay playsInline onClick={(event) => event.stopPropagation()} />
            ) : (
              <div className={previewWork.output_assets.length > 1 ? "work-output-grid" : undefined} onClick={(event) => event.stopPropagation()}>
                {(previewWork.output_assets.length ? previewWork.output_assets : [previewWork.cover_asset]).map((asset, index) => (
                  <img key={asset.local_url || asset.url} src={resolveAssetUrl(asset.url)} alt={`作品预览 ${index + 1}`} />
                ))}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </main>
  );
};
