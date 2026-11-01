import "./CanvasLoading.css";

/** Small companion to the floating-card loader for buttons and inline actions. */
export function LoadingIndicator({ size = 17 }: { size?: number; className?: string }) {
  return <span className="loading-pulse" style={{ width: size, height: size }} aria-hidden="true"><i /><i /><i /></span>;
}
