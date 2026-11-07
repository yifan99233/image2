import { CanvasLoading } from "@/components/canvas/canvas-loading";
import { useEffect, useState } from "react";
import { App, Button } from "antd";
import { Outlet } from "react-router-dom";
import { callHost, notifyHost } from "./bridge";
import { CANVAS_CHANNEL } from "./protocol";
import { setHostModels } from "./runtime";
import { useConfigStore } from "@/stores/use-config-store";
import { useThemeStore } from "@/stores/use-theme-store";
import { flushCanvasProjects, useCanvasStore } from "@/stores/canvas/use-canvas-store";

export function HostShell() {
    const [booted, setBooted] = useState(false);
    const [bootError, setBootError] = useState("");
    const [attempt, setAttempt] = useState(0);
    const saving = useCanvasStore((state) => state.saving);
    const error = useCanvasStore((state) => state.error);
    const { message } = App.useApp();
    useEffect(() => {
        let ignore = false;
        const initialize = async () => {
            setBootError("");
            const result = await callHost("bootstrap", null);
            if (ignore) return;
            setHostModels(result.models);
            useThemeStore.getState().setTheme(result.theme);
            const modelOptions = result.models.map((model) => `image2::${model.id}`);
            useConfigStore.setState((state) => ({ config: {
                ...state.config, baseUrl: "", apiKey: "", proxyEnabled: false, models: modelOptions,
                channels: [{ id: "image2", name: "本站模型", baseUrl: "", apiKey: "", apiFormat: "openai", models: result.models.map((model) => ({ name: String(model.id), capability: "image" })) }],
                model: modelOptions[0] || "", imageModel: modelOptions[0] || "", textModel: "", videoModel: "", audioModel: "", count: "1", canvasImageCount: "1",
            } }));
            await useCanvasStore.getState().loadMore();
            if (!ignore) setBooted(true);
        };
        void initialize().catch((cause) => { if (!ignore) setBootError(cause.message); });
        notifyHost("ready");
        return () => { ignore = true; };
    }, [attempt]);
    useEffect(() => {
        const receive = (event: MessageEvent) => {
            if (event.source === window.parent && event.origin === window.location.origin && event.data?.channel === CANVAS_CHANNEL && event.data.type === "theme" && ["light", "dark"].includes(event.data.theme)) useThemeStore.getState().setTheme(event.data.theme);
        };
        window.addEventListener("message", receive);
        return () => window.removeEventListener("message", receive);
    }, []);
    if (!booted) return <main className="flex h-dvh flex-col items-center justify-center gap-4 bg-background text-foreground" role="status">
        {bootError ? <p>{bootError}</p> : <CanvasLoading />}
        {bootError && <Button onClick={() => setAttempt((value) => value + 1)}>重试</Button>}
    </main>;
    return <div className="flex h-dvh flex-col overflow-hidden bg-background text-foreground">
        <div className="flex min-h-9 shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-1 text-xs">
            <div className="flex items-center gap-2" role="status">
                <span className={error ? "text-red-500" : "opacity-65"}>{error || (saving ? "正在保存…" : "已保存到云端")}</span>
                {error && <Button size="small" onClick={() => void flushCanvasProjects().catch((cause) => message.error(cause.message))}>重试保存</Button>}
            </div>
            <a className="shrink-0 opacity-45 hover:opacity-80" href="https://github.com/basketikun/infinite-canvas" target="_blank" rel="noreferrer">Infinite Canvas · basketikun · MIT</a>
        </div>
        <div className="relative min-h-0 flex-1 overflow-hidden"><Outlet /></div>
    </div>;
}
