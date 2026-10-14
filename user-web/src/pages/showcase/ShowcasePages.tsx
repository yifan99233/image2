import { useEffect, useMemo, useState } from "react";
import {
  Check,
  Coins,
  Copy,
  Download,
  FileImage,
  GalleryHorizontalEnd,
  Gift,
  Image,
  Images,
  Layers3,
  Play,
  Search,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { creditService } from "@/services/credits";
import { imageTaskService } from "@/services/imageTasks";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { workService } from "@/services/works";
import type { CreditBalance, HomepageCaseCarouselItem, ImageTask, SiteConfig, SiteContentMaterial, WorkItem } from "@/types/api";
import { isVideoUrl } from "@/pages/shared/mediaConfig";
import { ImagePreviewModal, VideoPreviewModal } from "@/pages/shared/mediaPreview";
import { resolveAssetUrl } from "@/utils/assets";
import { downloadImage } from "@/utils/download";
import { getGalleryAspectRatio } from "@/utils/galleryAspectRatio";
import { formatDateTime } from "@/utils/time";

const formatCredit = (balance: CreditBalance | null) => (balance ? balance.balance.toLocaleString() : "--");

const galleryAspectRatioStyle = (asset: { width?: number | null; height?: number | null }, fallback?: string | null) => {
  const aspectRatio = getGalleryAspectRatio(asset, fallback);
  return aspectRatio ? { aspectRatio } : undefined;
};

const dashboardCaseVideos = [
  { title: "电商套图", subtitle: "主图、场景图、详情页素材统一生成", tone: "blue" },
  { title: "产品效果图", subtitle: "上传商品图后快速延展应用场景", tone: "orange" },
  { title: "图片二次优化", subtitle: "改背景、换氛围、补细节", tone: "cyan" },
  { title: "案例展示", subtitle: "生成前后效果直接对比", tone: "green" },
] as const;

const defaultDashboardCaseCarousels: HomepageCaseCarouselItem[][] = [
  dashboardCaseVideos.slice(0, 2),
  dashboardCaseVideos.slice(2, 4),
];

const normalizeDashboardCaseCarousels = (groups?: HomepageCaseCarouselItem[][]): HomepageCaseCarouselItem[][] => {
  if (!Array.isArray(groups)) return defaultDashboardCaseCarousels.filter((group) => group.some((item) => item.image_url || item.file_url));
  const normalized = groups.slice(0, 2).map((group, groupIndex) => {
    if (!Array.isArray(group)) return defaultDashboardCaseCarousels[groupIndex].filter((item) => item.image_url || item.file_url);
    const items = group
      .slice(0, 4)
      .map((item) => ({
        title: String(item?.title || "").trim(),
        subtitle: String(item?.subtitle || "").trim(),
        image_url: String(item?.image_url || "").trim(),
        file_url: String(item?.file_url || "").trim(),
        link_url: String(item?.link_url || "").trim(),
        tone: item?.tone || "blue",
      }))
      .filter((item) => item.title && (item.image_url || item.file_url));
    return items;
  });
  return normalized.filter((group) => group.length);
};

const normalizeDashboardBatchBanners = (items?: SiteContentMaterial[]) => {
  if (!Array.isArray(items)) return [];
  return items
    .slice(0, 8)
    .map((item) => ({
      title: String(item?.title || "").trim(),
      image_url: String(item?.file_url || item?.cover_url || "").trim(),
    }))
    .filter((item) => item.image_url);
};

export const DashboardPage = () => {
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [works, setWorks] = useState<WorkItem[]>([]);
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [caseCarouselIndexes, setCaseCarouselIndexes] = useState([0, 0]);
  const [batchBannerIndex, setBatchBannerIndex] = useState(0);
  const [previewVideo, setPreviewVideo] = useState<{ title: string; url: string; poster?: string } | null>(null);
  const [previewImage, setPreviewImage] = useState<{ title: string; url: string } | null>(null);
  const [siteConfig, setSiteConfig] = useState<SiteConfig>(readCachedSiteConfig);

  useEffect(() => {
    let ignore = false;
    Promise.all([creditService.getBalance(), workService.getWorks({ limit: 80 }), imageTaskService.getTasks({ limit: 80 })])
      .then(([creditBalance, workItems, taskItems]) => {
        if (ignore) return;
        setBalance(creditBalance);
        setWorks(workItems);
        setTasks(taskItems);
        setError(null);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "控制台数据加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });

    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  const caseCarousels = useMemo(() => normalizeDashboardCaseCarousels(siteConfig.homepage_case_carousels), [siteConfig.homepage_case_carousels]);
  const batchBanners = useMemo(() => normalizeDashboardBatchBanners(siteConfig.homepage_batch_banners), [siteConfig.homepage_batch_banners]);

  useEffect(() => {
    if (!caseCarousels.length) return;
    const timer = window.setInterval(() => {
      setCaseCarouselIndexes((indexes) => caseCarousels.map((items, index) => ((indexes[index] || 0) + 1) % items.length));
    }, 4000);
    return () => window.clearInterval(timer);
  }, [caseCarousels]);

  useEffect(() => {
    if (batchBanners.length <= 1) return;
    const timer = window.setInterval(() => {
      setBatchBannerIndex((index) => (index + 1) % batchBanners.length);
    }, 3600);
    return () => window.clearInterval(timer);
  }, [batchBanners]);

  useEffect(() => {
    if (!previewVideo && !previewImage) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewVideo(null);
        setPreviewImage(null);
      }
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [previewVideo, previewImage]);

  const succeededTasks = tasks.filter((t) => t.status === "succeeded").length;
  const collectedWorks = works.filter((w) => w.is_collected).length;
  const activeBatchBanner = batchBanners.length ? batchBanners[batchBannerIndex % batchBanners.length] : null;
  const activeBatchBannerUrl = activeBatchBanner ? resolveAssetUrl(activeBatchBanner.image_url) : "";

  return (
    <main className="dash">
      {error ? <div className="dash-error">{error}</div> : null}

      {/* ---- Hero ---- */}
      <section className="dash-hero">
        <div className="dash-hero__bg" aria-hidden="true" />
        <div className="dash-hero__body">
          <span className="dash-hero__kicker">
            <Sparkles size={15} />
            AI 图片创作平台
          </span>
          <h1>
            多模型协作 · <em>智能创作</em>
          </h1>
          <p>围绕电商核心场景，把产品效果图、电商套图、图片二次优化和批量处理放在一个工作台完成。</p>
          <div className="dash-hero__actions">
            <Link className="dash-cta dash-cta--primary" to="/create/edit">
              <Wand2 size={18} />
              图生图
            </Link>
            <Link className="dash-cta dash-cta--secondary" to="/create/text-to-image">
              <Image size={18} />
              文生图
            </Link>
          </div>
          <div className="dash-hero-banner">
            <div className="dash-hero-banner__content">
              <span><Images size={16} />批量创作加速</span>
              <strong>多提示词生图，多素材批量改图</strong>
              <p>复制提示词列表或上传多张素材，按任务数量实时累计积分。</p>
              <div>
                <em>统一改图</em>
                <em>一图一词</em>
                <em>AI 优化提示词</em>
              </div>
              <Link className="dash-hero-banner__link" to="/create/batch-generate">开始批量创作</Link>
            </div>
            <button
              className="dash-hero-banner__preview"
              type="button"
              aria-label={activeBatchBannerUrl ? "预览批量创作图片" : "批量创作预览"}
              onClick={() => {
                if (activeBatchBannerUrl) setPreviewImage({ title: activeBatchBanner?.title || "批量创作加速", url: activeBatchBannerUrl });
              }}
            >
              {batchBanners.length ? (
                <>
                  <span className="dash-hero-banner__track" style={{ transform: `translateX(-${(batchBannerIndex % batchBanners.length) * 100}%)` }}>
                    {batchBanners.map((item, index) => (
                      <img key={`${item.image_url}-${index}`} src={resolveAssetUrl(item.image_url)} alt="" />
                    ))}
                  </span>
                  {batchBanners.length > 1 ? (
                    <span className="dash-hero-banner__dots">
                      {batchBanners.map((_, index) => <span className={index === batchBannerIndex % batchBanners.length ? "active" : ""} key={index} />)}
                    </span>
                  ) : null}
                </>
              ) : (
                <>
                  <i />
                  <i />
                  <i />
                  <b />
                </>
              )}
            </button>
          </div>
        </div>

        {caseCarousels.length ? <div className="dash-case-board" aria-label="电商核心场景案例">
          {caseCarousels.map((items, carouselIndex) => (
            <section className="dash-case-carousel" aria-label={`场景轮播 ${carouselIndex + 1}`} key={carouselIndex}>
              <div
                className="dash-case-carousel__track"
                style={{ transform: `translateX(-${(caseCarouselIndexes[carouselIndex] % items.length) * 100}%)` }}
              >
                {items.map((item, itemIndex) => {
                  const caseIndex = carouselIndex * 2 + itemIndex;
                  const mediaUrl = item.file_url ? resolveAssetUrl(item.file_url) : "";
                  const coverUrl = item.image_url ? resolveAssetUrl(item.image_url) : "";
                  const isVideo = isVideoUrl(mediaUrl);
                  const content = (
                    <>
                      <div className="dash-case-video__screen">
                        {isVideo ? (
                          <video className="dash-case-video__media" src={mediaUrl} muted playsInline preload="metadata" poster={coverUrl || undefined} />
                        ) : coverUrl ? (
                          <img className="dash-case-video__media" src={coverUrl} alt="" />
                        ) : null}
                        <span>{String(caseIndex + 1).padStart(2, "0")}</span>
                        {isVideo || !coverUrl ? <Play size={24} /> : null}
                      </div>
                      <div>
                        <strong>{item.title}</strong>
                        <p>{item.subtitle}</p>
                      </div>
                    </>
                  );
                  return (
                    isVideo ? (
                      <button
                        className={`dash-case-video dash-case-video--${item.tone || "blue"}`}
                        key={`${item.title}-${itemIndex}`}
                        onClick={() => setPreviewVideo({ title: item.title, url: mediaUrl, poster: coverUrl || undefined })}
                        type="button"
                      >
                        {content}
                      </button>
                    ) : coverUrl ? (
                      <button
                        className={`dash-case-video dash-case-video--${item.tone || "blue"}`}
                        key={`${item.title}-${itemIndex}`}
                        onClick={() => setPreviewImage({ title: item.title, url: coverUrl })}
                        type="button"
                      >
                        {content}
                      </button>
                    ) : (
                    item.link_url ? (
                      <a className={`dash-case-video dash-case-video--${item.tone || "blue"}`} href={item.link_url} key={`${item.title}-${itemIndex}`} rel="noreferrer" target={item.link_url.startsWith("/") ? undefined : "_blank"}>
                        {content}
                      </a>
                    ) : (
                      <article className={`dash-case-video dash-case-video--${item.tone || "blue"}`} key={`${item.title}-${itemIndex}`}>
                        {content}
                      </article>
                    )
                    )
                  );
                })}
              </div>
              <div className="dash-case-carousel__dots" aria-label={`切换场景轮播 ${carouselIndex + 1}`}>
                {items.map((item, itemIndex) => (
                  <button
                    aria-label={`查看${item.title}`}
                    aria-current={caseCarouselIndexes[carouselIndex] === itemIndex}
                    className={caseCarouselIndexes[carouselIndex] === itemIndex ? "is-active" : ""}
                    key={item.title}
                    onClick={() =>
                      setCaseCarouselIndexes((indexes) => indexes.map((value, index) => (index === carouselIndex ? itemIndex : value)))
                    }
                    type="button"
                  />
                ))}
              </div>
            </section>
          ))}
        </div> : null}
      </section>

      <VideoPreviewModal preview={previewVideo} onClose={() => setPreviewVideo(null)} />
      <ImagePreviewModal preview={previewImage} onClose={() => setPreviewImage(null)} />

      {/* ---- Stats strip ---- */}
      <section className="dash-stats">
        <article className="dash-stat">
          <Coins size={20} />
          <div>
            <strong>{formatCredit(balance)}</strong>
            <span>当前积分</span>
          </div>
        </article>
        <article className="dash-stat">
          <Play size={20} />
          <div>
            <strong>{isLoading ? "--" : tasks.length}</strong>
            <span>任务总数 · {succeededTasks} 已完成</span>
          </div>
        </article>
        <article className="dash-stat">
          <GalleryHorizontalEnd size={20} />
          <div>
            <strong>{isLoading ? "--" : works.length}</strong>
            <span>作品数量 · {collectedWorks} 已收藏</span>
          </div>
        </article>
        <Link className="dash-stat dash-stat--link" to="/billing/recharge">
          <Gift size={20} />
          <div>
            <strong>充值积分</strong>
            <span>获取更多创作额度</span>
          </div>
        </Link>
      </section>

      {/* ---- Quick start ---- */}
      <section className="dash-section">
        <div className="dash-section__head">
          <h2>快速开始</h2>
          <span>选择一个工具立即创作</span>
        </div>
        <div className="dash-quick-grid">
          {[
            { title: "图生图", path: "/create/edit", icon: Wand2, desc: "上传图片，按描述改图", color: "violet" },
            { title: "文生图", path: "/create/text-to-image", icon: Image, desc: "文字描述生成图片", color: "blue" },
            { title: "批量生图", path: "/create/batch-generate", icon: Images, desc: "一行一个提示词批量生成", color: "cyan" },
            { title: "批量改图", path: "/create/batch-edit", icon: Layers3, desc: "多图按同一描述批量改图", color: "orange" },
            { title: "我的作品", path: "/works", icon: GalleryHorizontalEnd, desc: "管理、筛选和下载", color: "blue" },
          ].map((entry) => {
            const Icon = entry.icon;
            return (
              <Link className={`dash-quick dash-quick--${entry.color}`} key={entry.path} to={entry.path}>
                <div className="dash-quick__icon"><Icon size={22} /></div>
                <strong>{entry.title}</strong>
                <span>{entry.desc}</span>
              </Link>
            );
          })}
        </div>
      </section>

      {/* ---- Recent works ---- */}
      <section className="dash-section">
        <div className="dash-section__head">
          <h2>最近作品</h2>
          <Link className="dash-section__more" to="/works">查看全部 →</Link>
        </div>
        {works.length ? (
          <div className="dash-works-grid">
            {works.slice(0, 6).map((work) => (
              <Link className="dash-work" key={work.id} to="/works">
                <img src={resolveAssetUrl(work.cover_asset.url)} alt={work.prompt_snapshot} />
                <div className="dash-work__overlay">
                  <span>{work.category}</span>
                  <p>{work.prompt_snapshot}</p>
                </div>
              </Link>
            ))}
          </div>
        ) : (
          <div className="dash-empty">
            <FileImage size={34} />
            <h3>{isLoading ? "加载中…" : "暂无作品"}</h3>
            <p>完成首次创作后，作品会展示在这里</p>
          </div>
        )}
      </section>
    </main>
  );
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

  const openGalleryWork = (work: WorkItem) => {
    setSelectedWork(work);
    setActivePreviewUrl(work.output_assets[0]?.url ?? work.cover_asset.url);
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
    <main className="page-surface">
      <header className="page-header">
        <div>
          <h1>创作广场</h1>
          <p>展示后台从真实成功任务中挑选的优秀示范。</p>
        </div>
        <div className="search-field">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索分类或提示词" />
        </div>
      </header>
      {isLoading ? <div className="list-state">正在加载推荐作品...</div> : null}
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
          const inputAspectRatio = getGalleryAspectRatio(inputAsset, work.aspect_ratio);
          const outputAspectRatio = getGalleryAspectRatio(outputAsset, work.aspect_ratio);

          return (
            <article
              className={`gallery-card ${hasComparison ? "gallery-card--compare" : "gallery-card--single"}`}
              key={work.id}
              role="button"
              tabIndex={0}
              onClick={() => openGalleryWork(work)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  openGalleryWork(work);
                }
              }}
            >
              <div className="gallery-card__media" aria-label={hasComparison ? "原图和生成图对比" : "生成结果图"}>
                {hasComparison && inputAsset ? (
                  <figure
                    className={`gallery-card__image gallery-card__image--input${inputAspectRatio ? " gallery-card__image--ratio" : ""}`}
                    style={inputAspectRatio ? { aspectRatio: inputAspectRatio } : undefined}
                  >
                    <img src={resolveAssetUrl(inputAsset.url)} alt="原图" />
                    <figcaption>原图</figcaption>
                  </figure>
                ) : null}
                <figure
                  className={`gallery-card__image gallery-card__image--output${outputAspectRatio ? " gallery-card__image--ratio" : ""}`}
                  style={outputAspectRatio ? { aspectRatio: outputAspectRatio } : undefined}
                >
                  <img src={resolveAssetUrl(outputAsset.url)} alt={work.prompt_snapshot} />
                  <figcaption>{hasComparison ? "生成图" : "AI 生成"}</figcaption>
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
