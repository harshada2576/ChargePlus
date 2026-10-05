"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { fetchStations } from "@/data/stations";
import type { Station } from "@/data/types";
import { StationCard } from "@/components/StationCard";
import { StationCardSkeleton } from "@/components/Skeleton";
import { Button } from "@/components/Button";
import { HeartIcon, ExploreIcon, AlertTriangleIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";

export function SavedClient() {
  const { t } = useI18n();
  const { savedIds, isAuthed, authReady } = useSession();
  const [stations, setStations] = useState<Station[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    setNonce((n) => n + 1);
  }, []);

  useEffect(() => {
    let active = true;
    fetchStations()
      .then((data) => {
        if (!active) return;
        setStations(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load stations");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [nonce]);

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  // Server-saved ids joined against canonical stations. A saved id with no
  // canonical record (removed station) is omitted, never fabricated.
  const byId = new Map(stations.map((s) => [s.id, s]));
  const list = [...savedIds].map((id) => byId.get(id)).filter((s): s is Station => !!s);

  if (!authReady) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <p className="text-center text-[13.5px] text-ink-600">{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-screen-md px-4 pb-10 pt-4 sm:px-6">
      <h1 className="text-[clamp(1.5rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("saved.title")}
      </h1>

      {loading ? (
        <div className="mt-4 space-y-3">
          <StationCardSkeleton />
          <StationCardSkeleton />
        </div>
      ) : error ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertTriangleIcon size={22} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("errors.network.title")}</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">{t("errors.network.body")}</p>
          <div className="mt-5">
            <Button size="md" variant="primary" onClick={reload}>
              {t("common.tryAgain")}
            </Button>
          </div>
        </div>
      ) : list.length === 0 ? (
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
