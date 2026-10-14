import { useState } from "react";
import { ImageOff } from "lucide-react";
import type { ImageAsset } from "@/types/api";
import { getAssetPreviewSource } from "@/utils/assetPreview";
import { resolveAssetUrl } from "@/utils/assets";

export function AssetPreviewImage({ asset, alt }: { asset: ImageAsset; alt: string }) {
  const source = resolveAssetUrl(getAssetPreviewSource(asset));
  const [failedSource, setFailedSource] = useState<string | null>(null);

  if (failedSource === source) {
    return (
      <span className="asset-preview-error" role="status">
        <ImageOff size={24} />
        <span>预览加载失败</span>
        <small>点击查看原图</small>
      </span>
    );
  }

  return (
    <img
      key={source}
      src={source}
      alt={alt}
      loading="lazy"
      decoding="async"
      onError={() => setFailedSource(source)}
    />
  );
}
