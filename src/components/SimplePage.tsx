import type { ReactNode } from "react";

export function SimplePage({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
      <h1 className="text-[clamp(1.6rem,3.5vw,2.1rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {title}
      </h1>
      <div className="mt-4 rounded-[20px] border border-ink-100 bg-white p-6 shadow-card text-[14px] text-ink-700">
        {children ?? (
          <p>This page is being prepared. We&apos;re focused on building the best charging discovery experience first.</p>
        )}
      </div>
    </div>
  );
}
