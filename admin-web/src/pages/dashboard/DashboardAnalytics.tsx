import { useEffect, useState } from "react";
import { RefreshCcw, TrendingUp } from "lucide-react";
import { request } from "../../services/http";
import { formatCurrency, formatDateTime } from "../../lib/format";
import "./dashboard-analytics.css";

type Totals = { new_users: number; active_users: number; tasks: number; revenue_cents: number;
  paid_orders: number; paid_users: number; charged_credits: number; refunded_credits: number; net_credits: number };
type Day = Omit<Totals, "paid_users"> & { date: string };
type Ranking = { user_id: number; site_id: number; username: string; charged_credits: number; refunded_credits: number; net_credits: number };
type Analytics = { days: number; day_offset: number; generated_at: string; start_at: string; end_at: string; scope: string; totals: Totals; daily: Day[]; consumption_ranking: Ranking[] };
const number = (value: number) => value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
const series = { new_users: "新增用户", active_users: "活跃客户", revenue_cents: "实收金额", net_credits: "图片净消耗" } as const;
type Series = keyof typeof series;
const periods = [{ value: "today", label: "当天", query: "days=1" }, { value: "yesterday", label: "昨天", query: "days=1&day_offset=1" }, ...([7, 15, 30] as const).map(days => ({ value: String(days), label: `${days} 天`, query: `days=${days}` }))];

export function DashboardAnalytics() {
  const [period, setPeriod] = useState("today");
  const selected = periods.find(option => option.value === period)!;
  const [version, setVersion] = useState(0);
  const [metric, setMetric] = useState<Series>("new_users");
  const [data, setData] = useState<Analytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setData(null);
    request<Analytics>(`/admin/dashboard/analytics?${selected.query}`, { signal: controller.signal })
      .then(result => { if (!controller.signal.aborted) setData(result); })
      .catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "经营数据加载失败"); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selected.query, version]);
  const display = (value: number) => metric === "revenue_cents" ? formatCurrency(value) : number(value);
  return <section className="dashboard-analytics" aria-label="经营增长分析">
    <header className="analytics-heading">
      <div><h2><TrendingUp size={22} /> 经营增长</h2><p>看增长、看消耗，了解客户最近的使用情况。</p></div>
      <div className="analytics-actions">
        <div className="analytics-segments" role="group" aria-label="统计周期">
          {periods.map(option => <button key={option.value} aria-pressed={period === option.value} onClick={() => setPeriod(option.value)}>{option.label}</button>)}
        </div>
        <button className="secondary-button compact" disabled={loading} onClick={() => setVersion(v => v + 1)} aria-label="刷新经营数据"><RefreshCcw size={16} />刷新</button>
      </div>
    </header>
    {loading ? <div className="analytics-loading" role="status">正在加载{selected.label}的经营数据…</div> : error ?
      <div className="analytics-error" role="alert"><strong>经营数据加载失败</strong><p>{error}</p><button className="secondary-button compact" onClick={() => setVersion(v => v + 1)}>重新加载</button></div> : data && <>
      <p className="analytics-caption">{data.scope} · 北京时间 {data.daily[0]?.date} 至 {data.daily.at(-1)?.date}（{data.day_offset ? "完整自然日" : "截至当前"}） · 更新于 {formatDateTime(data.generated_at)}</p>
      <div className="analytics-summary">
        {[
          ["新增用户", number(data.totals.new_users), "本周期注册、未删除用户"],
          ["活跃客户", number(data.totals.active_users), "本周期提交图片任务的去重客户"],
          ["实收金额", formatCurrency(data.totals.revenue_cents), `${number(data.totals.paid_users)} 位付费客户 · ${number(data.totals.paid_orders)} 笔订单`],
          ["图片净消耗", number(data.totals.net_credits), `积分 · 已扣除 ${number(data.totals.refunded_credits)} 退款`],
        ].map(([label, value, note]) => <article key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></article>)}
      </div>
      <div className="analytics-panels">
        <section className="panel analytics-trend">
          <div className="panel-header"><div><h3>每日趋势</h3><p>{data.day_offset ? "展示昨天完整自然日的数据。" : "按日观察增长与使用变化，今日数据持续累积。"}</p></div></div>
          <div className="analytics-segments analytics-series" role="group" aria-label="趋势指标">
            {(Object.keys(series) as Series[]).map(key => <button key={key} aria-pressed={metric === key} onClick={() => setMetric(key)}>{series[key]}</button>)}
          </div>
          <TrendChart daily={data.daily} metric={metric} display={display} />
          <details className="analytics-details"><summary>查看每日明细</summary><div className="table-wrap"><table>
            <thead><tr><th>日期</th><th>新增</th><th>活跃</th><th>实收金额</th><th>净消耗积分</th></tr></thead>
            <tbody>{data.daily.map(day => <tr key={day.date}><td>{day.date}</td><td>{number(day.new_users)}</td><td>{number(day.active_users)}</td><td>{formatCurrency(day.revenue_cents)}</td><td>{number(day.net_credits)}</td></tr>)}</tbody>
          </table></div></details>
        </section>
        <section className="panel analytics-ranking">
          <div className="panel-header"><div><h3>客户消耗排行榜 <span>TOP 10</span></h3><p>按本周期图片净消耗排序，单位：积分。</p></div></div>
          <div className="table-wrap"><table>
            <thead><tr><th>排名 / 客户</th><th>净消耗</th><th>退款</th></tr></thead>
            <tbody>{data.consumption_ranking.length ? data.consumption_ranking.map((customer, index) => <tr key={customer.user_id}>
              <td><div className="analytics-customer"><span className={`analytics-rank rank-${index + 1}`}>{index + 1}</span><div><strong>{customer.username}</strong><small>ID {customer.user_id}{data.scope === "全部站点" ? ` · 站点 ${customer.site_id}` : ""}</small></div></div></td>
              <td><strong>{number(customer.net_credits)}</strong><div className="analytics-bar"><span style={{ width: `${customer.net_credits / data.consumption_ranking[0].net_credits * 100}%` }} /></div></td>
              <td>{number(customer.refunded_credits)}</td>
            </tr>) : <tr><td colSpan={3}><div className="list-state">本周期暂无净消耗大于 0 的客户</div></td></tr>}</tbody>
          </table></div>
        </section>
      </div>
      <p className="analytics-caption analytics-method">统计口径：图片净消耗 = 周期内平台图片扣费 − 周期内图片退款，含进行中任务预扣；跨期退款可能产生负值。未计入上游直接 API 用量，排除已删除用户。实收按订单支付时间统计。</p>
    </>}
  </section>;
}

function TrendChart({ daily, metric, display }: { daily: Day[]; metric: Series; display: (value: number) => string }) {
  const values = daily.map(day => day[metric]);
  const min = Math.min(0, ...values), max = Math.max(1, ...values);
  const x = (index: number) => daily.length === 1 ? 378 : 76 + index / (daily.length - 1) * 604;
  const y = (value: number) => 195 - (value - min) / (max - min) * 162;
  return <div className="analytics-chart">
    {!values.some(Boolean) && <p className="analytics-zero">本周期暂无{series[metric]}数据</p>}
    <svg viewBox="0 0 720 240" role="img" aria-label={`近 ${daily.length} 天${series[metric]}趋势，具体数值可查看每日明细`}>
      {[min, (max + min) / 2, max].map((value, i) => <g key={i}><line x1="76" x2="680" y1={y(value)} y2={y(value)} className="chart-grid" /><text x="64" y={y(value) + 4} textAnchor="end">{display(value)}</text></g>)}
      <polyline points={values.map((value, index) => `${x(index)},${y(value)}`).join(" ")} className="chart-line" />
      {daily.map((day, index) => <circle key={day.date} cx={x(index)} cy={y(day[metric])} r="4" tabIndex={0}><title>{day.date} · {series[metric]} {display(day[metric])}</title></circle>)}
      {[...new Set([0, Math.floor((daily.length - 1) / 2), daily.length - 1])].map(index => <text key={index} x={x(index)} y="226" textAnchor="middle">{daily[index]?.date.slice(5)}</text>)}
    </svg>
  </div>;
}
