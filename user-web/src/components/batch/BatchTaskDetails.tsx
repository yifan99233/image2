import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { imageTaskService } from "@/services/imageTasks";
import type { ImageTask } from "@/types/api";

export function BatchTaskDetails({
  batchId,
  total,
  tasks,
  revision,
  onTasksLoaded,
  renderTasks,
}: {
  batchId: string;
  total: number;
  tasks: ImageTask[];
  revision: number;
  onTasksLoaded: (tasks: ImageTask[]) => void;
  renderTasks: (tasks: ImageTask[]) => ReactNode;
}) {
  const [ids, setIds] = useState<number[]>([]);
  const [cursor, setCursor] = useState<number | undefined>();
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const request = useRef<AbortController | null>(null);
  const loaded = useRef(onTasksLoaded);
  loaded.current = onTasksLoaded;

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
          beforeId,
          limit: 40,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        loaded.current(page);
        setIds((current) =>
          beforeId
            ? [...new Set([...current, ...page.map((task) => task.id)])]
            : page.map((task) => task.id),
        );
        setCursor(page.at(-1)?.id);
        setHasMore(page.length === 40);
      } catch (err) {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : "加载批次记录失败");
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [batchId],
  );
  useEffect(() => {
    void load();
    return () => request.current?.abort();
    // Reload after a record is deleted; other card actions update the shared cache.
  }, [load, revision, refresh]);

  const byId = new Map(tasks.map((task) => [task.id, task]));
  const records = ids.flatMap((id) => (byId.has(id) ? [byId.get(id)!] : []));
  const activeIds = JSON.stringify(
    records
      .filter((task) => ["pending", "queued", "running"].includes(task.status))
      .map((task) => task.id),
  );
  useEffect(() => {
    const taskIds: number[] = JSON.parse(activeIds);
    if (!taskIds.length) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const page = await imageTaskService.getTaskStatuses(taskIds);
        if (!stopped) loaded.current(page);
      } catch (err) {
        if (!stopped) setError(err instanceof Error ? err.message : "记录进度更新失败");
      }
      if (!stopped) timer = setTimeout(poll, 1600);
    };
    timer = setTimeout(poll, 1600);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [activeIds]);

  return (
    <section className="batch-progress__records" aria-label={`批次 ${batchId} 具体记录`}>
      <p className="batch-progress__hint">
        已显示 {records.length}/{total} 条记录
      </p>
      {renderTasks(records)}
      {error ? (
        <p role="alert" className="batch-progress__error">
          {error}{" "}
          <button
            className="task-button"
            type="button"
            disabled={loading}
            onClick={() => setRefresh((value) => value + 1)}
          >
            重试加载记录
          </button>
        </p>
      ) : null}
      {loading ? (
        <p role="status">正在加载批次记录…</p>
      ) : !records.length && !error ? (
        <p>暂无可见记录</p>
      ) : null}
      {hasMore && records.length < total ? (
        <button
          className="task-button"
          type="button"
          disabled={loading}
          onClick={() => void load(cursor)}
        >
          加载更多批次记录
        </button>
      ) : null}
    </section>
  );
}
