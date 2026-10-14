import type { ImageTask, ImageTaskStatus } from "@/types/api";

export type ImageTaskStatusLabels = Record<ImageTaskStatus, string>;

export const getImageTaskStatusLabel = (
  task: ImageTask,
  labels: ImageTaskStatusLabels,
): string => {
  if (task.progress_stage === "downloading") return "图片下载中";
  return labels[task.status];
};

export const getImageTaskProcessingMessage = (task: ImageTask): string => {
  if (task.status === "queued") return "等待模型资源";
  if (task.progress_stage === "downloading") return "正在下载图片";
  return "正在生成结果";
};
