import { CANVAS_CHANNEL, type CanvasMethod, type CanvasMethods } from "./protocol";

const pending = new Map<string, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();

window.addEventListener("message", (event: MessageEvent) => {
    if (event.origin !== window.location.origin || event.source !== window.parent || event.data?.channel !== CANVAS_CHANNEL || event.data.type !== "response") return;
    const request = pending.get(event.data.id);
    if (!request) return;
    pending.delete(event.data.id);
    if (event.data.error) request.reject(new Error(event.data.error));
    else request.resolve(event.data.result);
});

export function callHost<K extends CanvasMethod>(method: K, input: CanvasMethods[K]["input"], signal?: AbortSignal): Promise<CanvasMethods[K]["output"]> {
    if (window.parent === window) return Promise.reject(new Error("请从本站的「画布」菜单打开"));
    if (signal?.aborted) return Promise.reject(new DOMException("已停止等待", "AbortError"));
    return new Promise((resolve, reject) => {
        const id = crypto.randomUUID();
        const finish = () => { window.clearTimeout(timer); signal?.removeEventListener("abort", abort); pending.delete(id); };
        const abort = () => { finish(); reject(new DOMException("已停止等待，已提交的任务可在我的作品查看", "AbortError")); };
        const timer = window.setTimeout(() => { finish(); reject(new Error("请求超时，请检查网络后重试")); }, 120000);
        pending.set(id, {
            resolve: (value) => { finish(); resolve(value as CanvasMethods[K]["output"]); },
            reject: (error) => { finish(); reject(error); },
        });
        signal?.addEventListener("abort", abort, { once: true });
        window.parent.postMessage({ channel: CANVAS_CHANNEL, type: "request", id, method, input }, window.location.origin);
    });
}

export function notifyHost(type: string, extra: Record<string, unknown> = {}) {
    window.parent.postMessage({ channel: CANVAS_CHANNEL, type, ...extra }, window.location.origin);
}
