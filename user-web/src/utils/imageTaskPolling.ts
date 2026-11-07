type TaskStatus = { id: number; status: string };

const TERMINAL_STATUSES = new Set(["succeeded", "failed", "refunded"]);
const STATUS_BATCH_SIZE = 200;

/** One queue per page: new submissions join the unfinished tasks already watched. */
export function createImageTaskPoller<T extends TaskStatus>({
  fetchStatuses,
  onUpdates,
  onSettled,
  intervalMs = 1600,
}: {
  fetchStatuses: (ids: number[]) => Promise<T[]>;
  onUpdates: (updates: T[]) => void;
  onSettled: () => void;
  intervalMs?: number;
}) {
  const pendingIds = new Set<number>();
  let timer: ReturnType<typeof setTimeout> | null = null;
  let inFlight = false;
  let disposed = false;

  function schedule() {
    if (disposed || inFlight || timer !== null || !pendingIds.size) return;
    timer = setTimeout(() => { void poll(); }, intervalMs);
  }

  async function poll() {
    timer = null;
    if (disposed || !pendingIds.size) return;
    inFlight = true;
    try {
      const ids = [...pendingIds];
      for (let offset = 0; offset < ids.length; offset += STATUS_BATCH_SIZE) {
        if (disposed) return;
        const batch = ids.slice(offset, offset + STATUS_BATCH_SIZE).filter((id) => pendingIds.has(id));
        if (!batch.length) continue;
        let updates: T[];
        try {
          updates = await fetchStatuses(batch);
        } catch {
          // Keep these IDs queued after a network error; a later poll retries.
          continue;
        }
        if (disposed) return;
        const batchIds = new Set(batch);
        const relevant = updates.filter((task) => batchIds.has(task.id) && pendingIds.has(task.id));
        const settled = relevant.filter((task) => TERMINAL_STATUSES.has(task.status));
        settled.forEach((task) => pendingIds.delete(task.id));
        if (relevant.length) onUpdates(relevant);
        if (settled.length) onSettled();
      }
    } finally {
      inFlight = false;
      schedule();
    }
  }

  return {
    watch(ids: number[]) {
      if (disposed) return;
      ids.filter((id) => Number.isInteger(id) && id > 0).forEach((id) => pendingIds.add(id));
      schedule();
    },
    unwatch(ids: number[]) {
      ids.forEach((id) => pendingIds.delete(id));
      if (!pendingIds.size && timer !== null) {
        clearTimeout(timer);
        timer = null;
      }
    },
    dispose() {
      disposed = true;
      pendingIds.clear();
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}
