"use client";

import { useEffect } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { Button } from "@/components/Button";
import { AlertTriangleIcon } from "@/components/Icon";

/**
 * Station-detail error boundary. Rendered when the canonical loader throws
 * (genuine query failure) — never for a successful no-match, which uses
 * notFound() instead. Offers a retry without fabricating station data.
 */
export default function StationError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const { t } = useI18n();

  useEffect(() => {
    console.error("Station detail failed to load:", error);
  }, [error]);

  return (
    <div className="bg-ink-50">
      <div className="mx-auto max-w-screen-lg px-4 pb-16 pt-10 sm:px-6">
        <div className="rounded-[18px] border border-ink-100 bg-white p-6 text-center shadow-card">
          <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-red-50 text-red-600">
            <AlertTriangleIcon size={20} />
          </span>
          <h3 className="mt-3 text-[15.5px] font-semibold text-ink-900">
            {t("errors.network.title")}
          </h3>
          <p className="mt-1 text-[13px] text-ink-600">{t("errors.network.body")}</p>
          <div className="mt-4">
            <Button variant="primary" size="md" onClick={reset}>
              {t("common.tryAgain")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
