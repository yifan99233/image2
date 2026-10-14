import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ClipboardCheck,
  ContactRound,
  CreditCard,
  Eye,
  FlaskConical,
  Gift,
  Globe2,
  Image as ImageIcon,
  KeyRound,
  MessageSquareText,
  PackageOpen,
  Pencil,
  Plus,
  RefreshCcw,
  Route,
  RotateCcw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Star,
  UserCog,
  WalletCards,
  X,
} from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useMemo, useState } from "react";
import { formatCurrency, formatDateTime } from "../lib/format";
import { generatedSiteUrls } from "../config/deployment";
import {
  createAdminAccount,
  createSiteConfig,
  createModelPricesBatch,
  getAgentConfig,
  getAgentGroups,
  getZPayConfig,
  createImageSpec,
  createMaterialUploadToken,
  getAdminAccounts,
  getAuditLogs,
  getCreditLedgers,
  getFeedbacks,
  getImageTasks,
  getImageSpecs,
  getInviteRewardConfig,
  getLeadTrialApplications,
  getMaterials,
  getModelPrices,
  getModels,
  getRechargeOrders,
  getRechargePlans,
  getSigninRecords,
  getSigninRewardConfig,
  getSiteConfig,
  getSiteConfigs,
  getUserLeadModule,
  markLedger,
  refundTask,
  retryTask,
  runModelTest,
  saveRechargePlan,
  saveModel,
  saveInviteRewardConfig,
  saveAgentConfig,
  saveMaterial,
  saveSiteConfig,
  updateSiteConfig,
  saveUserLeadModule,
  saveZPayConfig,
  toggleTaskGallery,
  toggleModel,
  toggleMaterial,
  toggleModelPrice,
  toggleRechargePlan,
  updateAdminAccount,
  updateAdminAccountStatus,
  updateFeedback,
  updateImageSpec,
  updateLeadTrialApplication,
  updateModelVisibility,
  updateModelSpecs,
  updateSigninRewardConfig,
} from "../services/adminApi";
import type { MaterialFilters, ModelFilters, RechargeOrderFilters, RechargePlanFilters } from "../services/adminApi";
import { Dialog, type DialogState } from "./management/ManagementDialogs";
import type { AdminAccountInput, AdminImageModel, AdminImageModelInput, AdminRole, AdminUser, AgentConfig, AgentConfigInput, AgentGroup, AuditLog, CreditLedger, ImageSpec, ImageSpecs, ImageTask, InviteRewardConfig, LeadTrialApplication, LeadTrialApplicationStatus, ManagedUser, MaterialAsset, MaterialAssetInput, MaterialAssetType, ModelPrice, RechargeOrder, RechargePlan, RechargeOrderStatus, SigninRecord, SigninRewardConfig, SiteConfig, UserFeedback, UserFeedbackStatus, UserLeadModule, UserLeadModuleInput, ZPayConfig, ZPayConfigInput } from "../types";

const defaultPageSize = 20;
const pageSizeOptions = [10, 20, 50, 100];

type PaginationState = {
  page: number;
  pageSize: number;
  total: number;
};

const initialPagination: PaginationState = { page: 1, pageSize: defaultPageSize, total: 0 };

function useAutoDismissNotice(notice: string, setNotice: (value: string) => void) {
  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice, setNotice]);
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
  site_icon_url: "/image2ai-icon.svg",
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
  template_site_id: null,
  updated_at: null,
  ...patch,
});

const adminRoleLabel: Record<AdminRole, string> = {
  super_admin: "超级管理员",
  operator: "运营管理员",
  finance: "财务管理员",
  model_admin: "模型管理员",
};

const feedbackStatusLabel: Record<UserFeedbackStatus, string> = {
  pending: "待处理",
  processing: "处理中",
  resolved: "已解决",
  closed: "已关闭",
};

const feedbackStatusOptions: Array<{ value: "all" | UserFeedbackStatus; label: string }> = [
  { value: "all", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "processing", label: "处理中" },
  { value: "resolved", label: "已解决" },
  { value: "closed", label: "已关闭" },
];

const leadApplicationStatusLabel: Record<LeadTrialApplicationStatus, string> = {
  pending: "待处理",
  processing: "处理中",
  approved: "已开通",
  rejected: "暂不适配",
};

const leadApplicationStatusOptions: Array<{ value: "all" | LeadTrialApplicationStatus; label: string }> = [
  { value: "all", label: "全部状态" },
  { value: "pending", label: "待处理" },
  { value: "processing", label: "处理中" },
  { value: "approved", label: "已开通" },
  { value: "rejected", label: "暂不适配" },
];

const leadApplicationStatusTone: Record<LeadTrialApplicationStatus, "paid" | "pending" | "failed"> = {
  pending: "pending",
  processing: "pending",
  approved: "paid",
  rejected: "failed",
};

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

function Toolbar({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <div className="toolbar">
      <label className="search-field">
        <Search size={16} />
        <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      </label>
      <button className="secondary-button compact" type="button">
        <SlidersHorizontal size={15} />
        筛选
      </button>
    </div>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="filter-select">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  );
}

function StatusPill({ active }: { active: boolean }) {
  return <span className={`status-pill ${active ? "paid" : "failed"}`}>{active ? "启用" : "停用"}</span>;
}

function LoadState({ error, empty, onRetry }: { error: string; empty: boolean; onRetry: () => void }) {
  if (error) {
    return (
      <section className="inline-state error">
        <AlertTriangle size={17} />
        <span>{error}</span>
        <button className="secondary-button compact" onClick={onRetry}><RefreshCcw size={14} />重试</button>
      </section>
    );
  }
  if (empty) {
    return (
      <section className="inline-state">
        <ClipboardCheck size={17} />
        <span>暂无真实数据。当前页面只展示接口返回内容，不使用本地演示数据。</span>
      </section>
    );
  }
  return null;
}

function Pagination({
  pagination,
  onChange,
}: {
  pagination: PaginationState;
  onChange: (updater: (current: PaginationState) => PaginationState) => void;
}) {
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize));
  const start = pagination.total === 0 ? 0 : (pagination.page - 1) * pagination.pageSize + 1;
  const end = Math.min(pagination.total, pagination.page * pagination.pageSize);
  const changePage = (page: number) => onChange((current) => ({ ...current, page }));
  const changePageSize = (pageSize: number) => onChange((current) => ({ ...current, page: 1, pageSize }));

  return (
    <div className="pagination-bar">
      <span>
        共 {pagination.total} 条，当前 {start}-{end}
      </span>
      <div>
        <label className="page-size-select">
          每页
          <select value={pagination.pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>
            {pageSizeOptions.map((size) => <option key={size} value={size}>{size} 条</option>)}
          </select>
        </label>
        <button className="secondary-button compact" disabled={pagination.page <= 1} onClick={() => changePage(pagination.page - 1)}>上一页</button>
        <strong>{pagination.page} / {totalPages}</strong>
        <button className="secondary-button compact" disabled={pagination.page >= totalPages} onClick={() => changePage(pagination.page + 1)}>下一页</button>
      </div>
    </div>
  );
}

function useResetPageOnQuery(query: string, setPagination: (updater: (current: PaginationState) => PaginationState) => void) {
  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [query, setPagination]);
}

export function SiteConfigPage() {
  const [sites, setSites] = useState<SiteConfig[]>([]);
  const [selectedId, setSelectedId] = useState<number | "new">(1);
  const [form, setForm] = useState<SiteConfig>(createBlankSiteConfig({ id: 1, site_key: "main", site_name: "艺源", is_default: true }));
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  const selectedSite = selectedId === "new" ? null : sites.find((site) => site.id === selectedId) ?? null;

  async function load(preferredSelectedId: number | "new" = selectedId) {
    setIsLoading(true);
    setError("");
    try {
      const result = await getSiteConfigs();
      const nextSites = result.items.map((site) => ({
        ...createBlankSiteConfig(),
        ...site,
        homepage_case_carousels: normalizeHomepageCaseCarousels(site.homepage_case_carousels),
        homepage_batch_banners: normalizeHomepageBatchBanners(site.homepage_batch_banners),
      }));
      setSites(nextSites);
      const nextSelected = preferredSelectedId === "new" ? nextSites.find((site) => site.is_default) ?? nextSites[0] : nextSites.find((site) => site.id === preferredSelectedId) ?? nextSites.find((site) => site.is_default) ?? nextSites[0];
      if (nextSelected) {
        setSelectedId(nextSelected.id ?? 1);
        setForm({
          ...nextSelected,
          homepage_case_carousels: normalizeHomepageCaseCarousels(nextSelected.homepage_case_carousels),
          homepage_batch_banners: normalizeHomepageBatchBanners(nextSelected.homepage_batch_banners),
        });
      } else {
        const defaultConfig = await getSiteConfig();
        setSites([defaultConfig]);
        setSelectedId(defaultConfig.id ?? 1);
        setForm({
          ...createBlankSiteConfig(),
          ...defaultConfig,
          homepage_case_carousels: normalizeHomepageCaseCarousels(defaultConfig.homepage_case_carousels),
          homepage_batch_banners: normalizeHomepageBatchBanners(defaultConfig.homepage_batch_banners),
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "站点配置接口不可用");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function selectSite(site: SiteConfig) {
    setSelectedId(site.id ?? 1);
    setNotice("");
    setError("");
    setForm({
      ...createBlankSiteConfig(),
      ...site,
      homepage_case_carousels: normalizeHomepageCaseCarousels(site.homepage_case_carousels),
      homepage_batch_banners: normalizeHomepageBatchBanners(site.homepage_batch_banners),
    });
  }

  function createSiteDraft() {
    const nextId = Math.max(1, ...sites.map((site) => site.id ?? 1)) + 1;
    const siteKey = `site-${nextId}`;
    const template = sites.find((site) => site.site_key === "art") ?? sites.find((site) => site.is_default) ?? sites[0];
    setSelectedId("new");
    setNotice("");
    setError("");
    setForm(createBlankSiteConfig({
      ...template,
      id: undefined,
      site_key: siteKey,
      site_name: `子站点 ${nextId}`,
      is_default: false,
      template_site_id: template?.id ?? null,
      ...generatedSiteUrls(siteKey),
    }));
  }

  function selectSiteTemplate(templateId: number) {
    const template = sites.find((site) => site.id === templateId);
    if (!template) return;
    setForm((current) => createBlankSiteConfig({
      ...template,
      id: undefined,
      site_key: current.site_key,
      site_name: current.site_name,
      frontend_url: current.frontend_url,
      admin_url: current.admin_url,
      is_default: false,
      is_enabled: current.is_enabled,
      template_site_id: templateId,
    }));
  }

  function updateSiteKey(value: string) {
    setForm((current) => {
      if (selectedId !== "new") return { ...current, site_key: value };
      return { ...current, site_key: value, ...generatedSiteUrls(value) };
    });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const nextForm = {
      ...form,
      site_key: form.site_key.trim(),
      site_name: form.site_name.trim(),
      frontend_url: form.frontend_url.trim(),
      admin_url: form.admin_url.trim(),
      enabled_modules: form.enabled_modules.filter((module) => allSiteModules.includes(module as (typeof allSiteModules)[number])),
    };
    if (!nextForm.site_name) {
      setError("网站名称不能为空");
      return;
    }
    if (!nextForm.site_key) {
      setError("站点标识不能为空");
      return;
    }
    if (nextForm.system_announcement.is_enabled && !nextForm.system_announcement.content.trim()) {
      setError("启用系统公告前，请填写公告内容。");
      return;
    }
    if (!nextForm.is_default && sites.length === 1 && selectedId !== "new") {
      setError("默认总站点不能取消默认，请先设置另一个站点为默认。");
      return;
    }
    setError("");
    setNotice("");
    setIsSubmitting(true);
    try {
      const saved = selectedId === "new"
        ? await createSiteConfig(nextForm)
        : nextForm.id === 1
          ? await saveSiteConfig(nextForm)
          : await updateSiteConfig(nextForm.id ?? Number(selectedId), nextForm);
      setForm({
        ...saved,
        homepage_case_carousels: normalizeHomepageCaseCarousels(saved.homepage_case_carousels),
        homepage_batch_banners: normalizeHomepageBatchBanners(saved.homepage_batch_banners),
      });
      setSelectedId(saved.id ?? 1);
      setNotice(selectedId === "new"
        ? "子站已创建，并已复制模板站的模型、价格、规格、充值和基础配置。"
        : "站点配置已保存，前台刷新后读取最新配置。");
      await load(saved.id ?? 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "站点配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  function toggleSiteModule(moduleKey: string) {
    setForm((current) => {
      const modules = new Set(current.enabled_modules);
      if (modules.has(moduleKey)) modules.delete(moduleKey);
      else modules.add(moduleKey);
      if (!modules.size) modules.add("dashboard");
      return { ...current, enabled_modules: Array.from(modules) };
    });
  }

  return (
    <PageChrome title="总后台" description="仅系统超级管理员可见。用于开通子站点、配置前后台地址和模块开关。当前总站点保留为默认站点。">
      <section className="panel site-config-layout">
        {isLoading ? <div className="inline-state">正在读取站点配置...</div> : null}
        {error ? (
          <section className="inline-state error">
            <AlertTriangle size={17} />
            <span>{error}</span>
            <button className="secondary-button compact" type="button" onClick={() => void load()}><RefreshCcw size={14} />重试</button>
          </section>
        ) : null}
        {notice ? <div className="inline-state success"><CheckCircle2 size={17} /><span>{notice}</span></div> : null}
        <aside className="site-config-list">
          <div className="site-config-list__head">
            <strong>站点列表</strong>
            <button className="secondary-button compact" type="button" onClick={createSiteDraft}><Plus size={14} />新建子站</button>
          </div>
          {sites.map((site) => (
            <button
              className={`site-config-card ${selectedId !== "new" && selectedId === site.id ? "active" : ""}`}
              key={site.id ?? site.site_key}
              type="button"
              onClick={() => selectSite(site)}
            >
              <span>
                <strong>{site.site_name}</strong>
                <small>{site.site_key}{site.is_default ? " · 默认总站点" : ""}</small>
              </span>
              <em className={site.is_enabled ? "enabled" : "disabled"}>{site.is_enabled ? "启用" : "停用"}</em>
            </button>
          ))}
          {selectedId === "new" ? (
            <button className="site-config-card active" type="button">
              <span><strong>{form.site_name}</strong><small>{form.site_key} · 新子站</small></span>
              <em className="enabled">待保存</em>
            </button>
          ) : null}
        </aside>
        <form className="settings-form" onSubmit={submit}>
          <div className="detail-title">
            <Globe2 size={20} />
            <h3>{selectedId === "new" ? "新建子站点" : selectedSite?.is_default ? "默认总站点" : "子站点配置"}</h3>
          </div>
          <div className="form-grid">
            {selectedId === "new" ? (
              <label className="field">
                初始化模板
                <select
                  value={form.template_site_id ?? ""}
                  onChange={(event) => selectSiteTemplate(Number(event.target.value))}
                >
                  {sites.map((site) => (
                    <option key={site.id ?? site.site_key} value={site.id}>
                      {site.site_name}（{site.site_key}）
                    </option>
                  ))}
                </select>
                <small>默认使用 art 站点，一次复制模型、价格、规格、充值档位和基础配置。</small>
              </label>
            ) : null}
            <label className="field">站点标识<input value={form.site_key} onChange={(event) => updateSiteKey(event.target.value)} placeholder="main / site-a" disabled={form.id === 1} /></label>
            <label className="field">网站名称<input value={form.site_name} onChange={(event) => setForm((current) => ({ ...current, site_name: event.target.value }))} placeholder="例如 艺源" /></label>
            <label className="field">前台地址<input value={form.frontend_url} onChange={(event) => setForm((current) => ({ ...current, frontend_url: event.target.value }))} placeholder="https://site.example.com" /></label>
            <label className="field">后台地址<input value={form.admin_url} onChange={(event) => setForm((current) => ({ ...current, admin_url: event.target.value }))} placeholder="https://admin-site.example.com" /></label>
          </div>
          <div className="check-grid">
            <label><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm((current) => ({ ...current, is_enabled: event.target.checked }))} />启用该站点</label>
            <label><input type="checkbox" checked={form.is_default} onChange={(event) => setForm((current) => ({ ...current, is_default: event.target.checked }))} />设为默认总站点</label>
          </div>
          <div className="detail-title">
            <SlidersHorizontal size={20} />
            <h3>模块开关</h3>
          </div>
          <div className="check-grid site-module-grid">
            {siteModuleOptions.map((module) => (
              <label key={module.key}>
                <input type="checkbox" checked={form.enabled_modules.includes(module.key)} onChange={() => toggleSiteModule(module.key)} />
                {module.label}
              </label>
            ))}
          </div>
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={() => void load()} disabled={isLoading || isSubmitting}>重新读取</button>
            <button className="primary-button" disabled={isLoading || isSubmitting}>{isSubmitting ? "保存中..." : "保存配置"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}

export function UsersPage() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<AdminUser[]>([]);
  const [selected, setSelected] = useState<AdminUser | null>(null);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);

  async function load() {
    setError("");
    try {
      const result = await getAdminAccounts(query, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
      if (selected) setSelected(result.items.find((item) => item.id === selected.id) ?? null);
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "管理员账号接口不可用");
    }
  }

  useResetPageOnQuery(query, setPagination);
  useEffect(() => { void load(); }, [query, pagination.page, pagination.pageSize]);

  return (
    <PageChrome title="管理员账号" description="管理可登录后台的 admin 账号、角色和启用状态。" action={<button className="primary-button compact" onClick={() => setDialog({ kind: "adminAccount" })}><Plus size={15} />新增账号</button>}>
      <Toolbar value={query} onChange={setQuery} placeholder="搜索管理员账号、邮箱或 ID" />
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <div className="split-layout">
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr><th>账号</th><th>邮箱</th><th>角色</th><th>状态</th><th>创建时间</th><th>最后登录</th><th>操作</th></tr></thead>
              <tbody>{items.map((account) => (
                <tr key={account.id}>
                  <td><button className="link-button" onClick={() => setSelected(account)}>{account.username}<small>#{account.id}</small></button></td>
                  <td>{account.email}</td>
                  <td>{adminRoleLabel[account.role]}</td>
                  <td><StatusPill active={account.is_active} /></td>
                  <td>{account.created_at ? formatDateTime(account.created_at) : "-"}</td>
                  <td>{account.last_login_at ? formatDateTime(account.last_login_at) : "-"}</td>
                  <td className="row-actions">
                    <button className="secondary-button compact" onClick={() => setSelected(account)}><Eye size={14} />详情</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "adminAccount", account })}><Pencil size={14} />编辑</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "confirm", title: account.is_active ? "禁用管理员账号" : "启用管理员账号", body: `${account.username} ${account.is_active ? "禁用后将无法登录后台，当前登录账号不能禁用自身。" : "启用后将恢复后台登录能力。"}`, confirmLabel: account.is_active ? "禁用" : "启用", danger: account.is_active, onConfirm: async () => { await updateAdminAccountStatus(account.id, !account.is_active); } })}>{account.is_active ? <Ban size={14} /> : <CheckCircle2 size={14} />}{account.is_active ? "禁用" : "启用"}</button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
        <aside className="detail-drawer">
          {selected ? (
            <>
              <div className="detail-title">
                <UserCog size={20} />
                <h3>{selected.username}</h3>
              </div>
              <p>后台登录账号，角色为 {adminRoleLabel[selected.role]}。</p>
              <dl><dt>邮箱</dt><dd>{selected.email}</dd><dt>状态</dt><dd>{selected.is_active ? "启用" : "停用"}</dd><dt>创建时间</dt><dd>{selected.created_at ? formatDateTime(selected.created_at) : "-"}</dd><dt>最后登录</dt><dd>{selected.last_login_at ? formatDateTime(selected.last_login_at) : "-"}</dd><dt>更新时间</dt><dd>{selected.updated_at ? formatDateTime(selected.updated_at) : "-"}</dd></dl>
            </>
          ) : <div className="empty-detail"><ClipboardCheck size={22} /><span>选择管理员账号查看角色、状态和登录信息。</span></div>}
        </aside>
      </div>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export function LeadApplicationsPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | LeadTrialApplicationStatus>("all");
  const [items, setItems] = useState<LeadTrialApplication[]>([]);
  const [selected, setSelected] = useState<LeadTrialApplication | null>(null);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);

  async function load() {
    setError("");
    try {
      const result = await getLeadTrialApplications(query, status, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
      if (selected) setSelected(result.items.find((item) => item.id === selected.id) ?? null);
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "客资申请接口不可用");
    }
  }

  useResetPageOnQuery(query, setPagination);
  useEffect(() => { setPagination((current) => ({ ...current, page: 1 })); }, [status]);
  useEffect(() => { void load(); }, [query, status, pagination.page, pagination.pageSize]);

  function applicationUser(application: LeadTrialApplication): ManagedUser {
    return {
      id: application.user_id,
      username: application.username,
      email: application.email,
      is_active: application.is_active,
      is_internal: application.is_internal,
      image_concurrency_limit: 1,
      credit_balance: application.credit_balance,
      lead_module_enabled: application.lead_module_enabled,
      created_at: application.created_at ?? "",
    };
  }

  async function markApplication(application: LeadTrialApplication, nextStatus: LeadTrialApplicationStatus) {
    await updateLeadTrialApplication(application.id, nextStatus, application.admin_remark);
    await load();
  }

  return (
    <PageChrome title="客资申请开通" description="查看前台提交的试用申请，按业务范围、关键词、对标账号判断是否开通 AI 高效精准获客。">
      <div className="filter-toolbar dense">
        <label className="search-field compact-search">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索用户、关键词、对标账号、联系方式或 ID" />
        </label>
        <FilterSelect label="状态" value={status} options={leadApplicationStatusOptions} onChange={(value) => setStatus(value as "all" | LeadTrialApplicationStatus)} />
      </div>
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <div className="split-layout">
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>用户</th><th>业务范围</th><th>关键词</th><th>客资</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
              <tbody>{items.map((application) => (
                <tr key={application.id}>
                  <td>#{application.id}</td>
                  <td>{application.username}<small>{application.email || `用户 ID ${application.user_id}`}</small></td>
                  <td className="reason-cell"><p className="task-prompt">{application.business_scope}</p></td>
                  <td className="reason-cell"><p className="task-prompt">{application.keywords}</p></td>
                  <td><span className={`status-pill ${application.lead_module_enabled ? "paid" : "pending"}`}>{application.lead_module_enabled ? "已开通" : "未开通"}</span></td>
                  <td><span className={`status-pill ${leadApplicationStatusTone[application.status]}`}>{leadApplicationStatusLabel[application.status]}</span></td>
                  <td>{application.created_at ? formatDateTime(application.created_at) : "-"}</td>
                  <td className="row-actions">
                    <button className="secondary-button compact" onClick={() => setSelected(application)}><Eye size={14} />详情</button>
                    <button className="primary-button compact" onClick={() => setDialog({ kind: "leadModule", user: applicationUser(application) })}><KeyRound size={14} />开通客资</button>
                    {application.status === "pending" ? (
                      <button className="secondary-button compact" onClick={() => void markApplication(application, "processing")}>处理中</button>
                    ) : null}
                    {application.status !== "rejected" ? (
                      <button className="secondary-button compact" onClick={() => void markApplication(application, "rejected")}>暂不适配</button>
                    ) : null}
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
        <aside className="detail-drawer">
          {selected ? (
            <>
              <div className="detail-title">
                <ContactRound size={20} />
                <h3>申请 #{selected.id}</h3>
              </div>
              <p>{selected.business_scope}</p>
              <dl>
                <dt>用户</dt><dd>{selected.username}</dd>
                <dt>邮箱</dt><dd>{selected.email || "-"}</dd>
                <dt>联系方式</dt><dd>{selected.contact_info || "-"}</dd>
                <dt>高命中关键词</dt><dd>{selected.keywords || "-"}</dd>
                <dt>对标同行账号</dt><dd>{selected.competitor_accounts || "-"}</dd>
                <dt>申请状态</dt><dd>{leadApplicationStatusLabel[selected.status]}</dd>
                <dt>客资模块</dt><dd>{selected.lead_module_enabled ? "已开通" : "未开通"}</dd>
                <dt>处理备注</dt><dd>{selected.admin_remark || "-"}</dd>
                <dt>提交时间</dt><dd>{selected.created_at ? formatDateTime(selected.created_at) : "-"}</dd>
                <dt>处理时间</dt><dd>{selected.handled_at ? formatDateTime(selected.handled_at) : "-"}</dd>
              </dl>
              <div className="detail-actions">
                <button className="primary-button compact" onClick={() => setDialog({ kind: "leadModule", user: applicationUser(selected) })}><KeyRound size={14} />开通客资</button>
                <button className="secondary-button compact" onClick={() => void markApplication(selected, "approved")}>标记已开通</button>
                <button className="secondary-button compact" onClick={() => void markApplication(selected, "processing")}>标记处理中</button>
              </div>
            </>
          ) : <div className="empty-detail"><ContactRound size={22} /><span>选择一条申请查看业务范围、关键词、同行账号和联系方式。</span></div>}
        </aside>
      </div>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={async () => { await load(); setDialog({ kind: "none" }); }} />
    </PageChrome>
  );
}

export function FeedbacksPage() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | UserFeedbackStatus>("all");
  const [items, setItems] = useState<UserFeedback[]>([]);
  const [selected, setSelected] = useState<UserFeedback | null>(null);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);

  async function load() {
    setError("");
    try {
      const result = await getFeedbacks(query, status, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
      if (selected) setSelected(result.items.find((item) => item.id === selected.id) ?? null);
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "用户反馈接口不可用");
    }
  }

  useResetPageOnQuery(query, setPagination);
  useEffect(() => { setPagination((current) => ({ ...current, page: 1 })); }, [status]);
  useEffect(() => { void load(); }, [query, status, pagination.page, pagination.pageSize]);

  return (
    <PageChrome title="用户反馈" description="查看用户提交的问题和建议，处理状态和备注会同步给用户端。">
      <div className="filter-toolbar dense">
        <label className="search-field compact-search">
          <Search size={16} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索用户、邮箱、反馈内容或 ID" />
        </label>
        <FilterSelect label="状态" value={status} options={feedbackStatusOptions} onChange={(value) => setStatus(value as "all" | UserFeedbackStatus)} />
      </div>
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <div className="split-layout">
        <section className="panel">
          <div className="table-wrap">
            <table>
              <thead><tr><th>ID</th><th>用户</th><th>内容</th><th>图片</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead>
              <tbody>{items.map((feedback) => (
                <tr key={feedback.id}>
                  <td>#{feedback.id}</td>
                  <td>{feedback.username}<small>{feedback.email || `用户 ID ${feedback.user_id}`}</small></td>
                  <td className="reason-cell"><p className="task-prompt">{feedback.description}</p></td>
                  <td>{feedback.image_urls.length ? <span className="status-pill pending"><ImageIcon size={13} />{feedback.image_urls.length} 张</span> : "-"}</td>
                  <td><span className={`status-pill ${feedback.status === "resolved" ? "paid" : feedback.status === "closed" ? "failed" : "pending"}`}>{feedbackStatusLabel[feedback.status]}</span></td>
                  <td>{feedback.created_at ? formatDateTime(feedback.created_at) : "-"}</td>
                  <td className="row-actions">
                    <button className="secondary-button compact" onClick={() => setSelected(feedback)}><Eye size={14} />详情</button>
                    <button className="primary-button compact" onClick={() => setDialog({ kind: "feedback", feedback })}><Pencil size={14} />处理</button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
        <aside className="detail-drawer">
          {selected ? (
            <>
              <div className="detail-title">
                <MessageSquareText size={20} />
                <h3>反馈 #{selected.id}</h3>
              </div>
              <p>{selected.description}</p>
              <dl>
                <dt>用户</dt><dd>{selected.username}</dd>
                <dt>邮箱</dt><dd>{selected.email || "-"}</dd>
                <dt>状态</dt><dd>{feedbackStatusLabel[selected.status]}</dd>
                <dt>处理备注</dt><dd>{selected.admin_remark || "-"}</dd>
                <dt>提交时间</dt><dd>{selected.created_at ? formatDateTime(selected.created_at) : "-"}</dd>
                <dt>处理时间</dt><dd>{selected.handled_at ? formatDateTime(selected.handled_at) : "-"}</dd>
              </dl>
              {selected.image_urls.length ? (
                <div className="feedback-image-strip">
                  {selected.image_urls.map((url) => (
                    <a href={url} target="_blank" rel="noreferrer" key={url}><img src={url} alt="反馈截图" /></a>
                  ))}
                </div>
              ) : null}
            </>
          ) : <div className="empty-detail"><MessageSquareText size={22} /><span>选择一条反馈查看详细内容和截图。</span></div>}
        </aside>
      </div>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export { CreditsPage, RechargePlansPage, RechargeOrdersPage, InviteRewardPage, UserExperiencePage, ZPayConfigPage, AgentPage } from "./management/CommerceManagementPages";

export { OpenAgentReleasesPage } from "./management/OpenAgentReleasesPage";

export { SiteContentPage } from "./management/SiteContentPage";

export { MaterialsPage, SigninRewardsPage, ImageSpecsPage, ModelsPage, ModelPricesPage, TasksPage } from "./management/AssetModelManagementPages";

export function AuditLogsPage() {
  const [items, setItems] = useState<AuditLog[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  async function load() {
    setError("");
    try { const result = await getAuditLogs(query, pagination.page, pagination.pageSize); setItems(result.items); setPagination({ page: result.page, pageSize: result.page_size, total: result.total }); } catch (err) { setItems([]); setError(err instanceof Error ? err.message : "审计日志接口不可用"); }
  }
  useResetPageOnQuery(query, setPagination);
  useEffect(() => { void load(); }, [query, pagination.page, pagination.pageSize]);
  return (
    <PageChrome title="审计日志" description="追踪敏感操作的操作者、资源、时间和变更原因。">
      <Toolbar value={query} onChange={setQuery} placeholder="搜索操作者、动作、资源或原因" />
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <section className="panel"><div className="table-wrap"><table><thead><tr><th>操作者</th><th>动作</th><th>资源</th><th>原因</th><th>时间</th></tr></thead><tbody>{items.map((log) => <tr key={log.id}><td>{log.admin_username}</td><td>{log.action}</td><td>{log.resource_type} #{log.resource_id}</td><td>{log.reason ?? "-"}</td><td>{formatDateTime(log.created_at)}</td></tr>)}</tbody></table></div></section>
      <Pagination pagination={pagination} onChange={setPagination} />
    </PageChrome>
  );
}

const bizLabel = {
  recharge: "充值",
  image_task: "图片任务",
  refund: "退款",
  admin_adjustment: "人工调整",
  signin: "签到",
  invite: "邀请",
};

const rechargeStatusOptions: Array<{ value: NonNullable<RechargePlanFilters["status"]>; label: string }> = [
  { value: "all", label: "全部" },
  { value: "active", label: "已上架" },
  { value: "inactive", label: "已下架" },
];

const rechargeOrderStatusLabel: Record<RechargeOrderStatus, string> = {
  pending: "待支付",
  paid: "已支付",
  expired: "已过期",
  cancelled: "已取消",
  failed: "失败",
};

const rechargeOrderStatusTone: Record<RechargeOrderStatus, "pending" | "paid" | "failed"> = {
  pending: "pending",
  paid: "paid",
  expired: "failed",
  cancelled: "failed",
  failed: "failed",
};

const rechargeOrderStatusOptions: Array<{ value: NonNullable<RechargeOrderFilters["status"]>; label: string }> = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待支付" },
  { value: "paid", label: "已支付" },
  { value: "expired", label: "已过期" },
  { value: "cancelled", label: "已取消" },
  { value: "failed", label: "失败" },
];

const statusFilterOptions = [
  { value: "all", label: "全部" },
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
];

const capabilityFilterOptions = [
  { value: "all", label: "全部" },
  { value: "image", label: "图片" },
  { value: "text", label: "文本" },
  { value: "multimodal", label: "图文混合" },
];

const workTypeFilterOptions = [
  { value: "all", label: "全部" },
  { value: "text_to_image", label: "文生图" },
  { value: "image_to_image", label: "图生图" },
  { value: "text", label: "文本" },
];

const modelTagFilterOptions = [
  { value: "all", label: "全部" },
  { value: "recommended", label: "推荐" },
  { value: "stable", label: "稳定" },
  { value: "new", label: "新模型" },
];

const priceAbilityOptions = [
  { value: "text_to_image", label: "文生图" },
  { value: "image_to_image", label: "图生图" },
  { value: "text", label: "文本" },
] as const;

const taskStatus = {
  queued: "排队中",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  refunded: "已退款",
};

const capabilityLabel = {
  image: "图片",
  text: "文本",
  multimodal: "图文混合（暂不开放）",
};

function formatImageCapabilities(workType: string) {
  const parts = workType.split(",").map((item) => item.trim());
  const labels = parts.map((item) => imageCapabilityLabel[item] ?? item).filter(Boolean);
  return labels.length ? labels.join(" / ") : "-";
}

function formatPriceAbility(workType: string) {
  const option = priceAbilityOptions.find((item) => item.value === workType);
  if (option) return option.label;
  return imageCapabilityLabel[workType] ?? workType;
}

function formatSpecs(specs: ImageSpec[]) {
  return specs.length ? specs.map((spec) => spec.label).join(" / ") : "-";
}

const imageCapabilityLabel: Record<string, string> = {
  text_to_image: "文生图",
  image_to_image: "图生图",
  image_edit: "图生图",
  text: "文本",
};
