"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "@/lib/util";

type Variant = "primary" | "secondary" | "ghost" | "destructive";
type Size = "sm" | "md" | "lg";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  block?: boolean;
  iconLeft?: ReactNode;
  iconRight?: ReactNode;
  loading?: boolean;
  children?: ReactNode;
};

const variantClass: Record<Variant, string> = {
  primary:
    "bg-coral-600 text-white hover:bg-coral-700 active:bg-coral-700 disabled:bg-coral-300 disabled:text-white shadow-[0_1px_2px_rgba(240,128,128,0.25)]",
  secondary:
    "bg-white text-ink-900 border border-ink-200 hover:border-ink-300 hover:bg-ink-50 active:bg-ink-100 disabled:bg-ink-50 disabled:text-ink-400 disabled:border-ink-200",
  ghost:
    "bg-transparent text-ink-700 hover:bg-ink-100 active:bg-ink-200 disabled:text-ink-400",
  destructive:
    "bg-status-broken text-white hover:bg-status-broken/90 active:bg-status-broken/95",
};

const sizeClass: Record<Size, string> = {
  sm: "h-9 px-3 text-[13px] rounded-[10px] gap-1.5",
  md: "h-11 px-4 text-[14px] rounded-[12px] gap-2",
  lg: "h-12 px-5 text-[15px] rounded-[14px] gap-2",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  {
    variant = "primary",
    size = "md",
    block,
    iconLeft,
    iconRight,
    loading,
    disabled,
    children,
    className,
    type = "button",
    ...rest
  },
  ref
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center font-medium select-none transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
        variantClass[variant],
        sizeClass[size],
        block && "w-full",
        className
      )}
      {...rest}
    >
      {loading ? (
        <span
          className="inline-block h-4 w-4 rounded-full border-2 border-current border-r-transparent animate-spin"
          aria-hidden
        />
      ) : (
        iconLeft
      )}
      {children && <span className="truncate">{children}</span>}
      {!loading && iconRight}
    </button>
  );
});
