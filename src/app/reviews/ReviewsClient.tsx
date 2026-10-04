"use client";

import { useCallback, useEffect, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { fetchStations } from "@/data/stations";
import type { Station } from "@/data/types";
import { supabase } from "@/lib/supabase";
import { listOwnReviews, type OwnReview } from "@/lib/reviews";
import { stationDetailHref } from "@/data/exploreQuery";
import { Button } from "@/components/Button";
import { StarFilledIcon, StarIcon, ExploreIcon, ClockIcon, AlertTriangleIcon } from "@/components/Icon";
import { Link } from "@/i18n/Link";
import { AuthPrompt } from "../saved/SavedClient";

export function ReviewsClient() {
  const { t } = useI18n();
  const { user, isAuthed, authReady } = useSession();
  const [reviews, setReviews] = useState<OwnReview[]>([]);
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
    // Unauthenticated branch renders AuthPrompt; no state reset needed here.
    if (!user) return;
    Promise.all([listOwnReviews(supabase, user.id), fetchStations()])
      .then(([mine, all]) => {
        if (!active) return;
        setReviews(mine);
        setStations(all);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load reviews");
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [user, nonce]);

  if (!authReady) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <p className="text-center text-[13.5px] text-ink-600">{t("common.loading")}</p>
      </div>
    );
  }

  if (!isAuthed) {
    return (
      <div className="mx-auto max-w-screen-md px-4 py-10 sm:px-6">
        <AuthPrompt title={t("auth.prompt.title")} body={t("auth.prompt.body")} />
      </div>
    );
  }

  const byId = new Map(stations.map((s) => [s.id, s]));

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
        {t("profile.reviews")}
      </h1>
      <p className="mt-1 text-[14px] text-ink-600">
        Ratings and feedback you shared about charging experiences.
      </p>

      {loading ? (
        <p className="mt-8 text-center text-[13.5px] text-ink-600">{t("common.loading")}</p>
      ) : error ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertTriangleIcon size={24} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">{t("errors.network.title")}</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">{t("errors.network.body")}</p>
          <div className="mt-5">
            <Button size="md" variant="primary" onClick={reload}>
              {t("common.tryAgain")}
            </Button>
          </div>
        </div>
      ) : reviews.length === 0 ? (
        <div className="mt-8 rounded-[20px] border border-ink-100 bg-white p-8 text-center shadow-card">
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-coral-50 text-coral-700">
            <StarFilledIcon size={24} />
          </span>
          <h2 className="mt-3 text-[17px] font-semibold text-ink-900">No reviews yet</h2>
          <p className="mt-1 text-[13.5px] text-ink-600">
            Share your feedback on charger speeds, wait times, and location accessibility to guide others.
          </p>
          <div className="mt-5">
            <Link href="/explore">
              <Button size="md" variant="primary" iconLeft={<ExploreIcon size={16} />}>
                Explore stations to review
              </Button>
            </Link>
          </div>
        </div>
      ) : (
        <ul className="mt-5 space-y-3">
          {reviews.map((r) => {
            const station = byId.get(r.stationId);
            const dateStr = r.createdAt
              ? new Date(r.createdAt).toLocaleDateString(undefined, {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })
              : "Recently";

            return (
              <li
                key={r.id}
                className="rounded-[18px] border border-ink-100 bg-white p-4 shadow-card transition-shadow hover:shadow-card-hover"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <Link
                      href={stationDetailHref(r.stationId)}
                      className="text-[15px] font-semibold text-ink-900 hover:underline"
                    >
                      {station?.name ?? "Charging Station"}
                    </Link>
                    <p className="mt-0.5 text-[12.5px] text-ink-600">
                      {station?.area ?? "Area unknown"}
                    </p>
                  </div>
                  {/* Star rating pattern reused from StationReviewForm */}
                  <div className="flex items-center gap-1 text-coral-600">
                    {[1, 2, 3, 4, 5].map((i) => (
                      <span key={i}>
                        {i <= r.rating ? (
                          <StarFilledIcon size={16} />
                        ) : (
                          <StarIcon size={16} className="text-ink-300" />
                        )}
                      </span>
                    ))}
                  </div>
                </div>

                {r.comment && (
                  <p className="mt-3 text-[13.5px] text-ink-800">
                    {r.comment}
                  </p>
                )}

                <div className="mt-3 flex items-center gap-2 text-[12px] text-ink-500">
                  <ClockIcon size={13} />
                  <span>{dateStr}</span>
                  {r.moderationStatus && r.moderationStatus !== "approved" && (
                    <span className="rounded-full bg-ink-100 px-2 py-0.5 text-[11px] font-medium text-ink-600">
                      Under review
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
