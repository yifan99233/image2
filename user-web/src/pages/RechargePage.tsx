import { LoadingIndicator } from "@/components/ui/LoadingIndicator";
import { RedeemCredits } from "@/components/RedeemCredits";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Coins, QrCode } from "lucide-react";
import QRCode from "qrcode";
import { Button } from "@/components/ui/Button";
import { rechargeService } from "@/services/recharge";
import type { RechargeOrder, RechargePlan } from "@/types/api";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";

const formatMoney = (amountCents: number) => `¥${(amountCents / 100).toFixed(0)}`;

const paymentScanLabel = (paymentType?: string | null) => {
  if (paymentType === "wxpay") return "请使用微信扫码支付";
  if (paymentType === "alipay") return "请使用支付宝扫码支付";
  return "请使用对应 App 扫码支付";
};

export const RechargePage = () => {
  const pollingRef = useRef<number | null>(null);
  const [plans, setPlans] = useState<RechargePlan[]>([]);
  const [selectedPlanId, setSelectedPlanId] = useState<number | null>(null);
  const [order, setOrder] = useState<RechargeOrder | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paymentQrDataUrl, setPaymentQrDataUrl] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    rechargeService
      .getPlans()
      .then((items) => {
        if (ignore) return;
        setPlans(items);
        setSelectedPlanId(items.find((item) => item.is_recommended)?.id ?? items[0]?.id ?? null);
        setError(null);
      })
      .catch((err) => {
        if (!ignore) setError(err instanceof Error ? err.message : "充值档位加载失败");
      });
    return () => {
      ignore = true;
      if (pollingRef.current) window.clearInterval(pollingRef.current);
    };
  }, []);

  const selectedPlan = plans.find((plan) => plan.id === selectedPlanId) ?? null;
  const paymentLink = order?.pay_url || order?.qr_code_url || order?.qr_code || "";
  const orderStatusText = order?.status === "paid" ? "支付成功" : order ? "等待支付" : "未创建订单";

  useEffect(() => {
    let ignore = false;
    if (!paymentLink || order?.status !== "pending") {
      setPaymentQrDataUrl(null);
      return;
    }
    QRCode.toDataURL(paymentLink, { errorCorrectionLevel: "M", margin: 1, width: 220 })
      .then((dataUrl) => {
        if (!ignore) setPaymentQrDataUrl(dataUrl);
      })
      .catch(() => {
        if (!ignore) setPaymentQrDataUrl(null);
      });
    return () => {
      ignore = true;
    };
  }, [paymentLink, order?.status]);

  const createOrder = async () => {
    if (!selectedPlanId || isCreating) return;
    setIsCreating(true);
    setError(null);
    try {
      const nextOrder = await rechargeService.createOrder(selectedPlanId);
      setOrder(nextOrder);
      setIsPolling(true);
      if (pollingRef.current) window.clearInterval(pollingRef.current);
      pollingRef.current = window.setInterval(() => {
        void rechargeService
          .getOrder(nextOrder.id)
          .then((latestOrder) => {
            setOrder(latestOrder);
            if (latestOrder.status !== "pending" && pollingRef.current) {
              window.clearInterval(pollingRef.current);
              pollingRef.current = null;
              setIsPolling(false);
              if (latestOrder.status === "paid") notifyCreditBalanceChanged();
            }
          })
          .catch((err) => {
            setError(err instanceof Error ? err.message : "订单状态查询失败");
            if (pollingRef.current) window.clearInterval(pollingRef.current);
            pollingRef.current = null;
            setIsPolling(false);
          });
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "充值订单创建失败");
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <main className="page-surface">
      <header className="page-header">
        <div>
          <h1>积分充值</h1>
          <p>选择充值档位并创建订单，支付完成后积分会自动刷新到账。</p>
        </div>
      </header>

      <RedeemCredits />
      <section className="recharge-shell">
        {error ? <div className="recharge-error">{error}</div> : null}
        <div className="recharge-plans-panel">
          <div className="recharge-section-title">
            <div>
              <h2>选择充值档位</h2>
              <p>点击一个档位后，点击右侧的立即充值即可充值。</p>
            </div>
          </div>
          <div className="plan-grid">
            {plans.map((plan) => (
              <button
                className={plan.id === selectedPlanId ? "plan-card plan-card--active" : "plan-card"}
                key={plan.id}
                type="button"
                onClick={() => {
                  setSelectedPlanId(plan.id);
                  if (!order || order.status !== "pending") setOrder(null);
                }}
              >
                <span className="plan-card__top">
                  <strong>{plan.name}</strong>
                  {plan.badge ? <em>{plan.badge}</em> : null}
                </span>
                <span className="plan-card__price">{formatMoney(plan.amount_cents)}</span>
                <small>
                  {plan.credit_amount} 积分{plan.bonus_credit_amount > 0 ? ` + 赠送 ${plan.bonus_credit_amount}` : ""}
                </small>
                {plan.team_seat_count > 0 ? (
                  <small className="plan-card__benefit">
                    团队 {plan.team_seat_count} 席 · {plan.team_duration_days > 0 ? `${plan.team_duration_days} 天` : "永久权益"}
                  </small>
                ) : null}
              </button>
            ))}
          </div>
        </div>

        <aside className="payment-panel">
          <div className="payment-summary">
            <Coins size={22} />
            <div>
              <strong>{selectedPlan ? `${selectedPlan.total_credit_amount} 积分` : "请选择档位"}</strong>
              <span>{selectedPlan ? `${formatMoney(selectedPlan.amount_cents)} · ${selectedPlan.name}` : "选择档位后即可创建充值订单"}</span>
            </div>
          </div>
          <Button type="button" disabled={!selectedPlan || isCreating || isPolling || order?.status === "paid"} onClick={createOrder}>
            {isCreating || isPolling ? <LoadingIndicator className="spin-icon" size={17} /> : <Coins size={17} />}
            {order?.status === "paid" ? "已到账" : order ? "支付状态确认中" : "立即充值"}
          </Button>
          {order ? (
            <div className="qr-box">
              {order.status === "pending" ? (
                <div className={`scan-method-badge scan-method-badge--${order.payment_type === "wxpay" ? "wxpay" : "alipay"}`}>
                  {paymentScanLabel(order.payment_type)}
                </div>
              ) : null}
              {order.status === "paid" ? (
                <CheckCircle2 size={54} />
              ) : paymentQrDataUrl ? (
                <img className="payment-qr-image" src={paymentQrDataUrl} alt="支付二维码" />
              ) : (
                <QrCode size={54} />
              )}
              <strong>{orderStatusText}</strong>
              <span>订单号 {order.order_no}</span>
              {order.failure_message ? <small>{order.failure_message}</small> : null}
            </div>
          ) : null}
          {order && order.status !== "pending" && order.status !== "paid" ? (
            <Button type="button" disabled={!selectedPlan || isCreating} onClick={createOrder}>
              <Coins size={17} />
              重新创建订单
            </Button>
          ) : null}
        </aside>
      </section>
    </main>
  );
};
