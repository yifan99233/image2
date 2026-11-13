// Local media is restored from IndexedDB by storageKey; blob URLs cannot survive reloads.
export function cloudCanvasDocument(document: Record<string, unknown>): Record<string, unknown> {
    if (!Array.isArray(document.nodes)) return document;
    return { ...document, nodes: document.nodes.map((node) => {
        if (!node || !["video", "audio"].includes(node.type) || !node.metadata?.storageKey || !node.metadata.content?.startsWith("blob:")) return node;
        return { ...node, metadata: { ...node.metadata, content: "" } };
    }) };
}
