import type { ImageModel, ImageOutputFormat } from "@/types/api";

export const imageSizeError = (size: string): string | null => {
  if (!size || size === "auto") return null;
  if (!/^[0-9]{1,4}x[0-9]{1,4}$/.test(size)) return "请填写宽度和高度（像素）";
  const [width, height] = size.split("x").map(Number);
  if (!width || !height || width % 16 || height % 16) return "宽度和高度必须是 16 的正整数倍";
  if (Math.max(width, height) > 3840 || Math.max(width, height) > 3 * Math.min(width, height)) return "单边最多 3840 像素，宽高比需在 1:3 至 3:1 之间";
  if (width * height < 655360 || width * height > 8294400) return "总像素需在 655360 至 8294400 之间";
  return null;
};

export const imageOutputOptions = (model: ImageModel | null | undefined, size: string, outputFormat: ImageOutputFormat | "") => {
  const error = model?.supports_custom_size ? imageSizeError(size) : null;
  if (error) throw new Error(error);
  return {
    ...(model?.supports_custom_size && size ? { size } : {}),
    ...(model?.supports_output_format && outputFormat ? { output_format: outputFormat } : {}),
  };
};
