"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { SUPPORTED_LANGUAGES } from "@/i18n/dictionaries";
import type { LanguageCode } from "@/i18n/types";
import { BrandMark } from "@/components/BrandMark";
import {
  ChevronRightIcon,
  SavedIcon,
  BellIcon,
  InboxIcon,
  UserIcon,
  InfoIcon,
  CheckIcon,
} from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { cx } from "@/lib/util";

export function ProfileClient() {
  const { t, lang, setLang } = useI18n();
  const { user, isAuthed, signOut, savedIds, reports, reviews } = useSession();

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
          {t("profile.title")}
        </h1>
        <div className="mt-6 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-50 text-coral-700">
            <UserIcon size={22} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("auth.welcome")}</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">{t("auth.subtitle")}</p>
          <div className="mt-5 flex justify-center">
            <Link href="/login">
              <button className="inline-flex h-11 items-center rounded-full bg-coral-600 px-5 text-[14px] font-medium text-white hover:bg-coral-700">
                {t("profile.signIn")}
              </button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-md px-4 pb-10 pt-4 sm:px-6">
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("profile.title")}
      </h1>

      <section className="mt-5 rounded-[20px] border border-ink-100 bg-white p-5 shadow-card">
        <div className="flex items-center gap-4">
          <div className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-100 text-coral-700">
            <UserIcon size={22} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-[15px] font-semibold text-ink-900">
              {user?.name || user?.contact || "ChargePlus driver"}
            </p>
            <p className="truncate text-[12.5px] text-ink-600">
              {user?.kind === "email" ? user?.contact : `+${(user?.contact || "").replace(/^\+/, "")}`}
            </p>
          </div>
        </div>

        <div className="mt-4">
          <p className="text-[12px] font-semibold uppercase tracking-wider text-ink-600">
            {t("profile.language")}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {SUPPORTED_LANGUAGES.map((l) => (
              <button
                key={l.code}
                onClick={() => setLang(l.code as LanguageCode)}
                className={cx(
                  "inline-flex h-9 items-center rounded-full border px-3 text-[12.5px] font-medium transition-colors",
                  lang === l.code
                    ? "border-coral-600 bg-coral-50 text-coral-700"
                    : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
                )}
              >
                {l.nativeLabel}
              </button>
            ))}
          </div>
        </div>
      </section>

      <section className="mt-4 overflow-hidden rounded-[20px] border border-ink-100 bg-white shadow-card">
        <Row href="/saved" icon={<SavedIcon size={18} />} label={t("profile.saved")} value={String(savedIds.size)} />
        <Row href="/reports" icon={<InboxIcon size={18} />} label={t("profile.reports")} value={String(reports.length)} />
        <Row href="/reviews" icon={<InfoIcon size={18} />} label={t("profile.reviews")} value={String(reviews.length)} />
        <Row href="/alerts" icon={<BellIcon size={18} />} label={t("profile.alerts")} value={null} />
        <Row href="/help" icon={<InfoIcon size={18} />} label={t("profile.help")} value={null} />
      </section>

      <button
        onClick={signOut}
        className="mt-6 inline-flex h-11 w-full items-center justify-center rounded-full border border-ink-200 bg-white text-[14px] font-medium text-ink-800 hover:bg-ink-50"
      >
        {t("profile.logout")}
      </button>
    </div>
  );
}

function Row({
  href,
  icon,
  label,
  value,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  value: string | null;
}) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between gap-3 border-b border-ink-100 px-4 py-3.5 last:border-b-0 hover:bg-ink-50"
    >
      <span className="inline-flex items-center gap-3 text-ink-800">
        <span className="text-coral-700">{icon}</span>
        <span className="text-[14px]">{label}</span>
      </span>
      <span className="inline-flex items-center gap-2 text-ink-500">
        {value != null && <span className="text-[13px]">{value}</span>}
        <ChevronRightIcon size={16} />
      </span>
    </Link>
  );
}
