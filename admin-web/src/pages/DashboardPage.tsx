import { AlertTriangle, CheckCircle2, CircleDollarSign, RefreshCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { formatCurrency, formatDateTime } from "../lib/format";
import { getDashboard } from "../services/adminApi";
import { DashboardAnalytics } from "./dashboard/DashboardAnalytics";
import type { DashboardData } from "../types";

export function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(true);

  async function loadDashboard() {
    setIsLoading(true);
    setError("");
    try {
      setData(await getDashboard());
    } catch (err) {
      setError(err instanceof Error ? err.message : "控制台数据加载失败。");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadDashboard();
  }, []);

  if (isLoading) {
    return <DashboardSkeleton />;
  }

  if (error) {
    return (
      <section className="state-panel">
        <AlertTriangle size={28} />
        <h2>控制台加载失败</h2>
        <p>{error}</p>
        <button className="primary-button compact" onClick={loadDashboard}>
          <RefreshCcw size={16} />
          重试
        </button>
      </section>
    );
  }

  if (!data) {
    return (
      <section className="state-panel">
        <CircleDollarSign size={28} />
        <h2>暂无运营数据</h2>
        <p>后端返回空数据时，控制台会保持稳定空状态。</p>
      </section>
    );
  }

  const customerOwnerStats = data.customer_owner_stats ?? [];

  return (
    <div className="dashboard-grid">
      <DashboardAnalytics />
      <section className="metric-grid">
        {data.metrics.map((metric) => (
          <article className={`metric-card ${metric.tone}`} key={metric.key}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            <em>{metric.trend}</em>
          </article>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>运营客户数据</h2>
            <p>按客户归属统计今日已支付充值收益和客户情况。</p>
          </div>
          <Link className="secondary-button compact" to="/users">管理客户</Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>负责人</th><th>客户数</th><th>付费客户</th><th>支付订单</th><th>今日实收</th></tr>
            </thead>
            <tbody>
              {customerOwnerStats.length ? customerOwnerStats.map((stat) => (
                <tr key={stat.owner_id ?? "unassigned"}>
                  <td>{stat.owner_name}</td>
                  <td>{stat.customer_count.toLocaleString("zh-CN")}</td>
                  <td>{stat.paid_customer_count.toLocaleString("zh-CN")}</td>
                  <td>{stat.paid_order_count.toLocaleString("zh-CN")}</td>
                  <td><strong>{formatCurrency(stat.revenue_cents)}</strong></td>
                </tr>
              )) : <tr><td colSpan={5}><div className="list-state">暂无客户归属数据</div></td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel wide">
        <div className="panel-header">
          <div>
            <h2>最近充值订单</h2>
            <p>用于快速核对支付到账和待处理订单。</p>
          </div>
          <Link className="secondary-button compact" to="/recharge-orders">查看全部</Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>订单号</th>
                <th>用户</th>
                <th>金额</th>
                <th>到账积分</th>
                <th>状态</th>
                <th>创建时间</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_recharge_orders.map((order) => (
                <tr key={order.order_no}>
                  <td>{order.order_no}</td>
                  <td>{order.username}</td>
                  <td>{formatCurrency(order.amount_cents)}</td>
                  <td>{order.credit_amount.toLocaleString("zh-CN")}</td>
                  <td>
                    <span className={`status-pill ${statusTone[order.status]}`}>{statusLabel[order.status]}</span>
                  </td>
                  <td>{formatDateTime(order.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>失败模型调用</h2>
            <p>优先处理高频失败和超时模型。</p>
          </div>
        </div>
        <div className="stack-list">
          {data.recent_failed_model_calls.map((call) => (
            <article className="stack-item" key={call.task_no}>
              <div>
                <strong>{call.model_name}</strong>
                <span>{call.task_no} · {call.username}</span>
              </div>
              <p>{call.error_message}</p>
              <small>{call.latency_ms}ms · {formatDateTime(call.created_at)}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <h2>积分异常提醒</h2>
            <p>需要审计或人工复核的账务变化。</p>
          </div>
        </div>
        <div className="stack-list">
          {data.credit_alerts.map((alert) => (
            <article className={`stack-item alert ${alert.severity}`} key={alert.id}>
              <div>
                {alert.severity === "danger" ? <AlertTriangle size={18} /> : <CheckCircle2 size={18} />}
                <strong>{alert.title}</strong>
              </div>
              <p>{alert.detail}</p>
              <small>{formatDateTime(alert.created_at)}</small>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

const statusLabel = {
  pending: "待支付",
  paid: "已支付",
  expired: "已过期",
  cancelled: "已取消",
  failed: "失败",
};

const statusTone = {
  pending: "pending",
  paid: "paid",
  expired: "failed",
  cancelled: "failed",
  failed: "failed",
};

function DashboardSkeleton() {
  return (
    <div className="dashboard-grid">
      <section className="metric-grid">
        {Array.from({ length: 10 }).map((_, index) => (
          <article className="metric-card skeleton" key={index} />
        ))}
      </section>
      <section className="panel wide skeleton-block" />
      <section className="panel skeleton-block" />
      <section className="panel skeleton-block" />
    </div>
  );
}
