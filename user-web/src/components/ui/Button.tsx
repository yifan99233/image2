import { LoadingIndicator } from "./LoadingIndicator";
import type { ButtonHTMLAttributes, PropsWithChildren } from "react";
import { clsx } from "clsx";

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

type ButtonProps = PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: ButtonVariant;
    fullWidth?: boolean;
    isLoading?: boolean;
  }
>;

export const Button = ({
  children,
  className,
  variant = "primary",
  fullWidth = false,
  isLoading = false,
  disabled,
  ...props
}: ButtonProps) => (
  <button
    className={clsx("button", `button--${variant}`, fullWidth && "button--full", className)}
    disabled={disabled || isLoading}
    aria-busy={isLoading || undefined}
    {...props}
  >
    {isLoading ? <LoadingIndicator /> : null}
    {children}
  </button>
);
