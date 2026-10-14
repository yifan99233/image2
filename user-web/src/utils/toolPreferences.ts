import { DEFAULT_IMAGE_QUALITY, IMAGE_QUALITY_OPTIONS } from "@/constants/imageGeneration";
import type { ImageModel, ImageQuality } from "@/types/api";

type ToolPreference = {
  modelId: number | null;
  resolution: string;
  aspectRatio: string;
  duration: string;
  quality: ImageQuality;
};

const preferenceKey = (scope: string) => `image2ai.toolPreference.${scope}`;

const defaultPreference: ToolPreference = {
  modelId: null,
  resolution: "",
  aspectRatio: "",
  duration: "",
  quality: DEFAULT_IMAGE_QUALITY,
};

const isImageQuality = (value: unknown): value is ImageQuality =>
  IMAGE_QUALITY_OPTIONS.some((option) => option.value === value);

export const readToolPreference = (scope: string): ToolPreference => {
  try {
    const raw = window.localStorage.getItem(preferenceKey(scope));
    if (!raw) return defaultPreference;
    const parsed = JSON.parse(raw) as Partial<ToolPreference>;
    return {
      modelId: typeof parsed.modelId === "number" ? parsed.modelId : null,
      resolution: typeof parsed.resolution === "string" ? parsed.resolution : "",
      aspectRatio: typeof parsed.aspectRatio === "string" ? parsed.aspectRatio : "",
      duration: typeof parsed.duration === "string" ? parsed.duration : "",
      quality: isImageQuality(parsed.quality) ? parsed.quality : DEFAULT_IMAGE_QUALITY,
    };
  } catch {
    return defaultPreference;
  }
};

export const writeToolPreference = (scope: string, preference: ToolPreference) => {
  window.localStorage.setItem(
    preferenceKey(scope),
    JSON.stringify({
      modelId: preference.modelId,
      resolution: preference.resolution,
      aspectRatio: preference.aspectRatio,
      duration: preference.duration ?? "",
      quality: preference.quality,
    }),
  );
};

export const resolveToolPreference = (models: ImageModel[], preference: ToolPreference): ToolPreference => {
  const model = models.find((item) => item.id === preference.modelId) ?? models[0] ?? null;
  if (!model) return defaultPreference;

  const resolution = model.supported_resolutions.some((option) => option.value === preference.resolution)
    ? preference.resolution
    : model.supported_resolutions[0]?.value ?? "";
  const aspectRatio = model.supported_aspect_ratios.some((option) => option.value === preference.aspectRatio)
    ? preference.aspectRatio
    : model.supported_aspect_ratios[0]?.value ?? "";
  const durations = model.supported_durations ?? [];
  const duration = durations.some((option) => option.value === preference.duration)
    ? preference.duration
    : durations[0]?.value ?? "";

  return {
    modelId: model.id,
    resolution,
    aspectRatio,
    duration,
    quality: preference.quality,
  };
};
