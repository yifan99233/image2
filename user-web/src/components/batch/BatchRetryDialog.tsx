import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Loader2, RotateCcw, X } from "lucide-react";
import { imageTaskService } from "@/services/imageTasks";
import { ApiError } from "@/services/apiError";
import type { ImageBatchRetryQuote, ImageBatchSubmission } from "@/types/api";

export function BatchRetryDialog({
  batchId,
  onClose,
  onCreated,
}: {
  batchId: string;
  onClose: () => void;
  onCreated: (batch: ImageBatchSubmission) => void;
}) {
  const [quote, setQuote] = useState<ImageBatchRetryQuote | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const requestId = useRef(crypto.randomUUID());
  const inFlight = useRef(false);
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setQuote(null);
    imageTaskService
      .getBatchRetryQuote(batchId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setQuote(value);
      })
      .catch((err) => {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : "读取重试费用失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [batchId, refresh]);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !inFlight.current) close.current();
      if (event.key !== "Tab") return;
      const buttons = [
        ...(dialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)") ?? []),
      ];
      const first = buttons[0],
        last = buttons.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (
        event.shiftKey &&
        (document.activeElement === first || document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        last?.focus();
      } else if (
        !event.shiftKey &&
        (document.activeElement === last || document.activeElement === dialog.current)
      ) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", keydown);
      previousFocus?.focus();
    };
  }, []);

  const submit = async () => {
    if (!quote || inFlight.current) return;
    inFlight.current = true;
    setSubmitting(true);
    setError(null);
    try {
      const result = await imageTaskService.retryBatch(quote, requestId.current);
      onCreated(result);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
        if (err.status === 409 || err.status === 404) {
          setQuote(null);
          requestId.current = crypto.randomUUID();
        }
      } else {
        setError("提交结果尚未确认，请再次点击确认重试。重复提交不会重复创建任务或扣费。");
      }
    } finally {
      inFlight.current = false;
      setSubmitting(false);
    }
  };

  return createPortal(
    <div
      className="app-shell--yiyuan modal-backdrop batch-retry-modal"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget && !inFlight.current) onClose();
      }}
    >
      <div
        className="confirm-dialog batch-retry-dialog"
        ref={dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="batch-retry-title"
        aria-describedby="batch-retry-description"
        aria-busy={submitting || loading}
        tabIndex={-1}
      >
        <div className="batch-retry-dialog__heading">
          <div className="batch-retry-dialog__icon"><RotateCcw size={20} /></div>
          <button className="batch-retry-dialog__close" aria-label="关闭重试窗口" type="button" disabled={submitting} onClick={onClose}><X size={20} /></button>
        </div>
        <h2 id="batch-retry-title">重试失败图片</h2>
        <p id="batch-retry-description">
          在当前批次继续处理，保留原提示词、参考图和生成规格。
        </p>
        {loading ? <p role="status">正在计算重试数量和费用…</p> : null}
        {quote ? (
          <div className="batch-retry-dialog__quote">
            <div><span>重试数量</span><strong>{quote.task_count} <small>张</small></strong></div>
            <div><span>本次费用</span><strong>{quote.total_credit_cost} <small>积分</small></strong></div>
          </div>
        ) : null}
        {quote ? <p className="batch-retry-dialog__note">失败任务的退款按原记录处理，本次按当前价格计费。批次总张数保持不变。</p> : null}
        {error ? (
          <p className="batch-progress__error" role="alert">
            {error}
          </p>
        ) : null}
        {submitting ? <div className="batch-retry-dialog__status" role="status"><Loader2 size={16} className="spin-icon" /><span>正在接收重试请求…</span></div> : null}
        <div className="dialog-actions">
          <button className="task-button" type="button" disabled={submitting} onClick={onClose}>
            取消
          </button>
          {!quote && !loading ? (
            <button
              className="task-button"
              type="button"
              onClick={() => setRefresh((value) => value + 1)}
            >
              重新获取费用
            </button>
          ) : null}
          <button
            className="task-button task-button--blue"
            type="button"
            disabled={loading || submitting || !quote}
            onClick={() => void submit()}
          >
            {submitting ? <Loader2 size={15} className="spin-icon" /> : <RotateCcw size={15} />}
            {submitting ? "提交中…" : "确认重试"}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
