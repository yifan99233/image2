import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { X } from "lucide-react";
import { assignCustomerVip, getVipTiers, saveVipTier } from "../../services/adminApi";
import type { ManagedUser, VipTier } from "../../types";

export function customerVipLabel(user: ManagedUser) {
  const vip = user.vip;
  if (!vip) return "普通客户";
  if (!vip.is_active) return `${vip.name}（已停用）`;
  if (vip.expires_at && Date.parse(vip.expires_at) <= Date.now()) return `${vip.name}（已到期）`;
  return `${vip.name} · ${Number((vip.discount_rate * 10).toFixed(3))} 折`;
}

function VipModal({ title, busy, onClose, children }: { title: string; busy: boolean; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.querySelector<HTMLElement>("button, input, select")?.focus();
    return () => previous?.focus();
  }, []);
  return <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={title} onKeyDown={(event) => {
    if (event.key === "Escape" && !busy) onClose();
    if (event.key === "Tab") {
      const nodes = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)');
      if (!nodes?.length) return;
      const first = nodes[0], last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }}><div className="modal vip-modal" ref={ref}>
    <button className="modal-close" type="button" disabled={busy} onClick={onClose} aria-label="关闭"><X size={18} /></button>
    <h3>{title}</h3>{children}
  </div></div>;
}

export function VipTiersDialog({ tier, onClose, afterDone }: { tier?: VipTier; onClose: () => void; afterDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [name, setName] = useState(tier?.name ?? "");
  const [discount, setDiscount] = useState(String(tier ? Number((tier.discount_rate * 10).toFixed(3)) : 8));
  const [active, setActive] = useState(tier?.is_active ?? true);
  const [reason, setReason] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!name.trim() || !reason.trim()) { setError("请填写等级名称和变更原因"); return; }
    const rate = Number(discount) / 10;
    if (!Number.isFinite(rate) || rate < 0.01 || rate > 1) { setError("折扣须在 0.1 至 10 折之间"); return; }
    setBusy(true);
    try {
      await saveVipTier({ name: name.trim(), discount_rate: Number(rate.toFixed(4)), is_active: active, reason: reason.trim() }, tier?.id);
      afterDone(); onClose();
    } catch (err) { setError(err instanceof Error ? err.message : "保存失败"); }
    finally { setBusy(false); }
  }
  return <VipModal title={tier ? "编辑 VIP 等级" : "新建 VIP 等级"} busy={busy} onClose={onClose}>
    <p>折扣只作用于模型基础价格，固定加价照常收取。普通客户为 10 折。</p>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <label className="field">等级名称<input required maxLength={64} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <label className="field">客户折扣（折）<input required type="number" min="0.1" max="10" step="0.001" value={discount} onChange={(event) => setDiscount(event.target.value)} /><small>例如填写 8 表示八折，基础价格 × 0.8。</small></label>
        <label className="check-line"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />启用此等级</label>
        {tier ? <p className="inline-hint">修改折扣会影响该等级的所有客户；停用后新任务恢复普通价格。已提交任务保持原价。</p> : null}
        <label className="field">变更原因<textarea required maxLength={500} rows={2} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      </fieldset>
      {error ? <div className="form-error" role="alert">{error}</div> : null}
      <div className="modal-actions"><button className="secondary-button" type="button" disabled={busy} onClick={onClose}>取消</button><button className="primary-button" disabled={busy}>{busy ? "保存中…" : tier ? "保存等级变更" : "创建等级"}</button></div>
    </form>
  </VipModal>;
}

export function CustomerVipDialog({ user, onClose, afterDone }: { user: ManagedUser; onClose: () => void; afterDone: () => void }) {
  const [tiers, setTiers] = useState<VipTier[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tierId, setTierId] = useState(user.vip?.tier_id ? String(user.vip.tier_id) : "");
  const [expiry, setExpiry] = useState(() => {
    if (!user.vip?.expires_at) return "";
    const date = new Date(user.vip.expires_at);
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  });
  const [reason, setReason] = useState("");
  const selectedTier = tiers.find((tier) => String(tier.id) === tierId);
  async function load() {
    setLoading(true); setLoaded(false); setError("");
    try { setTiers(await getVipTiers(user.site_id)); setLoaded(true); }
    catch (err) { setError(err instanceof Error ? err.message : "VIP 等级读取失败"); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [user.id]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError("");
    if (!reason.trim()) { setError("请填写变更原因"); return; }
    if (tierId && !selectedTier?.is_active) { setError("请选择有效 VIP 等级"); return; }
    if (tierId && expiry && (!Number.isFinite(Date.parse(expiry)) || Date.parse(expiry) <= Date.now())) { setError("有效期须晚于当前时间"); return; }
    setBusy(true);
    try {
      await assignCustomerVip(user.id, { tier_id: tierId ? Number(tierId) : null, expires_at: tierId && expiry ? new Date(expiry).toISOString() : null, reason: reason.trim() });
      afterDone(); onClose();
    } catch (err) { setError(err instanceof Error ? err.message : "保存失败"); }
    finally { setBusy(false); }
  }
  return <VipModal title="设置客户 VIP" busy={busy} onClose={onClose}>
    <p>{user.username} · 当前：{customerVipLabel(user)}</p>
    <p>团队共用钱包时按钱包所有者的 VIP 等级计价，请为团队所有者设置。</p>
    <form onSubmit={submit}>
      <label className="field">客户等级<select value={tierId} disabled={busy || loading || !loaded} onChange={(event) => setTierId(event.target.value)}>
        <option value="">普通客户（不打折）</option>
        {tierId && !tiers.some((tier) => String(tier.id) === tierId) ? <option value={tierId} disabled>{user.vip?.name ?? "当前等级"}（不可用）</option> : null}
        {tiers.map((tier) => <option key={tier.id} value={tier.id} disabled={!tier.is_active}>{tier.name} · {Number((tier.discount_rate * 10).toFixed(3))} 折{tier.is_active ? "" : "（停用）"}</option>)}
      </select></label>
      {loading ? <div className="inline-state">正在读取等级…</div> : null}
      {tierId ? <label className="field">有效期（本地时间）<input type="datetime-local" value={expiry} disabled={busy} onChange={(event) => setExpiry(event.target.value)} /><small>留空表示长期有效；到期后新任务恢复普通价格。</small></label> : null}
      <label className="field">变更原因<textarea required maxLength={500} rows={2} disabled={busy} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
      {error ? <div className="form-error" role="alert">{error}<button className="link-button" type="button" disabled={busy} onClick={() => void load()}>重新读取</button></div> : null}
      <div className="modal-actions"><button className="secondary-button" type="button" disabled={busy} onClick={onClose}>取消</button><button className="primary-button" disabled={busy || loading || !loaded}>{busy ? "保存中…" : "保存客户 VIP"}</button></div>
    </form>
  </VipModal>;
}
