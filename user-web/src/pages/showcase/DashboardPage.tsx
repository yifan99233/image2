import { LoadingState } from "@/components/ui/LoadingState";
import { CreationProcessIcon } from "@/components/ui/CreationProcessIcon";
import { useEffect, useState } from "react";
import { ArrowRight, ArrowUpRight, CheckCheck, Coins, FileImage, Play, Plus } from "lucide-react";
import { Frame, GalleryHorizontalEnd, Image, Layers3 } from "@/components/ui/StudioIcons";
import { Link } from "react-router-dom";
import { creditService } from "@/services/credits";
import { imageTaskService } from "@/services/imageTasks";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import { workService } from "@/services/works";
import { useAuthStore } from "@/stores/authStore";
import type { CreditBalance, ImageTask, WorkItem } from "@/types/api";
import { isVideoUrl } from "@/pages/shared/mediaConfig";
import { ImagePreviewModal, VideoPreviewModal } from "@/pages/shared/mediaPreview";
import { resolveAssetUrl } from "@/utils/assets";

const creationTools = [
  {
    title: "图生图",
    path: "/create/edit",
    description: "给图片一个新灵感",
    hint: "上传图片，轻松换背景、改风格",
    tone: "blue",
    module: "image_edit",
  },
  {
    title: "文生图",
    path: "/create/text-to-image",
    description: "让文字变成画面",
    hint: "描述你的想法，生成理想图片",
    tone: "violet",
    module: "text_to_image",
  },
  {
    title: "批量生图",
    path: "/create/batch-generate",
    description: "一次生成，一整组创意",
    hint: "多个提示词，批量生成更高效",
    tone: "teal",
    module: "batch_generate",
  },
  {
    title: "批量改图",
    path: "/create/batch-edit",
    description: "多张图片，统一好风格",
    hint: "批量处理素材，告别重复操作",
    tone: "amber",
    module: "batch_edit",
  },
] as const;

function HomeThumbnail({
  src,
  alt,
  video = false,
}: {
  src?: string;
  alt: string;
  video?: boolean;
}) {
  const [failedSource, setFailedSource] = useState<string | null>(null);
  if (!src || failedSource === src) {
    return (
      <span className="studio-thumbnail-fallback">
        <FileImage size={27} strokeWidth={1.4} />
        <span>{src ? "图片暂时无法显示" : video ? "点击预览视频" : "创意，从这里开始"}</span>
      </span>
    );
  }
  return (
    <img
      src={resolveAssetUrl(src)}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailedSource(src)}
    />
  );
}

function CanvasIllustration() {
  return (
    <div className="studio-canvas-art" aria-hidden="true">
      <div className="studio-canvas-art__tile studio-canvas-art__tile--back">
        <Image size={25} strokeWidth={1.3} />
      </div>
      <div className="studio-canvas-art__tile studio-canvas-art__tile--front">
        <svg viewBox="0 0 120 100" fill="none">
          <rect width="120" height="100" rx="8" fill="#E4EDE8" />
          <circle cx="87" cy="27" r="13" fill="#F1C984" />
          <path d="M0 78L36 35L79 100H0V78Z" fill="#82AAA0" />
          <path d="M43 100L83 52L120 81V100H43Z" fill="#4D7B6C" />
        </svg>
        <span />
        <span />
        <span />
        <span />
      </div>
      <span className="studio-canvas-art__cursor">
        <ArrowUpRight size={17} />
        灵感
      </span>
    </div>
  );
}

export const DashboardPage = () => {
  const user = useAuthStore((state) => state.user);
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [works, setWorks] = useState<WorkItem[]>([]);
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [siteConfig, setSiteConfig] = useState(readCachedSiteConfig);
  const [previewImage, setPreviewImage] = useState<{ title: string; url: string } | null>(null);
  const [previewVideo, setPreviewVideo] = useState<{
    title: string;
    url: string;
    poster?: string;
  } | null>(null);

  useEffect(() => {
    let ignore = false;
    setIsLoading(true);
    setError(null);
    Promise.all([
      creditService.getBalance(),
      workService.getWorks({ limit: 80 }),
      imageTaskService.getTasks({ limit: 80 }),
    ])
      .then(([nextBalance, nextWorks, nextTasks]) => {
        if (ignore) return;
        setBalance(nextBalance);
        setWorks(nextWorks);
        setTasks(nextTasks);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "创作数据加载失败");
      })
      .finally(() => {
        if (!ignore) setIsLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, [refreshKey]);

  useEffect(() => {
    let ignore = false;
    loadSiteConfig().then((config) => {
      if (!ignore) setSiteConfig(config);
    });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (!previewImage && !previewVideo) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage(null);
        setPreviewVideo(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [previewImage, previewVideo]);

  const enabledModules = new Set(siteConfig.enabled_modules);
  const visibleTools = creationTools.filter((tool) => enabledModules.has(tool.module));
  const cases = siteConfig.homepage_case_carousels
    .flat()
    .filter((item) => item.title && (item.image_url || item.file_url || item.link_url))
    .slice(0, 4);
  const completedTasks = tasks.filter((task) => task.status === "succeeded").length;
  const dataUnavailable = isLoading || Boolean(error);
  const defaultCreatePath = visibleTools[0]?.path;
  const dateLabel = new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date());

  return (
    <main className="studio-home">
      <header className="studio-welcome">
        <div>
          <p className="studio-eyebrow">
            <span />
            欢迎回来，{user?.nickname || user?.username || "创作者"}
          </p>
          <h1>今天，让灵感成为作品。</h1>
          <p className="studio-welcome__description">
            从一张图片、一段文字开始，轻松开启新的创作。
          </p>
        </div>
        <time className="studio-date" dateTime={new Date().toLocaleDateString("en-CA")}>
          {dateLabel}
        </time>
      </header>

      <section className="studio-overview" aria-label="创作概览">
        <div className="studio-metric">
          <span className="studio-metric__icon">
            <Coins size={19} />
          </span>
          <div>
            <span>可用积分</span>
            <strong>{dataUnavailable || !balance ? "—" : balance.balance.toLocaleString()}</strong>
          </div>
          {enabledModules.has("recharge") && (
            <Link to="/support">
              充值
              <ArrowUpRight size={13} />
            </Link>
          )}
        </div>
        <div className="studio-metric">
          <span className="studio-metric__icon">
            <CheckCheck size={19} />
          </span>
          <div>
            <span>
              近期完成任务<small>最近 {tasks.length || 80} 条内</small>
            </span>
            <strong>
              {dataUnavailable ? "—" : completedTasks}
              <small>次</small>
            </strong>
          </div>
        </div>
        <div className="studio-metric">
          <span className="studio-metric__icon">
            <GalleryHorizontalEnd size={19} />
          </span>
          <div>
            <span>最近作品</span>
            <strong>
              {dataUnavailable ? "—" : works.length}
              <small>件</small>
            </strong>
          </div>
          {enabledModules.has("works") && (
            <Link to="/works" aria-label="查看所有作品">
              <ArrowUpRight size={17} />
            </Link>
          )}
        </div>
      </section>

      {error && (
        <div className="studio-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => setRefreshKey((key) => key + 1)}>
            重新加载
          </button>
        </div>
      )}

      {visibleTools.length > 0 && (
        <section className="studio-section" aria-labelledby="studio-tools-title">
          <div className="studio-section__head">
            <h2 id="studio-tools-title">
              开始创作<span>选择适合你的方式</span>
            </h2>
          </div>
          <div className="studio-tools">
            {visibleTools.map(({ title, path, module, description, hint, tone }, index) => (
              <Link className={`studio-tool studio-tool--${tone}`} to={path} key={path}>
                <div className="studio-tool__top">
                  <CreationProcessIcon mode={module} />
                  {index === 0 ? (
                    <span className="studio-tool__badge">常用</span>
                  ) : (
                    <ArrowUpRight className="studio-tool__arrow" size={18} />
                  )}
                </div>
                <h3>{title}</h3>
                <p>{description}</p>
                <small>{hint}</small>
              </Link>
            ))}
          </div>
        </section>
      )}

      <div className="studio-features">
        {enabledModules.has("batch_generate") && (
          <section className="studio-batch">
            <div className="studio-batch__copy">
              <span className="studio-feature-label">
                <Layers3 size={15} />
                批量创作，让效率加倍
              </span>
              <h2>
                一组素材，
                <br />
                更多可能。
              </h2>
              <p>
                商品套图、场景延展。
                <br />
                把重复的工作交给 AI，留更多时间给创意。
              </p>
              <Link to="/create/batch-generate">
                开始批量创作
                <ArrowRight size={16} />
              </Link>
            </div>
            <div className="studio-batch-art" aria-hidden="true">
              <div className="studio-batch-art__card studio-batch-art__card--one">
                <span />
                <i />
              </div>
              <div className="studio-batch-art__card studio-batch-art__card--two">
                <span />
                <i />
              </div>
              <div className="studio-batch-art__card studio-batch-art__card--three">
                <span />
                <i />
              </div>
              <span className="studio-batch-art__tag">
                <CheckCheck size={13} />
                多种风格 · 一次生成
              </span>
            </div>
          </section>
        )}
        {enabledModules.has("text_to_image") && (
          <Link className="studio-canvas" to="/create/canvas">
            <div className="studio-canvas__copy">
              <span className="studio-feature-label">
                <Frame size={15} />
                自由画布
              </span>
              <h2>
                给灵感，
                <br />
                多一点空间。
              </h2>
              <p>
                编排图片，串联想法。
                <br />
                在同一张画布上完成创作。
              </p>
              <span className="studio-canvas__link">
                打开画布
                <ArrowRight size={16} />
              </span>
            </div>
            <CanvasIllustration />
          </Link>
        )}
      </div>

      {enabledModules.has("works") && (
        <section className="studio-section" aria-labelledby="studio-works-title">
          <div className="studio-section__head">
            <h2 id="studio-works-title">
              最近作品<span>每一次创作，都值得留下</span>
            </h2>
            <Link to="/works">
              全部作品
              <ArrowRight size={15} />
            </Link>
          </div>
          {isLoading ? (
            <LoadingState label="正在加载最近作品" variant="cards" />
          ) : works.length ? (
            <div className="studio-works">
              {works.slice(0, 4).map((work) => (
                <Link className="studio-work" key={work.id} to="/works">
                  <div className="studio-work__image">
                    <HomeThumbnail
                      src={work.cover_asset.thumbnail_url || work.cover_asset.url}
                      alt={work.title || work.prompt_snapshot || "创作作品"}
                    />
                    <span>
                      查看作品
                      <ArrowUpRight size={15} />
                    </span>
                  </div>
                  <div className="studio-work__caption">
                    <strong>{work.title || work.prompt_snapshot || `作品 #${work.id}`}</strong>
                    <small>{work.category}</small>
                  </div>
                </Link>
              ))}
            </div>
          ) : (
            <div className="studio-empty">
              <span className="studio-empty__icon">
                <FileImage size={27} strokeWidth={1.4} />
              </span>
              <div>
                <h3>{error ? "暂时无法加载作品" : "你的下一件作品，就从这里开始"}</h3>
                <p>
                  {error
                    ? "请稍后重试，已有作品不会受到影响。"
                    : "完成创作后，作品会自动出现在这里，随时查看与下载。"}
                </p>
              </div>
              {!error && defaultCreatePath && (
                <Link to={defaultCreatePath}>
                  <Plus size={16} />
                  开始创作
                </Link>
              )}
            </div>
          )}
        </section>
      )}

      {cases.length > 0 && (
        <section className="studio-section" aria-labelledby="studio-cases-title">
          <div className="studio-section__head">
            <h2 id="studio-cases-title">
              探索创作场景<span>为你的下一个想法找点灵感</span>
            </h2>
            {enabledModules.has("gallery") && (
              <Link to="/gallery">
                创作广场
                <ArrowRight size={15} />
              </Link>
            )}
          </div>
          <div className="studio-cases">
            {cases.map((item, index) => {
              const video = isVideoUrl(item.file_url || "");
              const imageUrl = item.image_url || (!video ? item.file_url : "");
              const content = (
                <>
                  <span className="studio-case__image">
                    <HomeThumbnail src={imageUrl} alt={item.title} video={video} />
                    {video && (
                      <span className="studio-case__play">
                        <Play size={16} />
                      </span>
                    )}
                  </span>
                  <span className="studio-case__copy">
                    <strong>
                      {item.title}
                      <ArrowUpRight size={15} />
                    </strong>
                    <small>{item.subtitle}</small>
                  </span>
                </>
              );
              return imageUrl || video ? (
                <button
                  type="button"
                  className="studio-case"
                  key={`${item.title}-${index}`}
                  onClick={() =>
                    video
                      ? setPreviewVideo({
                          title: item.title,
                          url: resolveAssetUrl(item.file_url!),
                          poster: imageUrl ? resolveAssetUrl(imageUrl) : undefined,
                        })
                      : setPreviewImage({ title: item.title, url: resolveAssetUrl(imageUrl!) })
                  }
                >
                  {content}
                </button>
              ) : (
                <a
                  className="studio-case"
                  href={item.link_url}
                  key={`${item.title}-${index}`}
                  rel="noreferrer"
                  target={item.link_url?.startsWith("/") ? undefined : "_blank"}
                >
                  {content}
                </a>
              );
            })}
          </div>
        </section>
      )}
      <ImagePreviewModal preview={previewImage} onClose={() => setPreviewImage(null)} />
      <VideoPreviewModal preview={previewVideo} onClose={() => setPreviewVideo(null)} />
    </main>
  );
};
