import { GalleryHorizontalEnd, SlidersHorizontal } from "lucide-react";
import type { CreationPanel } from "@/hooks/useCreationPanel";

type Props = {
  panel: CreationPanel;
  onChange: (panel: CreationPanel) => void;
  resultCount: number;
};

export function CreationMobileTabs({ panel, onChange, resultCount }: Props) {
  return (
    <div className="mobile-creation-tabs" role="group" aria-label="切换创作视图">
      <button type="button" aria-pressed={panel === "form"} onClick={() => onChange("form")}>
        <SlidersHorizontal size={17} />
        创作设置
      </button>
      <button type="button" aria-pressed={panel === "results"} onClick={() => onChange("results")}>
        <GalleryHorizontalEnd size={17} />
        生成结果
        {resultCount > 0 && <span>{resultCount > 99 ? "99+" : resultCount}</span>}
      </button>
    </div>
  );
}
