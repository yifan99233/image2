import { LoadingArt } from "./LoadingArt";

type LoadingStateProps = {
  label?: string;
  variant?: "inline" | "cards" | "comparison";
};

export function LoadingState({ label = "正在加载…", variant = "inline" }: LoadingStateProps) {
  return (
    <div className={`loading-state loading-state--${variant}`}>
      <LoadingArt label={label} compact={variant === "inline"} hint="正在整理内容，请稍候" />
    </div>
  );
}
