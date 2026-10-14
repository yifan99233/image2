import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { request } from "@/services/http";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";

export function RedeemCredits() {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  return <section className="recharge-plans-panel redeem-credits">
    <div className="recharge-section-title"><div><h2>兑换码兑换</h2><p>输入兑换码，额度将计入赠送余额。每码仅可兑换一次。</p></div></div>
    <form onSubmit={async event => {
      event.preventDefault(); if (busy || !code.trim()) return;
      setBusy(true); setError(""); setSuccess("");
      try {
        const result = await request<{ amount: number }>("/credits/redeem", { method: "POST", body: { code: code.trim() } });
        setSuccess(`兑换成功：${result.amount} 积分已计入赠送余额。`); setCode(""); notifyCreditBalanceChanged();
      } catch (e) { setError(e instanceof Error ? e.message : "兑换失败，请稍后重试"); }
      finally { setBusy(false); }
    }}>
      <label className="field">兑换码<input autoComplete="off" spellCheck={false} required maxLength={100} value={code} disabled={busy} onChange={event => setCode(event.target.value)} placeholder="粘贴完整兑换码" /></label>
      <Button type="submit" isLoading={busy} disabled={!code.trim()}>兑换赠送积分</Button>
      {error && <p className="recharge-error" role="alert">{error}</p>}
      {success && <p role="status">{success}</p>}
    </form>
  </section>;
}
