import { X } from "lucide-react";
import type { SiteContentMaterial } from "@/types/api";
import { resolveAssetUrl } from "@/utils/assets";
import { isVideoUrl } from "./mediaConfig";

export function ConfiguredMedia({ item, className }: { item: SiteContentMaterial; className: string }) {
  const coverUrl = item.cover_url ? resolveAssetUrl(item.cover_url) : "";
  const fileUrl = item.file_url ? resolveAssetUrl(item.file_url) : "";
  if (fileUrl && isVideoUrl(fileUrl)) return <video className={className} src={fileUrl} muted playsInline preload="metadata" poster={coverUrl || undefined} />;
  if (coverUrl) return <img className={className} src={coverUrl} alt="" />;
  if (fileUrl) return <img className={className} src={fileUrl} alt="" />;
  return null;
}

export const VideoPreviewModal = ({
  preview,
  onClose,
}: {
  preview: { title: string; url: string; poster?: string } | null;
  onClose: () => void;
}) => preview ? (
  <div className="modal-backdrop" role="presentation" onClick={onClose}>
    <section className="video-preview-dialog" role="dialog" aria-modal="true" aria-label={`${preview.title}视频预览`} onClick={(event) => event.stopPropagation()}>
      <button className="video-preview-dialog__close" type="button" onClick={onClose} aria-label="关闭视频预览">
        <X size={18} />
      </button>
      <video src={preview.url} poster={preview.poster} controls autoPlay playsInline />
      <strong>{preview.title}</strong>
    </section>
  </div>
) : null;

export const ImagePreviewModal = ({
  preview,
  onClose,
}: {
  preview: { title: string; url: string } | null;
  onClose: () => void;
}) => preview ? (
  <div className="modal-backdrop" role="presentation" onClick={onClose}>
    <section className="image-preview-dialog" role="dialog" aria-modal="true" aria-label={`${preview.title}图片预览`} onClick={(event) => event.stopPropagation()}>
      <button type="button" onClick={onClose} aria-label="关闭图片预览">
        <X size={18} />
      </button>
      <img src={preview.url} alt={preview.title} />
    </section>
  </div>
) : null;
