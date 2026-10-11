"use client";

import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { STATIONS } from "@/data/stations";
import { StationCard } from "@/components/StationCard";
import { Button } from "@/components/Button";
import { HeartIcon, ExploreIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";

export function SavedClient() {
  const { t } = useI18n();
  const { savedIds, isAuthed } = useSession();
  const list = STATIONS.filter((s) => savedIds.has(s.id));

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-md px-4 pb-10 pt-4 sm:px-6">
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("saved.title")}
      </h1>

      {list.length === 0 ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-50 text-coral-700">
            <HeartIcon size={22} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("saved.empty.title")}</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">{t("saved.empty.body")}</p>
          <div className="mt-5">
            <Link href="/explore">
              <Button size="md" variant="primary" iconLeft={<ExploreIcon size={16} />}>
                {t("saved.empty.cta")}
              </Button>
            </Link>
          </div>
        </div>
      ) : (
        <ul className="mt-4 space-y-3">
          {list.map((s) => (
            <li key={s.id}>
              <StationCard station={s} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function AuthPrompt({ title, body }: { title: string; body: string }) {
  const { t } = useI18n();
  return (
    <div className="rounded-[20px] border border-ink-100 bg-white p-7 text-center shadow-card">
      <h2 className="text-[17px] font-semibold text-ink-900">{title}</h2>
      <p className="mt-1 text-[13.5px] text-ink-600">{body}</p>
      <div className="mt-5 flex justify-center gap-3">
        <Link href="/login">
          <Button size="md" variant="primary">
            {t("common.continue")}
          </Button>
        </Link>
      </div>
    </div>
  );
}
