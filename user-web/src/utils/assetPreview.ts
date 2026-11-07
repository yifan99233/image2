export type PreviewableAsset = {
  url: string;
  thumbnail_url?: string;
};

export function getAssetPreviewSource(asset: PreviewableAsset): string {
  return asset.thumbnail_url?.trim() || asset.url;
}
