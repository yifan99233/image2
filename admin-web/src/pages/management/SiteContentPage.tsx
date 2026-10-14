import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, ClipboardCheck, ContactRound, Image as ImageIcon, Images, KeyRound, RefreshCcw, Rocket, Trash2 } from "lucide-react";
import { createMaterialUploadToken, getSiteContentConfig, updateCurrentSiteContentConfig } from "../../services/adminApi";
import type { MaterialAssetType, SiteConfig } from "../../types";
import { DEFAULT_SITE_ICON_URL, publishSiteIcon } from "../../lib/siteBranding";

function useAutoDismissNotice(notice: string, setNotice: (value: string) => void) {
  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice, setNotice]);
}

function PageChrome({ title, description, action, children }: { title: string; description: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="page-stack">
      <div className="page-heading">
        <div>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
const defaultHomepageCaseCarousels: SiteConfig["homepage_case_carousels"] = [
  [
    { title: "电商套图", subtitle: "主图、场景图、详情页素材统一生成", image_url: "", file_url: "", link_url: "", tone: "blue" },
    { title: "产品效果图", subtitle: "上传商品图后快速延展应用场景", image_url: "", file_url: "", link_url: "", tone: "orange" },
  ],
  [
    { title: "图片二次优化", subtitle: "改背景、换氛围、补细节", image_url: "", file_url: "", link_url: "", tone: "cyan" },
    { title: "案例展示", subtitle: "生成前后效果直接对比", image_url: "", file_url: "", link_url: "", tone: "green" },
  ],
];

const defaultLeadCaseMaterials: SiteConfig["lead_case_materials"] = [
  { title: "家具", subtitle: "家居门店获客案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "blue" },
  { title: "大健康", subtitle: "养生门店转化案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "green" },
  { title: "珠宝", subtitle: "高客单私域案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "orange" },
  { title: "考公", subtitle: "课程线索转化案例", file_url: "", cover_url: "", link_url: "", tags: [], tone: "cyan" },
];

const defaultHomepageBatchBanners: SiteConfig["homepage_batch_banners"] = [];

const defaultOpenAgentInstallVideo: SiteConfig["opencode_install_video"] = {
  title: "从需求到交付的自动化流程",
  subtitle: "演示 Codex定制版如何读取需求、修改文件、运行验证并输出结果。",
  file_url: "",
  cover_url: "",
  link_url: "",
  tags: ["写代码", "做文件", "查资料"],
  tone: "blue",
};

const defaultSystemAnnouncement: SiteConfig["system_announcement"] = {
  is_enabled: false,
  title: "",
  content: "",
  image_url: "",
};

const normalizeHomepageCaseCarousels = (groups?: SiteConfig["homepage_case_carousels"]): SiteConfig["homepage_case_carousels"] => {
  if (!Array.isArray(groups)) return defaultHomepageCaseCarousels;
  const normalized = groups.slice(0, 2).map((group, index) => (Array.isArray(group) && group.length ? group : defaultHomepageCaseCarousels[index]));
  while (normalized.length < 2) normalized.push(defaultHomepageCaseCarousels[normalized.length]);
  return normalized;
};

const normalizeContentMaterials = (items?: SiteConfig["lead_case_materials"]): SiteConfig["lead_case_materials"] => {
  if (!Array.isArray(items) || !items.length) return defaultLeadCaseMaterials;
  const normalized = items.slice(0, 4).map((item, index) => ({
    ...defaultLeadCaseMaterials[index % defaultLeadCaseMaterials.length],
    ...item,
    tags: Array.isArray(item.tags) ? item.tags : [],
  }));
  return normalized.length ? normalized : defaultLeadCaseMaterials;
};

const normalizeHomepageBatchBanners = (items?: SiteConfig["homepage_batch_banners"]): SiteConfig["homepage_batch_banners"] => {
  if (!Array.isArray(items)) return defaultHomepageBatchBanners;
  return items
    .slice(0, 8)
    .map((item, index) => ({
      title: String(item?.title || `批量创作素材 ${index + 1}`).trim(),
      subtitle: String(item?.subtitle || "").trim(),
      file_url: String(item?.file_url || item?.cover_url || "").trim(),
      cover_url: String(item?.cover_url || item?.file_url || "").trim(),
      link_url: String(item?.link_url || "").trim(),
      tags: Array.isArray(item?.tags) ? item.tags : [],
      tone: item?.tone || "blue",
    }))
    .filter((item) => item.file_url || item.cover_url);
};

const normalizeOpenAgentInstallVideo = (item?: SiteConfig["opencode_install_video"]): SiteConfig["opencode_install_video"] => ({
  ...defaultOpenAgentInstallVideo,
  ...item,
  tags: Array.isArray(item?.tags) ? item.tags : defaultOpenAgentInstallVideo.tags,
});

const siteModuleOptions = [
  { key: "dashboard", label: "首页" },
  { key: "gallery", label: "创作广场" },
  { key: "image_edit", label: "图生图" },
  { key: "text_to_image", label: "文生图" },
  { key: "text_to_video", label: "文生视频" },
  { key: "image_to_video", label: "图生视频" },
  { key: "batch_generate", label: "批量生图" },
  { key: "batch_edit", label: "批量改图" },
  { key: "works", label: "我的作品" },
  { key: "leads", label: "获客模块" },
  { key: "opencode", label: "Codex定制版" },
  { key: "feedback", label: "用户反馈" },
  { key: "support", label: "联系客服" },
  { key: "signin", label: "签到积分" },
  { key: "invite", label: "邀请返利" },
  { key: "recharge", label: "充值积分" },
] as const;

const allSiteModules = siteModuleOptions.map((module) => module.key);

const createBlankSiteConfig = (patch: Partial<SiteConfig> = {}): SiteConfig => ({
  site_key: "subsite",
  site_name: "新子站点",
  site_icon_url: DEFAULT_SITE_ICON_URL,
  frontend_url: "",
  admin_url: "",
  is_default: false,
  is_enabled: true,
  enabled_modules: allSiteModules,
  support_qq: "",
  support_wechat: "",
  support_wechat_qrcode_url: "",
  support_email: "",
  homepage_case_carousels: defaultHomepageCaseCarousels,
  homepage_batch_banners: defaultHomepageBatchBanners,
  lead_case_materials: defaultLeadCaseMaterials,
  opencode_install_video: defaultOpenAgentInstallVideo,
  system_announcement: defaultSystemAnnouncement,
  updated_at: null,
  ...patch,
});

export function SiteContentPage() {
  const [form, setForm] = useState<SiteConfig>(createBlankSiteConfig({ id: 1, site_key: "main", site_name: "艺源", is_default: true }));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadState, setUploadState] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  async function load() {
    setIsLoading(true);
    setError("");
    try {
      const site = await getSiteContentConfig();
      const nextSite = {
        ...createBlankSiteConfig(),
        ...site,
        homepage_case_carousels: normalizeHomepageCaseCarousels(site.homepage_case_carousels),
        homepage_batch_banners: normalizeHomepageBatchBanners(site.homepage_batch_banners),
        lead_case_materials: normalizeContentMaterials(site.lead_case_materials),
        opencode_install_video: normalizeOpenAgentInstallVideo(site.opencode_install_video),
      };
      setForm(nextSite);
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材修改接口不可用");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function uploadFiles(files: File[], assetType: MaterialAssetType) {
    setNotice("");
    setError("");
    setUploadState(`正在上传 ${files.length} 个文件到七牛云...`);
    try {
      const uploaded: string[] = [];
      for (const file of files) {
        const uploadToken = await createMaterialUploadToken(file.name, assetType);
        const formData = new FormData();
        formData.append("token", uploadToken.token);
        formData.append("key", uploadToken.key);
        formData.append("file", file);
        const response = await fetch(uploadToken.upload_url, { method: "POST", body: formData });
        if (!response.ok) {
          const text = await response.text().catch(() => "");
          throw new Error(text || `七牛上传失败（${response.status}）`);
        }
        uploaded.push(uploadToken.public_url);
      }
      setNotice(`已上传 ${uploaded.length} 个文件，URL 已回填`);
      return uploaded;
    } catch (err) {
      setError(err instanceof Error ? err.message : "七牛上传失败");
      return [];
    } finally {
      setUploadState("");
    }
  }

  async function uploadQrcode(files: File[]) {
    const [url] = await uploadFiles(files.slice(0, 1), "image");
    if (url) setForm((current) => ({ ...current, support_wechat_qrcode_url: url }));
  }

  async function uploadSiteIcon(files: File[]) {
    const [url] = await uploadFiles(files.slice(0, 1), "image");
    if (url) setForm((current) => ({ ...current, site_icon_url: url }));
  }

  async function uploadHomepageImages(groupIndex: number, itemIndex: number, files: File[]) {
    const urls = await uploadFiles(files, "image");
    if (!urls.length) return;
    setForm((current) => {
      const groups = normalizeHomepageCaseCarousels(current.homepage_case_carousels).map((group) => group.map((item) => ({ ...item })));
      const group = groups[groupIndex] ?? [];
      urls.slice(0, 4 - itemIndex).forEach((url, offset) => {
        const index = itemIndex + offset;
        group[index] = { ...(group[index] ?? { title: `轮播 ${index + 1}`, subtitle: "", image_url: "", file_url: "", link_url: "", tone: "blue" }), image_url: url };
      });
      groups[groupIndex] = group.slice(0, 4);
      return { ...current, homepage_case_carousels: groups };
    });
  }

  async function uploadHomepageVideos(groupIndex: number, itemIndex: number, files: File[]) {
    const [url] = await uploadFiles(files.slice(0, 1), "video");
    if (url) updateHomepageItem(groupIndex, itemIndex, { file_url: url });
  }

  async function uploadHomepageBatchBanners(files: File[]) {
    const urls = await uploadFiles(files, "image");
    if (!urls.length) return;
    setForm((current) => {
      const existing = normalizeHomepageBatchBanners(current.homepage_batch_banners);
      const nextItems = urls.map((url, index) => ({
        title: `批量创作素材 ${existing.length + index + 1}`,
        subtitle: "",
        file_url: url,
        cover_url: url,
        link_url: "",
        tags: [],
        tone: "blue" as const,
      }));
      return { ...current, homepage_batch_banners: [...existing, ...nextItems].slice(0, 8) };
    });
  }

  async function uploadLeadCaseAssets(index: number, field: "file_url" | "cover_url", files: File[], assetType: MaterialAssetType) {
    const urls = await uploadFiles(files, assetType);
    if (!urls.length) return;
    setForm((current) => {
      const items = normalizeContentMaterials(current.lead_case_materials).map((item) => ({ ...item }));
      urls.slice(0, items.length - index).forEach((url, offset) => {
        items[index + offset] = { ...items[index + offset], [field]: url };
      });
      return { ...current, lead_case_materials: items };
    });
  }

  async function uploadOpenAgentAsset(field: "file_url" | "cover_url", files: File[], assetType: MaterialAssetType) {
    const [url] = await uploadFiles(files.slice(0, 1), assetType);
    if (url) updateOpenAgentVideo({ [field]: url });
  }

  function updateHomepageItem(groupIndex: number, itemIndex: number, patch: Partial<SiteConfig["homepage_case_carousels"][number][number]>) {
    setForm((current) => {
      const groups = normalizeHomepageCaseCarousels(current.homepage_case_carousels).map((group) => group.map((item) => ({ ...item })));
      groups[groupIndex][itemIndex] = { ...groups[groupIndex][itemIndex], ...patch };
      return { ...current, homepage_case_carousels: groups };
    });
  }

  function updateLeadCase(index: number, patch: Partial<SiteConfig["lead_case_materials"][number]>) {
    setForm((current) => {
      const items = normalizeContentMaterials(current.lead_case_materials).map((item) => ({ ...item }));
      items[index] = { ...items[index], ...patch };
      return { ...current, lead_case_materials: items };
    });
  }

  function removeHomepageBatchBanner(index: number) {
    setForm((current) => ({
      ...current,
      homepage_batch_banners: normalizeHomepageBatchBanners(current.homepage_batch_banners).filter((_, itemIndex) => itemIndex !== index),
    }));
  }

  function updateOpenAgentVideo(patch: Partial<SiteConfig["opencode_install_video"]>) {
    setForm((current) => ({ ...current, opencode_install_video: { ...normalizeOpenAgentInstallVideo(current.opencode_install_video), ...patch } }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError("");
    setNotice("");
    const nextForm: SiteConfig = {
      ...form,
      site_icon_url: form.site_icon_url.trim() || DEFAULT_SITE_ICON_URL,
      support_qq: form.support_qq.trim(),
      support_wechat: form.support_wechat.trim(),
      support_wechat_qrcode_url: form.support_wechat_qrcode_url.trim(),
      support_email: form.support_email.trim(),
      homepage_case_carousels: normalizeHomepageCaseCarousels(form.homepage_case_carousels),
      homepage_batch_banners: normalizeHomepageBatchBanners(form.homepage_batch_banners),
      lead_case_materials: normalizeContentMaterials(form.lead_case_materials),
      opencode_install_video: normalizeOpenAgentInstallVideo(form.opencode_install_video),
    };
    try {
      const saved = await updateCurrentSiteContentConfig(nextForm);
      setForm((current) => ({ ...current, site_icon_url: saved.site_icon_url }));
      publishSiteIcon(saved.site_icon_url);
      setNotice(`已保存 ${saved.site_name} 的素材修改配置`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材修改保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="素材修改" description="配置当前后台的客服信息、首页轮播、AI获客案例和 Codex 下载安装页素材。">
      <section className="panel">
        {isLoading ? <div className="inline-state">正在读取素材修改配置...</div> : null}
        {error ? <section className="inline-state error"><AlertTriangle size={17} /><span>{error}</span><button className="secondary-button compact" type="button" onClick={() => void load()}><RefreshCcw size={14} />重试</button></section> : null}
        {notice ? <div className="inline-state success"><CheckCircle2 size={17} /><span>{notice}</span></div> : null}
        <form className="settings-form" onSubmit={submit}>
          <div className="detail-title"><ImageIcon size={20} /><h3>网站图标</h3></div>
          <div className="site-icon-editor">
            <div className="site-icon-preview" aria-label="当前网站图标预览">
              <img src={form.site_icon_url || DEFAULT_SITE_ICON_URL} alt="" />
            </div>
            <div className="site-icon-editor__controls">
              <label className="field">
                上传新图标
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon"
                  onChange={(event) => {
                    const files = Array.from(event.target.files ?? []);
                    if (files.length) void uploadSiteIcon(files);
                    event.currentTarget.value = "";
                  }}
                />
                <small>{uploadState || "建议使用正方形 PNG、WebP 或 SVG；上传后保存才会正式生效。"}</small>
              </label>
              <div className="inline-actions">
                <button
                  className="secondary-button compact"
                  type="button"
                  disabled={form.site_icon_url === DEFAULT_SITE_ICON_URL}
                  onClick={() => setForm((current) => ({ ...current, site_icon_url: DEFAULT_SITE_ICON_URL }))}
                >
                  <RefreshCcw size={14} />
                  恢复默认图标
                </button>
              </div>
            </div>
          </div>

          <div className="form-grid">
            <label className="field">客服邮箱<input value={form.support_email} onChange={(event) => setForm((current) => ({ ...current, support_email: event.target.value }))} placeholder="support@example.com" /></label>
          </div>

          <div className="detail-title"><KeyRound size={20} /><h3>客服联系方式</h3></div>
          <div className="form-grid">
            <label className="field">QQ 客服<input value={form.support_qq} onChange={(event) => setForm((current) => ({ ...current, support_qq: event.target.value }))} /></label>
            <label className="field">微信客服<input value={form.support_wechat} onChange={(event) => setForm((current) => ({ ...current, support_wechat: event.target.value }))} /></label>
            <label className="field wide">微信客服二维码
              <input type="file" accept="image/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadQrcode(files); event.currentTarget.value = ""; }} />
              <small>{uploadState || "选择二维码图片后会直接上传到七牛云，并自动回填 CDN URL。"}</small>
            </label>
            {form.support_wechat_qrcode_url ? (
              <label className="field wide">当前二维码 URL<input value={form.support_wechat_qrcode_url} readOnly /></label>
            ) : null}
          </div>

          <div className="detail-title"><ImageIcon size={20} /><h3>首页轮播图素材</h3></div>
          <div className="homepage-carousel-config">
            {normalizeHomepageCaseCarousels(form.homepage_case_carousels).map((group, groupIndex) => (
              <section className="homepage-carousel-group" key={groupIndex}>
                <div className="homepage-carousel-group__head"><strong>{groupIndex === 0 ? "上方轮播" : "下方轮播"}</strong></div>
                {group.map((item, itemIndex) => (
                  <article className="homepage-carousel-item" key={`${groupIndex}-${itemIndex}`}>
                    <div className="homepage-carousel-item__head"><span>{String(groupIndex * 2 + itemIndex + 1).padStart(2, "0")}</span></div>
                    <div className="form-grid">
                      <label className="field">标题<input value={item.title} onChange={(event) => updateHomepageItem(groupIndex, itemIndex, { title: event.target.value })} /></label>
                      <label className="field">色调<select value={item.tone || "blue"} onChange={(event) => updateHomepageItem(groupIndex, itemIndex, { tone: event.target.value as NonNullable<typeof item.tone> })}><option value="blue">蓝色</option><option value="orange">橙色</option><option value="cyan">青绿色</option><option value="green">绿色</option></select></label>
                      <label className="field wide">说明<input value={item.subtitle} onChange={(event) => updateHomepageItem(groupIndex, itemIndex, { subtitle: event.target.value })} /></label>
                      <label className="field wide">封面图上传
                        <input multiple type="file" accept="image/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadHomepageImages(groupIndex, itemIndex, files); event.currentTarget.value = ""; }} />
                        <small>可一次上传多张，会从当前序号开始依次填入本轮播后续项。</small>
                      </label>
                      {item.image_url ? <label className="field wide">当前封面图 URL<input value={item.image_url} readOnly /></label> : null}
                      <label className="field wide">视频上传
                        <input type="file" accept="video/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadHomepageVideos(groupIndex, itemIndex, files); event.currentTarget.value = ""; }} />
                        <small>上传视频后，前台首页该轮播项会优先展示可播放视频；封面图会作为视频 poster。</small>
                      </label>
                      {item.file_url ? <label className="field wide">当前视频 URL<input value={item.file_url} readOnly /></label> : null}
                      <label className="field wide">跳转 URL<input value={item.link_url || ""} onChange={(event) => updateHomepageItem(groupIndex, itemIndex, { link_url: event.target.value })} /></label>
                    </div>
                  </article>
                ))}
              </section>
            ))}
          </div>

          <div className="detail-title"><Images size={20} /><h3>首页批量创作轮播素材</h3></div>
          <section className="homepage-carousel-group">
            <div className="form-grid">
              <label className="field wide">图片上传
                <input multiple type="file" accept="image/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadHomepageBatchBanners(files); event.currentTarget.value = ""; }} />
                <small>可一次上传多张，最多保留 8 张；前台“批量创作加速”卡片会按顺序轮播展示。</small>
              </label>
            </div>
            <div className="homepage-carousel-config">
              {normalizeHomepageBatchBanners(form.homepage_batch_banners).length ? normalizeHomepageBatchBanners(form.homepage_batch_banners).map((item, index) => (
                <article className="homepage-carousel-item" key={`${item.file_url}-${index}`}>
                  <div className="homepage-carousel-item__head">
                    <span>{String(index + 1).padStart(2, "0")}</span>
                    <button className="secondary-button compact danger" type="button" onClick={() => removeHomepageBatchBanner(index)}><Trash2 size={14} />移除</button>
                  </div>
                  <div className="form-grid">
                    <label className="field wide">当前图片 URL<input value={item.file_url || item.cover_url || ""} readOnly /></label>
                  </div>
                </article>
              )) : <div className="inline-state">暂未上传素材，前台会显示默认占位。</div>}
            </div>
          </section>

          <div className="detail-title"><ContactRound size={20} /><h3>AI 高效精准获客案例素材</h3></div>
          <div className="homepage-carousel-config">
            {normalizeContentMaterials(form.lead_case_materials).map((item, index) => (
              <article className="homepage-carousel-item" key={index}>
                <div className="homepage-carousel-item__head"><span>{String(index + 1).padStart(2, "0")}</span></div>
                <div className="form-grid">
                  <label className="field">标题<input value={item.title} onChange={(event) => updateLeadCase(index, { title: event.target.value })} /></label>
                  <label className="field">色调<select value={item.tone || "blue"} onChange={(event) => updateLeadCase(index, { tone: event.target.value as NonNullable<typeof item.tone> })}><option value="blue">蓝色</option><option value="orange">橙色</option><option value="cyan">青绿色</option><option value="green">绿色</option></select></label>
                  <label className="field wide">说明<input value={item.subtitle} onChange={(event) => updateLeadCase(index, { subtitle: event.target.value })} /></label>
                  <label className="field wide">视频上传
                    <input multiple type="file" accept="video/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadLeadCaseAssets(index, "file_url", files, "video"); event.currentTarget.value = ""; }} />
                    <small>可一次上传多个视频，会从当前案例开始依次填入后续案例。</small>
                  </label>
                  {item.file_url ? <label className="field wide">当前视频 URL<input value={item.file_url} readOnly /></label> : null}
                  <label className="field wide">封面上传
                    <input multiple type="file" accept="image/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadLeadCaseAssets(index, "cover_url", files, "image"); event.currentTarget.value = ""; }} />
                    <small>可一次上传多个封面，会从当前案例开始依次填入后续案例。</small>
                  </label>
                  {item.cover_url ? <label className="field wide">当前封面 URL<input value={item.cover_url} readOnly /></label> : null}
                </div>
              </article>
            ))}
          </div>

          <div className="detail-title"><Rocket size={20} /><h3>Codex 下载安装页右侧素材</h3></div>
          <div className="form-grid">
            <label className="field">标题<input value={form.opencode_install_video.title} onChange={(event) => updateOpenAgentVideo({ title: event.target.value })} /></label>
            <label className="field">标签<input value={(form.opencode_install_video.tags || []).join("，")} onChange={(event) => updateOpenAgentVideo({ tags: event.target.value.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean) })} /></label>
            <label className="field wide">说明<input value={form.opencode_install_video.subtitle} onChange={(event) => updateOpenAgentVideo({ subtitle: event.target.value })} /></label>
            <label className="field wide">视频上传
              <input type="file" accept="video/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadOpenAgentAsset("file_url", files, "video"); event.currentTarget.value = ""; }} />
              <small>上传后自动回填 Codex 下载安装页右侧视频 URL。</small>
            </label>
            {form.opencode_install_video.file_url ? <label className="field wide">当前视频 URL<input value={form.opencode_install_video.file_url} readOnly /></label> : null}
            <label className="field wide">封面上传
              <input type="file" accept="image/*" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length) void uploadOpenAgentAsset("cover_url", files, "image"); event.currentTarget.value = ""; }} />
              <small>上传后自动回填视频封面 URL。</small>
            </label>
            {form.opencode_install_video.cover_url ? <label className="field wide">当前封面 URL<input value={form.opencode_install_video.cover_url} readOnly /></label> : null}
          </div>

          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={() => void load()} disabled={isLoading || isSubmitting}>重新读取</button>
            <button className="primary-button" disabled={isLoading || isSubmitting}>{isSubmitting ? "保存中..." : "保存素材修改"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}
