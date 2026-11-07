export type GalleryAssetDimensions = {
  width?: number | null;
  height?: number | null;
};

const isPositiveFiniteNumber = (value: number): boolean => Number.isFinite(value) && value > 0;

const ratioFromValues = (width: number, height: number): string | undefined => {
  if (!isPositiveFiniteNumber(width) || !isPositiveFiniteNumber(height)) return undefined;
  return `${width} / ${height}`;
};

export function getGalleryAspectRatio(
  asset: GalleryAssetDimensions | null | undefined,
  fallback?: string | null,
): string | undefined {
  const assetRatio = ratioFromValues(Number(asset?.width), Number(asset?.height));
  if (assetRatio) return assetRatio;

  const values = String(fallback ?? "")
    .trim()
    .split(":")
    .map(Number);
  if (values.length !== 2) return undefined;
  return ratioFromValues(values[0], values[1]);
}
