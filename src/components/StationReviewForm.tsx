"use client";

import { useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { Button } from "./Button";
import { StarFilledIcon, StarIcon } from "./Icon";
import { useToast } from "./Toast";

export function StationReviewForm({
  stationId,
  onClose,
}: {
  stationId: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { show } = useToast();
  const { addReview } = useSession();
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    if (rating < 1) {
      setError("Required");
      return;
    }
    setSubmitting(true);
    setTimeout(() => {
      addReview({ stationId, rating, comment: comment.trim() });
      show(t("station.review.success"));
      setSubmitting(false);
      onClose();
    }, 400);
  }

  return (
    <div className="space-y-5">
      <div>
        <p className="text-[14.5px] text-ink-800">
          How was this charging station?
        </p>
        <div className="mt-3 flex items-center gap-1.5">
          {[1, 2, 3, 4, 5].map((i) => (
            <button
              key={i}
              type="button"
              onClick={() => setRating(i)}
              aria-label={`${i} stars`}
              className="inline-flex h-11 w-11 items-center justify-center rounded-full text-coral-600 hover:bg-coral-50"
            >
              {i <= rating ? <StarFilledIcon size={26} /> : <StarIcon size={26} className="text-ink-300" />}
            </button>
          ))}
        </div>
        {error && (
          <p className="mt-1.5 text-[12px] text-status-broken">{error}</p>
        )}
      </div>

      <label className="block">
        <span className="text-[13px] font-semibold text-ink-800">
          {t("station.review.placeholder")}
        </span>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={4}
          maxLength={500}
          className="mt-2 w-full rounded-[14px] border border-ink-200 bg-white p-3 text-[14px] text-ink-900 placeholder:text-ink-500 focus-visible:border-coral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600/30"
        />
      </label>

      <Button block size="lg" variant="primary" loading={submitting} onClick={submit}>
        {t("station.review.submit")}
      </Button>
    </div>
  );
}
