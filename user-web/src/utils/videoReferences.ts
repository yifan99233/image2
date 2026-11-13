import type { ImageAsset, ImageModel, VideoReferenceCapabilities } from "@/types/api";

export const mediaKindLabel = (mime: string) => ({ image: "图片", video: "视频", audio: "音频" }[mime.split("/")[0]] ?? "素材");
export const videoWorkType = (count: number) => count ? "image_to_video" : "text_to_video";
export function referenceCapabilities(model: ImageModel | null): VideoReferenceCapabilities {
  return model?.reference_capabilities ?? {
    kinds: ["image"], mime_types: ["image/png", "image/jpeg", "image/webp"], max_total: model?.max_input_images ?? 0,
    max_by_kind: { image: model?.max_input_images ?? 0 }, max_bytes_by_kind: { image: 10 * 1024 * 1024 },
    frame_order: false, audio_requires_visual: false,
  };
}

export function videoReferenceError(model: ImageModel | null, refs: Pick<ImageAsset, "mime_type" | "size_bytes">[], complete = true): string | null {
  if (!model) return "请先选择视频模型";
  if (complete && model.supported_work_types && !model.supported_work_types.includes(videoWorkType(refs.length))) {
    return refs.length ? "当前模型不支持参考素材，请移除素材或更换模型" : "当前模型需要参考素材，请添加素材或更换模型";
  }
  const caps = referenceCapabilities(model);
  if (refs.length > caps.max_total) return `当前模型最多支持 ${caps.max_total} 个参考素材，请移除多余素材`;
  const counts: Record<string, number> = {};
  let bytes = 0;
  for (const ref of refs) {
    const kind = ref.mime_type.split("/")[0];
    if (!caps.mime_types.includes(ref.mime_type) || !caps.kinds.includes(kind)) return `当前模型不支持此${mediaKindLabel(ref.mime_type)}格式，请移除素材或更换模型`;
    counts[kind] = (counts[kind] ?? 0) + 1;
    if (counts[kind] > caps.max_by_kind[kind]) return `当前模型最多支持 ${caps.max_by_kind[kind]} 个${mediaKindLabel(ref.mime_type)}素材`;
    if (ref.size_bytes > caps.max_bytes_by_kind[kind]) return `单个${mediaKindLabel(ref.mime_type)}不能超过 ${caps.max_bytes_by_kind[kind] / 1024 / 1024}MB`;
    bytes += ref.size_bytes;
  }
  if (caps.max_total_bytes && bytes > caps.max_total_bytes) return `参考素材合计不能超过 ${caps.max_total_bytes / 1024 / 1024}MB`;
  if (complete && caps.audio_requires_visual && counts.audio && !counts.image && !counts.video) return "音频参考需要同时添加图片或视频素材";
  return null;
}

export function referenceHint(model: ImageModel | null): string {
  if (!model) return "选择模型后可添加素材，不添加则按文字生成";
  if (model.supported_work_types && !model.supported_work_types.includes("image_to_video")) return "当前模型仅支持文字生成视频";
  const caps = referenceCapabilities(model);
  const formats = caps.mime_types.map(mime => ({ "image/jpeg": "JPG", "audio/mpeg": "MP3", "audio/mp4": "M4A", "video/quicktime": "MOV" }[mime] ?? mime.split("/")[1].toUpperCase())).join(" / ");
  const limits = caps.kinds.map(kind => `${mediaKindLabel(`${kind}/`)}最多 ${caps.max_by_kind[kind]} 个，单个 ${caps.max_bytes_by_kind[kind] / 1024 / 1024}MB`).join("；");
  return `${formats}。共 ${caps.max_total} 个以内；${limits}${caps.max_total_bytes ? `；合计 ${caps.max_total_bytes / 1024 / 1024}MB 以内` : ""}${caps.frame_order ? "。第 1 张为首帧，第 2 张为尾帧" : ""}${caps.audio_requires_visual ? "。音频需搭配图片或视频" : ""}`;
}

// Some browsers omit MIME for M4A/MOV; the server verifies the actual bytes.
export function fileReference(file: File) {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const mime = ({ jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", webp: "image/webp", gif: "image/gif", mp4: "video/mp4", mov: "video/quicktime", webm: "video/webm", mp3: "audio/mpeg", wav: "audio/wav", m4a: "audio/mp4", ogg: "audio/ogg" } as Record<string, string>)[ext];
  return { mime_type: mime ?? file.type, size_bytes: file.size };
}
