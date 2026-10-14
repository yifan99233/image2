import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Download, Loader2, RefreshCw, RotateCcw } from "lucide-react";
import { BatchRetryDialog } from "@/components/batch/BatchRetryDialog";
import { BatchTaskDetails } from "@/components/batch/BatchTaskDetails";
import { imageTaskService } from "@/services/imageTasks";
import type { ImageBatchSummary, ImageTask, ImageBatchSubmission } from "@/types/api";
import { startBrowserDownload } from "@/utils/download";
import { notifyCreditBalanceChanged } from "@/utils/creditEvents";
import { downloadBatchFromCdn } from "@/services/browserBatchDownload";
import type { ExportProgress } from "@/utils/browserBatchExport";

const message = (error: unknown) => (error instanceof Error ? error.message : "请求失败，请重试");
const isActive = (batch: ImageBatchSummary) =>
  batch.pending_count + batch.queued_count + batch.running_count > 0;

export function BatchTaskPanel({
  workType,
  latestBatchId,
  onBatchCreated,
  tasks = [],
  revision = 0,
  onTasksLoaded,
  renderTasks,
}: {
  workType: string;
  latestBatchId: string;
  onBatchCreated?: (batch: ImageBatchSubmission) => void;
  tasks?: ImageTask[];
  revision?: number;
  onTasksLoaded?: (tasks: ImageTask[]) => void;
  renderTasks?: (tasks: ImageTask[]) => ReactNode;
}) {
  const [batches, setBatches] = useState<ImageBatchSummary[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [retryBatchId, setRetryBatchId] = useState<string | null>(null);
  const [expandedRecords, setExpandedRecords] = useState<string | null>(null);
  const pageRequest = useRef<AbortController | null>(null);
  const downloadController = useRef<AbortController | null>(null);
  const [downloadProgress, setDownloadProgress] = useState<ExportProgress | null>(null);
  useEffect(() => () => { downloadController.current?.abort(); }, []);
  useEffect(() => {
    if (!downloading.length) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [downloading.length]);

  useEffect(() => {
    const controller = new AbortController();
    pageRequest.current?.abort();
    pageRequest.current = controller;
    setLoading(true);
    setError(null);
    imageTaskService
      .getBatches(workType, { signal: controller.signal })
      .then((page) => {
        if (controller.signal.aborted) return;
        setBatches(page.items);
        setPollError(null);
        setCursor(page.has_more ? page.next_cursor : null);
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(message(err));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      pageRequest.current?.abort();
    };
  }, [workType, latestBatchId, refresh, revision]);

  const activeIds = JSON.stringify(batches.filter(isActive).map((batch) => batch.batch_id));
  useEffect(() => {
    const ids: string[] = JSON.parse(activeIds);
    if (!ids.length) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const processedCounts = new Map<string, number>();
    const preparingIds = new Set(batches.filter(batch => (batch.submission_status && batch.submission_status !== "submitted") || (batch.retry_submission_status && batch.retry_submission_status !== "failed")).map(batch => batch.batch_id));
    const poll = async () => {
      try {
        const updates = await imageTaskService.getBatchStatuses(ids, controller.signal);
        if (controller.signal.aborted) return;
        if (updates.some(batch => batch.succeeded_count + batch.failed_count > (processedCounts.get(batch.batch_id) ?? 0))) {
          notifyCreditBalanceChanged();
        }
        if (updates.some(batch => preparingIds.has(batch.batch_id) && !batch.submission_status && !batch.retry_submission_status)) notifyCreditBalanceChanged();
        for (const batch of updates) if (!batch.submission_status && !batch.retry_submission_status) preparingIds.delete(batch.batch_id);
        for (const batch of updates) processedCounts.set(batch.batch_id, batch.succeeded_count + batch.failed_count);
        const byId = new Map(updates.map((batch) => [batch.batch_id, batch]));
        setBatches((current) =>
          current.flatMap((batch) =>
            byId.has(batch.batch_id)
              ? [byId.get(batch.batch_id)!]
              : ids.includes(batch.batch_id)
                ? []
                : [batch],
          ),
        );
        setPollError(null);
      } catch (err) {
        if (!controller.signal.aborted) setPollError(`进度更新失败：${message(err)}`);
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 3000);
    };
    timer = setTimeout(poll, 3000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [activeIds]);

  const loadMore = async () => {
    if (!cursor || loading) return;
    const controller = new AbortController();
    pageRequest.current = controller;
    setLoading(true);
    setError(null);
    try {
      const page = await imageTaskService.getBatches(workType, {
        beforeId: cursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setBatches((current) => [
        ...current,
        ...page.items.filter((batch) => !current.some((item) => item.batch_id === batch.batch_id)),
      ]);
      setCursor(page.has_more ? page.next_cursor : null);
    } catch (err) {
      if (!controller.signal.aborted) setError(message(err));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  };

  const download = async (batch: ImageBatchSummary) => {
    if (downloadController.current) return;
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloadProgress(null);
    setError(null);
    setDownloading((current) => [...current, batch.batch_id]);
    setNotice(null);
    try {
      if (workType === "batch_generate") {
        let lastProgress = 0;
        const result = await downloadBatchFromCdn(batch.batch_id, controller.signal, value => {
          const now = performance.now();
          if (now - lastProgress >= 100 || value.phase !== "images") { setDownloadProgress(value); lastProgress = now; }
        });
        setNotice(`ZIP 已保存：成功 ${result.succeeded} 张，失败 ${result.failed} 张${result.pending ? `，未完成 ${result.pending} 张` : ""}。内含完整汇总、失败汇总和统计文件。`);
        return;
      }
      const url = await imageTaskService.createExportDownloadUrl([], batch.batch_id);
      startBrowserDownload(url);
      setNotice(
        isActive(batch)
          ? "已开始下载当前结果；未完成任务会在汇总中标明，整批完成后可再次打包。"
          : workType === "batch_generate"
            ? "已开始下载 ZIP，内含图片文件夹、完整汇总 Excel、失败汇总 Excel 和结果统计 TXT。"
            : "已开始下载该批次的成功图片 ZIP。压缩包内附任务清单。",
      );
    } catch (err) {
      if (controller.signal.aborted || (err instanceof DOMException && err.name === "AbortError")) setNotice("下载已取消，未保存不完整压缩包。已有生图结果不受影响。");
      else setError(`打包下载失败：${message(err)}`);
    } finally {
      downloadController.current = null;
      setDownloading((current) => current.filter((id) => id !== batch.batch_id));
    }
  };

  return (
    <section className="batch-progress" aria-label="批次进度">
      <div className="batch-progress__heading">
        <div>
          <h3>批次进度</h3>
          <p>最近 30 天提交的批次 · 按整批统计，自动更新</p>
        </div>
        <button
          className="task-button"
          type="button"
          disabled={loading}
          onClick={() => setRefresh((value) => value + 1)}
          aria-label="刷新批次进度"
        >
          <RefreshCw size={15} />
          刷新
        </button>
      </div>
      {error || pollError ? (
        <p className="batch-progress__error" role="alert">
          {error || pollError}{" "}
          <button
            type="button"
            className="task-button"
            disabled={loading}
            onClick={() => setRefresh((value) => value + 1)}
          >
            重试
          </button>
        </p>
      ) : null}
      {notice ? (
        <p className="batch-progress__hint" role="status">
          {notice}
        </p>
      ) : null}
      {downloading.length && workType === "batch_generate" ? (
        <div className="batch-progress__hint" role="status">
          <p>{downloadProgress ? `${downloadProgress.phase === "reports" ? "正在整理汇总" : "CDN 直连下载"}：${downloadProgress.processed}/${downloadProgress.total}，成功 ${downloadProgress.succeeded}，失败 ${downloadProgress.failed}，已写入 ${(downloadProgress.bytes / 1024 ** 2).toFixed(1)} MB` : "请选择 ZIP 保存位置…"}</p>
          <p>图片直接保存到磁盘，请保持本页打开。取消或关闭页面后需要重新下载。</p>
          <button className="task-button" type="button" onClick={() => downloadController.current?.abort()}>取消下载</button>
        </div>
      ) : null}
      {loading && !batches.length ? (
        <p className="batch-progress__hint" role="status">
          正在加载批次…
        </p>
      ) : null}
      {!loading && !error && !pollError && !batches.length ? (
        <p className="batch-progress__hint">提交批量任务后，可在这里查看整批进度并打包下载。</p>
      ) : null}
      {batches.map((batch) => {
        const processed = batch.succeeded_count + batch.failed_count;
        const percent = batch.task_count ? Math.floor((processed / batch.task_count) * 100) : 0;
        const busy = downloading.includes(batch.batch_id);
        const preparing = Boolean(batch.submission_status && batch.submission_status !== "submitted");
        return (
          <article
            className="batch-progress__card"
            key={batch.batch_id}
            aria-label={`批次 ${batch.batch_id}`}
          >
            <div className="batch-progress__title">
              <strong>
                {batch.retry_of_batch_id ? "重试 · " : ""}
                {batch.submission_status === "failed" ? "批次提交失败"
                  : batch.submission_status === "needs_attention" ? "批次待确认"
                  : preparing ? "正在创建任务"
                  : isActive(batch)
                  ? "批次处理中"
                  : batch.failed_count
                    ? "批次已结束 · 有失败"
                    : "批次已完成"}
              </strong>
              <span>共 {batch.task_count} 张</span>
            </div>
            <p className="batch-progress__meta" title={batch.batch_id}>
              {new Date(batch.created_at).toLocaleString("zh-CN")} · {batch.batch_id.slice(-8)}
            </p>
            {preparing ? <p className={batch.submission_error ? "batch-progress__error" : "batch-progress__hint"} role={batch.submission_status === "failed" || batch.submission_status === "needs_attention" ? "alert" : "status"}>
              {batch.submission_error ?? "提示词已上传，正在后台创建任务；刷新页面可继续查看进度。"}
            </p> : null}
            {batch.retry_submission_status ? <p className={batch.retry_submission_error ? "batch-progress__error" : "batch-progress__hint"} role={batch.retry_submission_status === "needs_attention" || batch.retry_submission_status === "failed" ? "alert" : "status"}>
              {batch.retry_submission_error ?? `已接收重试，正在准备 ${batch.pending_count} 张图片；准备完成后自动进入生成队列。`}
            </p> : null}
            {batch.retry_of_batch_id ? (
              <p className="batch-progress__meta" title={batch.retry_of_batch_id}>
                来源批次：{batch.retry_of_batch_id.slice(-8)}
              </p>
            ) : null}
            <div className="batch-progress__label">
              <span>
                处理进度 {processed}/{batch.task_count}
              </span>
              <strong>{percent}%</strong>
            </div>
            <div
              className="batch-progress__bar"
              role="progressbar"
              aria-label={`批次 ${batch.batch_id} 处理进度`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={percent}
            >
              <span style={{ width: `${percent}%` }} />
            </div>
            <dl className="batch-progress__counts">
              <div>
                <dt>{preparing ? "待创建" : "排队中"}</dt>
                <dd>{batch.pending_count + batch.queued_count}</dd>
              </div>
              <div>
                <dt>生成中</dt>
                <dd>{batch.running_count}</dd>
              </div>
              <div>
                <dt>成功</dt>
                <dd>{batch.succeeded_count}</dd>
              </div>
              <div className={batch.failed_count ? "batch-progress__error" : undefined}>
                <dt>失败</dt>
                <dd>{batch.failed_count}</dd>
              </div>
            </dl>
            <div className="batch-progress__actions">
              <button
                className="task-button"
                type="button"
                disabled={preparing}
                aria-expanded={expandedRecords === batch.batch_id}
                onClick={() =>
                  setExpandedRecords((current) =>
                    current === batch.batch_id ? null : batch.batch_id,
                  )
                }
              >
                {expandedRecords === batch.batch_id
                  ? "收起具体记录"
                  : `展开具体记录（${batch.task_count}）`}
              </button>
              <button
                className="task-button task-button--blue"
                type="button"
                disabled={(!batch.downloadable_count && (workType !== "batch_generate" || !batch.failed_count)) || batch.latest_task_id === 0 || downloading.length > 0}
                onClick={() => void download(batch)}
              >
                {busy ? <Loader2 size={15} className="spin-icon" /> : <Download size={15} />}
                {busy ? "下载中…" : !batch.downloadable_count && batch.failed_count && workType === "batch_generate" ? "下载失败汇总" : `打包下载已成功（${batch.downloadable_count}）`}
              </button>
              {batch.failed_count ? (
                <button
                  className="task-button"
                  type="button"
                  aria-expanded={expanded === batch.batch_id}
                  onClick={() =>
                    setExpanded((current) => (current === batch.batch_id ? null : batch.batch_id))
                  }
                >
                  {expanded === batch.batch_id ? "收起失败项" : `查看失败（${batch.failed_count}）`}
                </button>
              ) : null}
              {batch.failed_count ? (
                <button
                  className="task-button task-button--blue"
                  type="button"
                  disabled={!batch.retryable_count}
                  onClick={() => setRetryBatchId(batch.batch_id)}
                  title={
                    !batch.retryable_count
                      ? "仅可重试本人提交且尚未重试的失败任务"
                      : "使用原提示词、参考图和规格重试失败项"
                  }
                >
                  <RotateCcw size={15} />
                  重试失败项（{batch.retryable_count}）
                </button>
              ) : null}
            </div>
            {batch.already_retried_count ? (
              <p className="batch-progress__hint">
                历史版本已另批重试 {batch.already_retried_count} 项，结果保留在对应历史记录中。
              </p>
            ) : null}
            {expanded === batch.batch_id ? (
              <BatchFailureList batchId={batch.batch_id} failedCount={batch.failed_count} />
            ) : null}
            {expandedRecords === batch.batch_id && onTasksLoaded && renderTasks ? (
              <BatchTaskDetails
                batchId={batch.batch_id}
                total={batch.task_count}
                tasks={tasks}
                revision={revision + refresh}
                onTasksLoaded={onTasksLoaded}
                renderTasks={renderTasks}
              />
            ) : null}
          </article>
        );
      })}
      {cursor ? (
        <button
          type="button"
          className="task-button"
          disabled={loading}
          onClick={() => void loadMore()}
        >
          {loading ? "加载中…" : "加载更多批次"}
        </button>
      ) : null}
      {retryBatchId ? (
        <BatchRetryDialog
          key={retryBatchId}
          batchId={retryBatchId}
          onClose={() => setRetryBatchId(null)}
          onCreated={(result) => {
            setRetryBatchId(null);
            setNotice(`已接收 ${result.task_count} 个失败重试任务，将在本批次继续处理。`);
            notifyCreditBalanceChanged();
            onBatchCreated?.(result);
            setRefresh((value) => value + 1);
          }}
        />
      ) : null}
    </section>
  );
}

function BatchFailureList({ batchId, failedCount }: { batchId: string; failedCount: number }) {
  const [tasks, setTasks] = useState<ImageTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(
    async (beforeId?: number) => {
      const controller = new AbortController();
      request.current?.abort();
      request.current = controller;
      setLoading(true);
      setError(null);
      try {
        const page = await imageTaskService.getTasks({
          batchId,
          status: "failed",
          limit: 20,
          beforeId,
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setTasks((current) =>
            beforeId
              ? [...current, ...page.filter((task) => !current.some((item) => item.id === task.id))]
              : page,
          );
          setHasMore(page.length === 20);
        }
      } catch (err) {
        if (!controller.signal.aborted) setError(message(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [batchId],
  );
  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load, failedCount, refresh]);
  return (
    <div className="batch-progress__failures" aria-label="批次失败详情">
      {tasks.map((task) => (
        <div key={task.id}>
          <strong>
            {task.input_group_name ? `${task.input_group_name} · ` : ""}
            {task.task_no}
          </strong>
          <p>{task.failure_message || "任务失败，未返回具体原因"}</p>
        </div>
      ))}
      {error ? (
        <p role="alert">
          {error}{" "}
          <button
            type="button"
            className="task-button"
            onClick={() => setRefresh((value) => value + 1)}
          >
            重试
          </button>
        </p>
      ) : null}
      {loading ? (
        <p role="status">正在加载失败详情…</p>
      ) : !tasks.length && !error ? (
        <p>暂无可见失败记录</p>
      ) : null}
      {!loading && hasMore && tasks.length > 0 && tasks.length < failedCount ? (
        <button
          className="task-button"
          type="button"
          onClick={() => void load(tasks[tasks.length - 1].id)}
        >
          加载更多失败项（已显示 {tasks.length}/{failedCount}）
        </button>
      ) : null}
    </div>
  );
}
