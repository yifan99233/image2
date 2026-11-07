import type { QuotaUsage } from "../services/team";

const numberFormatter = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 4 });

export function formatAmount(value: number | null | undefined): string {
  return value == null ? "—" : numberFormatter.format(value);
}

export function usageProgressPercent(usage: QuotaUsage): number {
  if (usage.used <= 0) return 0;
  if (usage.unlimited || usage.quota <= 0) return 1;
  return Math.min(100, Math.max(1, (usage.used / usage.quota) * 100));
}

export function UsageProgress({ usage }: { usage: QuotaUsage }) {
  const percent = usageProgressPercent(usage);
  const state = !usage.unlimited && percent >= 100 ? "is-exhausted" : !usage.unlimited && percent >= 80 ? "is-warning" : "";
  const progressLabel = usage.unlimited
    ? `不限额，已使用 ${formatAmount(usage.used)}`
    : `已使用 ${percent.toFixed(percent < 10 ? 2 : 0)}%`;

  return <div className={`usage-progress ${state}`}>
    <div className="usage-progress__labels">
      <span>已用 {formatAmount(usage.used)}</span>
      <strong>{usage.unlimited ? "不限额" : `${formatAmount(usage.quota)} 额度`}</strong>
    </div>
    <div className="usage-progress__track" aria-label={progressLabel} title={progressLabel}>
      <span style={{ width: `${percent}%` }} />
    </div>
    <small>{usage.unlimited ? "当前未设置使用上限" : `剩余 ${formatAmount(usage.remaining)}`}</small>
  </div>;
}
