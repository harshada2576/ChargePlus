"use client";

import { forwardRef } from "react";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cx } from "@/lib/util";

type Variant = "primary" | "ghost" | "subtle";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  label: string; // accessible label required
  active?: boolean;
  children: ReactNode;
};

const variantClass: Record<Variant, string> = {
  primary:
    "bg-coral-600 text-white hover:bg-coral-700 active:bg-coral-700",
  ghost:
    "bg-transparent text-ink-700 hover:bg-ink-100 active:bg-ink-200",
  subtle:
    "bg-white text-ink-700 border border-ink-200 hover:border-ink-300 hover:bg-ink-50",
};

const sizeClass = {
  sm: "h-9 w-9 rounded-full",
  md: "h-11 w-11 rounded-full",
  lg: "h-12 w-12 rounded-full",
} as const;

export const IconButton = forwardRef<HTMLButtonElement, Props>(function IconButton(
  { variant = "subtle", size = "md", label, active, className, children, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "inline-flex items-center justify-center transition-colors duration-150",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600 focus-visible:ring-offset-2 focus-visible:ring-offset-white",
        variantClass[variant],
        sizeClass[size],
        active && "ring-2 ring-coral-600 ring-offset-2 ring-offset-white",
        className
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
