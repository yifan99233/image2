import { useCallback, useEffect, useRef, useState } from "react";
import { request } from "../services/http";

type CodeRow = { id: string; code_hint: string; amount: number; status: string; note: string; batch_id: string; redeemed_by: number | null; created_at: string; expires_at: string | null };
type Generated = { batch_id: string; codes: { code: string; amount: number }[] };
const labels: Record<string, string> = { unused: "未使用", processing: "到账处理中", redeemed: "已兑换", disabled: "已停用", expired: "已过期" };

export function RedemptionCodesPage() {
  const [amount, setAmount] = useState(100);
  const [count, setCount] = useState(1);
  const [note, setNote] = useState("");
  const [expiry, setExpiry] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<CodeRow[]>([]);
  const [total, setTotal] = useState(0);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [confirmId, setConfirmId] = useState<string | null>(null);
  const generationId = useRef(crypto.randomUUID());
  const generationPayload = useRef<string | null>(null);
  const loadVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++loadVersion.current;
    setLoading(true);
    try {
      const data = await request<{ items: CodeRow[]; total: number }>(`/admin/redemption-codes?page=${page}&page_size=50${status ? `&status=${status}` : ""}`);
      if (version === loadVersion.current) { setRows(data.items); setTotal(data.total); }
    } catch (e) { if (version === loadVersion.current) setError(e instanceof Error ? e.message : "加载失败"); }
    finally { if (version === loadVersion.current) setLoading(false); }
  }, [page, status]);
  useEffect(() => { void load(); return () => { loadVersion.current++; }; }, [load]);
  const generate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    if (!Number.isInteger(amount) || amount < 1 || amount > 1000000 || !Number.isInteger(count) || count < 1 || count > 1000) { setError("额度须为 1–1000000 整数积分，数量须为 1–1000"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      const values = { amount, count, note, expires_at: expiry ? new Date(expiry).toISOString() : null };
      const signature = JSON.stringify(values);
      if (generationPayload.current !== null && signature !== generationPayload.current) generationId.current = crypto.randomUUID();
      generationPayload.current = signature;
      const result = await request<Generated>("/admin/redemption-codes", { method: "POST", body: JSON.stringify({ ...values, request_id: generationId.current }) });
      setGenerated(result); generationId.current = crypto.randomUUID(); generationPayload.current = null;
      setMessage(`已生成 ${result.codes.length} 个兑换码，共 ${amount * count} 赠送积分。请立即复制或下载保存。`);
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "生成失败"); }
    finally { setBusy(false); }
  };
  const exportText = generated?.codes.map(row => `${row.code}\t${row.amount}`).join("\n") ?? "";
  const download = () => {
    const url = URL.createObjectURL(new Blob(["兑换码\t赠送积分\n" + exportText], { type: "text/plain;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `兑换码-${generated?.batch_id}.txt`; link.click(); URL.revokeObjectURL(url);
  };
  const disable = async (id: string) => {
    setBusy(true); setError("");
    try { await request(`/admin/redemption-codes/${id}/disable`, { method: "POST" }); setConfirmId(null); setMessage("兑换码已停用"); await load(); }
    catch (e) { setError(e instanceof Error ? e.message : "停用失败"); }
    finally { setBusy(false); }
  };
  return <div className="management-page redemption-page">
    <header className="page-header"><div><h1>兑换码管理</h1><p>每码仅限一人兑换一次，额度计入赠送，不计入充值。</p></div></header>
    {error && <div role="alert" className="error-banner">{error}</div>}
    {message && <p role="status">{message}</p>}
    <section className="panel"><h2>生成兑换码</h2>
      <form onSubmit={generate} className="redemption-form">
        <label className="field">每码赠送积分<input type="number" min="1" max="1000000" step="1" required value={amount} onChange={e => setAmount(Number(e.target.value))} /></label>
        <label className="field">生成数量（1 为单个）<input type="number" min="1" max="1000" step="1" required value={count} onChange={e => setCount(Number(e.target.value))} /></label>
        <label className="field">到期时间（可选）<input type="datetime-local" value={expiry} onChange={e => setExpiry(e.target.value)} /></label>
        <label className="field">备注<input maxLength={200} value={note} onChange={e => setNote(e.target.value)} /></label>
        <p>本批次总额度：{(amount * count || 0).toLocaleString()} 积分。完整兑换码仅在生成后展示，请保存后再生成下一批。</p>
        <button className="primary-button" disabled={busy}>{busy ? "处理中…" : count === 1 ? "生成兑换码" : "批量生成兑换码"}</button>
      </form>
    </section>
    {generated && <section className="panel"><h2>本次生成结果</h2><label className="field">兑换码与额度<textarea readOnly rows={Math.min(8, generated.codes.length + 1)} value={exportText} /></label><div className="row-actions">
      <button className="secondary-button" onClick={async () => { try { await navigator.clipboard.writeText(exportText); setMessage("已复制兑换码和额度"); } catch { setError("复制失败，请下载保存或手动选择复制"); } }}>复制全部</button>
      <button className="secondary-button" onClick={download}>下载保存</button>
    </div></section>}
    <section className="panel"><div className="row-actions"><h2>兑换码记录</h2><label className="field">状态<select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}>{["", ...Object.keys(labels)].map(value => <option key={value} value={value}>{labels[value] ?? "全部"}</option>)}</select></label><button className="secondary-button" disabled={loading} onClick={() => void load()}>刷新</button></div>
      <div className="table-wrap"><table><thead><tr><th>尾号</th><th>赠送积分</th><th>状态</th><th>兑换用户 ID</th><th>到期时间</th><th>备注</th><th>操作</th></tr></thead><tbody>
        {loading ? <tr><td colSpan={7}>加载中…</td></tr> : rows.length === 0 ? <tr><td colSpan={7}>暂无兑换码记录，可在上方生成。</td></tr> : rows.map(row => <tr key={row.id}><td title={`批次 ${row.batch_id}`}>…{row.code_hint}</td><td>{row.amount.toLocaleString()}</td><td>{labels[row.status] ?? row.status}</td><td>{row.redeemed_by ?? "—"}</td><td>{row.expires_at ? new Date(row.expires_at).toLocaleString() : "永久有效"}</td><td>{row.note || "—"}</td><td>{["unused", "expired"].includes(row.status) && (confirmId === row.id ? <div><p>停用后将无法兑换。</p><button className="secondary-button compact" disabled={busy} onClick={() => void disable(row.id)}>确认停用</button><button className="secondary-button compact" disabled={busy} onClick={() => setConfirmId(null)}>取消</button></div> : <button className="secondary-button compact" disabled={busy} onClick={() => setConfirmId(row.id)}>停用</button>)}</td></tr>)}
      </tbody></table></div>
      <div className="row-actions"><button className="secondary-button" disabled={loading || page <= 1} onClick={() => setPage(p => p - 1)}>上一页</button><span>第 {page} 页 · 共 {total} 条</span><button className="secondary-button" disabled={loading || page * 50 >= total} onClick={() => setPage(p => p + 1)}>下一页</button></div>
    </section>
  </div>;
}
