import { type FormEvent, useEffect, useState } from "react";
import { CheckCircle2, ClipboardCheck, CreditCard, Gift, Pencil, Plus, RefreshCcw, Route, Search, ShieldAlert, Sparkles, WalletCards } from "lucide-react";
import { formatCurrency, formatDateTime } from "../../lib/format";
import { zpayDefaultUrls } from "../../config/deployment";
import { getAgentConfig, getAgentGroups, getCreditLedgers, getInviteRewardConfig, getRechargeOrders, getRechargePlans, getUserExperienceConfig, getZPayConfig, markLedger, saveAgentConfig, saveInviteRewardConfig, saveZPayConfig, toggleRechargePlan, updateUserExperienceConfig } from "../../services/adminApi";
import type { RechargeOrderFilters, RechargePlanFilters } from "../../services/adminApi";
import type { AgentConfig, AgentConfigInput, AgentGroup, CreditLedger, InviteRewardConfig, RechargeOrder, RechargeOrderStatus, RechargePlan, UserExperienceConfig, ZPayConfig, ZPayConfigInput } from "../../types";
import { Dialog, type DialogState } from "./ManagementDialogs";
import { FilterSelect, initialPagination, LoadState, PageChrome, Pagination, StatusPill, Toolbar, type PaginationState, useAutoDismissNotice, useResetPageOnQuery } from "./ManagementCommon";

const bizLabel = {
  recharge: "充值",
  image_task: "图片任务",
  admin_adjustment: "人工调整",
  signin: "签到",
  redemption_gift: "兑换码赠送",
  invite: "邀请",
  reward: "奖励",
  refund: "退款",
};

const rechargeStatusOptions: Array<{ value: NonNullable<RechargePlanFilters["status"]>; label: string }> = [
  { value: "all", label: "全部" },
  { value: "active", label: "已上架" },
  { value: "inactive", label: "已下架" },
];

const rechargeOrderStatusLabel: Record<RechargeOrderStatus, string> = {
  pending: "待支付",
  paid: "已支付",
  cancelled: "已取消",
  failed: "失败",
  expired: "已过期",
};

const rechargeOrderStatusTone: Record<RechargeOrderStatus, "pending" | "paid" | "failed"> = {
  pending: "pending",
  paid: "paid",
  cancelled: "failed",
  failed: "failed",
  expired: "failed",
};

const rechargeOrderStatusOptions: Array<{ value: NonNullable<RechargeOrderFilters["status"]>; label: string }> = [
  { value: "all", label: "全部" },
  { value: "pending", label: "待支付" },
  { value: "paid", label: "已支付" },
  { value: "cancelled", label: "已取消" },
  { value: "failed", label: "失败" },
  { value: "expired", label: "已过期" },
];

export function CreditsPage() {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<CreditLedger[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);

  async function load() {
    setError("");
    try {
      const result = await getCreditLedgers(query, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "积分流水接口不可用");
    }
  }
  useResetPageOnQuery(query, setPagination);
  useEffect(() => { void load(); }, [query, pagination.page, pagination.pageSize]);

  return (
    <PageChrome title="积分流水" description="按用户、业务类型、订单号或任务号核查平台积分变动。">
      <Toolbar value={query} onChange={setQuery} placeholder="搜索用户、业务类型、订单号或任务号" />
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead><tr><th>用户</th><th>业务</th><th>变动</th><th>余额</th><th>关联单号</th><th>标记</th><th>时间</th><th>操作</th></tr></thead>
            <tbody>{items.map((item) => (
              <tr key={item.id}>
                <td>{item.username}</td><td>{bizLabel[item.biz_type]}</td><td className={item.change_amount >= 0 ? "amount-plus" : "amount-minus"}>{item.change_amount > 0 ? "+" : ""}{item.change_amount}</td><td>{item.balance_after}</td><td>{item.related_no}</td><td>{item.is_flagged ? <span className="status-pill failed" title={item.flag_reason ?? undefined}>异常</span> : <span className="status-pill paid">正常</span>}</td><td>{formatDateTime(item.created_at)}</td>
                <td><button className="secondary-button compact" disabled={item.is_flagged} onClick={() => setDialog({ kind: "reason", title: "标记异常流水", body: `${item.username} 的 ${item.related_no ?? item.id} 将被标记为异常并写入备注。`, confirmLabel: "标记异常", onConfirm: (reason) => markLedger(item.id, reason) })}><ShieldAlert size={14} />{item.is_flagged ? "已标记" : "标记"}</button></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export function RechargePlansPage() {
  const [items, setItems] = useState<RechargePlan[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<RechargePlanFilters>({ status: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  async function load() {
    setError("");
    try { const result = await getRechargePlans(filters, pagination.page, pagination.pageSize); setItems(result.items); setPagination({ page: result.page, pageSize: result.page_size, total: result.total }); } catch (err) { setItems([]); setError(err instanceof Error ? err.message : "充值档位接口不可用"); }
  }
  useEffect(() => { setPagination((current) => ({ ...current, page: 1 })); }, [filters.status]);
  useEffect(() => { void load(); }, [filters.status, pagination.page, pagination.pageSize]);
  return (
    <PageChrome title="充值档位" description="维护金额、到账积分和可选的团队席位权益；支付成功会按订单快照发放。" action={<button className="primary-button compact" onClick={() => setDialog({ kind: "plan" })}><Plus size={15} />新增档位</button>}>
      <div className="filter-toolbar">
        <div className="filter-group" role="group" aria-label="上下架状态">
          {rechargeStatusOptions.map((option) => (
            <button
              key={option.value}
              className={filters.status === option.value ? "active" : ""}
              type="button"
              onClick={() => setFilters((current) => ({ ...current, status: option.value as RechargePlanFilters["status"] }))}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <section className="panel"><div className="table-wrap"><table><thead><tr><th>名称</th><th>金额</th><th>基础积分</th><th>赠送</th><th>总到账</th><th>团队权益</th><th>标签</th><th>排序</th><th>状态</th><th>操作</th></tr></thead><tbody>{items.map((plan) => <tr key={plan.id}><td>{plan.name}</td><td>{formatCurrency(plan.amount_cents)}</td><td>{plan.credit_amount}</td><td>{plan.bonus_credit_amount}</td><td>{plan.credit_amount + plan.bonus_credit_amount}</td><td>{plan.team_seat_count > 0 ? `${plan.team_seat_count} 席 · ${plan.team_duration_days > 0 ? `${plan.team_duration_days} 天` : "永久"}` : "-"}</td><td>{plan.badge ?? "-"}</td><td>{plan.sort_order}</td><td><StatusPill active={plan.is_active} /></td><td className="row-actions"><button className="secondary-button compact" onClick={() => setDialog({ kind: "plan", plan })}><Pencil size={14} />编辑</button><button className="secondary-button compact" onClick={async () => { await toggleRechargePlan(plan.id); await load(); }}>{plan.is_active ? "下架" : "上架"}</button></td></tr>)}</tbody></table></div></section>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog state={dialog} onClose={() => setDialog({ kind: "none" })} afterDone={load} />
    </PageChrome>
  );
}

export function RechargeOrdersPage() {
  const [items, setItems] = useState<RechargeOrder[]>([]);
  const [error, setError] = useState("");
  const [filters, setFilters] = useState<RechargeOrderFilters>({ query: "", status: "all" });
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);

  async function load() {
    setError("");
    try {
      const result = await getRechargeOrders(filters, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "充值订单接口不可用");
    }
  }

  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [filters.query, filters.status]);
  useEffect(() => { void load(); }, [filters.query, filters.status, pagination.page, pagination.pageSize]);

  return (
    <PageChrome title="充值订单" description="查看用户充值订单、支付状态、到账积分和第三方交易号。">
      <div className="filter-toolbar">
        <label className="search-field">
          <Search size={16} />
          <input
            value={filters.query ?? ""}
            onChange={(event) => setFilters((current) => ({ ...current, query: event.target.value }))}
            placeholder="搜索订单号、交易号、用户名、邮箱或用户 ID"
          />
        </label>
        <div className="filter-group" role="group" aria-label="订单状态">
          {rechargeOrderStatusOptions.map((option) => (
            <button
              key={option.value}
              className={filters.status === option.value ? "active" : ""}
              type="button"
              onClick={() => setFilters((current) => ({ ...current, status: option.value }))}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <section className="panel">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>订单号</th>
                <th>用户</th>
                <th>金额</th>
                <th>到账积分</th>
                <th>团队权益</th>
                <th>支付</th>
                <th>状态</th>
                <th>交易号</th>
                <th>创建时间</th>
                <th>支付时间</th>
              </tr>
            </thead>
            <tbody>
              {items.map((order) => (
                <tr key={order.id}>
                  <td>{order.order_no}</td>
                  <td>{order.username}<small>{order.email || `用户 ID ${order.user_id}`}</small></td>
                  <td>{formatCurrency(order.amount_cents)}</td>
                  <td>{order.total_credit_amount.toLocaleString("zh-CN")}<small>基础 {order.credit_amount} / 赠送 {order.bonus_credit_amount}</small></td>
                  <td>{order.team_seat_count > 0 ? `${order.team_seat_count} 席 · ${order.team_duration_days > 0 ? `${order.team_duration_days} 天` : "永久"}` : "-"}</td>
                  <td>{order.payment_provider || "-"}<small>{order.payment_type || "-"}</small></td>
                  <td><span className={`status-pill ${rechargeOrderStatusTone[order.status]}`}>{rechargeOrderStatusLabel[order.status]}</span></td>
                  <td>{order.payment_trade_no || "-"}</td>
                  <td>{order.created_at ? formatDateTime(order.created_at) : "-"}</td>
                  <td>{order.paid_at ? formatDateTime(order.paid_at) : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
    </PageChrome>
  );
}

export function UserExperiencePage() {
  const [config, setConfig] = useState<UserExperienceConfig | null>(null);
  const [form, setForm] = useState({ max_batch_tasks: 50, qiniu_storage_enabled: false });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useAutoDismissNotice(notice, setNotice);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function load() {
    setError("");
    try {
      const nextConfig = await getUserExperienceConfig();
      setConfig(nextConfig);
      setForm({
        max_batch_tasks: nextConfig.max_batch_tasks,
        qiniu_storage_enabled: Boolean(nextConfig.qiniu_storage_enabled),
      });
    } catch (err) {
      setConfig(null);
      setError(err instanceof Error ? err.message : "用户体验配置接口不可用");
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!Number.isFinite(form.max_batch_tasks) || form.max_batch_tasks < 1) {
      setError("单次批量任务上限至少为 1");
      return;
    }
    if (form.max_batch_tasks > 20000) {
      setError("单次批量任务上限不能超过 20000");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await updateUserExperienceConfig({
        max_batch_tasks: Math.floor(form.max_batch_tasks),
        qiniu_storage_enabled: form.qiniu_storage_enabled,
      });
      setConfig(nextConfig);
      setForm({
        max_batch_tasks: nextConfig.max_batch_tasks,
        qiniu_storage_enabled: Boolean(nextConfig.qiniu_storage_enabled),
      });
      setNotice("用户体验配置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "用户体验配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="用户体验配置" description="控制用户端批量创作、图片存储等节点体验开关，修改后立即对用户端与任务写入生效。">
      <LoadState error={error && !config ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <Sparkles size={20} />
            <div>
              <h3>批量任务限制</h3>
              <p>限制批量生图、批量改图一次可提交的任务条数。用户端会展示该上限，后端也会按此值校验。</p>
            </div>
          </div>
          <div className="form-grid">
            <label className="field">
              单次批量任务上限
              <input
                min={1}
                max={20000}
                type="number"
                value={form.max_batch_tasks}
                onChange={(event) => setForm({ ...form, max_batch_tasks: Number(event.target.value) })}
              />
            </label>
            <label className="field">
              配置更新时间
              <input disabled value={config?.updated_at ? formatDateTime(config.updated_at) : "-"} />
            </label>
          </div>
          <div className="inline-state">
            <ClipboardCheck size={17} />
            <span>建议按服务器并发与队列承载能力调整，默认 50，最大 500。</span>
          </div>

          <div className="settings-form__head" style={{ marginTop: 24 }}>
            <Sparkles size={20} />
            <div>
              <h3>七牛云图片存储</h3>
              <p>控制当前节点新上传、新生成的图片是否写入七牛云。关闭后回退到 MinIO。历史图片 URL 保持不变。</p>
            </div>
          </div>
          <label className="check-line">
            <input
              type="checkbox"
              checked={form.qiniu_storage_enabled}
              onChange={(event) => setForm({ ...form, qiniu_storage_enabled: event.target.checked })}
            />
            启用七牛云云存储
          </label>
          <div className="inline-state">
            <ClipboardCheck size={17} />
            <span>
              {form.qiniu_storage_enabled
                ? "开启后新图片写入七牛（需服务器已配置 QINIU_ACCESS_KEY / QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_CDN_BASE_URL）。"
                : "关闭时新图片写入 MinIO。密钥与 CDN 域名仍由服务器环境变量提供，这里只控制是否启用。"}
            </span>
          </div>

          {error && config ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存配置"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}

export function InviteRewardPage() {
  const [config, setConfig] = useState<InviteRewardConfig | null>(null);
  const [form, setForm] = useState({ is_enabled: false, valid_user_reward_credits: 0, recharge_reward_percent: 0 });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useAutoDismissNotice(notice, setNotice);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function load() {
    setError("");
    try {
      const nextConfig = await getInviteRewardConfig();
      setConfig(nextConfig);
      setForm({
        is_enabled: nextConfig.is_enabled,
        valid_user_reward_credits: nextConfig.valid_user_reward_credits,
        recharge_reward_percent: nextConfig.recharge_reward_percent,
      });
    } catch (err) {
      setConfig(null);
      setError(err instanceof Error ? err.message : "邀请奖励配置接口不可用");
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.valid_user_reward_credits < 0) {
      setError("有效用户奖励积分不能小于 0");
      return;
    }
    if (form.recharge_reward_percent < 0 || form.recharge_reward_percent > 100) {
      setError("后续充值奖励比例必须在 0 到 100 之间");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await saveInviteRewardConfig(form);
      setConfig(nextConfig);
      setNotice("邀请奖励配置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "邀请奖励配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="邀请奖励" description="配置用户端邀请赚积分入口、有效用户奖励和后续充值奖励比例。">
      <LoadState error={error && !config ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <Gift size={20} />
            <div>
              <h3>邀请赚积分开关</h3>
              <p>关闭后用户端顶部不会展示“邀请赚积分”入口，直接访问页面也会显示活动未开启。</p>
            </div>
          </div>
          <label className="check-line"><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} /> 开启邀请赚积分</label>
          <div className="form-grid">
            <label className="field">邀请有效用户奖励积分<input min={0} type="number" value={form.valid_user_reward_credits} onChange={(event) => setForm({ ...form, valid_user_reward_credits: Number(event.target.value) })} /></label>
            <label className="field">后续充值奖励比例（%）<input min={0} max={100} type="number" value={form.recharge_reward_percent} onChange={(event) => setForm({ ...form, recharge_reward_percent: Number(event.target.value) })} /></label>
          </div>
          <div className="inline-state">
            <ClipboardCheck size={17} />
            <span>{config?.valid_user_rule_label ?? "被邀请用户完成首次付费充值后成为有效用户"}</span>
          </div>
          {error && config ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存配置"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}

const defaultZPayForm: ZPayConfigInput = {
  is_enabled: false,
  pid: "",
  pkey: "",
  api_base: "https://pay.example.com",
  notify_url: zpayDefaultUrls.notify,
  return_url: zpayDefaultUrls.return,
  payment_type: "alipay",
  payment_mode: "qrcode",
  timeout_seconds: 10,
  order_expire_minutes: 30,
};

export function ZPayConfigPage() {
  const [config, setConfig] = useState<ZPayConfig | null>(null);
  const [form, setForm] = useState<ZPayConfigInput>(defaultZPayForm);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  async function load() {
    setIsLoading(true);
    setError("");
    try {
      const nextConfig = await getZPayConfig();
      setConfig(nextConfig);
      setForm({
        is_enabled: nextConfig.is_enabled,
        pid: nextConfig.pid,
        pkey: "",
        api_base: nextConfig.api_base || defaultZPayForm.api_base,
        notify_url: nextConfig.notify_url || defaultZPayForm.notify_url,
        return_url: nextConfig.return_url || defaultZPayForm.return_url,
        payment_type: nextConfig.payment_type,
        payment_mode: nextConfig.payment_mode,
        timeout_seconds: nextConfig.timeout_seconds,
        order_expire_minutes: nextConfig.order_expire_minutes,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "ZPay 配置加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => { void load(); }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const saved = await saveZPayConfig(form);
      setConfig(saved);
      setForm((current) => ({ ...current, pkey: "" }));
      setNotice(saved.is_enabled ? "ZPay 支付已启用，用户端充值将读取当前配置。" : "ZPay 配置已保存，当前处于停用状态。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ZPay 配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="支付配置" description="配置用户端充值使用的 ZPay 商户参数、支付方式、回调地址和订单有效期。">
      <LoadState error={error && !config ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <CreditCard size={20} />
            <div>
              <h3>ZPay 商户配置</h3>
              <p>密钥只在保存时写入，页面不会明文回显。留空密钥表示沿用当前已保存密钥。</p>
            </div>
          </div>
          <label className="check-line">
            <input checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} type="checkbox" />
            启用 ZPay 支付
          </label>
          <div className="form-grid">
            <label className="field">商户 ID / PID<input value={form.pid} onChange={(event) => setForm({ ...form, pid: event.target.value })} placeholder="ZPay 分配的 pid" /></label>
            <label className="field">商户密钥 / PKEY<input value={form.pkey ?? ""} onChange={(event) => setForm({ ...form, pkey: event.target.value })} type="password" placeholder={config?.pkey_masked ? `当前 ${config.pkey_masked}，留空不修改` : "保存后不明文回显"} /></label>
            <label className="field wide">网关地址<input value={form.api_base} onChange={(event) => setForm({ ...form, api_base: event.target.value })} placeholder="https://pay.example.com" /></label>
            <label className="field wide">异步通知地址<input value={form.notify_url} onChange={(event) => setForm({ ...form, notify_url: event.target.value })} placeholder={zpayDefaultUrls.notify} /></label>
            <label className="field wide">同步返回地址<input value={form.return_url} onChange={(event) => setForm({ ...form, return_url: event.target.value })} placeholder={zpayDefaultUrls.return} /></label>
            <label className="field">支付类型
              <select value={form.payment_type} onChange={(event) => setForm({ ...form, payment_type: event.target.value as ZPayConfigInput["payment_type"] })}>
                <option value="alipay">支付宝</option>
                <option value="wxpay">微信支付</option>
                <option value="qqpay">QQ 钱包</option>
                <option value="bank">网银</option>
                <option value="jdpay">京东支付</option>
              </select>
            </label>
            <label className="field">收银模式
              <select value={form.payment_mode} onChange={(event) => setForm({ ...form, payment_mode: event.target.value as ZPayConfigInput["payment_mode"] })}>
                <option value="qrcode">二维码接口</option>
                <option value="popup">跳转收银台</option>
              </select>
            </label>
            <label className="field">请求超时（秒）<input min={3} max={60} type="number" value={form.timeout_seconds} onChange={(event) => setForm({ ...form, timeout_seconds: Number(event.target.value) })} /></label>
            <label className="field">订单有效期（分钟）<input min={1} max={1440} type="number" value={form.order_expire_minutes} onChange={(event) => setForm({ ...form, order_expire_minutes: Number(event.target.value) })} /></label>
          </div>
          {config?.updated_at ? <div className="inline-hint">最后更新：{formatDateTime(config.updated_at)}</div> : null}
          {error && config ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="secondary-button" type="button" disabled={isLoading} onClick={() => void load()}><RefreshCcw size={15} />重新加载</button>
            <button className="primary-button" disabled={isSubmitting || isLoading}>{isSubmitting ? "保存中" : "保存支付配置"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}

export function AgentPage() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [form, setForm] = useState<AgentConfigInput>({
    is_enabled: false,
    image_billing_enabled: false,
    base_url: "",
    admin_api_key: "",
    credit_to_agent_rate: 1,
    text_group_id: null,
    image_group_id: null,
    create_api_key_path: "",
    user_concurrency: 5,
    user_rpm_limit: 0,
  });
  const [groups, setGroups] = useState<AgentGroup[]>([]);
  const [isLoadingGroups, setIsLoadingGroups] = useState(false);
  const [error, setError] = useState("");
  const [groupError, setGroupError] = useState("");
  const [notice, setNotice] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  useAutoDismissNotice(notice, setNotice);

  async function fetchGroups(baseUrl: string, adminApiKey = "", showNotice = true) {
    setIsLoadingGroups(true);
    setGroupError("");
    if (showNotice) setNotice("");
    try {
      const nextGroups = await getAgentGroups({ base_url: baseUrl, admin_api_key: adminApiKey });
      setGroups(nextGroups);
      if (showNotice) setNotice(nextGroups.length ? `已查询到 ${nextGroups.length} 个分组` : "未查询到可用分组");
    } catch (err) {
      setGroups([]);
      setGroupError(err instanceof Error ? err.message : "分组查询失败");
    } finally {
      setIsLoadingGroups(false);
    }
  }

  async function loadConfig() {
    const nextConfig = await getAgentConfig();
    setConfig(nextConfig);
    const baseUrl = nextConfig.base_url || "";
    setForm({
      is_enabled: nextConfig.is_enabled,
      image_billing_enabled: nextConfig.image_billing_enabled,
      base_url: baseUrl,
      admin_api_key: "",
      credit_to_agent_rate: nextConfig.credit_to_agent_rate,
      text_group_id: nextConfig.text_group_id ?? null,
      image_group_id: nextConfig.image_group_id ?? null,
      create_api_key_path: "",
      user_concurrency: nextConfig.user_concurrency ?? 5,
      user_rpm_limit: nextConfig.user_rpm_limit,
    });
    await fetchGroups(baseUrl, "", false);
  }

  async function load() {
    setError("");
    try {
      await loadConfig();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent 配置接口不可用");
    }
  }

  useEffect(() => { void load(); }, []);

  async function loadGroups() {
    await fetchGroups(form.base_url, form.admin_api_key, true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (form.credit_to_agent_rate <= 0) {
      setError("积分兑换比例必须大于 0");
      return;
    }
    if (!Number.isInteger(form.credit_to_agent_rate)) {
      setError("积分兑换比例必须是正整数");
      return;
    }
    setIsSubmitting(true);
    setError("");
    setNotice("");
    try {
      const nextConfig = await saveAgentConfig(form);
      setConfig(nextConfig);
      setForm((current) => ({ ...current, admin_api_key: "" }));
      setNotice("Agent 配置已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Agent 配置保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <PageChrome title="配置" description="配置 Agent 服务、分组绑定、用户注册默认限制和图片计费兑换比例。">
      <LoadState error={error && !config ? error : ""} empty={false} onRetry={load} />
      <section className="panel">
        <form className="settings-form" onSubmit={submit}>
          <div className="settings-form__head">
            <Route size={20} />
            <div>
              <h3>Agent 服务配置</h3>
              <p>后台只配置服务和分组；用户注册后会自动创建 Agent 账号，并创建文本、图片两个 API Key。</p>
            </div>
          </div>
          <label className="check-line"><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} /> 开启 Agent 功能</label>
          <label className="check-line"><input type="checkbox" checked={form.image_billing_enabled} onChange={(event) => setForm({ ...form, image_billing_enabled: event.target.checked })} /> 图片和视频使用统一账户余额</label>
          <div className="form-grid">
            <label className="field">Base URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://agent.example.com" /></label>
            <label className="field">管理员 Key<input value={form.admin_api_key ?? ""} onChange={(event) => setForm({ ...form, admin_api_key: event.target.value })} type="password" placeholder={config?.admin_api_key_masked || "保存后不明文回显"} /></label>
            <label className="field">图片计费兑换比例<input min={1} step="1" type="number" value={form.credit_to_agent_rate} onChange={(event) => setForm({ ...form, credit_to_agent_rate: Number(event.target.value) })} /><small>1 表示 1 图片积分 = 1 账户余额；25 表示图片价格 25 积分时扣 1 账户余额。</small></label>
            <label className="field">默认并发<input min={0} type="number" value={form.user_concurrency} onChange={(event) => setForm({ ...form, user_concurrency: Number(event.target.value) })} /></label>
            <label className="field">默认 RPM<input min={0} type="number" value={form.user_rpm_limit} onChange={(event) => setForm({ ...form, user_rpm_limit: Number(event.target.value) })} /></label>
          </div>
          <div className="inline-actions">
            <button className="secondary-button" type="button" disabled={isLoadingGroups} onClick={loadGroups}><RefreshCcw size={16} />{isLoadingGroups ? "查询中" : "查询分组"}</button>
            <span className="muted">使用当前 Base URL 和管理员 Key 查询 sub2api 分组。</span>
          </div>
          {groupError ? <div className="form-error">{groupError}</div> : null}
          <div className="form-grid">
            <label className="field">文本分组
              <select value={form.text_group_id ?? ""} onChange={(event) => setForm({ ...form, text_group_id: event.target.value ? Number(event.target.value) : null })}>
                <option value="">请选择文本分组</option>
                {form.text_group_id && !groups.some((group) => group.id === form.text_group_id) ? <option value={form.text_group_id}>已保存分组 ID {form.text_group_id}</option> : null}
                {groups.map((group) => <option key={group.id} value={group.id}>{group.name}（ID {group.id}{group.platform ? ` · ${group.platform}` : ""}）</option>)}
              </select>
            </label>
            <label className="field">图片分组
              <select value={form.image_group_id ?? ""} onChange={(event) => setForm({ ...form, image_group_id: event.target.value ? Number(event.target.value) : null })}>
                <option value="">请选择图片分组</option>
                {form.image_group_id && !groups.some((group) => group.id === form.image_group_id) ? <option value={form.image_group_id}>已保存分组 ID {form.image_group_id}</option> : null}
                {groups.map((group) => <option key={group.id} value={group.id}>{group.name}（ID {group.id}{group.platform ? ` · ${group.platform}` : ""}）</option>)}
              </select>
            </label>
          </div>
          <div className="inline-state"><ClipboardCheck size={17} /><span>当前 Key：{config?.admin_api_key_masked || "未配置"}；更新时间：{config?.updated_at ? formatDateTime(config.updated_at) : "-"}</span></div>
          {error && config ? <div className="form-error">{error}</div> : null}
          {notice ? <section className="inline-result"><CheckCircle2 size={17} />{notice}</section> : null}
          <div className="modal-actions">
            <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中" : "保存配置"}</button>
          </div>
        </form>
      </section>
    </PageChrome>
  );
}
