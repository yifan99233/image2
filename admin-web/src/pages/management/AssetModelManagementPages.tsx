import { type FormEvent, useEffect, useState } from "react";
import { AlertTriangle, Ban, CheckCircle2, CheckSquare, FileImage, FlaskConical, Gift, Image as ImageIcon, PackageOpen, Pencil, Plus, RefreshCw, RefreshCcw, RotateCcw, Search, ShieldAlert, SlidersHorizontal, Square, Star, Trash2, UserCog, WalletCards } from "lucide-react";
import { formatCurrency, formatDateTime } from "../../lib/format";
import { createImageSpec, createMaterialUploadToken, deleteModel, disableModelPricesBatch, getImageSpecs, getMaterials, getModelPrices, getModels, getSigninRecords, getSigninRewardConfig, runModelTest, saveMaterial, toggleMaterial, toggleModel, toggleModelPrice, updateImageSpec, updateModelVisibility, updateSigninRewardConfig } from "../../services/adminApi";
import type { MaterialFilters, ModelFilters } from "../../services/adminApi";
import type { AdminImageModel, AuditLog, ImageSpec, ImageSpecs, MaterialAsset, MaterialAssetInput, MaterialAssetType, ModelPrice, SigninRecord, SigninRewardConfig } from "../../types";
import { Dialog, type DialogState } from "./ManagementDialogs";
import { FilterSelect, initialPagination, LoadState, PageChrome, Pagination, StatusPill, Toolbar, type PaginationState, useAutoDismissNotice, useResetPageOnQuery } from "./ManagementCommon";

const defaultMaterialForm: MaterialAssetInput = {
  asset_type: "video",
  title: "",
  description: "",
  file_url: "",
  cover_url: "",
  mime_type: "",
  file_size: 0,
  sort_order: 50,
  is_active: true,
};

const materialTypeOptions: Array<{ value: "all" | MaterialAssetType; label: string }> = [
  { value: "all", label: "全部类型" },
  { value: "video", label: "视频" },
  { value: "image", label: "图片" },
  { value: "file", label: "文件" },
];

const materialStatusOptions = [
  { value: "all", label: "全部状态" },
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
];

function formatFileSize(size: number) {
  if (!size) return "-";
  if (size >= 1024 * 1024 * 1024) return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`;
  if (size >= 1024 * 1024) return `${(size / 1024 / 1024).toFixed(2)} MB`;
  if (size >= 1024) return `${(size / 1024).toFixed(2)} KB`;
  return `${size} B`;
}

const statusFilterOptions = [
  { value: "all", label: "全部" },
  { value: "active", label: "启用" },
  { value: "inactive", label: "停用" },
];

const capabilityFilterOptions = [
  { value: "all", label: "全部" },
  { value: "image", label: "图片" },
  { value: "video", label: "视频" },
  { value: "text", label: "文本" },
  { value: "multimodal", label: "图文混合" },
];

const workTypeFilterOptions = [
  { value: "all", label: "全部" },
  { value: "text_to_image", label: "文生图" },
  { value: "image_to_image", label: "图生图" },
  { value: "text_to_video", label: "文生视频" },
  { value: "image_to_video", label: "图生视频" },
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
  { value: "text_to_video", label: "文生视频" },
  { value: "image_to_video", label: "图生视频" },
  { value: "text", label: "文本" },
] as const;

const capabilityLabel: Record<string, string> = {
  image: "图片",
  video: "视频",
  text: "文本",
  multimodal: "图文混合（暂不开放）",
};

const imageCapabilityLabel: Record<string, string> = {
  text_to_image: "文生图",
  image_to_image: "图生图",
  image_edit: "图生图",
  text_to_video: "文生视频",
  image_to_video: "图生视频",
  text: "文本",
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

function formatSpecs(specs: ImageSpec[] | undefined) {
  if (!specs?.length) return "-";
  return specs.map((spec) => spec.label).join(" / ");
}

const storageModeLabel: Record<string, string> = {
  local: "本地存储",
  third_party: "三方存储",
  native: "原生存储",
};

function isVideoAdminModel(model: AdminImageModel) {
  if (model.capability_type === "video") return true;
  const workTypes = model.work_type.split(",").map((item) => item.trim()).filter(Boolean);
  return workTypes.length > 0 && workTypes.every((item) => item === "text_to_video" || item === "image_to_video");
}

function formatPriceSpec(price: ModelPrice, model?: AdminImageModel) {
  if (model && isVideoAdminModel(model)) {
    return `${price.resolution} · ${price.aspect_ratio}秒`;
  }
  if (price.work_type === "text" || price.work_type === "text_generation") {
    return "按次";
  }
  return `${price.resolution} · ${price.aspect_ratio} · ${price.output_count}张`;
}

export function MaterialsPage() {
  const [items, setItems] = useState<MaterialAsset[]>([]);
  const [form, setForm] = useState<MaterialAssetInput>(defaultMaterialForm);
  const [editingId, setEditingId] = useState<number | undefined>();
  const [filters, setFilters] = useState<MaterialFilters>({ query: "", assetType: "all", status: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [uploadState, setUploadState] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [filters.query, filters.assetType, filters.status]);

  async function load() {
    setError("");
    try {
      const result = await getMaterials(filters, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination((current) => ({ ...current, total: result.total, page: result.page, pageSize: result.page_size }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材接口不可用");
      setItems([]);
    }
  }

  useEffect(() => { void load(); }, [filters, pagination.page, pagination.pageSize]);

  async function uploadMaterialFile(file: File) {
    setError("");
    setNotice("");
    setUploadState("正在获取七牛上传凭证...");
    try {
      const uploadToken = await createMaterialUploadToken(file.name, form.asset_type);
      const formData = new FormData();
      formData.append("token", uploadToken.token);
      formData.append("key", uploadToken.key);
      formData.append("file", file);
      setUploadState("正在上传到七牛云...");
      const response = await fetch(uploadToken.upload_url, { method: "POST", body: formData });
      if (!response.ok) {
        const text = await response.text().catch(() => "");
        throw new Error(text || `七牛上传失败（${response.status}）`);
      }
      setForm((current) => ({
        ...current,
        title: current.title || file.name.replace(/\.[^.]+$/, ""),
        file_url: uploadToken.public_url,
        mime_type: file.type,
        file_size: file.size,
      }));
      setNotice(`已上传 ${file.name}，七牛 URL 已回填`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "七牛上传失败");
    } finally {
      setUploadState("");
    }
  }

  function editMaterial(material: MaterialAsset) {
    setEditingId(material.id);
    setForm({
      asset_type: material.asset_type,
      title: material.title,
      description: material.description,
      file_url: material.file_url,
      cover_url: material.cover_url,
      mime_type: material.mime_type,
      file_size: material.file_size,
      sort_order: material.sort_order,
      is_active: material.is_active,
    });
    setNotice(`正在编辑素材：${material.title}`);
  }

  function resetForm() {
    setEditingId(undefined);
    setForm(defaultMaterialForm);
    setNotice("");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.title.trim() || !form.file_url.trim()) {
      setError("素材标题和七牛文件 URL 不能为空");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveMaterial({ ...form, title: form.title.trim(), file_url: form.file_url.trim(), cover_url: form.cover_url.trim(), description: form.description.trim() }, editingId);
      setNotice(`已保存素材：${saved.title}`);
      resetForm();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "素材保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="素材管理" description="上传和管理素材视频、图片和文件。文件直传七牛云，后台只保存 CDN 地址和配置。">
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <PackageOpen size={20} />
            <div>
              <h3>{editingId ? "编辑素材" : "新增素材"}</h3>
              <p>视频等大文件直接上传到七牛云，不经过 MinIO。</p>
            </div>
          </div>
          <div className="form-grid">
            <label className="field">素材类型
              <select value={form.asset_type} onChange={(event) => setForm({ ...form, asset_type: event.target.value as MaterialAssetType })}>
                {materialTypeOptions.filter((option) => option.value !== "all").map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </label>
            <label className="field">标题<input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="例如：商品展示素材视频" /></label>
            <label className="field">排序<input min={0} type="number" value={form.sort_order} onChange={(event) => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
            <label className="field">文件大小 bytes<input min={0} type="number" value={form.file_size} onChange={(event) => setForm({ ...form, file_size: Number(event.target.value) })} /></label>
            <label className="field wide">上传到七牛
              <input type="file" accept={form.asset_type === "video" ? "video/*" : form.asset_type === "image" ? "image/*" : undefined} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadMaterialFile(file); event.currentTarget.value = ""; }} />
              <small>{uploadState || "选择素材文件后会直接上传到七牛云，并自动回填文件 URL、大小和 MIME。"}</small>
            </label>
            <label className="field wide">文件 URL<input value={form.file_url} onChange={(event) => setForm({ ...form, file_url: event.target.value })} placeholder="上传后自动回填，也可手动粘贴七牛 CDN URL" /></label>
            <label className="field wide">封面 URL<input value={form.cover_url} onChange={(event) => setForm({ ...form, cover_url: event.target.value })} placeholder="可选，视频封面图 URL" /></label>
            <label className="field">MIME<input value={form.mime_type} onChange={(event) => setForm({ ...form, mime_type: event.target.value })} placeholder="例如 video/mp4" /></label>
            <label className="field wide">描述<textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} rows={3} /></label>
          </div>
          <label className="check-line"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /> 启用素材</label>
          {form.file_url ? <div className="inline-hint">当前文件：{form.file_url}（{formatFileSize(form.file_size)}）</div> : null}
          {error ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={resetForm}>清空</button>
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存素材"}</button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="toolbar">
          <label className="search-field">
            <Search size={16} />
            <input value={filters.query ?? ""} onChange={(event) => setFilters({ ...filters, query: event.target.value })} placeholder="搜索标题、描述或 URL" />
          </label>
          <FilterSelect label="类型" value={filters.assetType ?? "all"} onChange={(value) => setFilters({ ...filters, assetType: value as MaterialFilters["assetType"] })} options={materialTypeOptions} />
          <FilterSelect label="状态" value={filters.status ?? "all"} onChange={(value) => setFilters({ ...filters, status: value as MaterialFilters["status"] })} options={materialStatusOptions} />
        </div>
        <LoadState error={error && !items.length ? error : ""} empty={!error && items.length === 0} onRetry={load} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>标题</th><th>类型</th><th>状态</th><th>大小</th><th>排序</th><th>地址</th><th>更新时间</th><th>操作</th></tr></thead>
            <tbody>{items.map((material) => (
              <tr key={material.id}>
                <td>{material.title}<small>{material.description || "-"}</small></td>
                <td>{materialTypeOptions.find((option) => option.value === material.asset_type)?.label ?? material.asset_type}</td>
                <td><StatusPill active={material.is_active} /></td>
                <td>{formatFileSize(material.file_size)}</td>
                <td>{material.sort_order}</td>
                <td><a href={material.file_url} target="_blank" rel="noreferrer">打开</a></td>
                <td>{material.updated_at ? formatDateTime(material.updated_at) : "-"}</td>
                <td className="table-actions">
                  <button className="secondary-button compact" onClick={() => editMaterial(material)}><Pencil size={14} />编辑</button>
                  <button className="secondary-button compact" onClick={async () => { await toggleMaterial(material.id); await load(); }}>{material.is_active ? <Ban size={14} /> : <CheckCircle2 size={14} />}{material.is_active ? "停用" : "启用"}</button>
                </td>
              </tr>
            ))}</tbody>
          </table>
        </div>
        <Pagination pagination={pagination} onChange={setPagination} />
      </section>
    </PageChrome>
  );
}

export function SigninRewardsPage() {
  const [config, setConfig] = useState<SigninRewardConfig | null>(null);
  const [form, setForm] = useState({ is_enabled: false, daily_credits: 0 });
  const [records, setRecords] = useState<SigninRecord[]>([]);
  const [query, setQuery] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  async function loadConfig() {
    const nextConfig = await getSigninRewardConfig();
    setConfig(nextConfig);
    setForm({ is_enabled: nextConfig.is_enabled, daily_credits: nextConfig.daily_credits });
  }

  async function loadRecords() {
    const result = await getSigninRecords(query, pagination.page, pagination.pageSize);
    setRecords(result.items);
    setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
  }

  async function load() {
    setError("");
    try {
      await Promise.all([loadConfig(), loadRecords()]);
    } catch (err) {
      setConfig(null);
      setRecords([]);
      setError(err instanceof Error ? err.message : "签到配置接口不可用");
    }
  }

  useResetPageOnQuery(query, setPagination);
  useEffect(() => { void load(); }, [query, pagination.page, pagination.pageSize]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.daily_credits < 0) {
      setError("每日签到积分不能小于 0");
      return;
    }
    if (form.is_enabled && form.daily_credits <= 0) {
      setError("开启签到前必须配置大于 0 的每日积分");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await updateSigninRewardConfig(form);
      setConfig(nextConfig);
      setForm({ is_enabled: nextConfig.is_enabled, daily_credits: nextConfig.daily_credits });
      setNotice("签到配置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "签到配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="签到配置" description="配置用户端每日签到开关、奖励积分，并查看真实签到记录。">
      <LoadState error={error && !config ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <Gift size={20} />
            <div>
              <h3>每日签到奖励</h3>
              <p>关闭后用户无法签到；开启时后端按自然日和唯一约束防止重复领取。</p>
            </div>
          </div>
          <label className="check-line"><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} /> 开启每日签到</label>
          <div className="form-grid">
            <label className="field">每日奖励积分<input min={0} type="number" value={form.daily_credits} onChange={(event) => setForm({ ...form, daily_credits: Number(event.target.value) })} /></label>
            <label className="field">配置更新时间<input disabled value={config?.updated_at ? formatDateTime(config.updated_at) : "-"} /></label>
          </div>
          {error && config ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存配置"}</button>
          </div>
        </form>
      </section>

      <Toolbar value={query} onChange={setQuery} placeholder="搜索用户名或邮箱" />
      <LoadState error="" empty={records.length === 0} onRetry={loadRecords} />
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead><tr><th>用户</th><th>签到日期</th><th>奖励积分</th><th>连续天数</th><th>签到时间</th></tr></thead>
            <tbody>{records.map((record) => (
              <tr key={record.id}>
                <td>{record.username}<small>{record.email}</small></td>
                <td>{record.sign_date}</td>
                <td className="amount-plus">+{record.awarded_credits}</td>
                <td>{record.streak_days} 天</td>
                <td>{formatDateTime(record.created_at)}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
    </PageChrome>
  );
}

type SpecKind = "resolutions" | "aspect-ratios" | "durations";

const specKindPlaceholder: Record<SpecKind, { code: string; label: string }> = {
  resolutions: { code: "1k", label: "1K" },
  "aspect-ratios": { code: "1:1", label: "1:1" },
  durations: { code: "6", label: "6 秒" },
};

function SpecEditor({ kind, onDone }: { kind: SpecKind; onDone: () => void }) {
  const [form, setForm] = useState({ code: "", label: "", sort_order: 50, is_active: true });
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.code.trim() || !form.label.trim()) {
      setError("编码和名称不能为空");
      return;
    }
    setIsSubmitting(true);
    setError("");
    try {
      await createImageSpec(kind, form);
      setForm({ code: "", label: "", sort_order: 50, is_active: true });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "规范保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form className="inline-form" onSubmit={submit}>
      <label className="field">编码<input value={form.code} onChange={(event) => setForm({ ...form, code: event.target.value })} placeholder={specKindPlaceholder[kind].code} /></label>
      <label className="field">展示名称<input value={form.label} onChange={(event) => setForm({ ...form, label: event.target.value })} placeholder={specKindPlaceholder[kind].label} /></label>
      <label className="field">排序<input type="number" value={form.sort_order} onChange={(event) => setForm({ ...form, sort_order: Number(event.target.value) })} /></label>
      <label className="check-line inline-check"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /> 启用</label>
      <button className="primary-button compact" disabled={isSubmitting}><Plus size={14} />新增</button>
      {error ? <div className="form-error inline-error">{error}</div> : null}
    </form>
  );
}

function SpecTable({ kind, items, onDone }: { kind: SpecKind; items: ImageSpec[]; onDone: () => void }) {
  async function patchSpec(spec: ImageSpec, input: Partial<ImageSpec>) {
    await updateImageSpec(kind, spec.id, input);
    onDone();
  }

  return (
    <section className="panel">
      <SpecEditor kind={kind} onDone={onDone} />
      <div className="table-wrap">
        <table>
          <thead><tr><th>编码</th><th>展示名称</th><th>排序</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>{items.map((spec) => (
            <tr key={spec.id}>
              <td>{spec.code}</td>
              <td>{spec.label}</td>
              <td>{spec.sort_order}</td>
              <td><StatusPill active={spec.is_active} /></td>
              <td className="row-actions"><button className="secondary-button compact" onClick={() => patchSpec(spec, { is_active: !spec.is_active })}>{spec.is_active ? "停用" : "启用"}</button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}

export function ImageSpecsPage() {
  const [activeTab, setActiveTab] = useState<"resolutions" | "aspect_ratios" | "durations">("resolutions");
  const [specs, setSpecs] = useState<ImageSpecs>({ resolutions: [], aspect_ratios: [], durations: [] });
  const [error, setError] = useState("");

  async function load() {
    setError("");
    try {
      const next = await getImageSpecs();
      setSpecs({ resolutions: next.resolutions ?? [], aspect_ratios: next.aspect_ratios ?? [], durations: next.durations ?? [] });
    } catch (err) {
      setSpecs({ resolutions: [], aspect_ratios: [], durations: [] });
      setError(err instanceof Error ? err.message : "图片规范接口不可用");
    }
  }

  useEffect(() => { void load(); }, []);

  return (
    <PageChrome title="模型规范管理" description="维护平台可用的分辨率、尺寸比例和视频时长，模型与价格配置会引用这里的规范。">
      <div className="tabs">
        <button className={activeTab === "resolutions" ? "active" : ""} onClick={() => setActiveTab("resolutions")}>分辨率管理</button>
        <button className={activeTab === "aspect_ratios" ? "active" : ""} onClick={() => setActiveTab("aspect_ratios")}>尺寸管理</button>
        <button className={activeTab === "durations" ? "active" : ""} onClick={() => setActiveTab("durations")}>视频时长</button>
      </div>
      <LoadState error={error} empty={false} onRetry={load} />
      {activeTab === "resolutions" ? (
        <SpecTable kind="resolutions" items={specs.resolutions} onDone={load} />
      ) : activeTab === "aspect_ratios" ? (
        <SpecTable kind="aspect-ratios" items={specs.aspect_ratios} onDone={load} />
      ) : (
        <SpecTable kind="durations" items={specs.durations} onDone={load} />
      )}
    </PageChrome>
  );
}

export function ModelsPage() {
  const [items, setItems] = useState<AdminImageModel[]>([]);
  const [testResult, setTestResult] = useState<{ status: "succeeded" | "failed"; message: string } | null>(null);
  const [testingModelId, setTestingModelId] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [filters, setFilters] = useState<ModelFilters>({ query: "", provider: "", status: "all", capabilityType: "all", workType: "all", tag: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  async function load() {
    setError("");
    try { const result = await getModels(filters, pagination.page, pagination.pageSize); setItems(result.items); setPagination({ page: result.page, pageSize: result.page_size, total: result.total }); } catch (err) { setItems([]); setError(err instanceof Error ? err.message : "模型接口不可用"); }
  }
  async function handleToggleModel(model: AdminImageModel) {
    try {
      await toggleModel(model.id);
      await load();
    } catch (err) {
      void err;
    }
  }
  async function handleRunModelTest(model: AdminImageModel) {
    setTestingModelId(model.id);
    setTestResult(null);
    const isTextModel =
      model.capability_type === "text" ||
      model.work_type.split(",").map((item) => item.trim()).filter(Boolean).every((item) => item === "text" || item === "text_generation");
    const prompt = isTextModel
      ? "请回复：ok。仅用于文本模型接口连通性测试。"
      : "生成商品主图测试";
    try {
      const result = await runModelTest(model.id, prompt);
      setTestResult({ status: result.status, message: `${model.name}: ${result.summary} (${result.duration_ms}ms)` });
    } catch (err) {
      setTestResult({ status: "failed", message: `${model.name}: ${err instanceof Error ? err.message : "模型测试请求失败"}` });
    } finally {
      setTestingModelId(null);
    }
  }
  async function handleDeleteModel(model: AdminImageModel) {
    await deleteModel(model.id);
    await load();
  }
  useEffect(() => { setPagination((current) => ({ ...current, page: 1 })); }, [filters.query, filters.provider, filters.status, filters.capabilityType, filters.workType, filters.tag]);
  useEffect(() => { void load(); }, [filters.query, filters.provider, filters.status, filters.capabilityType, filters.workType, filters.tag, pagination.page, pagination.pageSize]);
  return (
    <PageChrome title="模型管理" description="管理图片、视频与文本模型的供应商、连接配置、能力标签和上下架状态。视频模型按分辨率 × 时长计费，并支持配置画面比例；文本模型用于提示词优化。" action={<button className="primary-button compact" onClick={() => setDialog({ kind: "model" })}><Plus size={15} />新增模型</button>}>
      <div className="filter-toolbar dense">
        <label className="search-field compact-search">
          <Search size={16} />
          <input value={filters.query ?? ""} onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))} placeholder="搜索模型名称、编码或厂商模型" />
        </label>
        <label className="search-field compact-search">
          <Search size={16} />
          <input value={filters.provider ?? ""} onChange={(event) => setFilters((current) => ({ ...current, provider: event.target.value }))} placeholder="供应商" />
        </label>
        <FilterSelect label="状态" value={filters.status ?? "all"} options={statusFilterOptions} onChange={(value) => setFilters((current) => ({ ...current, status: value as ModelFilters["status"] }))} />
        <FilterSelect label="一级能力" value={filters.capabilityType ?? "all"} options={capabilityFilterOptions} onChange={(value) => setFilters((current) => ({ ...current, capabilityType: value as ModelFilters["capabilityType"] }))} />
        <FilterSelect label="二级能力" value={filters.workType ?? "all"} options={workTypeFilterOptions} onChange={(value) => setFilters((current) => ({ ...current, workType: value as ModelFilters["workType"] }))} />
        <FilterSelect label="标签" value={filters.tag ?? "all"} options={modelTagFilterOptions} onChange={(value) => setFilters((current) => ({ ...current, tag: value as ModelFilters["tag"] }))} />
      </div>
      {testResult && (
        <section className={`inline-result ${testResult.status === "failed" ? "inline-result--failed" : "inline-result--success"}`}>
          {testResult.status === "failed" ? <AlertTriangle size={17} /> : <CheckCircle2 size={17} />}
          <span>{testResult.message}</span>
        </section>
      )}
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>模型</th><th>供应商</th><th>接入</th><th>一级能力</th><th>二级能力</th><th>支持分辨率</th><th>支持比例/时长</th><th>存储</th><th>Base URL</th><th>API Key</th><th>标签</th><th>启用</th><th>上架</th><th>操作</th></tr>
            </thead>
            <tbody>
              {items.map((model) => (
                <tr key={model.id}>
                  <td>{model.name}<small>{model.code}</small></td>
                  <td>{model.provider_name}</td>
                  <td><span className="status-pill pending">{model.access_mode === "sdk" ? "SDK" : "API"}</span></td>
                  <td>{capabilityLabel[model.capability_type ?? "image"]}</td>
                  <td>{formatImageCapabilities(model.work_type)}</td>
                  <td>{formatSpecs(model.supported_resolutions)}</td>
                  <td>{isVideoAdminModel(model)
                    ? `${formatSpecs(model.supported_aspect_ratios)}${model.supported_aspect_ratios?.length && model.supported_durations?.length ? " / " : ""}${formatSpecs(model.supported_durations)}`
                    : formatSpecs(model.supported_aspect_ratios)}</td>
                  <td><span className="status-pill pending">{storageModeLabel[model.storage_mode ?? "local"] ?? model.storage_mode ?? "本地存储"}</span></td>
                  <td>{model.base_url_masked}</td>
                  <td>{model.api_key_masked}</td>
                  <td><span className="tag-row">{model.is_recommended && "推荐 "}{model.is_stable && "稳定 "}{model.is_new && "新"}</span></td>
                  <td><StatusPill active={model.is_active} /></td>
                  <td><span className={`status-pill ${model.is_public ? "paid" : "pending"}`}>{model.is_public ? "已上架" : "未上架"}</span></td>
                  <td className="row-actions">
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "model", model })}><Pencil size={14} />编辑</button>
                    <button className="secondary-button compact" disabled={model.is_active} onClick={() => setDialog({ kind: "modelSpecs", model })}><SlidersHorizontal size={14} />规格</button>
                    <button className="secondary-button compact" disabled={testingModelId === model.id} onClick={() => void handleRunModelTest(model)}><FlaskConical size={14} />{testingModelId === model.id ? "测试中" : "测试"}</button>
                    <button className="secondary-button compact" onClick={() => void handleToggleModel(model)}>{model.is_active ? "停用" : "启用"}</button>
                    <button className="secondary-button compact" onClick={async () => { await updateModelVisibility(model.id, !model.is_public); await load(); }}>{model.is_public ? "下架" : "上架"}</button>
                    <button
                      className="danger-button compact"
                      onClick={() => setDialog({
                        kind: "confirm",
                        title: "删除模型",
                        body: `将删除模型「${model.name}」以及它的全部价格配置和规格关联。历史任务记录会保留，但不再关联到该模型配置。`,
                        confirmLabel: "删除模型",
                        danger: true,
                        onConfirm: () => handleDeleteModel(model),
                      })}
                    >
                      <Trash2 size={14} />删除
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export function ModelPricesPage() {
  const [items, setItems] = useState<ModelPrice[]>([]);
  const [models, setModels] = useState<AdminImageModel[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selectedPriceIds, setSelectedPriceIds] = useState<Set<number>>(new Set());
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  useAutoDismissNotice(notice, setNotice);
  async function load() {
    setError("");
    try {
      const [priceResult, modelResult] = await Promise.all([getModelPrices("", pagination.page, pagination.pageSize), getModels("", 1, 100)]);
      setItems(priceResult.items);
      setModels(modelResult.items);
      setSelectedPriceIds((current) => {
        const activeIds = new Set(priceResult.items.filter((price) => price.is_active).map((price) => price.id));
        return new Set([...current].filter((id) => activeIds.has(id)));
      });
      setPagination({ page: priceResult.page, pageSize: priceResult.page_size, total: priceResult.total });
    } catch (err) {
      setItems([]);
      setModels([]);
      setSelectedPriceIds(new Set());
      setError(err instanceof Error ? err.message : "价格配置接口不可用");
    }
  }
  useEffect(() => { void load(); }, [pagination.page, pagination.pageSize]);
  const activeItems = items.filter((price) => price.is_active);
  const selectedActiveCount = [...selectedPriceIds].filter((id) => activeItems.some((price) => price.id === id)).length;
  const allActiveItemsSelected = activeItems.length > 0 && selectedActiveCount === activeItems.length;
  const toggleSelectedPrice = (price: ModelPrice) => {
    if (!price.is_active) return;
    setSelectedPriceIds((current) => {
      const next = new Set(current);
      if (next.has(price.id)) next.delete(price.id);
      else next.add(price.id);
      return next;
    });
  };
  const toggleCurrentPageActive = () => {
    setSelectedPriceIds((current) => {
      const next = new Set(current);
      if (allActiveItemsSelected) activeItems.forEach((price) => next.delete(price.id));
      else activeItems.forEach((price) => next.add(price.id));
      return next;
    });
  };
  const disableSelectedPrices = async () => {
    const ids = [...selectedPriceIds];
    const result = await disableModelPricesBatch({ price_ids: ids });
    setSelectedPriceIds(new Set());
    setNotice(`已停用 ${result.updated_count} 条价格`);
  };
  const disableAllActivePrices = async () => {
    const result = await disableModelPricesBatch({ all_active: true });
    setSelectedPriceIds(new Set());
    setNotice(`已停用全部启用价格，共 ${result.updated_count} 条`);
  };
  return (
    <PageChrome
      title="价格配置"
      description="图片按能力、分辨率、比例和输出张数计费；视频按能力、分辨率和时长计费；文本按次计费。"
      action={
        <div className="row-actions">
          <button
            className="danger-button compact"
            disabled={pagination.total === 0}
            onClick={() => setDialog({
              kind: "confirm",
              title: "停用全部价格",
              body: "将停用当前站点下所有启用的价格版本。停用后，启用模型时会重新校验价格配置。",
              confirmLabel: "全部停用",
              danger: true,
              onConfirm: disableAllActivePrices,
            })}
          >
            <Ban size={15} />全部停用
          </button>
          <button className="primary-button compact" onClick={() => setDialog({ kind: "price", models })}><Plus size={15} />配置模型价格</button>
        </div>
      }
    >
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      {notice ? <section className="inline-state success"><CheckCircle2 size={17} /><span>{notice}</span></section> : null}
      <div className="filter-toolbar dense">
        <button className="secondary-button compact" disabled={activeItems.length === 0} onClick={toggleCurrentPageActive}>
          {allActiveItemsSelected ? <CheckSquare size={15} /> : <Square size={15} />}
          {allActiveItemsSelected ? "取消本页选择" : "选择本页启用项"}
        </button>
        <button
          className="secondary-button compact"
          disabled={selectedActiveCount === 0}
          onClick={() => setDialog({
            kind: "confirm",
            title: "批量停用价格",
            body: `将停用已选择的 ${selectedActiveCount} 条启用价格版本。停用后，相关模型启用校验会要求补齐价格配置。`,
            confirmLabel: "批量停用",
            danger: true,
            onConfirm: disableSelectedPrices,
          })}
        >
          <Ban size={15} />批量停用
        </button>
        <span className="muted-meta">已选择 {selectedActiveCount} 条，本页启用 {activeItems.length} 条</span>
      </div>
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>选择</th><th>模型</th><th>能力</th><th>规格</th><th>质量</th><th>基础价格</th><th>固定加价</th><th>版本</th><th>原因</th><th>状态</th><th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((price) => {
                const checked = selectedPriceIds.has(price.id);
                return (
                  <tr key={price.id}>
                    <td>
                      <button className="secondary-button compact" disabled={!price.is_active} onClick={() => toggleSelectedPrice(price)} aria-label={checked ? "取消选择价格" : "选择价格"}>
                        {checked ? <CheckSquare size={15} /> : <Square size={15} />}
                      </button>
                    </td>
                    <td>{price.model_name}</td>
                    <td>{formatPriceAbility(price.work_type)}</td>
                    <td>{formatPriceSpec(price, models.find((model) => model.id === price.model_id))}</td>
                    <td>{{ any: "通用", low: "低", medium: "中（含自动）", high: "高" }[price.quality ?? "any"]}</td>
                    <td>{price.credit_cost}</td><td>{price.fixed_surcharge ?? 0}</td>
                    <td>v{price.version}</td>
                    <td>{price.change_reason}</td>
                    <td><StatusPill active={price.is_active} /></td>
                    <td><button className="secondary-button compact" onClick={async () => { await toggleModelPrice(price.id); await load(); }}>{price.is_active ? "停用" : "启用"}</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export { TasksPage } from "./TasksPage";
