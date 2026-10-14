import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Plus, RefreshCcw, Search } from "lucide-react";
import { hasPermission } from "../../lib/permissions";
import { getUsers, getVipTiers, type VipStatus } from "../../services/adminApi";
import { useAuth } from "../../store/auth";
import type { ManagedUser, VipTier } from "../../types";
import { CustomerVipDialog, VipTiersDialog, customerVipLabel } from "./CustomerVipDialogs";
import { FilterSelect, LoadState, PageChrome, Pagination, StatusPill, initialPagination } from "./ManagementCommon";

function useVipAccess() {
  const { user } = useAuth();
  return {
    canRead: hasPermission(user, "users:read"),
    canWrite: Boolean(user?.system_super_admin || user?.role === "super_admin" || user?.role === "finance"),
    siteId: user?.site_id,
    adminId: user?.id,
    isSystem: user?.system_super_admin,
  };
}

export function VipTiersPage() {
  const { canRead, canWrite, siteId, adminId } = useVipAccess();
  const [tiers, setTiers] = useState<VipTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [dialog, setDialog] = useState<VipTier | "new" | null>(null);
  const [notice, setNotice] = useState("");
  const reload = () => setRevision((value) => value + 1);
  useEffect(() => {
    if (!canRead) return;
    let ignore = false;
    setLoading(true); setError("");
    getVipTiers().then((data) => { if (!ignore) setTiers(data); })
      .catch((err) => { if (!ignore) { setTiers([]); setError(err instanceof Error ? err.message : "等级读取失败"); } })
      .finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [canRead, siteId, adminId, revision]);
  if (!canRead) return <div className="inline-state error">无权查看 VIP 客户等级设置。</div>;
  return <PageChrome title="VIP 客户等级设置" description="设置等级名称、客户折扣和启停状态。折扣仅作用于模型基础价格。"
    action={canWrite ? <button className="primary-button" onClick={() => setDialog("new")}><Plus size={16} />新建等级</button> : undefined}>
    <div className="filter-toolbar"><span className="muted-meta">单次价格 = 基础价格 × 等级折扣 + 固定加价</span><Link className="link-button" to="/vip-customers">前往 VIP 客户管理</Link><button className="secondary-button compact" disabled={loading} onClick={reload}><RefreshCcw size={14} />刷新</button></div>
    {notice ? <div className="inline-state success" role="status">{notice}</div> : null}
    {!canWrite ? <p className="inline-hint">当前账号可查看等级，修改需要管理员或财务权限。</p> : null}
    {loading ? <div className="inline-state" role="status">正在读取等级…</div> : error ? <LoadState error={error} empty={false} onRetry={reload} /> : !tiers.length ?
      <div className="inline-state">还没有 VIP 等级。创建等级后，可在「VIP 客户管理」为客户分配。</div> :
      <div className="panel table-wrap"><table><thead><tr><th>等级名称</th><th>客户折扣</th><th>固定加价</th><th>状态</th>{canWrite ? <th>操作</th> : null}</tr></thead><tbody>
        {tiers.map((tier) => <tr key={tier.id}><td><strong>{tier.name}</strong></td><td>{Number((tier.discount_rate * 10).toFixed(3))} 折</td><td>按模型配置收取，不参与折扣</td><td><StatusPill active={tier.is_active} /></td>{canWrite ? <td><button className="secondary-button compact" onClick={() => setDialog(tier)}>编辑等级</button></td> : null}</tr>)}
      </tbody></table></div>}
    {dialog ? <VipTiersDialog key={dialog === "new" ? "new" : dialog.id} tier={dialog === "new" ? undefined : dialog} onClose={() => setDialog(null)} afterDone={() => { setNotice("等级已保存，对新提交的任务生效。"); reload(); }} /> : null}
  </PageChrome>;
}

const statusOptions = [
  { value: "all", label: "全部客户" }, { value: "active", label: "有效 VIP" },
  { value: "expired", label: "已到期" }, { value: "disabled", label: "等级已停用" },
  { value: "ordinary", label: "普通客户" },
];

export function VipCustomersPage() {
  const { canRead, canWrite, siteId, adminId, isSystem } = useVipAccess();
  const [items, setItems] = useState<ManagedUser[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<VipStatus>("all");
  const [pagination, setPagination] = useState(initialPagination);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [customer, setCustomer] = useState<ManagedUser | null>(null);
  const [notice, setNotice] = useState("");
  const reload = () => setRevision((value) => value + 1);
  useEffect(() => {
    if (!canRead) return;
    let ignore = false;
    setLoading(true); setError("");
    const timer = window.setTimeout(() => {
      getUsers(query, pagination.page, pagination.pageSize, status).then((data) => {
        if (ignore) return;
        const lastPage = Math.max(1, Math.ceil(data.total / pagination.pageSize));
        setItems(data.items);
        setPagination((current) => ({ ...current, total: data.total, page: Math.min(current.page, lastPage) }));
      }).catch((err) => {
        if (!ignore) { setItems([]); setError(err instanceof Error ? err.message : "客户读取失败"); }
      }).finally(() => { if (!ignore) setLoading(false); });
    }, 200);
    return () => { ignore = true; window.clearTimeout(timer); };
  }, [canRead, siteId, adminId, query, status, pagination.page, pagination.pageSize, revision]);
  if (!canRead) return <div className="inline-state error">无权查看 VIP 客户管理。</div>;
  return <PageChrome title="VIP 客户管理" description="为客户分配 VIP 等级、设置有效期或恢复普通客户。可搜索普通客户开通 VIP。"
    action={<Link className="secondary-button" to="/vip-tiers">客户等级设置</Link>}>
    <div className="filter-toolbar">
      <label className="search-field"><Search size={16} /><input aria-label="搜索客户" value={query} placeholder="搜索用户名、邮箱或用户 ID" onChange={(event) => { setQuery(event.target.value); setPagination((current) => ({ ...current, page: 1 })); }} /></label>
      <FilterSelect label="会员状态" value={status} options={statusOptions} onChange={(value) => { setStatus(value as VipStatus); setPagination((current) => ({ ...current, page: 1 })); }} />
      <button className="secondary-button compact" disabled={loading} onClick={reload}><RefreshCcw size={14} />刷新</button>
    </div>
    <p className="inline-hint">到期或等级停用后，新任务恢复普通价格。团队共用钱包时，以钱包所有者的 VIP 等级计价。</p>
    {!canWrite ? <p className="inline-hint">当前账号可查看客户等级，修改需要管理员或财务权限。</p> : null}
    {notice ? <div className="inline-state success" role="status">{notice}</div> : null}
    {loading ? <div className="inline-state" role="status">正在读取客户…</div> : error ? <LoadState error={error} empty={false} onRetry={reload} /> : !items.length ?
      <div className="inline-state">没有符合条件的客户，请调整搜索或会员状态。</div> : <>
        <div className="panel table-wrap"><table><thead><tr><th>客户</th>{isSystem ? <th>站点 ID</th> : null}<th>VIP 等级</th><th>有效期</th>{canWrite ? <th>操作</th> : null}</tr></thead><tbody>
          {items.map((user) => <tr key={user.id}><td><strong>{user.username}</strong><small>{user.email} · ID {user.id}</small></td>{isSystem ? <td>{user.site_id}</td> : null}<td>{customerVipLabel(user)}</td><td>{user.vip ? user.vip.expires_at ? new Date(user.vip.expires_at).toLocaleString("zh-CN") : "长期有效" : "—"}</td>{canWrite ? <td><button className="secondary-button compact" onClick={() => setCustomer(user)}>{user.vip ? "调整 VIP" : "开通 VIP"}</button></td> : null}</tr>)}
        </tbody></table></div>
        <Pagination pagination={pagination} onChange={setPagination} />
      </>}
    {customer ? <CustomerVipDialog key={customer.id} user={customer} onClose={() => setCustomer(null)} afterDone={() => { setNotice(`${customer.username} 的 VIP 设置已保存。`); reload(); }} /> : null}
  </PageChrome>;
}
