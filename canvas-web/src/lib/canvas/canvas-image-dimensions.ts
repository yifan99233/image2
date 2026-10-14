import { NODE_DEFAULT_SIZE } from "@/constant/canvas";
import { CanvasNodeType, type CanvasNodeData } from "@/types/canvas";
import { fitNodeSize, hasImageDimensions } from "./canvas-node-size";

// Repair documents saved by the old adapter, which fitted unknown dimensions to 1×1.
export function restoreImageNodeSize(node: CanvasNodeData): CanvasNodeData {
    if (node.type !== CanvasNodeType.Image || !node.metadata) return node;
    const { metadata } = node;
    if (!metadata.content && !metadata.storageKey && !metadata.images?.some((image) => image.content || image.storageKey)) return node;
    const collapsed = !hasImageDimensions(node.width, node.height) || ((node.width <= 1 || node.height <= 1) && !hasImageDimensions(metadata.naturalWidth, metadata.naturalHeight));
    if (!collapsed) return node;
    const defaults = NODE_DEFAULT_SIZE[CanvasNodeType.Image];
    return {
        ...node,
        ...fitNodeSize(metadata.naturalWidth || 0, metadata.naturalHeight || 0, defaults.width, defaults.height),
    };
}

export function applyImageDimensions(node: CanvasNodeData, content: string, width: number, height: number, imageId?: string): CanvasNodeData {
    if (node.type !== CanvasNodeType.Image || !node.metadata || !hasImageDimensions(width, height)) return node;
    const { metadata } = node;
    const image = imageId ? metadata.images?.find((item) => item.id === imageId) : undefined;
    const isPrimary = imageId === (metadata.primaryImageId || metadata.images?.[0]?.id);
    // A slow load from a replaced/deleted image must not update the current node.
    if ((imageId && !image) || (image?.content || (isPrimary ? metadata.content : undefined)) !== content) return node;
    if ((!image || (image.naturalWidth === width && image.naturalHeight === height)) && (!isPrimary || (metadata.naturalWidth === width && metadata.naturalHeight === height))) return node;
    const restored = restoreImageNodeSize(node);
    const size = isPrimary && !metadata.freeResize && !hasImageDimensions(metadata.naturalWidth, metadata.naturalHeight) ? fitNodeSize(width, height, restored.width, restored.height) : { width: restored.width, height: restored.height };
    return {
        ...restored,
        ...size,
        metadata: {
            ...metadata,
            ...(isPrimary ? { naturalWidth: width, naturalHeight: height } : {}),
            images: metadata.images?.map((item) => (item.id === imageId ? { ...item, naturalWidth: width, naturalHeight: height } : item)),
        },
    };
}
