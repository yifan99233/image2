import { LoadingState } from "@/components/ui/LoadingState";
import { useCallback, useEffect, useState } from "react";
import {
  BadgeCheck,
  BellRing,
  BookOpen,
  Code2,
  Download,
  PackageOpen,
  Play,
  RefreshCw,
  Sparkles,
  TableProperties,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { opencodeService } from "@/services/opencode";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import type { OpenAgentDownload, OpenAgentUsageRecord, SiteConfig, SiteContentMaterial } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { formatDateTime } from "@/utils/time";

const isVideoUrl = (value?: string) => /\.(mp4|webm|mov|m4v)(\?|#|$)/i.test(value || "");

const hasConfiguredVideo = (item: SiteContentMaterial) => isVideoUrl(resolveAssetUrl(item.file_url || ""));
const hasConfiguredMaterial = (item: SiteContentMaterial) => Boolean((item.file_url || "").trim() || (item.cover_url || "").trim());

const renderConfiguredMedia = (item: SiteContentMaterial, className: string) => {
  const coverUrl = item.cover_url ? resolveAssetUrl(item.cover_url) : "";
  const fileUrl = item.file_url ? resolveAssetUrl(item.file_url) : "";
  if (fileUrl && isVideoUrl(fileUrl)) return <video className={className} src={fileUrl} muted playsInline preload="metadata" poster={coverUrl || undefined} />;
  if (coverUrl) return <img className={className} src={coverUrl} alt="" />;
  if (fileUrl) return <img className={className} src={fileUrl} alt="" />;
  return null;
};

const VideoPreviewModal = ({
  preview,
  onClose,
}: {
  preview: { title: string; url: string; poster?: string } | null;
  onClose: () => void;
}) => preview ? (
  <div className="modal-backdrop" role="presentation" onClick={onClose}>
    <section className="video-preview-dialog" role="dialog" aria-modal="true" aria-label={`${preview.title}视频预览`} onClick={(event) => event.stopPropagation()}>
      <button className="video-preview-dialog__close" type="button" onClick={onClose} aria-label="关闭视频预览">
        <X size={18} />
      </button>
      <video src={preview.url} poster={preview.poster} controls autoPlay playsInline />
      <strong>{preview.title}</strong>
    </section>
  </div>
) : null;

const UtilityPage = ({ title, intro, icon: Icon }: { title: string; intro: string; icon: typeof BellRing }) => (
  <main className="page-surface">
    <section className="utility-shell">
      <div className="utility-icon">
        <Icon size={30} />
      </div>
      <div>
        <h1>{title}</h1>
        <p>{intro}</p>
      </div>
      <div className="empty-state">
        <BellRing size={34} />
        <h3>等待后端接口接入</h3>
        <p>这里不会展示模拟结果；接口完成后会接入真实提交、查询和状态反馈。</p>
      </div>
    </section>
  </main>
);
export const DeveloperApiPage = () => (
  <UtilityPage title="API 接入" intro="API Key 和调用日志需要后端接口；当前只展示接入入口状态。" icon={Code2} />
);

const formatUsageCost = (value: number) => {
  if (!Number.isFinite(value) || value === 0) return "0";
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
};

const formatUsageDuration = (value?: number | null) => {
  if (value === null || value === undefined) return "--";
  return `${value}ms`;
};

const formatDownloadSize = (bytes?: number | null) => {
  if (!bytes || bytes <= 0) return "待发布";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
};

const downloadOrder = ["mac-arm64-dmg", "mac-arm64-zip", "mac-x64-dmg", "mac-x64-zip", "windows-universal-installer", "windows-universal-portable"];

export const OpenAgentInstallPage = () => {
  const [downloads, setDownloads] = useState<OpenAgentDownload[]>([]);
  const [siteConfig, setSiteConfig] = useState<SiteConfig>(readCachedSiteConfig);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [previewVideo, setPreviewVideo] = useState<{ title: string; url: string; poster?: string } | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      const items = await opencodeService.getDownloads();
      setDownloads([...items].sort((a, b) => downloadOrder.indexOf(a.key) - downloadOrder.indexOf(b.key)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Codex定制版下载列表加载失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
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
    if (!previewVideo) return;
    const handleKeydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPreviewVideo(null);
    };
    window.addEventListener("keydown", handleKeydown);
    return () => window.removeEventListener("keydown", handleKeydown);
  }, [previewVideo]);

  const macDownloads = downloads.filter((item) => item.platform === "mac");
  const windowsDownloads = downloads.filter((item) => item.platform === "windows");
  const installVideo = siteConfig.opencode_install_video;
  const installVideoUrl = resolveAssetUrl(installVideo.file_url || "");
  const installPosterUrl = installVideo.cover_url ? resolveAssetUrl(installVideo.cover_url) : undefined;
  const hasInstallMaterial = hasConfiguredMaterial(installVideo);
  const hasInstallVideo = hasConfiguredVideo(installVideo);

  return (
    <main className="tool-page openagent-install-page">
      <section className="openagent-hero">
        <div className="openagent-hero__copy">
          <div className="openagent-kicker"><Sparkles size={16} />Codex 级桌面智能体</div>
          <h1>Codex定制版</h1>
          <p>
            不是只会回答问题，而是能动手做事，写代码、做文件、查资料、生成内容、调试流程，像一个随叫随到的小型创作与工程工作间。
          </p>
          <div className="openagent-hero__actions">
            <a className="button button--primary" href="#openagent-downloads"><Download size={18} />下载 Codex定制版</a>
          </div>
        </div>
        {hasInstallMaterial ? <div className="openagent-visual">
          <div className="openagent-video-case">
            <button
              className="openagent-video-case__screen"
              disabled={!hasInstallVideo}
              onClick={() => hasInstallVideo && setPreviewVideo({ title: installVideo.title, url: installVideoUrl, poster: installPosterUrl })}
              type="button"
            >
              {renderConfiguredMedia(installVideo, "openagent-video-case__media")}
              {hasInstallVideo ? <Play size={34} /> : null}
              <span>案例视频</span>
              {hasInstallVideo ? <em>点击预览</em> : null}
            </button>
            <div className="openagent-video-case__body">
              <strong>{installVideo.title}</strong>
              <p>{installVideo.subtitle}</p>
              <div>
                {(installVideo.tags?.length ? installVideo.tags : ["写代码", "做文件", "查资料"]).map((tag) => <span key={tag}>{tag}</span>)}
              </div>
            </div>
          </div>
        </div> : null}
      </section>
      <VideoPreviewModal preview={previewVideo} onClose={() => setPreviewVideo(null)} />

      <section className="openagent-proof-grid" aria-label="能力概览">
        {[
          ["工程级上下文", "理解项目结构、依赖关系和历史改动，在真实仓库中完成可验证的修改。"],
          ["端到端执行", "从需求拆解到命令运行、结果检查、错误修复，尽量把工作推进到可交付状态。"],
          ["本地优先", "桌面端直连你的工作环境，适合代码、文件、脚本和自动化流程。"],
          ["统一账户", "沿用站内 Codex定制版余额与 Key，调用记录和消耗可在后台查看。"],
        ].map(([title, desc]) => (
          <article key={title}>
            <BadgeCheck size={20} />
            <strong>{title}</strong>
            <p>{desc}</p>
          </article>
        ))}
      </section>

      <section className="tool-step openagent-download-section" id="openagent-downloads">
        <div className="tool-step__head">
          <span>1</span>
          <strong>选择安装包</strong>
          <small>Mac / Windows 全架构覆盖</small>
        </div>
        {error ? <div className="list-state list-state--error"><span>{error}</span><button className="task-button task-button--blue" type="button" onClick={load}>重试</button></div> : null}
        {isLoading ? <LoadingState label="正在加载下载版本…" /> : null}
        <div className="openagent-download-groups">
          <DownloadGroup title="macOS" subtitle="Apple Silicon 与 Intel 芯片" items={macDownloads} />
          <DownloadGroup title="Windows" subtitle="64 位 / 32 位，安装包与免安装包" items={windowsDownloads} />
        </div>
      </section>

      <section className="openagent-setup-grid">
        <article>
          <span>2</span>
          <strong>登录同一个账号</strong>
          <p>安装后使用站内账号登录，Codex定制版会读取已生成的文本 Key 和图片 Key。</p>
        </article>
        <article>
          <span>3</span>
          <strong>充值统一账户余额</strong>
          <p>站内充值成功后余额会自动到账，图片、视频和 Token 共用同一个账户余额。</p>
        </article>
        <article>
          <span>4</span>
          <strong>开始交付任务</strong>
          <p>把需求、仓库和文件交给 Codex定制版，让它规划、编辑、执行并验证结果。</p>
        </article>
      </section>
    </main>
  );
};

function DownloadGroup({ title, subtitle, items }: { title: string; subtitle: string; items: OpenAgentDownload[] }) {
  return (
    <section className="openagent-download-group">
      <div>
        <PackageOpen size={20} />
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </div>
      <div className="openagent-download-list">
        {items.map((item) => (
          <article className="openagent-download-card" key={item.key}>
            <div>
              <strong>{item.label}</strong>
              <span>{item.version ? `v${item.version} · ${formatDownloadSize(item.file_size)}` : "待发布"}</span>
            </div>
            {item.file_url ? (
              <a className="button button--secondary" href={item.file_url} target="_blank" rel="noreferrer">
                <Download size={16} />
                下载
              </a>
            ) : (
              <button className="button button--ghost" type="button" disabled>待发布</button>
            )}
          </article>
        ))}
      </div>
    </section>
  );
}

export const OpenAgentUsagePage = () => {
  const [records, setRecords] = useState<OpenAgentUsageRecord[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const pageSize = 20;

  const load = useCallback(async (targetPage: number) => {
    setIsLoading(true);
    setError("");
    try {
      const result = await opencodeService.getUsage(targetPage, pageSize);
      setRecords(result.items);
      setPage(result.page);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Codex定制版使用记录加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [pageSize]);

  useEffect(() => { void load(1); }, [load]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageTokens = records.reduce((sum, record) => sum + record.tokens, 0);
  const pageCost = records.reduce((sum, record) => sum + record.cost, 0);

  function goPage(nextPage: number) {
    if (nextPage < 1 || nextPage > pageCount || isLoading) return;
    void load(nextPage);
  }

  return (
    <main className="page-surface">
      <header className="page-header">
        <div className="tool-title">
          <span><TableProperties size={22} /></span>
          <div>
            <h1>Codex定制版使用记录</h1>
            <p>查看当前账号下 API 密钥的模型调用和计费记录。</p>
          </div>
        </div>
        <Button variant="secondary" onClick={() => void load(page)} isLoading={isLoading}>
          <RefreshCw size={16} />
          刷新
        </Button>
      </header>

      <section className="ledger-summary">
        <article>
          <span>记录总数</span>
          <strong>{isLoading ? "--" : total.toLocaleString()}</strong>
        </article>
        <article>
          <span>当前页 Token</span>
          <strong>{pageTokens.toLocaleString()}</strong>
        </article>
        <article>
          <span>当前页费用</span>
          <strong>{formatUsageCost(pageCost)}</strong>
        </article>
      </section>

      {error ? <div className="list-state list-state--error"><span>{error}</span><button className="task-button task-button--blue" type="button" onClick={() => void load(page)}>重试</button></div> : null}

      <section className="usage-table-card">
        {isLoading ? <LoadingState label="正在加载使用记录…" /> : null}
        {!isLoading && records.length ? (
          <div className="usage-table-wrap">
            <table className="usage-table">
              <thead>
                <tr>
                  <th>API 密钥</th>
                  <th>模型</th>
                  <th>IP</th>
                  <th>计费模式</th>
                  <th>Token</th>
                  <th>费用</th>
                  <th>首 Token</th>
                  <th>耗时</th>
                  <th>时间</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <tr key={record.id}>
                    <td>{record.api_key_name || "--"}</td>
                    <td>{record.model || "--"}</td>
                    <td>{record.ip_address || "--"}</td>
                    <td>{record.billing_mode || "--"}</td>
                    <td>{record.tokens.toLocaleString()}</td>
                    <td>{formatUsageCost(record.cost)}</td>
                    <td>{formatUsageDuration(record.first_token_ms)}</td>
                    <td>{formatUsageDuration(record.duration_ms)}</td>
                    <td>{formatDateTime(record.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        {!isLoading && !records.length && !error ? <div className="empty-state"><TableProperties size={34} /><h3>暂无使用记录</h3><p>产生 Codex定制版调用后会显示在这里。</p></div> : null}
      </section>

      <div className="usage-pagination">
        <Button variant="secondary" disabled={page <= 1 || isLoading} onClick={() => goPage(page - 1)}>上一页</Button>
        <span>第 {page} / {pageCount} 页</span>
        <Button variant="secondary" disabled={page >= pageCount || isLoading} onClick={() => goPage(page + 1)}>下一页</Button>
      </div>
    </main>
  );
};

export const LicensePage = () => (
  <UtilityPage title="版权服务" intro="授权证明和商业使用记录需要后端接口；当前只展示入口状态。" icon={BadgeCheck} />
);

export const TeamPage = () => (
  <UtilityPage title="团队版" intro="团队成员和额度管理需要后端接口；当前只展示入口状态。" icon={BookOpen} />
);
