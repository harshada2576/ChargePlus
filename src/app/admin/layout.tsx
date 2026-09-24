import type { ReactNode } from "react";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ChargePlus — Operations & Administration Console",
  description: "Internal operations and system management console for ChargePlus.",
  robots: {
    index: false,
    follow: false,
  },
};

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="-mb-20 min-h-screen bg-[#0B1120] font-sans text-slate-200 antialiased selection:bg-coral-500 selection:text-white md:-mb-12">
      {children}
    </div>
  );
}
