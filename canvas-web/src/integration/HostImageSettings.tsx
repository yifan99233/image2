import { useEffect, useState } from "react";
import { InputNumber, Select } from "antd";
import type { AiConfig } from "@/stores/use-config-store";
import { generationInput, getHostModel } from "./runtime";
import { callHost } from "./bridge";

export function HostImageSettings({ config, onConfigChange }: { config: AiConfig; onConfigChange: (key: "quality" | "size" | "count" | "background", value: string) => void }) {
    const model = getHostModel(config.model);
    const [quote, setQuote] = useState("");
    let spec: ReturnType<typeof generationInput> | null = null;
    try { spec = generationInput(config, "规格报价"); } catch { /* No model is configured. */ }
    const resolution = spec?.resolution || "";
    const ratio = spec?.aspectRatio || "";
    useEffect(() => {
        let ignore = false;
        setQuote("正在计算积分…");
        try {
            const input = generationInput(config, "规格报价");
            callHost("generation.quote", input).then((result) => { if (!ignore) setQuote(`预计 ${result.credit_cost} 积分`); }).catch((error) => { if (!ignore) setQuote(error.message); });
        } catch { setQuote("暂无可用模型，请联系管理员配置"); }
        return () => { ignore = true; };
    }, [config.model, config.size, config.count, config.quality]);
    if (!model || !spec) return <p className="text-sm opacity-70">暂无可用模型，请联系管理员配置</p>;
    return <div className="space-y-4" onPointerDown={(event) => event.stopPropagation()}>
        <label className="grid gap-2 text-sm">分辨率<Select aria-label="分辨率" value={resolution} options={model.supported_resolutions} onChange={(value) => onConfigChange("size", `${value}|${ratio}`)} /></label>
        <label className="grid gap-2 text-sm">画面比例<Select aria-label="画面比例" value={ratio} options={model.supported_aspect_ratios} onChange={(value) => onConfigChange("size", `${resolution}|${value}`)} /></label>
        <label className="grid gap-2 text-sm">质量<Select aria-label="质量" value={config.quality || "auto"} options={[{ value: "auto", label: "自动" }, { value: "high", label: "高" }, { value: "medium", label: "中" }, { value: "low", label: "低" }]} onChange={(value) => onConfigChange("quality", value)} /></label>
        <label className="grid gap-2 text-sm">生成张数<InputNumber aria-label="生成张数" min={1} max={model.max_output_images} precision={0} value={Number(config.count)} onChange={(value) => onConfigChange("count", String(value || 1))} /></label>
        <p className="text-xs opacity-70" role="status">{quote}</p>
    </div>;
}
