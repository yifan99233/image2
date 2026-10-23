import { LoadingState } from "@/components/ui/LoadingState";
import { useEffect, useState } from "react";
import { Check, Copy, Download, FileImage, Image, Search, Sparkles, Wand2, X } from "lucide-react";
import { Link } from "react-router-dom";
import { workService } from "@/services/works";
import type { WorkItem } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { downloadImage } from "@/utils/download";
import { getGalleryAspectRatio } from "@/utils/galleryAspectRatio";
import { formatDateTime } from "@/utils/time";

export { DashboardPage } from "./DashboardPage";

const galleryAspectRatioStyle = (asset: { width?: number | null; height?: number | null }, fallback?: string | null) => {
  const aspectRatio = getGalleryAspectRatio(asset, fallback);
  return aspectRatio ? { aspectRatio } : undefined;
};

export const GalleryPage = () => {
  const [works, setWorks] = useState<WorkItem[]>([]);
  const [query, setQuery] = useState("");
  const [selectedWork, setSelectedWork] = useState<WorkItem | null>(null);
  const [activePreviewUrl, setActivePreviewUrl] = useState<string | null>(null);
  const [copiedPromptWorkId, setCopiedPromptWorkId] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    workService
      .getGalleryWorks()
      .then((items) => {
        if (!ignore) {
          setWorks(items);
          setError(null);
        }
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "创作广场加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  const filteredWorks = works.filter((work) =>
    `${work.category}${work.prompt_snapshot}`.toLowerCase().includes(query.toLowerCase()),
  );
  const selectedPreviewUrl = activePreviewUrl ?? selectedWork?.output_assets[0]?.url ?? selectedWork?.cover_asset.url ?? null;
  const isEditGalleryWork = (work: WorkItem) => ["image_edit", "image_to_image", "batch_edit"].includes(work.work_type ?? "");

  useEffect(() => {
    if (!copiedPromptWorkId) return;
    const timerId = window.setTimeout(() => setCopiedPromptWorkId(null), 1800);
    return () => window.clearTimeout(timerId);
  }, [copiedPromptWorkId]);

  const openGalleryWork = (work: WorkItem, previewUrl?: string) => {
    setSelectedWork(work);
    setActivePreviewUrl(previewUrl ?? work.output_assets[0]?.url ?? work.cover_asset.url);
  };

  const closeGalleryWork = () => {
    setSelectedWork(null);
    setActivePreviewUrl(null);
  };

  const copyPrompt = async (work: WorkItem) => {
    try {
      await navigator.clipboard.writeText(work.prompt_snapshot);
      setCopiedPromptWorkId(work.id);
    } catch {
      setCopiedPromptWorkId(null);
    }
  };

  return (
    <main className="page-surface gallery-page">
      <header className="page-header">
        <div>
          <h1>创作广场</h1>
          <p>对比原图与生成效果，发现更多创作灵感。</p>
        </div>
        <div className="search-field">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索分类或提示词" aria-label="搜索创作案例" />
        </div>
      </header>
      {isLoading ? <LoadingState label="正在加载推荐作品…" variant="comparison" /> : null}
      {error ? <div className="list-state list-state--error">{error}</div> : null}
      {!isLoading && !error && !filteredWorks.length ? (
        <div className="empty-state">
          <FileImage size={34} />
          <h3>暂无推荐作品</h3>
          <p>后台将成功任务设为示范后，这里会展示真实结果图和提示词。</p>
        </div>
      ) : null}
      <section className="gallery-grid">
        {filteredWorks.map((work) => {
          const inputAsset = work.input_assets[0] ?? null;
          const outputAsset = work.output_assets[0] ?? work.cover_asset;
          const hasComparison = isEditGalleryWork(work) && Boolean(inputAsset);
          const title = work.title ?? `作品 #${work.id}`;
          const shouldShowCategory = work.category.trim().toLowerCase() !== title.trim().toLowerCase();
          const continuePath = isEditGalleryWork(work) ? "/create/edit" : "/create/text-to-image";

          return (
            <article
              className={`gallery-card ${hasComparison ? "gallery-card--compare" : "gallery-card--single"}`}
              key={work.id}

            >
              <div className="gallery-card__media" aria-label={hasComparison ? "原图和生成图对比" : "生成结果图"}>
                {hasComparison && inputAsset ? (
                  <figure
                    className="gallery-card__image gallery-card__image--input"
                  >
                    <button className="gallery-card__preview" type="button" aria-label={`查看${title}的原图`} onClick={() => openGalleryWork(work, inputAsset.url)}>
                      <img src={resolveAssetUrl(inputAsset.url)} alt="原图" loading="lazy" />
                    </button>
                    <figcaption>原图</figcaption>
                  </figure>
                ) : null}
                <figure
                  className="gallery-card__image gallery-card__image--output"
                >
                  <button className="gallery-card__preview" type="button" aria-label={`查看${title}的生成结果`} onClick={() => openGalleryWork(work, outputAsset.url)}>
                    <img src={resolveAssetUrl(outputAsset.url)} alt="生成结果" loading="lazy" />
                  </button>
                  <figcaption>{hasComparison ? "生成结果" : "AI 生成"}</figcaption>
                </figure>
              </div>
              <div className="gallery-card__body">
                {shouldShowCategory ? <span>{work.category}</span> : null}
                <h2>{title}</h2>
                <p>{work.prompt_snapshot}</p>
                <Link className="button button--secondary" to={continuePath} onClick={(event) => event.stopPropagation()}>
                  <Wand2 size={16} />
                  继续创作
                </Link>
              </div>
            </article>
          );
        })}
      </section>
      {selectedWork ? (
        <div className="modal-backdrop gallery-detail-backdrop" role="presentation" onClick={closeGalleryWork}>
          <section className="gallery-detail-dialog" role="dialog" aria-modal="true" aria-label="创作详情" onClick={(event) => event.stopPropagation()}>
            <div className="gallery-detail-viewer">
              {selectedPreviewUrl ? <img src={resolveAssetUrl(selectedPreviewUrl)} alt={selectedWork.title ?? "创作结果"} /> : null}
            </div>
            <aside className="gallery-detail-panel">
              <button className="gallery-detail-close" type="button" aria-label="关闭详情" onClick={closeGalleryWork}>
                <X size={20} />
              </button>
              <div className="gallery-detail-title">
                <h2>模型：{selectedWork.category}</h2>
                <p>{formatDateTime(selectedWork.created_at)}</p>
              </div>
              <div className="gallery-detail-scroll">
                <div className="gallery-detail-section">
                  <div className="gallery-detail-section__head">
                    <Sparkles size={16} />
                    <strong>创作提示词</strong>
                  </div>
                  <div className="gallery-detail-prompt-box">
                    <button className="gallery-detail-copy" type="button" onClick={() => void copyPrompt(selectedWork)}>
                      {copiedPromptWorkId === selectedWork.id ? <Check size={14} /> : <Copy size={14} />}
                      {copiedPromptWorkId === selectedWork.id ? "已复制" : "复制"}
                    </button>
                    <p className="gallery-detail-prompt">{selectedWork.prompt_snapshot}</p>
                  </div>
                </div>
                <div className="gallery-detail-section">
                  <div className="gallery-detail-section__head">
                    <Image size={16} />
                    <strong>AI 生成结果</strong>
                  </div>
                  <div className="gallery-detail-thumbs">
                    {selectedWork.output_assets.map((asset, index) => (
                      <button
                        className={activePreviewUrl === asset.url ? "is-active" : undefined}
                        key={`output-${asset.url}-${index}`}
                        style={galleryAspectRatioStyle(asset, selectedWork.aspect_ratio)}
                        data-has-aspect-ratio={getGalleryAspectRatio(asset, selectedWork.aspect_ratio) ? "true" : undefined}
                        type="button"
                        onClick={() => setActivePreviewUrl(asset.url)}
                      >
                        <img src={resolveAssetUrl(asset.url)} alt={`结果图 ${index + 1}`} />
                        <span>结果图</span>
                      </button>
                    ))}
                  </div>
                </div>
                {isEditGalleryWork(selectedWork) && selectedWork.input_assets.length ? (
                  <div className="gallery-detail-section">
                    <div className="gallery-detail-section__head">
                      <FileImage size={16} />
                      <strong>原图（{selectedWork.input_assets.length} 张）</strong>
                    </div>
                    <div className="gallery-detail-thumbs gallery-detail-thumbs--inputs">
                      {selectedWork.input_assets.map((asset, index) => (
                        <button
                          className={activePreviewUrl === asset.url ? "is-active" : undefined}
                          key={`input-${asset.url}-${index}`}
                          style={galleryAspectRatioStyle(asset, selectedWork.aspect_ratio)}
                          data-has-aspect-ratio={getGalleryAspectRatio(asset, selectedWork.aspect_ratio) ? "true" : undefined}
                          type="button"
                          onClick={() => setActivePreviewUrl(asset.url)}
                        >
                          <img src={resolveAssetUrl(asset.url)} alt={`原图 ${index + 1}`} />
                          <span>原图 {index + 1}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
              {selectedPreviewUrl ? (
                <button className="button button--primary button--full gallery-detail-download" type="button" onClick={() => void downloadImage(resolveAssetUrl(selectedPreviewUrl), `gallery-${selectedWork.id}.png`)}>
                  <Download size={17} />
                  下载图片
                </button>
              ) : null}
            </aside>
          </section>
        </div>
      ) : null}
    </main>
  );
};
