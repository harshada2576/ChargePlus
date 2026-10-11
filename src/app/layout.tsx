import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { I18nProvider } from "@/i18n/I18nProvider";
import { SessionProvider } from "@/state/SessionProvider";
import { ToastProvider } from "@/components/Toast";
import { SiteHeader } from "@/components/SiteHeader";
import { BottomNav } from "@/components/BottomNav";
import { SiteFooter } from "@/components/SiteFooter";

export const metadata: Metadata = {
  title: "ChargePlus — Find the right charger, before you reach the queue",
  description:
    "Find EV charging stations, compare options and know what to expect before you arrive.",
  icons: {
    icon: [
      {
        url:
          "data:image/svg+xml;utf8," +
          encodeURIComponent(
            `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="9" fill="#F08080"/><path d="M17.5 6 L10 18 H15 L13 26 L22 13 H17 Z" fill="#fff"/></svg>`
          ),
      },
    ],
  },
};

export const viewport = {
  themeColor: "#FBC4AB",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-ink-50 text-ink-900 antialiased">
        <I18nProvider>
          <SessionProvider>
            <ToastProvider>
              <SiteHeader />
              <main className="pb-20 md:pb-12">{children}</main>
              <SiteFooter />
              <BottomNav />
            </ToastProvider>
          </SessionProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
