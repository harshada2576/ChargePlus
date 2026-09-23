import { cx } from "@/lib/util";

export function Skeleton({
  className,
  variant = "block",
}: {
  className?: string;
  variant?: "block" | "circle" | "line";
}) {
  return (
    <span
      className={cx(
        "skeleton block",
        variant === "circle" && "rounded-full",
        variant === "line" && "h-3 w-full rounded-md",
        variant === "block" && "rounded-[10px]",
        className
      )}
      aria-hidden
    />
  );
}

export function StationCardSkeleton() {
  return (
    <div className="rounded-[18px] border border-ink-100 bg-white p-4 shadow-card">
      <Skeleton className="h-4 w-2/3" />
      <Skeleton className="mt-2 h-3 w-1/3" />
      <Skeleton className="mt-4 h-3 w-1/2" />
      <Skeleton className="mt-3 h-3 w-1/3" />
      <div className="mt-4 flex items-center justify-between">
        <Skeleton className="h-5 w-24 rounded-full" />
        <Skeleton className="h-9 w-24" />
      </div>
    </div>
  );
}
