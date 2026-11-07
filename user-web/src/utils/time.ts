import type { ImageTask } from "@/types/api";

export const formatDateTime = (value?: string | null) => {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
};

export const getTaskElapsedMs = (task: ImageTask, now: number) => {
  if (task.generation_duration_seconds !== null && task.generation_duration_seconds !== undefined) {
    return Math.max(0, task.generation_duration_seconds * 1000);
  }

  if (!task.worker_started_at) return null;
  const start = new Date(task.worker_started_at).getTime();
  if (Number.isNaN(start)) return null;

  const finished = task.finished_at ? new Date(task.finished_at).getTime() : null;
  const end = finished && !Number.isNaN(finished) ? finished : now;
  return Math.max(0, end - start);
};

export const formatElapsedTime = (milliseconds: number | null) => {
  if (milliseconds === null) return "--";

  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) return `${hours}时${minutes}分${seconds}秒`;
  if (minutes > 0) return `${minutes}分${seconds}秒`;
  return `${seconds}秒`;
};
