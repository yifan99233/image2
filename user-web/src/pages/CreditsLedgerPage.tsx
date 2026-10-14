import { useEffect, useMemo, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, Coins, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { creditService } from "@/services/credits";
import type { CreditBalance, CreditLedgerItem } from "@/types/api";

const formatPaymentAmount = (amountCents: number) => `¥${(amountCents / 100).toFixed(2)}`;

const bizTypeLabels: Record<CreditLedgerItem["biz_type"], string> = {
  recharge: "充值",
  redemption_gift: "兑换码赠送",
  image_task: "消费",
  refund: "退款",
  admin_adjustment: "后台调整",
  signin: "签到",
  invite: "邀请",
  agent_transfer: "Codex定制版划转",
  agent_transfer_refund: "Codex定制版退回",
};

export const CreditsLedgerPage = () => {
  const [items, setItems] = useState<CreditLedgerItem[]>([]);
  const [balance, setBalance] = useState<CreditBalance | null>(null);
  const [filter, setFilter] = useState<"all" | CreditLedgerItem["biz_type"]>("all");
  const [keyword, setKeyword] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const [creditBalance, ledger] = await Promise.all([creditService.getBalance(), creditService.getLedger()]);
      setBalance(creditBalance);
      setItems(ledger);
    } catch (err) {
      setError(err instanceof Error ? err.message : "积分记录加载失败");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(
    () =>
      items.filter((item) => {
        const typeMatched = filter === "all" || item.biz_type === filter;
        const keywordMatched = !keyword || item.description.toLowerCase().includes(keyword.toLowerCase());
        return typeMatched && keywordMatched;
      }),
    [filter, items, keyword],
  );

  const summary = useMemo(
    () =>
      filtered.reduce(
        (acc, item) => {
          if (item.direction === "credit") acc.credit += item.amount;
          if (item.direction === "debit") acc.debit += item.amount;
          return acc;
        },
        { credit: 0, debit: 0 },
      ),
    [filtered],
  );

  return (
    <main className="page-surface">
      <header className="page-header">
        <div>
          <h1>积分记录</h1>
          <p>查看充值、消费、退款、签到和邀请奖励的积分流水。</p>
        </div>
        <Button variant="secondary" onClick={load} isLoading={isLoading}>
          <RefreshCw size={16} />
          刷新
        </Button>
      </header>

      <section className="ledger-summary">
        <article><span>赠送余额</span><strong>{balance ? balance.gift_balance.toLocaleString() : "--"}</strong></article>
        <article><span>累计赠送</span><strong>{balance ? balance.total_gifted.toLocaleString() : "--"}</strong></article>
        <article>
          <span>当前余额</span>
          <strong>{balance ? balance.balance.toLocaleString() : "--"}</strong>
        </article>
        <article>
          <span>累计充值</span>
          <strong>{balance ? balance.total_recharged.toLocaleString() : "--"}</strong>
        </article>
        <article>
          <span>累计消耗</span>
          <strong>{balance ? balance.total_consumed.toLocaleString() : "--"}</strong>
        </article>
        <article>
          <span>当前筛选净变化</span>
          <strong>{(summary.credit - summary.debit).toLocaleString()}</strong>
        </article>
      </section>

      {error ? (
        <div className="list-state list-state--error">
          {error}
          <Button variant="ghost" onClick={load}>重试</Button>
        </div>
      ) : null}

      <div className="filter-toolbar">
        <div className="search-field">
          <Search size={17} />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索流水说明" />
        </div>
        <select value={filter} onChange={(event) => setFilter(event.target.value as typeof filter)}>
          <option value="all">全部类型</option>
          {Object.entries(bizTypeLabels).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <section className="ledger-list">
        {isLoading ? <div className="list-state">正在加载积分流水...</div> : null}
        {!isLoading && !error && filtered.length === 0 ? (
          <div className="empty-state">
            <Coins size={34} />
            <h3>暂无流水</h3>
            <p>充值、生成图片或获得奖励后，积分变化会显示在这里。</p>
          </div>
        ) : null}
        {filtered.map((item) => (
          <article className="ledger-row" key={item.id}>
            <div className={item.direction === "credit" ? "ledger-icon ledger-icon--credit" : "ledger-icon ledger-icon--debit"}>
              {item.direction === "credit" ? <ArrowUpCircle size={18} /> : <ArrowDownCircle size={18} />}
            </div>
            <div>
              <strong>{item.description}</strong>
              <span>
                {bizTypeLabels[item.biz_type]}
                {item.biz_type === "recharge" && typeof item.payment_amount_cents === "number"
                  ? ` · 充值金额 ${formatPaymentAmount(item.payment_amount_cents)}`
                  : ""}
                · {item.created_at}
              </span>
            </div>
            <div className={item.direction === "credit" ? "ledger-amount ledger-amount--credit" : "ledger-amount ledger-amount--debit"}>
              {item.direction === "credit" ? "+" : "-"}
              {item.amount}
              <small>余额 {item.balance_after}</small>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
};
