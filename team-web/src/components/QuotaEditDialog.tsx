import { type FormEvent, useEffect, useState } from "react";
import { CircleAlert, LoaderCircle, X } from "lucide-react";
import type { MemberUsage, QuotaUpdateInput } from "../services/team";

const memberName = (member: MemberUsage) => member.nickname || member.username || member.email;

function parseQuota(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

export function QuotaEditDialog({
  member,
  siteName,
  onClose,
  onSave,
}: {
  member: MemberUsage;
  siteName: string;
  onClose: () => void;
  onSave: (input: QuotaUpdateInput) => Promise<void>;
}) {
  const [textQuota, setTextQuota] = useState(String(member.text?.quota ?? 0));
  const [imageQuota, setImageQuota] = useState(String(member.image?.quota ?? 0));
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape" && !isSaving) onClose(); };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isSaving, onClose]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedTextQuota = parseQuota(textQuota);
    const parsedImageQuota = parseQuota(imageQuota);
    if (parsedTextQuota == null || parsedImageQuota == null) {
      setError("请输入大于或等于 0 的额度");
      return;
    }
    setError("");
    setIsSaving(true);
    try {
      await onSave({ text_quota: parsedTextQuota, image_quota: parsedImageQuota });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "额度保存失败");
    } finally {
      setIsSaving(false);
    }
  }

  return <div className="dialog-backdrop" role="presentation" onMouseDown={() => !isSaving && onClose()}>
    <form className="dialog quota-dialog" role="dialog" aria-modal="true" aria-labelledby="quota-dialog-title" onMouseDown={(event) => event.stopPropagation()} onSubmit={submit}>
      <button className="icon-button" type="button" aria-label="关闭" disabled={isSaving} onClick={onClose}><X size={18} /></button>
      <div><p className="eyebrow">成员额度</p><h2 id="quota-dialog-title">编辑 {memberName(member)} 的使用上限</h2></div>
      <p>两项额度由 {siteName || "当前子站"} 账户服务分别强制执行。填写 0 表示不限额，已产生的用量不会因修改额度而清零。</p>
      <div className="quota-form-grid">
        <label>Token 额度<input type="number" min="0" step="0.0001" value={textQuota} onChange={(event) => setTextQuota(event.target.value)} autoFocus /></label>
        <label>图片/视频额度<input type="number" min="0" step="0.0001" value={imageQuota} onChange={(event) => setImageQuota(event.target.value)} /></label>
      </div>
      <div className="quota-help"><strong>0 = 不限额</strong><span>建议为不同业务分别设置上限，避免互相挤占。</span></div>
      {error ? <p className="form-error"><CircleAlert size={15} />{error}</p> : null}
      <div className="dialog-actions"><button className="button button-quiet" type="button" disabled={isSaving} onClick={onClose}>取消</button><button className="button button-primary" disabled={isSaving}>{isSaving ? <LoaderCircle className="spin" size={16} /> : null}保存额度</button></div>
    </form>
  </div>;
}
