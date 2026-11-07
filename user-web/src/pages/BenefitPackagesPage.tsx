import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Loader2, QrCode, ShoppingBag } from "lucide-react";
import QRCode from "qrcode";
import { Button } from "@/components/ui/Button";
import { benefitService } from "@/services/benefits";
import type { BenefitGrant, BenefitOrder, BenefitPackage, BenefitResourceType } from "@/types/api";

const resourceLabels: Record<BenefitResourceType, string> = {
  credits: "积分",
  team_seats: "团队人数",
  image_concurrency: "图片并发",
  video_concurrency: "视频并发",
  task_queue_limit: "排队任务",
  api_quota: "API 额度",
  storage_quota: "存储空间",
};

const formatMoney = (amountCents: number) => `¥${(amountCents / 100).toFixed(0)}`;

export const BenefitPackagesPage = () => {
  const [packages, setPackages] = useState<BenefitPackage[]>([]);
  const [grants, setGrants] = useState<BenefitGrant[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [order, setOrder] = useState<BenefitOrder | null>(null);
  const [qrCode, setQrCode] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const pollingRef = useRef<number | null>(null);

  useEffect(() => {
    let ignore = false;
    Promise.all([benefitService.getPackages(), benefitService.getGrants()]).then(([items, currentGrants]) => {
      if (ignore) return;
      setPackages(items);
      setGrants(currentGrants);
      setSelectedId(items.find((item) => item.is_recommended)?.id ?? items[0]?.id ?? null);
    }).catch((reason) => {
      if (!ignore) setError(reason instanceof Error ? reason.message : "权益套餐加载失败");
    }).finally(() => {
      if (!ignore) setLoading(false);
    });
    return () => { ignore = true; if (pollingRef.current) window.clearInterval(pollingRef.current); };
  }, []);

  const selected = packages.find((item) => item.id === selectedId) ?? null;
  const paymentLink = order?.pay_url || order?.qr_code || "";

  useEffect(() => {
    let ignore = false;
    if (!paymentLink || order?.status !== "pending") { setQrCode(null); return; }
    QRCode.toDataURL(paymentLink, { errorCorrectionLevel: "M", margin: 1, width: 220 }).then((value) => { if (!ignore) setQrCode(value); });
    return () => { ignore = true; };
  }, [paymentLink, order?.status]);

  const pollOrder = (orderId: number) => {
    if (pollingRef.current) window.clearInterval(pollingRef.current);
    pollingRef.current = window.setInterval(() => {
      void benefitService.getOrder(orderId).then((latest) => {
        setOrder(latest);
        if (latest.status !== "pending" && pollingRef.current) {
          window.clearInterval(pollingRef.current);
          pollingRef.current = null;
        }
      }).catch(() => undefined);
    }, 2000);
  };

  const createOrder = async () => {
    if (!selected || creating) return;
    if (selected.purchase_mode === "subscription") {
      setError("自动订阅暂未接入当前支付渠道，请先选择一次性套餐");
      return;
    }
    setCreating(true);
    setError("");
    try {
      const nextOrder = await benefitService.createOrder(selected.id);
      setOrder(nextOrder);
      pollOrder(nextOrder.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建权益订单失败");
    } finally {
      setCreating(false);
    }
  };

  return <main className="page-surface"><header className="page-header"><div><h1>会员权益</h1><p>按套餐获得积分、团队席位、并发和其他额度，权益按套餐配置的有效期生效。</p></div></header>
    {error ? <div className="recharge-error">{error}</div> : null}
    {loading ? <div className="list-state">正在加载权益套餐…</div> : null}
    {!loading && grants.length ? <section className="panel"><div className="recharge-section-title"><div><h2>当前生效权益</h2><p>按当前工作区展示，过期权益会自动停止。</p></div></div><div className="plan-grid">{grants.map((grant) => <div className="plan-card" key={grant.id}><span className="plan-card__top"><strong>{resourceLabels[grant.resource_type]}</strong><em>{grant.status === "scheduled" ? "待生效" : "生效中"}</em></span><span className="plan-card__price">{Number(grant.remaining_amount ?? grant.amount).toLocaleString()}</span><small>{grant.expires_at ? `有效至 ${new Date(grant.expires_at).toLocaleString()}` : "永久有效"}</small></div>)}</div></section> : null}
    {!loading && !packages.length ? <div className="list-state">当前没有上架的权益套餐。</div> : null}
    {packages.length ? <section className="recharge-shell"><div className="recharge-plans-panel"><div className="recharge-section-title"><div><h2>选择权益套餐</h2><p>套餐中的按天、按周权益会在对应周期自动发放。</p></div></div><div className="plan-grid">{packages.map((packageItem) => <button className={packageItem.id === selectedId ? "plan-card plan-card--active" : "plan-card"} key={packageItem.id} type="button" onClick={() => { setSelectedId(packageItem.id); setOrder(null); }}>{<span className="plan-card__top"><strong>{packageItem.name}</strong>{packageItem.badge ? <em>{packageItem.badge}</em> : null}</span>}<span className="plan-card__price">{formatMoney(packageItem.amount_cents)}</span><small>{packageItem.purchase_mode === "subscription" ? `自动订阅 · ${packageItem.billing_interval}（待支付接入）` : "一次性购买"} · {packageItem.validity_mode === "fixed_days" ? `${packageItem.validity_value} 天有效` : packageItem.validity_mode === "permanent" ? "永久有效" : "订阅周期有效"}</small><small className="plan-card__benefit">{packageItem.items.map((item) => `${resourceLabels[item.resource_type]} ${item.amount}${item.grant_mode === "one_time" ? "" : ` · ${item.grant_mode === "daily" ? "每日" : "每周"}`}`).join(" · ")}</small></button>)}</div></div><aside className="payment-panel"><div className="payment-summary"><ShoppingBag size={22} /><div><strong>{selected?.name ?? "请选择套餐"}</strong><span>{selected ? `${formatMoney(selected.amount_cents)} · ${selected.purchase_mode === "subscription" ? "自动订阅（待支付接入）" : "一次性购买"}` : "选择套餐后创建订单"}</span></div></div><Button type="button" disabled={!selected || selected.purchase_mode === "subscription" || creating || order?.status === "paid"} onClick={() => void createOrder()}>{creating ? <Loader2 className="spin-icon" size={17} /> : <ShoppingBag size={17} />}{order?.status === "paid" ? "已生效" : selected?.purchase_mode === "subscription" ? "订阅待接入" : "立即购买"}</Button>{order ? <div className="qr-box">{order.status === "paid" ? <CheckCircle2 size={54} /> : qrCode ? <img className="payment-qr-image" src={qrCode} alt="支付二维码" /> : <QrCode size={54} />}<strong>{order.status === "paid" ? "支付成功，权益已发放" : order.status === "pending" ? "等待支付" : "订单未完成"}</strong><span>订单号 {order.order_no}</span>{order.failure_message ? <small>{order.failure_message}</small> : null}</div> : null}</aside></section> : null}
  </main>;
};
