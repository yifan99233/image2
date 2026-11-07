import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CircleAlert, Coins, LoaderCircle, Pencil, RefreshCw, Search, UserRound, UsersRound } from "lucide-react";
import { QuotaEditDialog } from "../components/QuotaEditDialog";
import { formatAmount, UsageProgress } from "../components/UsageProgress";
import { teamApi, type MemberUsage, type MemberUsagePage, type QuotaUpdateInput } from "../services/team";

const PAGE_SIZE = 20;
const emptyPage: MemberUsagePage = { items: [], total: 0, page: 1, page_size: PAGE_SIZE };
const memberName = (member: MemberUsage) => member.nickname || member.username || member.email;

function PersonalUsage({ usage, showTeamBalance }: { usage: MemberUsage; showTeamBalance: boolean }) {
  if (!usage.available || !usage.text || !usage.image) {
    return <section className="panel usage-unavailable"><CircleAlert size={22} /><div><h2>额度账户暂不可用</h2><p>账户仍在准备或暂时无法连接，请稍后刷新。</p></div></section>;
  }
  return <>
    <section className={showTeamBalance ? "usage-summary-grid" : "usage-summary-grid usage-summary-grid--personal"}>
      {showTeamBalance ? <article className="panel wallet-card"><span className="metric-icon"><Coins size={20} /></span><div><small>团队总账户余额</small><strong>{formatAmount(usage.balance)}</strong><p>仅团队管理员可见；所有成员共用</p></div></article> : null}
      <article className="panel quota-card"><header><div><small>Token</small><strong>文本与代码模型</strong></div><span className="status-pill">{usage.text.status === "quota_exhausted" ? "额度已用完" : "正常"}</span></header><UsageProgress usage={usage.text} /></article>
      <article className="panel quota-card"><header><div><small>图片 / 视频</small><strong>视觉生成模型</strong></div><span className="status-pill">{usage.image.status === "quota_exhausted" ? "额度已用完" : "正常"}</span></header><UsageProgress usage={usage.image} /></article>
    </section>
  </>;
}

export function TeamUsagePage({ permissions, siteName, onNotice, onError }: { permissions: string[]; siteName: string; onNotice: (message: string) => void; onError: (message: string) => void }) {
  const [myUsage, setMyUsage] = useState<MemberUsage | null>(null);
  const [membersPage, setMembersPage] = useState<MemberUsagePage>(emptyPage);
  const [isLoading, setIsLoading] = useState(true);
  const [isMembersLoading, setIsMembersLoading] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [editingMember, setEditingMember] = useState<MemberUsage | null>(null);
  const canViewTeam = permissions.includes("usage:view");
  const canManageQuota = permissions.includes("budgets:manage");

  const loadMyUsage = useCallback(async () => {
    const usage = await teamApi.getMyUsage();
    setMyUsage(usage);
  }, []);

  const loadMembers = useCallback(async (nextPage: number, nextSearch: string) => {
    if (!canViewTeam) return;
    setIsMembersLoading(true);
    try {
      setMembersPage(await teamApi.getMemberUsage(nextPage, PAGE_SIZE, nextSearch));
    } finally {
      setIsMembersLoading(false);
    }
  }, [canViewTeam]);

  const reload = useCallback(async () => {
    setIsLoading(true);
    try {
      await Promise.all([loadMyUsage(), loadMembers(page, search)]);
    } catch (err) {
      onError(err instanceof Error ? err.message : "额度与用量加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [loadMembers, loadMyUsage, onError, page, search]);

  useEffect(() => { void reload(); }, [reload]);

  const pageCount = useMemo(() => Math.max(1, Math.ceil(membersPage.total / membersPage.page_size)), [membersPage]);

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPage(1);
    setSearch(searchInput.trim());
  }

  async function saveQuotas(member: MemberUsage, input: QuotaUpdateInput) {
    const saved = await teamApi.updateMemberQuotas(member.membership_id, input);
    setMembersPage((current) => ({ ...current, items: current.items.map((candidate) => candidate.membership_id === saved.membership_id ? saved : candidate) }));
    if (myUsage?.membership_id === saved.membership_id) setMyUsage(saved);
    onNotice(`已更新 ${memberName(member)} 的额度`);
  }

  if (isLoading && !myUsage) return <section className="page-loading"><LoaderCircle className="spin" size={24} />正在同步额度与用量</section>;

  return <>
    <header className="content-heading usage-heading"><div><p className="eyebrow">额度中心</p><h1>额度与用量</h1><p>{canViewTeam ? `查看 ${siteName || "当前子站"} 团队账户与成员用量；额度修改后立即生效。` : "查看你自己的额度与用量；团队余额和其他成员信息不可见。"}</p></div><button className="button button-quiet" type="button" disabled={isLoading || isMembersLoading} onClick={() => void reload()}><RefreshCw className={isLoading || isMembersLoading ? "spin" : ""} size={16} />刷新数据</button></header>
    {myUsage ? <PersonalUsage usage={myUsage} showTeamBalance={canViewTeam} /> : null}
    {canViewTeam ? <section className="panel team-usage-panel">
      <header className="panel-heading usage-table-heading"><div><h2>团队成员用量</h2><p>实时读取每位成员绑定的 Token 与图片/视频 Key 用量。</p></div><span>{membersPage.total} 人</span></header>
      <form className="usage-toolbar" onSubmit={submitSearch}><label><Search size={16} /><input value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="搜索姓名、账号或邮箱" aria-label="搜索成员" /></label><button className="button button-quiet" type="submit">搜索</button></form>
      {isMembersLoading ? <div className="table-loading"><LoaderCircle className="spin" size={20} />正在读取团队用量</div> : membersPage.items.length === 0 ? <div className="empty-state"><UsersRound size={26} /><h3>没有匹配的团队成员</h3><p>调整搜索条件后再试。</p></div> : <div className="usage-table">
        <div className="usage-table__head"><span>成员</span><span>Token</span><span>图片 / 视频</span><span>操作</span></div>
        {membersPage.items.map((member) => <article key={member.membership_id}>
          <div className="member-identity"><span className="avatar"><UserRound size={15} /></span><div><strong>{memberName(member)}</strong><small>{member.email}</small></div></div>
          {member.available && member.text ? <UsageProgress usage={member.text} /> : <span className="unavailable-label">账户未就绪</span>}
          {member.available && member.image ? <UsageProgress usage={member.image} /> : <span className="unavailable-label">—</span>}
          {canManageQuota && member.available ? <button className="row-action" type="button" title="编辑额度" aria-label={`编辑 ${memberName(member)} 的额度`} onClick={() => setEditingMember(member)}><Pencil size={16} /></button> : <span className="row-action-placeholder">—</span>}
        </article>)}
      </div>}
      {membersPage.total > membersPage.page_size ? <footer className="pagination"><span>第 {membersPage.page} / {pageCount} 页</span><div><button className="button button-quiet" type="button" disabled={page <= 1 || isMembersLoading} onClick={() => setPage((current) => Math.max(1, current - 1))}>上一页</button><button className="button button-quiet" type="button" disabled={page >= pageCount || isMembersLoading} onClick={() => setPage((current) => current + 1)}>下一页</button></div></footer> : null}
    </section> : <section className="panel self-only-note"><UserRound size={20} /><div><h2>仅显示你的额度</h2><p>团队总览与其他成员用量仅团队管理员可见。</p></div></section>}
    {editingMember ? <QuotaEditDialog member={editingMember} siteName={siteName} onClose={() => setEditingMember(null)} onSave={(input) => saveQuotas(editingMember, input)} /> : null}
  </>;
}
