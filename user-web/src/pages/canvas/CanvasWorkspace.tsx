import { useEffect, useMemo, useRef, useState } from "react";
import { CanvasLoading } from "@/components/ui/CanvasLoading";
import { useThemeStore } from "@/stores/themeStore";
import { createCanvasHost } from "./host";
import { CANVAS_CHANNEL, type CanvasMethod } from "../../../../canvas-web/src/integration/protocol";

export function CanvasWorkspace({ visible }: { visible: boolean }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const host = useMemo(createCanvasHost, []);
  const theme = useThemeStore((state) => state.themeMode);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const receive = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      const data = event.data;
      if (data?.channel !== CANVAS_CHANNEL) return;
      if (data.type === "ready") { setReady(true); return; }
      if (data.type !== "request" || typeof data.id !== "string" || typeof data.method !== "string") return;
      const source = event.source as Window;
      try {
        const result = await host(data.method as CanvasMethod, data.input);
        if (active) source.postMessage({ channel: CANVAS_CHANNEL, type: "response", id: data.id, result }, event.origin);
      } catch (cause) {
        if (active) source.postMessage({ channel: CANVAS_CHANNEL, type: "response", id: data.id, error: cause instanceof Error ? cause.message : "画布操作失败" }, event.origin);
      }
    };
    window.addEventListener("message", receive);
    const timeout = window.setTimeout(() => setError("画布加载较慢，请检查网络或重新加载"), 30000);
    return () => { active = false; window.removeEventListener("message", receive); window.clearTimeout(timeout); };
  }, [host]);

  useEffect(() => {
    if (ready) frame.current?.contentWindow?.postMessage({ channel: CANVAS_CHANNEL, type: "theme", theme }, window.location.origin);
  }, [ready, theme]);

  return (
    <section className="canvas-workspace" hidden={!visible} aria-label="画布工作台">
      {!ready && <div className="canvas-workspace__loading">
        {error ? <p role="status">{error}</p> : <CanvasLoading /> }
        {error && <button className="button button--secondary" type="button" onClick={() => { setError(""); if (frame.current) frame.current.src = "/canvas-app/"; }}>重新加载</button>}
      </div>}
      <iframe ref={frame} src="/canvas-app/" title="画布" className="canvas-workspace__frame" allow="clipboard-read; clipboard-write" />
    </section>
  );
}
