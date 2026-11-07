export function hasImageDimensions(width?: number, height?: number) {
    return Number.isFinite(width) && Number.isFinite(height) && (width || 0) > 0 && (height || 0) > 0;
}

export function fitNodeSize(width: number, height: number, maxWidth = 640, maxHeight = 640) {
    // Providers may return an image URL before its dimensions are known.
    if (!hasImageDimensions(width, height)) return { width: maxWidth, height: maxHeight };
    const w = Math.max(1, width);
    const h = Math.max(1, height);
    const scale = Math.min(1, maxWidth / w, maxHeight / h);
    return { width: w * scale, height: h * scale };
}

export function nodeSizeFromRatio(size: string, baseWidth: number, baseHeight: number) {
    const match = size
        ?.split("|")
        .at(-1)
        ?.match(/^(\d+)(?:x|:)(\d+)$/);
    if (!match) return null;
    const width = Number(match[1]);
    const height = Number(match[2]);
    const ratio = width / Math.max(1, height);
    if (ratio < 0.25 || ratio > 4) return { width: baseWidth, height: baseHeight };
    return ratio >= baseWidth / baseHeight ? { width: baseWidth, height: baseWidth / ratio } : { width: baseHeight * ratio, height: baseHeight };
}
