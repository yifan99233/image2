import { FormEvent, useEffect, useMemo, useState } from "react";
import { Pencil, Plus, X } from "lucide-react";
import { formatCurrency } from "../../lib/format";
import { getBenefitPackages, grantBenefitPackage, saveBenefitPackage, toggleBenefitPackage, type BenefitPackageFilters } from "../../services/adminApi";
import type { BenefitGrantMode, BenefitPackage, BenefitResourceType } from "../../types";
import { FilterSelect, initialPagination, LoadState, PageChrome, Pagination, StatusPill, type PaginationState } from "./ManagementCommon";

type DraftItem = {
  resource_type: BenefitResourceType;
  amount: number;
  grant_mode: BenefitGrantMode;
  grant_count: number | null;
  scope: "user" | "team";
  aggregation_mode: "sum" | "max" | "replace";
  expiry_policy: "grant_period" | "package_end" | "permanent";
  sort_order: number;
};

type DraftPackage = {
  code: string;
  name: string;
  description: string;
  amountCents: number;
  currency: string;
  purchase_mode: "one_time" | "subscription";
  billing_interval: "month" | "quarter" | "year" | null;
  validity_mode: "fixed_days" | "billing_period" | "permanent";
  validity_value: number | null;
  activation_policy: "payment_success";
  timezone: string;
  stacking_policy: "reject" | "extend" | "stack";
  badge: string;
  sort_order: number;
  is_recommended: boolean;
  is_active: boolean;
  items: DraftItem[];
};

const resourceLabels: Record<BenefitResourceType, string> = {
  credits: "积分",
  team_seats: "团队人数",
  image_concurrency: "图片并发",
  video_concurrency: "视频并发",
  task_queue_limit: "排队任务数",
  api_quota: "API 调用额度",
  storage_quota: "存储空间",
};

const resourceTypes = Object.keys(resourceLabels) as BenefitResourceType[];

const emptyItem = (): DraftItem => ({ resource_type: "credits", amount: 1000, grant_mode: "one_time", grant_count: null, scope: "team", aggregation_mode: "sum", expiry_policy: "package_end", sort_order: 50 });

const emptyDraft = (): DraftPackage => ({ code: "", name: "", description: "", amountCents: 9900, currency: "CNY", purchase_mode: "one_time", billing_interval: null, validity_mode: "fixed_days", validity_value: 30, activation_policy: "payment_success", timezone: "Asia/Shanghai", stacking_policy: "reject", badge: "", sort_order: 50, is_recommended: false, is_active: true, items: [emptyItem()] });

function draftFromPackage(packageItem: BenefitPackage): DraftPackage {
  return { code: packageItem.code, name: packageItem.name, description: packageItem.description, amountCents: packageItem.amount_cents, currency: packageItem.currency, purchase_mode: packageItem.purchase_mode, billing_interval: packageItem.billing_interval, validity_mode: packageItem.validity_mode, validity_value: packageItem.validity_value, activation_policy: packageItem.activation_policy, timezone: packageItem.timezone, stacking_policy: packageItem.stacking_policy, badge: packageItem.badge ?? "", sort_order: packageItem.sort_order, is_recommended: packageItem.is_recommended, is_active: packageItem.is_active, items: packageItem.items.map(({ id: _id, value_type: _valueType, ...item }) => ({ ...item })) };
}

function PackageEditor({ packageItem, onClose, afterDone }: { packageItem?: BenefitPackage; onClose: () => void; afterDone: () => void }) {
  const [draft, setDraft] = useState<DraftPackage>(() => packageItem ? draftFromPackage(packageItem) : emptyDraft());
  const [amountYuan, setAmountYuan] = useState(() => ((packageItem?.amount_cents ?? 9900) / 100).toFixed(2));
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const updateItem = (index: number, patch: Partial<DraftItem>) => setDraft((current) => ({ ...current, items: current.items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item) }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const amountCents = Math.round(Number(amountYuan) * 100);
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(draft.code)) return setError("套餐编码只能使用小写字母、数字、下划线和短横线");
    if (!draft.name.trim() || amountCents <= 0 || draft.items.length === 0) return setError("请填写套餐名称、有效价格，并至少配置一项权益");
    if (draft.purchase_mode === "subscription" && !draft.billing_interval) return setError("订阅套餐必须选择周期");
    if (draft.validity_mode === "fixed_days" && (!draft.validity_value || draft.validity_value <= 0)) return setError("固定有效期必须大于 0 天");
    if (draft.items.some((item) => item.amount <= 0 || (item.grant_mode !== "one_time" && (!item.grant_count || item.grant_count <= 0)))) return setError("权益数量和周期发放次数必须大于 0");
    setSaving(true);
    setError("");
    try {
      const { amountCents: _amountCents, ...draftFields } = draft;
      await saveBenefitPackage({ ...draftFields, amount_cents: amountCents, badge: draft.badge || null, items: draft.items }, packageItem?.id);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "权益套餐保存失败");
    } finally {
      setSaving(false);
    }
  }

  return <div className="modal-backdrop" role="dialog" aria-modal="true"><form className="modal modal--wide" onSubmit={submit}>
    <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
    <h3>{packageItem ? "编辑权益套餐" : "新增权益套餐"}</h3>
    <div className="form-grid">
      <label className="field">套餐编码<input value={draft.code} disabled={Boolean(packageItem)} onChange={(event) => setDraft({ ...draft, code: event.target.value })} /></label>
      <label className="field">套餐名称<input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
      <label className="field">价格（元）<input min={0.01} step={0.01} type="number" value={amountYuan} onChange={(event) => setAmountYuan(event.target.value)} /></label>
      <label className="field">购买模式<select value={draft.purchase_mode} onChange={(event) => { const purchaseMode = event.target.value as DraftPackage["purchase_mode"]; setDraft({ ...draft, purchase_mode: purchaseMode, billing_interval: purchaseMode === "subscription" ? "month" : null, validity_mode: purchaseMode === "subscription" ? "billing_period" : (draft.validity_mode === "billing_period" ? "fixed_days" : draft.validity_mode), validity_value: purchaseMode === "subscription" ? null : (draft.validity_mode === "billing_period" ? 30 : draft.validity_value) }); }}><option value="one_time">一次性购买</option><option value="subscription">订阅（待支付接入）</option></select></label>
      {draft.purchase_mode === "subscription" ? <label className="field">订阅周期<select value={draft.billing_interval ?? "month"} onChange={(event) => setDraft({ ...draft, billing_interval: event.target.value as DraftPackage["billing_interval"] })}><option value="month">月付</option><option value="quarter">季付</option><option value="year">年付</option></select></label> : null}
      <label className="field">有效期<select value={draft.validity_mode} onChange={(event) => setDraft({ ...draft, validity_mode: event.target.value as DraftPackage["validity_mode"], validity_value: event.target.value === "fixed_days" ? (draft.validity_value || 30) : null })}><option value="fixed_days">固定天数</option><option value="billing_period">订阅周期</option><option value="permanent">永久</option></select></label>
      {draft.validity_mode === "fixed_days" ? <label className="field">有效天数<input min={1} type="number" value={draft.validity_value ?? 30} onChange={(event) => setDraft({ ...draft, validity_value: Number(event.target.value) })} /></label> : null}
      <label className="field">激活方式<select value={draft.activation_policy} disabled><option value="payment_success">支付成功立即生效</option></select></label>
      <label className="field">叠加策略<select value={draft.stacking_policy} onChange={(event) => setDraft({ ...draft, stacking_policy: event.target.value as DraftPackage["stacking_policy"] })}><option value="reject">禁止重复购买</option><option value="extend">顺延有效期</option><option value="stack">权益数量叠加</option></select></label>
      <label className="field">标签<input value={draft.badge} onChange={(event) => setDraft({ ...draft, badge: event.target.value })} /></label>
      <label className="field">排序<input type="number" value={draft.sort_order} onChange={(event) => setDraft({ ...draft, sort_order: Number(event.target.value) })} /></label>
    </div>
    <label className="field">说明<textarea rows={2} value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
    <section className="panel panel--nested"><div className="panel-heading"><div><h4>套餐权益</h4><p>模型权限和分辨率不作为套餐权益。</p></div><button className="secondary-button compact" type="button" onClick={() => setDraft((current) => ({ ...current, items: [...current.items, emptyItem()] }))}><Plus size={14} />添加权益</button></div>
      {draft.items.map((item, index) => <div className="form-grid" key={`${item.resource_type}-${index}`}>
        <label className="field">权益<select value={item.resource_type} onChange={(event) => updateItem(index, { resource_type: event.target.value as BenefitResourceType })}>{resourceTypes.map((type) => <option key={type} value={type}>{resourceLabels[type]}</option>)}</select></label>
        <label className="field">数量<input min={0.01} step={0.01} type="number" value={item.amount} onChange={(event) => updateItem(index, { amount: Number(event.target.value) })} /></label>
        <label className="field">发放方式<select value={item.grant_mode} onChange={(event) => updateItem(index, { grant_mode: event.target.value as BenefitGrantMode, grant_count: event.target.value === "one_time" ? null : (item.grant_count || 30) })}><option value="one_time">一次性</option><option value="daily">按天</option><option value="weekly">按周</option></select></label>
        {item.grant_mode !== "one_time" ? <label className="field">发放次数<input min={1} type="number" value={item.grant_count ?? 1} onChange={(event) => updateItem(index, { grant_count: Number(event.target.value) })} /></label> : null}
        <label className="field">有效期<select value={item.expiry_policy} onChange={(event) => updateItem(index, { expiry_policy: event.target.value as DraftItem["expiry_policy"] })}><option value="grant_period">到下一次发放</option><option value="package_end">到套餐结束</option><option value="permanent">永久</option></select></label>
        <label className="field">作用范围<select value={item.scope} onChange={(event) => updateItem(index, { scope: event.target.value as DraftItem["scope"] })}><option value="team">团队</option><option value="user">个人</option></select></label>
        <label className="field">叠加计算<select value={item.aggregation_mode} onChange={(event) => updateItem(index, { aggregation_mode: event.target.value as DraftItem["aggregation_mode"] })}><option value="sum">数量相加</option><option value="max">取最大值</option><option value="replace">最新替换</option></select></label>
        {draft.items.length > 1 ? <button className="secondary-button compact" type="button" onClick={() => setDraft((current) => ({ ...current, items: current.items.filter((_, itemIndex) => itemIndex !== index) }))}>删除</button> : null}
      </div>)}
    </section>
    <label className="check-line"><input type="checkbox" checked={draft.is_recommended} onChange={(event) => setDraft({ ...draft, is_recommended: event.target.checked })} /> 推荐套餐</label>
    {error ? <div className="form-error">{error}</div> : null}
    <div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>取消</button><button className="primary-button" disabled={saving}>{saving ? "保存中" : "保存套餐"}</button></div>
  </form></div>;
}

function ManualGrantDialog({ packageItem, onClose, afterDone }: { packageItem: BenefitPackage; onClose: () => void; afterDone: () => void }) {
  const [userId, setUserId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [startsAt, setStartsAt] = useState("");
  const [reason, setReason] = useState("后台开通权益套餐");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const parsedUserId = Number(userId);
    const parsedTeamId = teamId ? Number(teamId) : null;
    if (!Number.isInteger(parsedUserId) || parsedUserId <= 0) return setError("请输入有效的用户 ID");
    if (parsedTeamId !== null && (!Number.isInteger(parsedTeamId) || parsedTeamId <= 0)) return setError("团队 ID 必须是正整数");
    if (!reason.trim()) return setError("请填写开通原因");
    setSaving(true);
    setError("");
    try {
      await grantBenefitPackage(packageItem.id, {
        user_id: parsedUserId,
        team_id: parsedTeamId,
        starts_at: startsAt ? new Date(startsAt).toISOString() : null,
        reason: reason.trim(),
      });
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "后台开通失败");
    } finally {
      setSaving(false);
    }
  }

  return <div className="modal-backdrop" role="dialog" aria-modal="true"><form className="modal" onSubmit={submit}>
    <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
    <h3>后台开通套餐</h3>
    <p className="modal-description">{packageItem.name} · 不经过支付，直接按套餐配置发放权益。团队套餐可留空团队 ID，系统会尝试使用用户作为所有者的团队。</p>
    <label className="field">用户 ID<input type="number" min={1} value={userId} onChange={(event) => setUserId(event.target.value)} placeholder="例如 10001" /></label>
    <label className="field">团队 ID（可选）<input type="number" min={1} value={teamId} onChange={(event) => setTeamId(event.target.value)} placeholder="团队权益建议填写" /></label>
    <label className="field">开始时间（可选）<input type="datetime-local" value={startsAt} onChange={(event) => setStartsAt(event.target.value)} /><small>留空立即生效，填写未来时间则按计划时间生效。</small></label>
    <label className="field">开通原因<textarea rows={3} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
    {error ? <div className="form-error">{error}</div> : null}
    <div className="modal-actions"><button className="secondary-button" type="button" onClick={onClose}>取消</button><button className="primary-button" disabled={saving}>{saving ? "开通中" : "确认开通"}</button></div>
  </form></div>;
}

export function BenefitPackagesPage() {
  const [items, setItems] = useState<BenefitPackage[]>([]);
  const [filters, setFilters] = useState<BenefitPackageFilters>({ status: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  const [error, setError] = useState("");
  const [editor, setEditor] = useState<BenefitPackage | null | undefined>(undefined);
  const [grantPackage, setGrantPackage] = useState<BenefitPackage | null>(null);

  async function load() {
    try {
      setError("");
      const result = await getBenefitPackages(filters, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "权益套餐接口不可用");
    }
  }

  useEffect(() => { setPagination((current) => ({ ...current, page: 1 })); }, [filters.status]);
  useEffect(() => { void load(); }, [filters.status, pagination.page, pagination.pageSize]);
  const statusOptions = useMemo(() => [{ value: "all", label: "全部" }, { value: "active", label: "已上架" }, { value: "inactive", label: "已下架" }], []);

  return <PageChrome title="权益套餐" description="自由组合积分、团队人数、并发、任务容量、API 和存储权益，并配置价格与发放周期。" action={<button className="primary-button compact" onClick={() => setEditor(null)}><Plus size={15} />新增套餐</button>}>
    <div className="filter-toolbar"><FilterSelect label="状态" value={filters.status ?? "all"} options={statusOptions} onChange={(value) => setFilters({ status: value as BenefitPackageFilters["status"] })} /></div>
    <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
    <section className="panel"><div className="table-wrap"><table><thead><tr><th>套餐</th><th>价格</th><th>购买模式</th><th>有效期</th><th>权益</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((packageItem) => <tr key={packageItem.id}><td><strong>{packageItem.name}</strong><small>{packageItem.code}</small></td><td>{formatCurrency(packageItem.amount_cents)}</td><td>{packageItem.purchase_mode === "subscription" ? `订阅（待支付接入） · ${packageItem.billing_interval}` : "一次性"}</td><td>{packageItem.validity_mode === "fixed_days" ? `${packageItem.validity_value} 天` : packageItem.validity_mode === "permanent" ? "永久" : "订阅周期"}</td><td>{packageItem.items.map((item) => `${resourceLabels[item.resource_type]} ${item.amount}${item.grant_mode === "one_time" ? "" : ` · ${item.grant_mode === "daily" ? "每日" : "每周"} ${item.grant_count} 次`}`).join("；")}</td><td>v{packageItem.version}</td><td><StatusPill active={packageItem.is_active} /></td><td className="row-actions"><button className="secondary-button compact" onClick={() => setGrantPackage(packageItem)}>后台开通</button><button className="secondary-button compact" onClick={() => setEditor(packageItem)}><Pencil size={14} />编辑</button><button className="secondary-button compact" onClick={async () => { await toggleBenefitPackage(packageItem.id); await load(); }}>{packageItem.is_active ? "下架" : "上架"}</button></td></tr>)}</tbody></table></div></section>
    <Pagination pagination={pagination} onChange={setPagination} />
    {editor !== undefined ? <PackageEditor packageItem={editor ?? undefined} onClose={() => setEditor(undefined)} afterDone={load} /> : null}
    {grantPackage ? <ManualGrantDialog packageItem={grantPackage} onClose={() => setGrantPackage(null)} afterDone={load} /> : null}
  </PageChrome>;
}
