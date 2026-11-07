import "./CanvasLoading.css";

export function LoadingArt({ label = "正在加载", hint = "精彩即将呈现，请稍候", compact = false }: { label?: string; hint?: string; compact?: boolean }) {
  return (
    <div className={`canvas-loading-art${compact ? " canvas-loading-art--compact" : ""}`} role="status" aria-live="polite" aria-busy="true">
      <div className="canvas-loading-art__scene" aria-hidden="true">
        <svg viewBox="0 0 260 144" fill="none">
          <path className="canvas-loading-art__link" d="M74 87C112 87 125 57 166 57" />
          <g className="canvas-loading-art__back">
            <rect x="145" y="21" width="76" height="86" rx="14" fill="currentColor" fillOpacity=".07" stroke="currentColor" strokeOpacity=".25" />
            <path d="M162 42h36M162 51h25M162 60h30" stroke="currentColor" strokeOpacity=".45" strokeWidth="3" strokeLinecap="round" />
          </g>
          <g className="canvas-loading-art__front">
            <rect x="39" y="42" width="88" height="77" rx="15" className="canvas-loading-art__paper" />
            <rect x="55" y="57" width="56" height="45" rx="7" fill="currentColor" fillOpacity=".08" />
            <circle cx="94" cy="68" r="5" fill="currentColor" fillOpacity=".45" />
            <path d="m57 93 15-17 12 12 8-7 17 15" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </g>
          <path className="canvas-loading-art__spark" d="m143 104 3 8 8 3-8 3-3 8-3-8-8-3 8-3Z" fill="currentColor" fillOpacity=".6" />
        </svg>
      </div>
      <strong>{label.replace(/[… .]+$/, "")}</strong>
      {hint && <p>{hint}</p>}
      <span className="canvas-loading-art__track" aria-hidden="true"><i /></span>
    </div>
  );
}
