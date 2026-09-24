import { cx } from "@/lib/util";

export function BrandMark({
  size = "md",
  withWordmark = true,
  className,
}: {
  size?: "sm" | "md" | "lg";
  withWordmark?: boolean;
  className?: string;
}) {
  const iconSize =
    size === "sm" ? 22 : size === "lg" ? 34 : 28;
  const fontSize =
    size === "sm" ? "text-[15px]" : size === "lg" ? "text-[22px]" : "text-[17px]";

  return (
    <div className={cx("inline-flex items-center gap-2", className)}>
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 32 32"
        aria-hidden="true"
        className="shrink-0"
      >
        <defs>
          <linearGradient id="cp-mark" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0%" stopColor="#F8AD9D" />
            <stop offset="100%" stopColor="#F08080" />
          </linearGradient>
        </defs>
        <rect x="1" y="1" width="30" height="30" rx="9" fill="url(#cp-mark)" />
        {/* simple bolt */}
        <path
          d="M17.5 6 L10 18 H15 L13 26 L22 13 H17 Z"
          fill="#FFF"
          stroke="#FFF"
          strokeWidth="0.5"
          strokeLinejoin="round"
        />
      </svg>
      {withWordmark && (
        <span className={cx("font-semibold tracking-[-0.01em] text-ink-900", fontSize)}>
          ChargePlus
        </span>
      )}
    </div>
  );
}
