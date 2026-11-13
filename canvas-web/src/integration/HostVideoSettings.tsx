import { useEffect, useState } from "react";
import { Select } from "antd";
import type { AiConfig } from "@/stores/use-config-store";
import { generationInput, getHostModel } from "./runtime";
import { callHost } from "./bridge";

export function HostVideoSettings({ config, onConfigChange }: { config: AiConfig; onConfigChange: (key: keyof AiConfig, value: string) => void }) {
    const model = getHostModel(config.model);
    const [quote, setQuote] = useState("");
    let spec: ReturnType<typeof generationInput> | undefined;
    try { spec = generationInput(config, "规格报价"); } catch { /* No available model. */ }
    useEffect(() => {
        let ignore = false;
        setQuote("正在计算积分…");
        try {
            const input = generationInput(config, "规格报价");
            callHost("generation.quote", input).then((result) => { if (!ignore) setQuote(`预计 ${result.credit_cost} 积分`); }).catch((error) => { if (!ignore) setQuote(error.message); });
        } catch { setQuote("暂无可用视频模型，请联系管理员配置"); }
        return () => { ignore = true; };
    }, [config.model, config.size, config.vquality, config.videoSeconds]);
    if (!model || !spec) return <p className="text-sm opacity-70">暂无可用视频模型，请联系管理员配置</p>;
    return <div className="space-y-4">
        <label className="grid gap-2 text-sm">分辨率<Select aria-label="视频分辨率" value={spec.resolution} options={model.supported_resolutions} onChange={(value) => onConfigChange("vquality", value)} /></label>
        <label className="grid gap-2 text-sm">画面比例<Select aria-label="视频画面比例" value={spec.aspectRatio} options={model.supported_aspect_ratios} onChange={(value) => onConfigChange("size", value)} /></label>
        <label className="grid gap-2 text-sm">时长<Select aria-label="视频时长" value={spec.duration} options={model.supported_durations} onChange={(value) => onConfigChange("videoSeconds", value)} /></label>
        <p className="text-xs opacity-70" role="status">{quote}</p>
    </div>;
}
