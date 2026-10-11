"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { BrandMark } from "./BrandMark";
import { Link } from "@/i18n/Link";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { usePathname } from "next/navigation";

export function SiteFooter() {
  const { t } = useI18n();
  const pathname = usePathname() || "/";

  // Admin route uses its own dedicated layout per Spec §56
  if (pathname.startsWith("/admin")) return null;

  return (
    <footer className="hidden border-t border-ink-100 bg-apricot-50/60 md:block">
      <div className="mx-auto grid max-w-screen-xl gap-8 px-6 py-10 sm:grid-cols-2 md:grid-cols-4">
        <div>
          <BrandMark />
          <p className="mt-3 max-w-xs text-[13px] text-ink-700">{t("footer.tagline")}</p>
        </div>

        <div>
          <h4 className="text-[12px] font-semibold uppercase tracking-wider text-ink-700">
            ChargePlus
          </h4>
          <ul className="mt-3 space-y-2 text-[13.5px]">
            <li>
              <Link href="/explore" className="hover:text-coral-700">
                {t("footer.find")}
              </Link>
            </li>
            <li>
              <Link href="/about" className="hover:text-coral-700">
                {t("footer.about")}
              </Link>
            </li>
            <li>
              <Link href="/help" className="hover:text-coral-700">
                {t("footer.help")}
              </Link>
            </li>
            <li>
              <Link href="/contact" className="hover:text-coral-700">
                {t("footer.contact")}
              </Link>
            </li>
          </ul>
        </div>

        <div>
          <h4 className="text-[12px] font-semibold uppercase tracking-wider text-ink-700">
            Legal
          </h4>
          <ul className="mt-3 space-y-2 text-[13.5px]">
            <li>
              <Link href="/privacy" className="hover:text-coral-700">
                {t("footer.privacy")}
              </Link>
            </li>
            <li>
              <Link href="/terms" className="hover:text-coral-700">
                {t("footer.terms")}
              </Link>
            </li>
          </ul>
        </div>

        <div>
          <h4 className="text-[12px] font-semibold uppercase tracking-wider text-ink-700">
            Language
          </h4>
          <div className="mt-3">
            <LanguageSwitcher />
          </div>
        </div>
      </div>

      <div className="border-t border-ink-100/70 bg-white/40">
        <div className="mx-auto flex max-w-screen-xl items-center justify-between px-6 py-4 text-[12px] text-ink-600">
          <span>© {new Date().getFullYear()} ChargePlus</span>
          <span>Mumbai · India</span>
        </div>
      </div>
    </footer>
  );
}
