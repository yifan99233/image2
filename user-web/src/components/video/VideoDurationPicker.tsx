import { useId } from "react";
import type { ModelOption } from "@/types/api";
import "./video-duration-picker.css";

export function VideoDurationPicker({ options, value, onChange, disabled = false }: {
  options: ModelOption[];
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  if (!options.length) return <p className="video-duration-picker__empty">当前模型暂无可用时长</p>;
  const selected = options[selectedIndex];
  return (
    <fieldset className="video-duration-picker" disabled={disabled}>
      <legend>视频时长</legend>
      <div className="video-duration-picker__heading">
        <label htmlFor={id}>选择时长</label>
        <output htmlFor={id}>{selected.label || `${selected.value} 秒`}</output>
      </div>
      {options.length > 1 ? <input id={id} type="range" min={0} max={options.length - 1} step={1}
        value={selectedIndex} aria-label="视频时长" aria-valuetext={selected.label || `${selected.value} 秒`}
        onChange={(event) => onChange(options[Number(event.target.value)].value)} /> : null}
      <div className="video-duration-picker__options" role="group" aria-label="可选视频时长">
        {options.map((option) => <button key={option.value} type="button"
          aria-pressed={option.value === value} className={option.value === value ? "is-selected" : ""}
          onClick={() => onChange(option.value)}>{option.label || `${option.value} 秒`}</button>)}
      </div>
      <small>生成费用以当前时长的预估为准</small>
    </fieldset>
  );
}
