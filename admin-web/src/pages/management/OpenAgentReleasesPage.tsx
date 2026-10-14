import { type FormEvent, type ReactNode, useEffect, useState } from "react";
import { AlertTriangle, Ban, CheckCircle2, ClipboardCheck, Pencil, RefreshCcw, Rocket, Search } from "lucide-react";
import { formatDateTime } from "../../lib/format";
import { createOpenAgentUploadToken, getOpenAgentReleases, saveOpenAgentRelease, toggleOpenAgentRelease } from "../../services/adminApi";
import type { OpenAgentReleaseFilters } from "../../services/adminApi";
import type { OpenAgentRelease, OpenAgentReleaseInput } from "../../types";

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
const defaultOpenAgentReleaseForm: OpenAgentReleaseInput = {
  channel: "prod",
  version: "1.17.14",
  platform: "mac",
  arch: "arm64-dmg",
  file_url: "",
  file_sha512: "",
  file_size: 1,
  release_notes: "",
  is_active: true,
  is_mandatory: false,
};

const openAgentReleaseTargets = [
  { value: "mac-arm64-dmg", label: "macOS M 系列 DMG（安装包）", platform: "mac", arch: "arm64-dmg", expected: "openagent-mac-arm64.dmg" },
  { value: "mac-arm64", label: "macOS M 系列 ZIP（自动更新 / 免安装）", platform: "mac", arch: "arm64", expected: "openagent-mac-arm64.zip" },
  { value: "mac-x64-dmg", label: "macOS Intel DMG（安装包）", platform: "mac", arch: "x64-dmg", expected: "openagent-mac-x64.dmg" },
  { value: "mac-x64", label: "macOS Intel ZIP（自动更新 / 免安装）", platform: "mac", arch: "x64", expected: "openagent-mac-x64.zip" },
  { value: "windows-universal-installer", label: "Windows 合并安装包（x64 + 32 位）", platform: "windows", arch: "universal-installer", expected: "openagent-win-setup.exe" },
  { value: "windows-universal-portable", label: "Windows 合并免安装包（x64 + 32 位）", platform: "windows", arch: "universal-portable", expected: "openagent-win-portable.exe" },
] as const;

const releaseTargetLabel = (platform: string, arch: string) => {
  const target = openAgentReleaseTargets.find((item) => item.platform === platform && item.arch === arch);
  return target?.label ?? `${platform}/${arch}`;
};

const arrayBufferToBase64 = (buffer: ArrayBuffer) => {
  const bytes = new Uint8Array(buffer);
  const chunks: string[] = [];
  const chunkSize = 0x8000;
  for (let index = 0; index < bytes.length; index += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(index, index + chunkSize)));
  }
  return window.btoa(chunks.join(""));
};

export function OpenAgentReleasesPage() {
  const [items, setItems] = useState<OpenAgentRelease[]>([]);
  const [form, setForm] = useState<OpenAgentReleaseInput>(defaultOpenAgentReleaseForm);
  const [filters, setFilters] = useState<OpenAgentReleaseFilters>({ query: "", channel: "all", platform: "all", arch: "all", status: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [uploadState, setUploadState] = useState("");
  useAutoDismissNotice(notice, setNotice);

  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [filters.query, filters.channel, filters.platform, filters.arch, filters.status]);

  async function load() {
    setError("");
    try {
      const result = await getOpenAgentReleases(filters, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination((current) => ({ ...current, total: result.total, page: result.page, pageSize: result.page_size }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "OpenAgent 更新接口不可用");
    }
  }

  useEffect(() => { void load(); }, [filters, pagination.page, pagination.pageSize]);

  function editRelease(release: OpenAgentRelease) {
    setForm({
      channel: release.channel,
      version: release.version,
      platform: release.platform,
      arch: release.arch,
      file_url: release.file_url,
      file_sha512: release.file_sha512,
      file_size: release.file_size,
      release_notes: release.release_notes,
      is_active: release.is_active,
      is_mandatory: release.is_mandatory,
    });
    setNotice(`正在编辑 ${release.channel}/${release.arch} ${release.version}`);
  }

  function applyReleaseTarget(value: string) {
    const target = openAgentReleaseTargets.find((item) => item.value === value);
    if (!target) return;
    setForm((current) => ({ ...current, platform: target.platform, arch: target.arch }));
    setNotice(`已选择 ${target.label}，建议上传 ${target.expected}`);
  }

  async function uploadReleaseFile(file: File) {
    setError("");
    setNotice("");
    setUploadState("正在计算 sha512...");
    try {
      const digest = await window.crypto.subtle.digest("SHA-512", await file.arrayBuffer());
      const sha512 = arrayBufferToBase64(digest);
      setUploadState("正在获取七牛上传凭证...");
      const uploadToken = await createOpenAgentUploadToken(file.name);
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
        file_url: uploadToken.public_url,
        file_size: file.size,
        file_sha512: sha512,
      }));
      setNotice(`已上传 ${file.name}，下载地址和 sha512 已回填`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "七牛上传失败");
    } finally {
      setUploadState("");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const missingFields = [
      !form.version.trim() ? "版本号" : "",
      !form.file_url.trim() ? "下载 URL" : "",
      !form.file_sha512.trim() ? "sha512" : "",
    ].filter(Boolean);
    if (missingFields.length) {
      setError(`${missingFields.join("、")}不能为空`);
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveOpenAgentRelease({ ...form, version: form.version.trim(), file_url: form.file_url.trim(), file_sha512: form.file_sha512.trim() });
      setNotice(`已保存 ${saved.channel}/${saved.arch} ${saved.version}`);
      setForm(defaultOpenAgentReleaseForm);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "OpenAgent 更新版本保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function toggle(release: OpenAgentRelease) {
    setError("");
    setNotice("");
    try {
      const updated = await toggleOpenAgentRelease(release.id);
      setNotice(`${updated.channel}/${updated.arch} ${updated.version} 已${updated.is_active ? "启用" : "停用"}`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "状态更新失败");
    }
  }

  return (
    <PageChrome title="OpenAgent 更新" description="管理 OpenAgent 桌面端分频道、分架构更新包；客户端检查更新会读取 magic 这里生成的 latest-mac.yml。">
      <LoadState error={error && items.length === 0 ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <Rocket size={20} />
            <div>
              <h3>发布更新包</h3>
              <p>先把 zip/dmg 和 blockmap 上传到对象存储或静态目录，再把 electron-builder 生成的 sha512、size 和下载 URL 填到这里。</p>
            </div>
          </div>
          <div className="form-grid">
            <label className="field">频道
              <select value={form.channel} onChange={(event) => setForm({ ...form, channel: event.target.value as OpenAgentReleaseInput["channel"] })}>
                <option value="prod">prod</option>
                <option value="beta">beta</option>
              </select>
            </label>
            <label className="field">发布包类型
              <select value={`${form.platform}-${form.arch}`} onChange={(event) => applyReleaseTarget(event.target.value)}>
                {openAgentReleaseTargets.map((target) => <option key={target.value} value={target.value}>{target.label}</option>)}
              </select>
            </label>
            <label className="field">版本号<input value={form.version} onChange={(event) => setForm({ ...form, version: event.target.value })} placeholder="1.17.14" /></label>
            <label className="field">文件大小 bytes<input min={1} type="number" value={form.file_size} onChange={(event) => setForm({ ...form, file_size: Number(event.target.value) })} /></label>
            <label className="field wide">上传包到七牛
              <input type="file" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadReleaseFile(file); event.currentTarget.value = ""; }} />
              <small>{uploadState || "选择本地 dist 里的 dmg/zip/exe，上传后自动回填七牛 URL、base64 sha512 和文件大小。"}</small>
            </label>
            <label className="field wide">下载 URL<input value={form.file_url} onChange={(event) => setForm({ ...form, file_url: event.target.value })} placeholder="上传到七牛后自动回填，也可手动粘贴 CDN 地址" /></label>
            <label className="field wide">sha512<input value={form.file_sha512} onChange={(event) => setForm({ ...form, file_sha512: event.target.value })} placeholder="上传时自动计算；Mac 自动更新包必须是 base64 sha512" /></label>
            <label className="field wide">更新说明<textarea value={form.release_notes} onChange={(event) => setForm({ ...form, release_notes: event.target.value })} rows={3} /></label>
          </div>
          <div className="inline-hint">当前写入：{form.platform}/{form.arch}。其中 mac/arm64 与 mac/x64 会被 latest-mac.yml 更新接口读取；DMG 和 Windows 合并包用于用户下载页。</div>
          <div className="inline-actions">
            <label className="check-line"><input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} /> 启用发布</label>
            <label className="check-line"><input type="checkbox" checked={form.is_mandatory} onChange={(event) => setForm({ ...form, is_mandatory: event.target.checked })} /> 强制更新标记</label>
          </div>
          {error && items.length > 0 ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="secondary-button" type="button" onClick={() => setForm(defaultOpenAgentReleaseForm)}>清空</button>
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存发布"}</button>
          </div>
        </form>
      </section>

      <section className="panel">
        <div className="toolbar">
          <label className="search-field">
            <Search size={16} />
            <input value={filters.query ?? ""} onChange={(event) => setFilters({ ...filters, query: event.target.value })} placeholder="搜索版本、URL 或说明" />
          </label>
          <FilterSelect label="频道" value={filters.channel ?? "all"} onChange={(value) => setFilters({ ...filters, channel: value as OpenAgentReleaseFilters["channel"] })} options={[{ value: "all", label: "全部频道" }, { value: "prod", label: "prod" }, { value: "beta", label: "beta" }]} />
          <FilterSelect label="平台" value={filters.platform ?? "all"} onChange={(value) => setFilters({ ...filters, platform: value as OpenAgentReleaseFilters["platform"] })} options={[{ value: "all", label: "全部平台" }, { value: "mac", label: "macOS" }, { value: "windows", label: "Windows" }]} />
          <FilterSelect label="包类型" value={filters.arch ?? "all"} onChange={(value) => setFilters({ ...filters, arch: value })} options={[{ value: "all", label: "全部包" }, ...openAgentReleaseTargets.map((target) => ({ value: target.arch, label: target.label }))]} />
          <FilterSelect label="状态" value={filters.status ?? "all"} onChange={(value) => setFilters({ ...filters, status: value as OpenAgentReleaseFilters["status"] })} options={[{ value: "all", label: "全部状态" }, { value: "active", label: "启用" }, { value: "inactive", label: "停用" }]} />
        </div>
        <LoadState error="" empty={items.length === 0 && !error} onRetry={load} />
        <div className="table-wrap">
          <table>
            <thead><tr><th>频道</th><th>版本</th><th>平台</th><th>包类型</th><th>状态</th><th>大小</th><th>发布时间</th><th>文件</th><th>操作</th></tr></thead>
            <tbody>
              {items.map((release) => (
                <tr key={release.id}>
                  <td>{release.channel}</td>
                  <td>{release.version}</td>
                  <td>{release.platform}</td>
                  <td>{releaseTargetLabel(release.platform, release.arch)}</td>
                  <td><StatusPill active={release.is_active} /></td>
                  <td>{release.file_size.toLocaleString("zh-CN")}</td>
                  <td>{release.published_at ? formatDateTime(release.published_at) : "-"}</td>
                  <td><a href={release.file_url} target="_blank" rel="noreferrer">打开</a></td>
                  <td className="table-actions">
                    <button className="secondary-button compact" onClick={() => editRelease(release)}><Pencil size={14} />编辑</button>
                    <button className="secondary-button compact" onClick={() => toggle(release)}>{release.is_active ? <Ban size={14} /> : <CheckCircle2 size={14} />}{release.is_active ? "停用" : "启用"}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination pagination={pagination} onChange={setPagination} />
      </section>
    </PageChrome>
  );
}

