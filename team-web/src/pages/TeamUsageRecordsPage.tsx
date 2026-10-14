import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Clock3, LoaderCircle, RefreshCw, RotateCcw, ScrollText } from "lucide-react";
import {
  teamApi,
  type TeamMember,
  type TeamUsageRecord,
  type TeamUsageRecordFilters,
  type TeamUsageRecordPage,
} from "../services/team";

const PAGE_SIZE = 20;
const emptyPage: TeamUsageRecordPage = { items: [], total: 0, page: 1, page_size: PAGE_SIZE };
const memberName = (member: Pick<TeamMember, "nickname" | "username" | "email">) => member.nickname || member.username || member.email;

const formatDateTime = (value: string) => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
};

const formatDuration = (value?: number | null) => value == null ? "—" : value >= 1000 ? `${(value / 1000).toFixed(2)} 秒` : `${value} ms`;

const formatCost = (value: number) => {
  if (!Number.isFinite(value) || value === 0) return "0";
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
};

const billingModeLabels: Record<string, string> = {
  token: "Token",
  tokens: "Token",
  image: "图片",
  video: "视频",
  per_request: "按次",
};

const billingModeLabel = (value: string) => billingModeLabels[value] || value || "—";

export function TeamUsageRecordsPage({ members, onError }: { members: TeamMember[]; onError: (message: string) => void }) {
  const [recordsPage, setRecordsPage] = useState<TeamUsageRecordPage>(emptyPage);
  const [filters, setFilters] = useState<TeamUsageRecordFilters>({});
  const [draftMemberId, setDraftMemberId] = useState("");
  const [draftStartDate, setDraftStartDate] = useState("");
  const [draftEndDate, setDraftEndDate] = useState("");
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);

  const load = useCallback(async (targetPage: number, targetFilters: TeamUsageRecordFilters) => {
    setIsLoading(true);
    try {
      const result = await teamApi.getUsageRecords(targetPage, PAGE_SIZE, targetFilters);
      setRecordsPage(result);
      setPage(result.page);
    } catch (err) {
      onError(err instanceof Error ? err.message : "团队使用记录加载失败");
    } finally {
      setIsLoading(false);
    }
  }, [onError]);

  useEffect(() => { void load(1, {}); }, [load]);

  const pageCount = useMemo(() => Math.max(1, Math.ceil(recordsPage.total / recordsPage.page_size)), [recordsPage]);
  const pageTokens = useMemo(() => recordsPage.items.reduce((sum, record) => sum + record.tokens, 0), [recordsPage]);
  const pageCost = useMemo(() => recordsPage.items.reduce((sum, record) => sum + record.cost, 0), [recordsPage]);

  function submitFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (draftStartDate && draftEndDate && draftStartDate > draftEndDate) {
      onError("开始日期不能晚于结束日期");
      return;
    }
    const nextFilters: TeamUsageRecordFilters = {
      memberUserId: draftMemberId ? Number(draftMemberId) : null,
      startDate: draftStartDate,
      endDate: draftEndDate,
    };
    setFilters(nextFilters);
    setPage(1);
    void load(1, nextFilters);
  }

  function resetFilters() {
    setDraftMemberId("");
    setDraftStartDate("");
    setDraftEndDate("");
    setFilters({});
    setPage(1);
    void load(1, {});
  }

  function goPage(nextPage: number) {
    if (nextPage < 1 || nextPage > pageCount || isLoading) return;
    void load(nextPage, filters);
  }

  return <>
    <header className="content-heading usage-records-heading"><div><p className="eyebrow">团队审计</p><h1>使用记录</h1><p>仅团队管理员可查看当前团队全部成员的模型调用与计费明细。</p></div><button className="button button-quiet" type="button" disabled={isLoading} onClick={() => void load(page, filters)}><RefreshCw className={isLoading ? "spin" : ""} size={16} />刷新记录</button></header>

    <section className="record-metrics">
      <article className="panel"><span><ScrollText size={18} /></span><div><small>记录总数</small><strong>{isLoading && recordsPage.total === 0 ? "—" : recordsPage.total.toLocaleString()}</strong></div></article>
      <article className="panel"><span><Clock3 size={18} /></span><div><small>当前页 Token</small><strong>{pageTokens.toLocaleString()}</strong></div></article>
      <article className="panel"><span>¥</span><div><small>当前页费用</small><strong>{formatCost(pageCost)}</strong></div></article>
    </section>

    <section className="panel usage-records-panel">
      <form className="usage-record-filters" onSubmit={submitFilters}>
        <label><span>团队成员</span><select value={draftMemberId} onChange={(event) => setDraftMemberId(event.target.value)}><option value="">全部成员</option>{members.map((member) => <option key={member.membership_id} value={member.user_id}>{memberName(member)}</option>)}</select></label>
        <label><span>开始日期</span><input type="date" value={draftStartDate} onChange={(event) => setDraftStartDate(event.target.value)} /></label>
        <label><span>结束日期</span><input type="date" value={draftEndDate} onChange={(event) => setDraftEndDate(event.target.value)} /></label>
        <div><button className="button button-quiet" type="button" disabled={isLoading} onClick={resetFilters}><RotateCcw size={15} />重置</button><button className="button button-primary" disabled={isLoading}>查询</button></div>
      </form>

      {isLoading ? <div className="table-loading"><LoaderCircle className="spin" size={20} />正在读取团队使用记录</div> : recordsPage.items.length === 0 ? <div className="empty-state"><ScrollText size={28} /><h3>暂无使用记录</h3><p>当前筛选范围内还没有模型调用。</p></div> : <div className="usage-record-table"><div className="usage-record-table__head"><span>成员 / Key</span><span>模型 / 模式</span><span>Token / 费用</span><span>IP / 响应</span><span>调用时间</span></div>{recordsPage.items.map((record: TeamUsageRecord) => <article key={`${record.id}-${record.created_at}`}>
        <div className="usage-record-cell usage-record-identity" data-label="成员 / Key"><strong>{memberName(record.member)}</strong><span>{record.api_key_name || "未命名 Key"}</span>{record.member.email ? <small>{record.member.email}</small> : null}</div>
        <div className="usage-record-cell" data-label="模型 / 模式"><strong title={record.model}>{record.model || "—"}</strong><span>{billingModeLabel(record.billing_mode)}</span></div>
        <div className="usage-record-cell" data-label="Token / 费用"><strong>{record.tokens.toLocaleString()} Token</strong><span>{formatCost(record.cost)}</span></div>
        <div className="usage-record-cell" data-label="IP / 响应"><strong>{record.ip_address || "—"}</strong><span>首 Token {formatDuration(record.first_token_ms)}</span><small>总耗时 {formatDuration(record.duration_ms)}</small></div>
        <div className="usage-record-cell" data-label="调用时间"><strong>{formatDateTime(record.created_at)}</strong></div>
      </article>)}</div>}

      {recordsPage.total > recordsPage.page_size ? <footer className="pagination"><span>第 {page} / {pageCount} 页</span><div><button className="button button-quiet" type="button" disabled={page <= 1 || isLoading} onClick={() => goPage(page - 1)}>上一页</button><button className="button button-quiet" type="button" disabled={page >= pageCount || isLoading} onClick={() => goPage(page + 1)}>下一页</button></div></footer> : null}
    </section>
  </>;
}
