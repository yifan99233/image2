import { type ReactNode, useEffect } from "react";
import { AlertTriangle, ClipboardCheck, RefreshCcw, Search, SlidersHorizontal } from "lucide-react";

export const defaultPageSize = 20;
export const pageSizeOptions = [10, 20, 50, 100];

export type PaginationState = {
  page: number;
  pageSize: number;
  total: number;
};

export const initialPagination: PaginationState = { page: 1, pageSize: defaultPageSize, total: 0 };

export function useAutoDismissNotice(notice: string, setNotice: (value: string) => void) {
  useEffect(() => {
    if (!notice) return;
    const timerId = window.setTimeout(() => setNotice(""), 3000);
    return () => window.clearTimeout(timerId);
  }, [notice, setNotice]);
}

export function PageChrome({ title, description, action, children }: { title: string; description: string; action?: ReactNode; children: ReactNode }) {
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

export function Toolbar({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) {
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

export function FilterSelect({
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

export function StatusPill({ active }: { active: boolean }) {
  return <span className={`status-pill ${active ? "paid" : "failed"}`}>{active ? "启用" : "停用"}</span>;
}

export function LoadState({ error, empty, onRetry }: { error: string; empty: boolean; onRetry: () => void }) {
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

export function Pagination({
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

export function useResetPageOnQuery(query: string, setPagination: (updater: (current: PaginationState) => PaginationState) => void) {
  useEffect(() => {
    setPagination((current) => ({ ...current, page: 1 }));
  }, [query, setPagination]);
}
