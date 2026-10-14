import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Check, CircleAlert, Clipboard, Code2, Eye, EyeOff, KeyRound, LoaderCircle, Pencil, Plus, RefreshCw, Trash2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { opencodeService } from "@/services/opencode";
import { loadSiteConfig, readCachedSiteConfig } from "@/services/siteConfigStore";
import type { OpenAgentKey, OpenAgentKeyCreateInput, OpenAgentKeyGroup, OpenAgentKeyPage, OpenAgentKeyUpdateInput, SiteConfig } from "@/types/api";
import { buildCcsImportUrl } from "@/utils/ccswitch";
import { formatDateTime } from "@/utils/time";

type KeyFormState = {
  name: string;
  groupId: string;
  quota: string;
  expirationEnabled: boolean;
  expirationDays: string;
  expirationAt: string;
  rateLimit5h: string;
  rateLimit1d: string;
  rateLimit7d: string;
  ipWhitelist: string;
  ipBlacklist: string;
  status: "active" | "inactive";
};

const emptyForm = (groups: OpenAgentKeyGroup[]): KeyFormState => ({
  name: "",
  groupId: groups[0] ? String(groups[0].id) : "",
  quota: "0",
  expirationEnabled: false,
  expirationDays: "30",
  expirationAt: "",
  rateLimit5h: "0",
  rateLimit1d: "0",
  rateLimit7d: "0",
  ipWhitelist: "",
  ipBlacklist: "",
  status: "active",
});

const toLocalDateTime = (value?: string | null) => {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
};

const parseAmount = (value: string, label: string) => {
  const amount = Number(value || 0);
  if (!Number.isFinite(amount) || amount < 0) throw new Error(`${label}不能小于 0`);
  return amount;
};

const parseLines = (value: string) => value.split(/\r?\n|,/).map((line) => line.trim()).filter(Boolean);

const keyStatusLabel = (status: string) => ({
  active: "正常",
  inactive: "已停用",
  quota_exhausted: "额度已用完",
  expired: "已过期",
}[status] || status || "未知");

const maskKey = (key: string) => key.length <= 18 ? `${key.slice(0, 5)}••••${key.slice(-4)}` : `${key.slice(0, 10)}••••••••••${key.slice(-6)}`;

function KeyEditor({
  groups,
  keyItem,
  onClose,
  onSave,
}: {
  groups: OpenAgentKeyGroup[];
  keyItem: OpenAgentKey | null;
  onClose: () => void;
  onSave: (input: OpenAgentKeyCreateInput | OpenAgentKeyUpdateInput) => Promise<void>;
}) {
  const [form, setForm] = useState<KeyFormState>(() => keyItem ? {
    name: keyItem.name,
    groupId: keyItem.group ? String(keyItem.group.id) : groups[0] ? String(groups[0].id) : "",
    quota: String(keyItem.quota),
    expirationEnabled: Boolean(keyItem.expires_at),
    expirationDays: "30",
    expirationAt: toLocalDateTime(keyItem.expires_at),
    rateLimit5h: String(keyItem.rate_limit_5h),
    rateLimit1d: String(keyItem.rate_limit_1d),
    rateLimit7d: String(keyItem.rate_limit_7d),
    ipWhitelist: keyItem.ip_whitelist.join("\n"),
    ipBlacklist: keyItem.ip_blacklist.join("\n"),
    status: keyItem.status === "inactive" ? "inactive" : "active",
  } : emptyForm(groups));
  const [error, setError] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape" && !isSaving) onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSaving, onClose]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const groupId = Number(form.groupId);
      if (!form.name.trim()) throw new Error("请输入 Key 名称");
      if (!Number.isInteger(groupId) || groupId <= 0) throw new Error("请选择分组");
      const common = {
        name: form.name.trim(),
        group_id: groupId,
        quota: parseAmount(form.quota, "额度"),
        rate_limit_5h: parseAmount(form.rateLimit5h, "5 小时限额"),
        rate_limit_1d: parseAmount(form.rateLimit1d, "每日限额"),
        rate_limit_7d: parseAmount(form.rateLimit7d, "每周限额"),
        ip_whitelist: parseLines(form.ipWhitelist),
        ip_blacklist: parseLines(form.ipBlacklist),
      };
      const input = keyItem ? {
        ...common,
        status: form.status,
        expires_at: form.expirationEnabled && form.expirationAt ? new Date(form.expirationAt).toISOString() : "",
      } satisfies OpenAgentKeyUpdateInput : {
        ...common,
        expires_in_days: form.expirationEnabled ? Math.max(1, Number(form.expirationDays) || 30) : null,
      } satisfies OpenAgentKeyCreateInput;
      setError("");
      setIsSaving(true);
      await onSave(input);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Key 保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  return <div className="modal-backdrop opencode-key-backdrop" role="presentation" onMouseDown={() => !isSaving && onClose()}>
    <form className="opencode-key-dialog" role="dialog" aria-modal="true" aria-labelledby="key-dialog-title" onMouseDown={(event) => event.stopPropagation()} onSubmit={submit}>
      <button className="opencode-key-dialog__close" type="button" aria-label="关闭" disabled={isSaving} onClick={onClose}><X size={18} /></button>
      <header><span><KeyRound size={18} /></span><div><h2 id="key-dialog-title">{keyItem ? "编辑 Key" : "创建 Key"}</h2><p>选择当前站点可用分组，并配置这把 Key 的使用边界。</p></div></header>
      <div className="opencode-key-form-grid">
        <label>Key 名称<input value={form.name} maxLength={120} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} autoFocus /></label>
        <label>分组<select value={form.groupId} onChange={(event) => setForm((current) => ({ ...current, groupId: event.target.value }))}>{groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}</select></label>
        <label>总额度<input type="number" min="0" step="0.0001" value={form.quota} onChange={(event) => setForm((current) => ({ ...current, quota: event.target.value }))} /><small>0 表示不限额</small></label>
        {keyItem ? <label>状态<select value={form.status} onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as "active" | "inactive" }))}><option value="active">正常</option><option value="inactive">停用</option></select></label> : null}
      </div>
      <section className="opencode-key-form-section">
        <label className="opencode-toggle"><input type="checkbox" checked={form.expirationEnabled} onChange={(event) => setForm((current) => ({ ...current, expirationEnabled: event.target.checked }))} /><span>设置有效期</span></label>
        {form.expirationEnabled ? keyItem ? <label>到期时间<input type="datetime-local" value={form.expirationAt} onChange={(event) => setForm((current) => ({ ...current, expirationAt: event.target.value }))} /></label> : <label>有效天数<input type="number" min="1" max="3650" value={form.expirationDays} onChange={(event) => setForm((current) => ({ ...current, expirationDays: event.target.value }))} /></label> : null}
      </section>
      <section className="opencode-key-form-section"><h3>窗口限额</h3><div className="opencode-key-form-grid opencode-key-form-grid--three"><label>5 小时<input type="number" min="0" step="0.0001" value={form.rateLimit5h} onChange={(event) => setForm((current) => ({ ...current, rateLimit5h: event.target.value }))} /></label><label>每日<input type="number" min="0" step="0.0001" value={form.rateLimit1d} onChange={(event) => setForm((current) => ({ ...current, rateLimit1d: event.target.value }))} /></label><label>每周<input type="number" min="0" step="0.0001" value={form.rateLimit7d} onChange={(event) => setForm((current) => ({ ...current, rateLimit7d: event.target.value }))} /></label></div><small>0 表示对应窗口不限额。</small></section>
      <details className="opencode-key-network"><summary>IP 访问限制（可选）</summary><div><label>白名单<textarea rows={3} value={form.ipWhitelist} placeholder="每行一个 IP 或 CIDR" onChange={(event) => setForm((current) => ({ ...current, ipWhitelist: event.target.value }))} /></label><label>黑名单<textarea rows={3} value={form.ipBlacklist} placeholder="每行一个 IP 或 CIDR" onChange={(event) => setForm((current) => ({ ...current, ipBlacklist: event.target.value }))} /></label></div></details>
      {error ? <p className="opencode-key-form-error"><CircleAlert size={16} />{error}</p> : null}
      <footer><Button variant="secondary" type="button" disabled={isSaving} onClick={onClose}>取消</Button><Button type="submit" isLoading={isSaving}>{keyItem ? "保存修改" : "创建 Key"}</Button></footer>
    </form>
  </div>;
}

export function OpenAgentKeysPage() {
  const [keyPage, setKeyPage] = useState<OpenAgentKeyPage | null>(null);
  const [siteConfig, setSiteConfig] = useState<SiteConfig>(readCachedSiteConfig);
  const [revealed, setRevealed] = useState<Set<number>>(new Set());
  const [editingKey, setEditingKey] = useState<OpenAgentKey | null | undefined>(undefined);
  const [deletingKey, setDeletingKey] = useState<OpenAgentKey | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [copiedBaseUrl, setCopiedBaseUrl] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDeleting, setIsDeleting] = useState(false);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError("");
    try {
      setKeyPage(await opencodeService.getKeys());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Key 列表加载失败");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { loadSiteConfig().then(setSiteConfig).catch(() => undefined); }, []);

  const totalUsed = useMemo(() => keyPage?.total_used ?? keyPage?.items.reduce((sum, key) => sum + key.total_actual_cost, 0) ?? 0, [keyPage]);
  const todayUsed = useMemo(() => keyPage?.today_used ?? keyPage?.items.reduce((sum, key) => sum + key.today_actual_cost, 0) ?? 0, [keyPage]);

  async function copyKey(key: OpenAgentKey) {
    await navigator.clipboard.writeText(key.key);
    setCopiedId(key.id);
    setNotice(`已复制 ${key.name}`);
    window.setTimeout(() => setCopiedId((current) => current === key.id ? null : current), 1800);
  }

  async function copyBaseUrl() {
    if (!keyPage?.api_base_url) return;
    await navigator.clipboard.writeText(keyPage.api_base_url);
    setCopiedBaseUrl(true);
    setNotice("Base URL 已复制");
    window.setTimeout(() => setCopiedBaseUrl(false), 1800);
  }

  function importToCcs(key: OpenAgentKey, app?: "opencode") {
    if (!keyPage?.api_base_url) { setError("API 地址尚未配置"); return; }
    try {
      setError("");
      window.location.href = buildCcsImportUrl(
        key,
        keyPage.api_base_url,
        siteConfig.site_name,
        app ? { app } : undefined,
      );
      window.setTimeout(() => { if (document.hasFocus()) setNotice("如果 CC Switch 未自动打开，请先安装客户端后重试。"); }, 500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CC Switch 导入配置生成失败");
    }
  }

  async function saveKey(input: OpenAgentKeyCreateInput | OpenAgentKeyUpdateInput) {
    if (editingKey) await opencodeService.updateKey(editingKey.id, input as OpenAgentKeyUpdateInput);
    else await opencodeService.createKey(input as OpenAgentKeyCreateInput);
    setNotice(editingKey ? "Key 已更新" : "Key 已创建");
    await load();
  }

  async function deleteKey() {
    if (!deletingKey) return;
    setIsDeleting(true);
    try {
      await opencodeService.deleteKey(deletingKey.id);
      setNotice("Key 已删除");
      setDeletingKey(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Key 删除失败");
    } finally {
      setIsDeleting(false);
    }
  }

  return <main className="opencode-page opencode-key-page">
    <header className="page-header opencode-key-page-header"><div className="tool-title"><span><KeyRound size={22} /></span><div><h1>Key 管理</h1><p>为当前账号创建和管理 API Key；团队成员的消费统一从团队总账户余额扣除。</p></div></div><div className="opencode-key-header-actions"><Button variant="secondary" isLoading={isLoading} onClick={() => void load()}><RefreshCw size={16} />刷新</Button><Button disabled={!keyPage?.groups.length} onClick={() => setEditingKey(null)}><Plus size={16} />创建 Key</Button></div></header>
    <section className="opencode-key-summary">{keyPage?.can_view_team_balance ? <article><span>团队总账户余额</span><strong>{keyPage.agent_balance?.toFixed(4) ?? "--"}</strong><small>仅团队管理员可见</small></article> : <article><span>我的今日用量</span><strong>{todayUsed.toFixed(4)}</strong><small>仅统计当前账号的 Key</small></article>}<article><span>我的 Key</span><strong>{keyPage?.items.length ?? "--"}</strong><small>仅显示当前账号创建的 Key</small></article><article><span>我的累计用量</span><strong>{totalUsed.toFixed(4)}</strong><small>按个人 Key 汇总</small></article></section>
    {keyPage?.api_base_url ? <section className="opencode-key-base-url"><div><span>Base URL</span><code>{keyPage.api_base_url}</code><small>用于 OpenCode、CC Switch 或兼容 OpenAI 的客户端</small></div><button type="button" onClick={() => void copyBaseUrl()}>{copiedBaseUrl ? <Check size={15} /> : <Clipboard size={15} />}{copiedBaseUrl ? "已复制" : "复制地址"}</button></section> : null}
    {notice ? <div className="opencode-key-notice"><Check size={16} />{notice}<button type="button" onClick={() => setNotice("")} aria-label="关闭提示"><X size={14} /></button></div> : null}
    {error ? <div className="list-state list-state--error"><span>{error}</span><button className="task-button task-button--blue" type="button" onClick={() => void load()}>生成 / 同步账户</button></div> : null}
    <section className="opencode-key-panel">
      {isLoading && !keyPage ? <div className="opencode-key-loading"><LoaderCircle className="spin" size={22} />正在同步 Key 与用量</div> : null}
      {!isLoading && keyPage?.items.length === 0 ? <div className="empty-state"><KeyRound size={34} /><h3>还没有可用 Key</h3><p>创建第一把 Key 后即可复制使用或一键导入 CCS。</p><Button disabled={!keyPage.groups.length} onClick={() => setEditingKey(null)}><Plus size={16} />创建 Key</Button></div> : null}
      {keyPage?.items.length ? <div className="opencode-key-table"><div className="opencode-key-table__head"><span>Key</span><span>分组 / 状态</span><span>额度与用量</span><span>并发 / 最近使用</span><span>有效期 / 创建时间</span><span>操作</span></div>{keyPage.items.map((key) => <article className="opencode-key-table__row" key={key.id}>
        <div className="opencode-key-cell opencode-key-identity" data-label="Key"><strong>{key.name}</strong><div className="opencode-key-secret"><code>{revealed.has(key.id) ? key.key : maskKey(key.key)}</code><button type="button" onClick={() => setRevealed((current) => { const next = new Set(current); if (next.has(key.id)) next.delete(key.id); else next.add(key.id); return next; })} aria-label={revealed.has(key.id) ? "隐藏 Key" : "显示 Key"}>{revealed.has(key.id) ? <EyeOff size={15} /> : <Eye size={15} />}</button><button type="button" onClick={() => void copyKey(key)} aria-label="复制 Key">{copiedId === key.id ? <Check size={15} /> : <Clipboard size={15} />}</button></div></div>
        <div className="opencode-key-cell opencode-key-group" data-label="分组 / 状态"><strong>{key.group?.name || "未分组"}</strong><span className={`opencode-key-status opencode-key-status--${key.status}`}>{keyStatusLabel(key.status)}</span></div>
        <div className="opencode-key-cell opencode-key-usage" data-label="额度与用量"><strong>{key.quota > 0 ? `${key.quota_used.toFixed(4)} / ${key.quota.toFixed(4)}` : `${key.quota_used.toFixed(4)} / 不限额`}</strong><span>今日 {key.today_actual_cost.toFixed(4)} · 累计 {key.total_actual_cost.toFixed(4)}</span>{key.rate_limit_5h > 0 || key.rate_limit_1d > 0 || key.rate_limit_7d > 0 ? <small>窗口 5h {key.usage_5h.toFixed(2)}/{key.rate_limit_5h || "∞"} · 1d {key.usage_1d.toFixed(2)}/{key.rate_limit_1d || "∞"} · 7d {key.usage_7d.toFixed(2)}/{key.rate_limit_7d || "∞"}</small> : null}</div>
        <div className="opencode-key-cell" data-label="并发 / 最近使用"><strong>{key.current_concurrency}{key.max_concurrency > 0 ? ` / ${key.max_concurrency}` : ""} 并发</strong><span>{key.last_used_at ? formatDateTime(key.last_used_at) : "尚未使用"}</span>{key.last_used_ip ? <small>{key.last_used_ip}</small> : null}</div>
        <div className="opencode-key-cell" data-label="有效期 / 创建时间"><strong>{key.expires_at ? formatDateTime(key.expires_at) : "长期有效"}</strong><span>创建于 {formatDateTime(key.created_at)}</span></div>
        <div className="opencode-key-cell opencode-key-actions" data-label="操作"><button type="button" onClick={() => importToCcs(key)}><Upload size={15} />导入 CCS</button><button type="button" onClick={() => importToCcs(key, "opencode")}><Code2 size={15} />导入 OpenCode</button><button type="button" onClick={() => setEditingKey(key)}><Pencil size={15} />编辑</button><button className="danger" type="button" onClick={() => setDeletingKey(key)}><Trash2 size={15} />删除</button></div>
      </article>)}</div> : null}
    </section>
    {editingKey !== undefined && keyPage ? <KeyEditor groups={keyPage.groups} keyItem={editingKey} onClose={() => setEditingKey(undefined)} onSave={saveKey} /> : null}
    {deletingKey ? <div className="modal-backdrop opencode-key-backdrop" role="presentation" onMouseDown={() => !isDeleting && setDeletingKey(null)}><section className="opencode-key-confirm" role="dialog" aria-modal="true" aria-labelledby="delete-key-title" onMouseDown={(event) => event.stopPropagation()}><CircleAlert size={24} /><h2 id="delete-key-title">删除 {deletingKey.name}</h2><p>删除后该 Key 会立即失效，正在使用它的客户端将无法继续请求。此操作不可撤销。</p><footer><Button variant="secondary" disabled={isDeleting} onClick={() => setDeletingKey(null)}>取消</Button><Button variant="danger" isLoading={isDeleting} onClick={() => void deleteKey()}>删除 Key</Button></footer></section></div> : null}
  </main>;
}
