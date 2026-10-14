import { customerVipLabel } from "./CustomerVipDialogs";
import { Ban, CheckCircle2, ClipboardCheck, Eye, KeyRound, LogIn, Search, SlidersHorizontal, UserCog, UsersRound, WalletCards, X } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { formatDateTime } from "../../lib/format";
import { usePermission } from "../../hooks/usePermission";
import { useAuth } from "../../store/auth";
import {
  adjustUserCredits,
  createUserImpersonation,
  getCustomerOwners,
  grantUserTeamEntitlement,
  getUserCreditBalance,
  getUsers,
  resetUserPassword,
  saveUserLeadModule,
  updateUserImageConcurrency,
  updateUserCustomerOwner,
  updateUserStatus,
  updateUserTags,
} from "../../services/adminApi";
import type { CustomerOwnerOption, ManagedUser, PageResult, UserLeadModuleInput } from "../../types";
import { useAutoDismissNotice } from "./ManagementCommon";

const defaultPageSize = 20;
const pageSizeOptions = [10, 20, 50, 100];

type PaginationState = {
  page: number;
  pageSize: number;
  total: number;
};

const initialPagination: PaginationState = { page: 1, pageSize: defaultPageSize, total: 0 };

type DialogState =
  | { kind: "none" }
  | { kind: "confirm"; title: string; body: string; confirmLabel: string; danger?: boolean; onConfirm: () => Promise<void> | void }
  | { kind: "credit"; user: ManagedUser }
  | { kind: "password"; user: ManagedUser }
  | { kind: "imageConcurrency"; user: ManagedUser }
  | { kind: "leadModule"; user: ManagedUser }
  | { kind: "teamEntitlement"; user: ManagedUser };

function PageChrome({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <section className="page-stack">
      <div className="page-heading">
        <div>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
      </div>
      {children}
    </section>
  );
}

function Toolbar({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
  return (
    <div className="filter-toolbar">
      <label className="search-field">
        <Search size={16} />
        <input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} />
      </label>
    </div>
  );
}

function StatusPill({ active }: { active: boolean }) {
  return <span className={`status-pill ${active ? "paid" : "failed"}`}>{active ? "启用" : "停用"}</span>;
}

function LoadState({ error, empty, onRetry }: { error: string; empty: boolean; onRetry: () => void }) {
  if (error) {
    return <div className="list-state error"><span>{error}</span><button className="secondary-button compact" onClick={onRetry}>重试</button></div>;
  }
  if (empty) return <div className="list-state">暂无数据</div>;
  return null;
}

function Pagination({ pagination, onChange }: { pagination: PaginationState; onChange: (updater: (current: PaginationState) => PaginationState) => void }) {
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize));
  return (
    <div className="pagination-bar">
      <span>共 {pagination.total} 条</span>
      <select value={pagination.pageSize} onChange={(event) => onChange((current) => ({ ...current, page: 1, pageSize: Number(event.target.value) }))}>
        {pageSizeOptions.map((size) => <option key={size} value={size}>{size} 条/页</option>)}
      </select>
      <button className="secondary-button compact" disabled={pagination.page <= 1} onClick={() => onChange((current) => ({ ...current, page: current.page - 1 }))}>上一页</button>
      <span>{pagination.page} / {totalPages}</span>
      <button className="secondary-button compact" disabled={pagination.page >= totalPages} onClick={() => onChange((current) => ({ ...current, page: current.page + 1 }))}>下一页</button>
    </div>
  );
}

function useResetPageOnQuery(query: string, setPagination: (updater: (current: PaginationState) => PaginationState) => void) {
  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [query, setPagination]);
}

function CreditDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [idempotencyKey] = useState(() => crypto.randomUUID().replaceAll("-", ""));
  const [mode, setMode] = useState<"increase" | "decrease">("increase");
  const [amount, setAmount] = useState(100);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentBalance, setCurrentBalance] = useState(user.credit_balance);
  const [balanceSource, setBalanceSource] = useState(user.credit_balance_source ?? "local");
  const [isBalanceLoading, setIsBalanceLoading] = useState(true);
  const [balanceNotice, setBalanceNotice] = useState("");
  const normalizedAmount = Math.max(0, Math.abs(amount));
  const signedAmount = mode === "increase" ? normalizedAmount : -normalizedAmount;
  const nextBalance = currentBalance + signedAmount;

  useEffect(() => {
    let cancelled = false;
    setIsBalanceLoading(true);
    setBalanceNotice("");
    void getUserCreditBalance(user.id)
      .then((result) => {
        if (cancelled) return;
        setCurrentBalance(result.balance);
        setBalanceSource(result.source);
        if (result.source === "local_fallback") {
          setBalanceNotice("实时钱包暂时不可用，当前展示的是本地缓存；提交后以上游返回结果为准。");
        }
      })
      .catch(() => {
        if (cancelled) return;
        setBalanceNotice("实时余额刷新失败，暂时沿用列表余额；请核对后再提交。");
      })
      .finally(() => {
        if (!cancelled) setIsBalanceLoading(false);
      });
    return () => { cancelled = true; };
  }, [user.id]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (normalizedAmount <= 0) return setError("调整积分必须大于 0");
    if (!reason.trim()) return setError("人工调整必须填写原因");
    setError("");
    setIsSubmitting(true);
    try {
      await adjustUserCredits(user.id, signedAmount, reason.trim(), idempotencyKey);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "积分调整失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭" disabled={isSubmitting}><X size={18} /></button>
        <h3>人工增减积分</h3>
        <p>
          {user.username} {isBalanceLoading ? "正在同步实时余额…" : `${balanceSource === "authoritative" ? "实时" : "当前"}余额 ${currentBalance.toLocaleString("zh-CN")}`}。
          团队成员共享同一钱包，请调整团队所有者。
        </p>
        {balanceNotice ? <div className="inline-state warning">{balanceNotice}</div> : null}
        <div className="segmented-control" role="group" aria-label="调整类型">
          <button className={mode === "increase" ? "active" : ""} type="button" onClick={() => setMode("increase")} disabled={isSubmitting}>增加</button>
          <button className={mode === "decrease" ? "active danger" : ""} type="button" onClick={() => setMode("decrease")} disabled={isSubmitting}>扣除</button>
        </div>
        <label className="field">{mode === "increase" ? "本次增加积分" : "本次扣除积分"}<input min={1} type="number" value={normalizedAmount} onChange={(event) => setAmount(Number(event.target.value))} disabled={isSubmitting} /></label>
        <div className={`balance-preview ${nextBalance < 0 ? "danger" : ""}`}><span>预计余额</span><strong>{isBalanceLoading ? "同步中…" : nextBalance.toLocaleString("zh-CN")}</strong></div>
        <label className="field">调整原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} disabled={isSubmitting} /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={isSubmitting}>取消</button>
          <button className={mode === "decrease" ? "danger-button" : "primary-button"} disabled={isSubmitting || isBalanceLoading}>
            {isSubmitting ? "处理中…" : mode === "increase" ? "确认增加" : "确认扣除"}
          </button>
        </div>
      </form>
    </div>
  );
}

function ImageConcurrencyDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [limit, setLimit] = useState(Math.max(1, user.image_concurrency_limit || 1));
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const nextLimit = Math.max(1, Math.floor(Number(limit) || 1));
    setError("");
    setIsSubmitting(true);
    try {
      await updateUserImageConcurrency(user.id, nextLimit);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "图片并发保存失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>图片并发上限</h3>
        <p>{user.username} 同时运行中的图片任务不会超过该数值。</p>
        <label className="field">并发上限<input min={1} type="number" value={limit} onChange={(event) => setLimit(Math.max(1, Number(event.target.value)))} /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "保存中..." : "保存并发上限"}</button>
        </div>
      </form>
    </div>
  );
}

function PasswordResetDialog({
  user,
  onClose,
  afterDone,
}: {
  user: ManagedUser;
  onClose: () => void;
  afterDone: () => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (newPassword.length < 8) return setError("新密码至少需要 8 位");
    if (newPassword.length > 128) return setError("新密码不能超过 128 位");
    if (newPassword !== confirmation) return setError("两次输入的密码不一致");
    setError("");
    setIsSubmitting(true);
    try {
      await resetUserPassword(user.id, newPassword);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "密码重置失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="password-reset-title">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭" disabled={isSubmitting}><X size={18} /></button>
        <h3 id="password-reset-title">重置用户密码</h3>
        <p>为 {user.username} 设置新密码。新密码用于后续登录；已签发的登录令牌不会立即失效。</p>
        <label className="field">新密码<input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={newPassword} onChange={(event) => setNewPassword(event.target.value)} disabled={isSubmitting} autoFocus /></label>
        <label className="field">确认新密码<input type="password" autoComplete="new-password" minLength={8} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={isSubmitting} /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={isSubmitting}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "重置中…" : "确认重置"}</button>
        </div>
      </form>
    </div>
  );
}

function LeadModuleDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [form, setForm] = useState<UserLeadModuleInput>({
    is_enabled: true,
    enterprise_id: "",
    enterprise_account: "",
    enterprise_password: "",
  });
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      await saveUserLeadModule(user.id, form);
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "客资模块保存失败");
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>客资模块</h3>
        <p>{user.username} 的客资账号开通信息。</p>
        <label className="check-line"><input type="checkbox" checked={form.is_enabled} onChange={(event) => setForm({ ...form, is_enabled: event.target.checked })} />启用客资模块</label>
        <label className="field">企业 ID<input value={form.enterprise_id ?? ""} onChange={(event) => setForm({ ...form, enterprise_id: event.target.value })} /></label>
        <label className="field">企业账号<input value={form.enterprise_account ?? ""} onChange={(event) => setForm({ ...form, enterprise_account: event.target.value })} /></label>
        <label className="field">企业密码<input value={form.enterprise_password ?? ""} onChange={(event) => setForm({ ...form, enterprise_password: event.target.value })} /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose}>取消</button>
          <button className="primary-button">保存</button>
        </div>
      </form>
    </div>
  );
}

function TeamEntitlementDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [seatCount, setSeatCount] = useState(3);
  const [durationDays, setDurationDays] = useState(0);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const seats = Math.floor(Number(seatCount) || 0);
    const duration = Math.floor(Number(durationDays) || 0);
    if (seats < 2) return setError("团队版至少需要 2 个席位（含所有者）");
    if (duration < 0) return setError("有效天数不能小于 0");
    if (!reason.trim()) return setError("后台开通必须填写原因");
    setError("");
    setIsSubmitting(true);
    try {
      await grantUserTeamEntitlement(user.id, { seat_count: seats, duration_days: duration, reason: reason.trim() });
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "团队权益开通失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal" onSubmit={submit}>
        <button className="modal-close" type="button" onClick={onClose} aria-label="关闭"><X size={18} /></button>
        <h3>开通团队版</h3>
        <p>为 {user.username} 增加团队席位。席位含所有者；有效天数填 0 即永久有效。该操作会写入管理员审计。</p>
        <div className="form-grid">
          <label className="field">团队席位<input min={2} max={1000} type="number" value={seatCount} onChange={(event) => setSeatCount(Number(event.target.value))} /></label>
          <label className="field">有效天数<input min={0} max={3650} type="number" value={durationDays} onChange={(event) => setDurationDays(Number(event.target.value))} /></label>
        </div>
        <label className="field">开通原因<textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={4} placeholder="例如：企业客户试用、销售补偿" /></label>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" type="button" onClick={onClose} disabled={isSubmitting}>取消</button>
          <button className="primary-button" disabled={isSubmitting}>{isSubmitting ? "开通中..." : "确认开通"}</button>
        </div>
      </form>
    </div>
  );
}

function Dialog({ state, onClose, afterDone, onPasswordReset }: { state: DialogState; onClose: () => void; afterDone: () => void; onPasswordReset: () => void }) {
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  if (state.kind === "none") return null;
  if (state.kind === "credit") return <CreditDialog user={state.user} onClose={onClose} afterDone={afterDone} />;
  if (state.kind === "password") return <PasswordResetDialog user={state.user} onClose={onClose} afterDone={onPasswordReset} />;
  if (state.kind === "imageConcurrency") return <ImageConcurrencyDialog user={state.user} onClose={onClose} afterDone={afterDone} />;
  if (state.kind === "leadModule") return <LeadModuleDialog user={state.user} onClose={onClose} afterDone={afterDone} />;
  if (state.kind === "teamEntitlement") return <TeamEntitlementDialog user={state.user} onClose={onClose} afterDone={afterDone} />;
  if (state.kind !== "confirm") return null;
  const confirmState = state;

  async function confirm() {
    setError("");
    setIsSubmitting(true);
    try {
      await confirmState.onConfirm();
      afterDone();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal">
        <button className="modal-close" onClick={onClose} aria-label="关闭" disabled={isSubmitting}><X size={18} /></button>
        <h3>{confirmState.title}</h3>
        <p>{confirmState.body}</p>
        {error && <div className="form-error">{error}</div>}
        <div className="modal-actions">
          <button className="secondary-button" onClick={onClose} disabled={isSubmitting}>取消</button>
          <button className={confirmState.danger ? "danger-button" : "primary-button"} onClick={() => void confirm()} disabled={isSubmitting}>
            {isSubmitting ? "处理中…" : confirmState.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function CustomerUsersPage() {
  const { can } = usePermission();
  const { user: currentAdmin } = useAuth();
  const canResetUserPassword = can("users:password:reset");
  const canManageCustomerOwnership = can("users:ownership:write");
  const canImpersonate =
    can("users:impersonate")
    && currentAdmin?.username.trim().toLowerCase() === "yifan"
    && currentAdmin.role === "super_admin"
    && currentAdmin.system_super_admin;
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<ManagedUser[]>([]);
  const [selected, setSelected] = useState<ManagedUser | null>(null);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pagination, setPagination] = useState<PaginationState>(initialPagination);
  const [customerOwners, setCustomerOwners] = useState<CustomerOwnerOption[]>([]);
  const [savingOwnerUserId, setSavingOwnerUserId] = useState<number | null>(null);

  useEffect(() => {
    if (!canManageCustomerOwnership) return;
    void getCustomerOwners()
      .then(setCustomerOwners)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "客户归属管理员读取失败"));
  }, [canManageCustomerOwnership]);

  async function load() {
    setError("");
    try {
      const result: PageResult<ManagedUser> = await getUsers(query, pagination.page, pagination.pageSize);
      setItems(result.items);
      setPagination({ page: result.page, pageSize: result.page_size, total: result.total });
      if (selected) setSelected(result.items.find((managedUser) => managedUser.id === selected.id) ?? null);
    } catch (err) {
      setItems([]);
      setError(err instanceof Error ? err.message : "用户管理接口不可用");
    }
  }

  useResetPageOnQuery(query, setPagination);
  useAutoDismissNotice(notice, setNotice);
  useEffect(() => { void load(); }, [query, pagination.page, pagination.pageSize]);

  function requestImpersonation(user: ManagedUser) {
    setDialog({
      kind: "confirm",
      title: `代登录 ${user.username}`,
      body: "将以该用户身份打开一个新窗口，用于排查前台问题。链接 60 秒内有效且只能使用一次，代登录会话持续 1 小时并写入审计日志。",
      confirmLabel: "确认代登录",
      onConfirm: async () => {
        const loginWindow = window.open("about:blank", "_blank");
        if (loginWindow) loginWindow.opener = null;
        try {
          const { login_url: loginUrl } = await createUserImpersonation(user.id);
          if (loginWindow) {
            loginWindow.location.replace(loginUrl);
          } else {
            const fallbackWindow = window.open(loginUrl, "_blank", "noopener,noreferrer");
            if (!fallbackWindow) throw new Error("浏览器阻止了新窗口，请允许本站打开弹窗后重试");
          }
          setNotice(`已为 ${user.username} 打开代登录窗口`);
        } catch (impersonationError) {
          loginWindow?.close();
          throw impersonationError;
        }
      },
    });
  }

  async function changeCustomerOwner(user: ManagedUser, rawOwnerId: string) {
    const ownerAdminId = rawOwnerId ? Number(rawOwnerId) : null;
    setSavingOwnerUserId(user.id);
    setError("");
    try {
      await updateUserCustomerOwner(user.id, ownerAdminId);
      setNotice(`${user.username} 的客户归属已更新`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "客户归属更新失败");
    } finally {
      setSavingOwnerUserId(null);
    }
  }

  function ownerLabel(user: ManagedUser) {
    return user.customer_owner_admin_name || "未分配";
  }

  return (
      <PageChrome title="用户管理" description="管理前台用户、客户归属、积分余额、启停状态，以及按席位开通团队版。">
      <Toolbar value={query} onChange={setQuery} placeholder="搜索用户、邮箱、手机号或 ID" />
      {notice ? <div className="inline-state success"><CheckCircle2 size={17} /><span>{notice}</span></div> : null}
      <LoadState error={error} empty={!error && items.length === 0} onRetry={load} />
      <div className="split-layout">
        <section className="panel">
          <div className="table-wrap">
            <table>
            <thead><tr><th>用户</th><th>邮箱</th><th>手机号</th><th>积分</th><th>VIP 等级</th><th>团队</th><th>图片并发</th><th>标签</th><th>客资</th><th>状态</th><th>注册时间</th><th>最后登录</th><th>操作</th></tr></thead>
              <tbody>{items.map((user) => (
                <tr key={user.id}>
                  <td><button className="link-button" onClick={() => setSelected(user)}>{user.username}<small>#{user.id}</small></button></td>
                  <td>{user.email}</td>
                  <td>{user.phone || "-"}</td>
                  <td title={user.credit_balance_source === "authoritative" ? "上游实时余额" : user.credit_balance_source === "local_fallback" ? "上游同步失败，暂显本地缓存" : "本地积分余额"}>
                    {user.credit_balance.toLocaleString("zh-CN")}{user.credit_balance_source === "local_fallback" ? "（缓存）" : ""}
                  </td>
                  <td>{customerVipLabel(user)}{user.vip?.expires_at ? <small>{formatDateTime(user.vip.expires_at)} 到期</small> : null}</td>
                  <td><span className={`status-pill ${(user.team_seat_limit ?? 0) >= 2 ? "paid" : "pending"}`}>{(user.team_seat_limit ?? 0) >= 2 ? `${user.team_seat_limit} 席` : "未开通"}</span></td>
                  <td>{Math.max(1, user.image_concurrency_limit || 1)}</td>
                  <td><span className={`status-pill ${user.is_internal ? "paid" : "pending"}`}>{user.is_internal ? "内部用户" : "普通用户"}</span></td>
                  <td><span className={`status-pill ${user.lead_module_enabled ? "paid" : "pending"}`}>{user.lead_module_enabled ? "已开通" : "未开通"}</span></td>
                  <td><StatusPill active={user.is_active} /></td>
                  <td>{user.created_at ? formatDateTime(user.created_at) : "-"}</td>
                  <td>{user.last_login_at ? formatDateTime(user.last_login_at) : "-"}</td>
                  <td className="row-actions">
                    <button className="secondary-button compact" onClick={() => setSelected(user)}><Eye size={14} />详情</button>
                    {canImpersonate ? <button className="secondary-button compact" onClick={() => requestImpersonation(user)}><LogIn size={14} />代登录</button> : null}
                    {canResetUserPassword ? <button className="secondary-button compact" onClick={() => setDialog({ kind: "password", user })}><KeyRound size={14} />重置密码</button> : null}
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "imageConcurrency", user })}><SlidersHorizontal size={14} />编辑并发</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "leadModule", user })}><KeyRound size={14} />客资</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "teamEntitlement", user })}><UsersRound size={14} />团队版</button>
                    <button className="secondary-button compact" onClick={async () => { await updateUserTags(user.id, { is_internal: !user.is_internal }); await load(); }}>{user.is_internal ? "取消内部" : "设为内部"}</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "credit", user })}><WalletCards size={14} />调分</button>
                    <button className="secondary-button compact" onClick={() => setDialog({ kind: "confirm", title: user.is_active ? "禁用用户" : "启用用户", body: `${user.username} ${user.is_active ? "禁用后将无法继续使用前台服务。" : "启用后将恢复前台使用能力。"}`, confirmLabel: user.is_active ? "禁用" : "启用", danger: user.is_active, onConfirm: async () => { await updateUserStatus(user.id, !user.is_active); } })}>{user.is_active ? <Ban size={14} /> : <CheckCircle2 size={14} />}{user.is_active ? "禁用" : "启用"}</button>
                  </td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        </section>
        <aside className="detail-drawer">
          {selected ? (
            <>
              <div className="detail-title"><UserCog size={20} /><h3>{selected.username}</h3></div>
              <p>前台用户账号，可管理积分余额、登录状态和客资模块。</p>
              <div className="detail-owner-section">
                <div className="detail-owner-heading">
                  <span>客户归属</span>
                  <strong>{ownerLabel(selected)}</strong>
                </div>
                {canManageCustomerOwnership ? (
                  <label className="field detail-owner-field">
                    <span>分配给后台账号</span>
                    <select
                      value={selected.customer_owner_admin_id ?? ""}
                      disabled={savingOwnerUserId === selected.id}
                      aria-label={`${selected.username} 客户归属`}
                      onChange={(event) => void changeCustomerOwner(selected, event.target.value)}
                    >
                      <option value="">未分配</option>
                      {selected.customer_owner_admin_id && !customerOwners.some((owner) => owner.id === selected.customer_owner_admin_id) ? (
                        <option value={selected.customer_owner_admin_id}>{ownerLabel(selected)}（已停用）</option>
                      ) : null}
                      {customerOwners.map((owner) => <option key={owner.id} value={owner.id}>{owner.username}</option>)}
                    </select>
                    <small>{savingOwnerUserId === selected.id ? "正在保存…" : "选择后自动保存"}</small>
                  </label>
                ) : null}
              </div>
              <div className="detail-actions">
                {canImpersonate ? (
                  <button className="secondary-button compact" type="button" onClick={() => requestImpersonation(selected)}>
                    <LogIn size={14} />
                    代登录
                  </button>
                ) : null}
                {canResetUserPassword ? (
                  <button className="secondary-button compact" type="button" onClick={() => setDialog({ kind: "password", user: selected })}>
                    <KeyRound size={14} />
                    重置密码
                  </button>
                ) : null}
                <button className="secondary-button compact" type="button" onClick={() => setDialog({ kind: "imageConcurrency", user: selected })}>
                  <SlidersHorizontal size={14} />
                  编辑图片并发
                </button>
                <button className="secondary-button compact" type="button" onClick={() => setDialog({ kind: "teamEntitlement", user: selected })}>
                  <UsersRound size={14} />
                  开通团队版
                </button>
              </div>
              <dl>
                <dt>邮箱</dt><dd>{selected.email}</dd>
                <dt>手机号</dt><dd>{selected.phone || "-"}</dd>
                <dt>积分余额</dt><dd>{selected.credit_balance.toLocaleString("zh-CN")}{selected.credit_balance_source === "local_fallback" ? "（缓存）" : ""}</dd>
                <dt>团队席位</dt><dd>{(selected.team_seat_limit ?? 0) >= 2 ? `${selected.team_seat_limit} 席` : "未开通"}</dd>
                <dt>图片并发</dt><dd>{Math.max(1, selected.image_concurrency_limit || 1)}</dd>
                <dt>用户标签</dt><dd>{selected.is_internal ? "内部用户" : "普通用户"}</dd>
                <dt>客资模块</dt><dd>{selected.lead_module_enabled ? "已开通" : "未开通"}</dd>
                <dt>状态</dt><dd>{selected.is_active ? "启用" : "停用"}</dd>
                <dt>注册时间</dt><dd>{selected.created_at ? formatDateTime(selected.created_at) : "-"}</dd>
                <dt>最后登录</dt><dd>{selected.last_login_at ? formatDateTime(selected.last_login_at) : "-"}</dd>
              </dl>
            </>
          ) : <div className="empty-detail"><ClipboardCheck size={22} /><span>选择用户查看积分、状态和客资开通情况。</span></div>}
        </aside>
      </div>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog
        state={dialog}
        onClose={() => setDialog({ kind: "none" })}
        afterDone={load}
        onPasswordReset={() => {
          setNotice("用户密码已重置");
          void load();
        }}
      />
    </PageChrome>
  );
}
