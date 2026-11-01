import { useId } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { ImageModel, ImageOutputFormat } from "@/types/api";
import { imageSizeError } from "@/utils/imageOutputOptions";
import "./image-output-settings.css";

export const ImageCustomSizeChoice = ({ selected, onSelect, disabled }: {
  selected: boolean;
  onSelect: () => void;
  disabled?: boolean;
}) => (
  <button className={selected ? "aspect-choice is-active" : "aspect-choice"}
    type="button" role="radio" aria-checked={selected} disabled={disabled} onClick={onSelect}>
    <span className="aspect-choice__preview"><SlidersHorizontal size={24} aria-hidden="true" /></span>
    <strong>自定义</strong>
  </button>
);

export const ImageCustomSizeFields = ({ size, onSizeChange, disabled }: {
  size: string;
  onSizeChange: (size: string) => void;
  disabled?: boolean;
}) => {
  const id = useId();
  const [width = "", height = ""] = size.split("x");
  const error = imageSizeError(size);
  return (
    <fieldset className="image-custom-size" disabled={disabled}>
      <legend>自定义尺寸</legend>
      <div className="image-output-settings__dimensions">
        <label htmlFor={`${id}-width`}>宽度（px）
          <input id={`${id}-width`} type="number" inputMode="numeric" min="16" max="3840" step="16" value={width}
            aria-invalid={Boolean(error)} aria-describedby={`${id}-size-help`}
            onChange={(event) => onSizeChange(`${event.target.value}x${height}`)} />
        </label>
        <span aria-hidden="true">×</span>
        <label htmlFor={`${id}-height`}>高度（px）
          <input id={`${id}-height`} type="number" inputMode="numeric" min="16" max="3840" step="16" value={height}
            aria-invalid={Boolean(error)} aria-describedby={`${id}-size-help`}
            onChange={(event) => onSizeChange(`${width}x${event.target.value}`)} />
        </label>
      </div>
      <small id={`${id}-size-help`} className={error ? "image-output-settings__error" : ""} aria-live="polite">
        {error || "按填写的宽高生成；费用仍按所选规格预估。"}
      </small>
      <small>宽高为 16 的倍数，单边最多 3840 px，宽高比 1:3–3:1，总像素约 0.66–8.29 百万。</small>
    </fieldset>
  );
};

export const ImageOutputSettings = ({ model, outputFormat, onFormatChange, disabled }: {
  model?: ImageModel | null;
  outputFormat: ImageOutputFormat | "";
  onFormatChange: (format: ImageOutputFormat | "") => void;
  disabled?: boolean;
}) => {
  const id = useId();
  if (!model?.supports_output_format) return null;
  return (
    <fieldset className="image-output-settings" disabled={disabled}>
      <legend id={`${id}-format-label`}>图片格式</legend>
      <div className="image-output-settings__choices" role="group" aria-labelledby={`${id}-format-label`}>
        {([ ["", "默认"], ["png", "PNG"], ["jpeg", "JPEG"], ["webp", "WebP"] ] as const).map(([value, label]) => (
          <button key={value} type="button" aria-pressed={outputFormat === value} onClick={() => onFormatChange(value)}>{label}</button>
        ))}
      </div>
    </fieldset>
  );
};
