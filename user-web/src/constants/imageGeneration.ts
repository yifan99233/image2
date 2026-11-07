import type { ImageQuality } from "@/types/api";

export const DEFAULT_IMAGE_QUALITY: ImageQuality = "auto";

export const IMAGE_QUALITY_OPTIONS: ReadonlyArray<{
  value: ImageQuality;
  label: string;
}> = [
  { value: "auto", label: "自动" },
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
];
