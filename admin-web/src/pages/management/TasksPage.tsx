import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { RotateCcw, Search, Star, WalletCards } from "lucide-react";
import { formatDateTime } from "../../lib/format";
import {
  getImageTasks,
  refundTask,
  retryTask,
  toggleTaskGallery,
  type ImageTaskFilters,
} from "../../services/adminApi";
import type { ImageTask } from "../../types";
import { Dialog, type DialogState } from "./ManagementDialogs";
import {
  FilterSelect,
  initialPagination,
  LoadState,
  PageChrome,
  Pagination,
  type PaginationState,
} from "./ManagementCommon";
const taskStatus = {
  pending: "待处理",
  queued: "排队中",
  running: "执行中",
  succeeded: "成功",
  failed: "失败",
  refunded: "已退款",
};
const statusOptions = [
  { value: "all", label: "全部状态" },
  { value: "succeeded", label: "成功" },
  { value: "failed", label: "失败（含已退款）" },
  { value: "pending", label: "待处理" },
  { value: "queued", label: "排队中" },
  { value: "running", label: "执行中" },
  { value: "refunded", label: "已退款" },
];
const defaultDraft = {
  status: "all",
  galleryReviewStatus: "all",
  keyword: "",
  userMode: "username",
  user: "",
};
const defaultFilters: ImageTaskFilters = {
  status: "all",
  galleryReviewStatus: "all",
  username: "",
  keyword: "",
};
export function TasksPage() {
  const [items, setItems] = useState<ImageTask[]>([]);
  const [dialog, setDialog] = useState<DialogState>({ kind: "none" });
  const [error, setError] = useState("");
  const [pagination, setPagination] =
    useState<PaginationState>(initialPagination);
  const [draft, setDraft] = useState(defaultDraft);
  const [filters, setFilters] = useState<ImageTaskFilters>(defaultFilters);
  const [filterError, setFilterError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const request = useRef<AbortController | null>(null);
  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setLoading(true);
    setError("");
    setItems([]);
    try {
      const result = await getImageTasks(
        filters.keyword,
        pagination.page,
        pagination.pageSize,
        filters,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setItems(result.items);
      setPagination({
        page: result.page,
        pageSize: result.page_size,
        total: result.total,
      });
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : "任务接口不可用");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [filters, pagination.page, pagination.pageSize]);
  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load, revision]);
  const search = (event: FormEvent) => {
    event.preventDefault();
    const user = draft.user.trim();
    if (
      draft.userMode === "id" &&
      user &&
      (!/^[1-9]\d*$/.test(user) || !Number.isSafeInteger(Number(user)))
    ) {
      setFilterError("用户 ID 请输入有效的正整数");
      return;
    }
    setFilterError("");
    setFilters({
      status: draft.status as ImageTaskFilters["status"],
      galleryReviewStatus: draft.galleryReviewStatus as ImageTaskFilters["galleryReviewStatus"],
      keyword: draft.keyword.trim(),
      username: draft.userMode === "username" ? user : "",
      userId: draft.userMode === "id" && user ? Number(user) : undefined,
    });
    setPagination((current) => ({ ...current, page: 1 }));
    setRevision((current) => current + 1);
  };
  const reset = () => {
    setDraft(defaultDraft);
    setFilters(defaultFilters);
    setFilterError("");
    setPagination((current) => ({ ...current, page: 1 }));
    setRevision((current) => current + 1);
  };
  return (
    <PageChrome
      title="任务管理"
      description="查看任务状态和失败原因，审核用户提交的广场作品；只有人工审核通过后才会公开展示。"
    >
      <form
        className="filter-toolbar task-query-toolbar"
        onSubmit={search}
        aria-label="任务查询条件"
      >
        <FilterSelect
          label="任务状态"
          value={draft.status}
          options={statusOptions}
          onChange={(status) => setDraft((current) => ({ ...current, status }))}
        />
        <FilterSelect
          label="广场状态"
          value={draft.galleryReviewStatus}
          options={[
            { value: "all", label: "全部广场状态" },
            { value: "pending", label: "待审核" },
            { value: "approved", label: "已展示" },
            { value: "rejected", label: "已驳回／下架" },
            { value: "none", label: "未提交" },
          ]}
          onChange={(galleryReviewStatus) => setDraft((current) => ({ ...current, galleryReviewStatus }))}
        />
        <FilterSelect
          label="用户维度"
          value={draft.userMode}
          options={[
            { value: "username", label: "用户名" },
            { value: "id", label: "用户 ID" },
          ]}
          onChange={(userMode) => {
            setDraft((current) => ({ ...current, userMode, user: "" }));
            setFilterError("");
          }}
        />
        <label className="search-field compact-search">
          <span>用户</span>
          <input
            aria-label="查询用户"
            value={draft.user}
            maxLength={100}
            inputMode={draft.userMode === "id" ? "numeric" : "text"}
            placeholder={
              draft.userMode === "id"
                ? "输入用户 ID"
                : "输入用户名，支持部分匹配"
            }
            onChange={(event) =>
              setDraft((current) => ({ ...current, user: event.target.value }))
            }
          />
        </label>
        <label className="search-field compact-search">
          <Search size={16} />
          <input
            aria-label="任务关键词"
            value={draft.keyword}
            maxLength={200}
            placeholder="任务编号、模型或提示词"
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                keyword: event.target.value,
              }))
            }
          />
        </label>
        <button
          className="primary-button compact"
          type="submit"
          disabled={loading}
        >
          <Search size={15} />
          {loading ? "查询中…" : "查询"}
        </button>
        <button
          className="secondary-button compact"
          type="button"
          onClick={reset}
        >
          重置
        </button>
      </form>
      <p className="muted-meta">
        查询条件可组合使用；失败包含已退款任务。输入条件后点击查询。
      </p>
      {filterError ? (
        <p className="inline-state error" role="alert">
          {filterError}
        </p>
      ) : null}
      {loading ? (
        <section className="inline-state" role="status">
          正在查询任务…
        </section>
      ) : error ? (
        <LoadState error={error} empty={false} onRetry={load} />
      ) : !items.length ? (
        <section className="inline-state">
          当前条件没有匹配任务，请调整查询条件。
        </section>
      ) : null}
      <section className="panel">
        <div className="table-wrap">
          <table className="task-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>用户</th>
                <th>模型</th>
                <th>状态</th>
                <th>广场</th>
                <th>积分</th>
                <th>内容</th>
                <th>失败原因</th>
                <th>生成时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((task) => {
                const canFeature =
                  task.status === "succeeded" && Boolean(task.output_image_url) && !task.deleted_at && task.gallery_review_status === "pending";
                const hasFailureMessage =
                  task.status === "failed" || task.status === "refunded";
                return (
                  <tr key={task.id}>
                    <td>{task.task_no}</td>
                    <td>
                      {task.username}
                      <small className="task-user-id">
                        用户 ID：{task.user_id}
                      </small>
                    </td>
                    <td>{task.model_name}</td>
                    <td>
                      <span
                        className={`status-pill ${task.status === "succeeded" ? "paid" : hasFailureMessage ? "failed" : "pending"}`}
                      >
                        {taskStatus[task.status]}
                      </span>
                    </td>
                    <td>
                      {task.deleted_at ? <span className="status-pill">已删除</span> : task.is_gallery_featured ? (
                        <span className="status-pill paid">已展示</span>
                      ) : (
                        <span className={`status-pill ${task.gallery_review_status === "rejected" ? "failed" : "pending"}`}>
                          {task.gallery_review_status === "pending" ? "待审核" : task.gallery_review_status === "rejected" ? "已驳回／下架" : "未提交"}
                        </span>
                      )}
                    </td>
                    <td>{task.credit_cost}</td>
                    <td className="task-content-cell">
                      <p className="task-prompt">{task.prompt || "-"}</p>
                      <TaskImageStrip task={task} />
                    </td>
                    <td
                      className={
                        hasFailureMessage
                          ? "reason-cell reason-cell--failed"
                          : "reason-cell"
                      }
                    >
                      {task.failure_message ||
                        (hasFailureMessage ? "未记录失败原因" : "-")}
                    </td>
                    <td className="time-cell">
                      <span>
                        生图{" "}
                        {formatTaskSeconds(task.generation_duration_seconds)}
                      </span>
                      <small>
                        总耗时 {formatTaskSeconds(task.total_duration_seconds)}
                      </small>
                      <span>提交 {formatDateTime(task.created_at)}</span>
                      <small>
                        开始{" "}
                        {task.worker_started_at
                          ? formatDateTime(task.worker_started_at)
                          : "-"}
                      </small>
                      <small>
                        完成{" "}
                        {task.finished_at
                          ? formatDateTime(task.finished_at)
                          : "-"}
                      </small>
                      <small>
                        排队 {formatTaskSeconds(task.queue_duration_seconds)}
                      </small>
                    </td>
                    <td className="row-actions">
                      <button
                        className="secondary-button compact"
                        disabled={task.status !== "failed"}
                        onClick={() =>
                          setDialog({
                            kind: "reason",
                            title: "人工退款",
                            body: `${task.task_no} 将退还积分并记录审计原因。`,
                            confirmLabel: "确认退款",
                            onConfirm: (reason) => refundTask(task.id, reason),
                          })
                        }
                      >
                        <WalletCards size={14} />
                        退款
                      </button>
                      <button
                        className="secondary-button compact"
                        disabled={task.status !== "failed"}
                        onClick={() =>
                          setDialog({
                            kind: "confirm",
                            title: "重试失败任务",
                            body: `${task.task_no} 将重新进入队列，原失败记录不会被覆盖。`,
                            confirmLabel: "确认重试",
                            onConfirm: () => retryTask(task.id),
                          })
                        }
                      >
                        <RotateCcw size={14} />
                        重试
                      </button>
                      <button
                        className="secondary-button compact"
                        disabled={Boolean(task.deleted_at) || (!task.is_gallery_featured && !canFeature)}
                        title={
                          !task.is_gallery_featured && !canFeature
                            ? "只有用户提交的待审核作品才能审核通过"
                            : undefined
                        }
                        onClick={() => setDialog(task.is_gallery_featured ? {
                          kind: "reason",
                          title: "下架广场作品",
                          body: `${task.task_no} 将停止公开展示，原作品保留。下架原因将记录在审计日志中。`,
                          confirmLabel: "确认下架",
                          onConfirm: (reason) => toggleTaskGallery(task.id, false, reason),
                        } : {
                          kind: "confirm",
                          title: "审核通过并展示",
                          body: `请确认已检查 ${task.task_no} 的图片和提示词，且内容适合公开。通过后将在创作广场展示。`,
                          confirmLabel: "通过并展示",
                          onConfirm: () => toggleTaskGallery(task.id, true),
                        })}
                      >
                        <Star size={14} />
                        {task.is_gallery_featured ? "下架广场" : "审核通过"}
                      </button>
                      {task.gallery_review_status === "pending" && !task.deleted_at ? (
                        <button className="secondary-button compact" onClick={() => setDialog({
                          kind: "reason",
                          title: "驳回广场申请",
                          body: `${task.task_no} 不会公开展示，原作品保留。请填写驳回原因。`,
                          confirmLabel: "确认驳回",
                          onConfirm: (reason) => toggleTaskGallery(task.id, false, reason),
                        })}>驳回</button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
      <Pagination pagination={pagination} onChange={setPagination} />
      <Dialog
        state={dialog}
        onClose={() => setDialog({ kind: "none" })}
        afterDone={load}
      />
    </PageChrome>
  );
}

function TaskImageStrip({ task }: { task: ImageTask }) {
  const images = [
    { label: "原图", url: task.input_image_url },
    { label: "结果图", url: task.output_image_url },
  ];

  if (!images.some((image) => Boolean(image.url))) {
    return (
      <div className="task-image-strip task-image-strip--empty">暂无图片</div>
    );
  }

  return (
    <div className="task-image-strip">
      {images.map((image) =>
        image.url ? (
          <a
            className="task-thumb"
            href={image.url}
            target="_blank"
            rel="noreferrer"
            key={image.label}
            title={`查看${image.label}`}
          >
            <img
              src={image.url}
              alt={`${task.task_no} ${image.label}`}
              loading="lazy"
            />
            <span>{image.label}</span>
          </a>
        ) : (
          <span className="task-thumb task-thumb--empty" key={image.label}>
            <span>{image.label}</span>
            <small>无</small>
          </span>
        ),
      )}
    </div>
  );
}

function formatTaskSeconds(value?: number | null) {
  if (value === null || value === undefined) return "-";
  const totalSeconds = Math.max(0, Math.round(value));
  if (totalSeconds < 60) return `${totalSeconds}秒`;
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds > 0 ? `${minutes}分${seconds}秒` : `${minutes}分`;
}
