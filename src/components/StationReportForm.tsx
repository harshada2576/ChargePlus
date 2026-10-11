"use client";

import { useState } from "react";
import type { QueueLevel, StationStatus } from "@/data/types";
import { useI18n } from "@/i18n/I18nProvider";
import { useSession } from "@/state/SessionProvider";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/Button";
import { cx } from "@/lib/util";

export function StationReportForm({
  stationId,
  onClose,
}: {
  stationId: string;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { addReport } = useSession();
  const { show } = useToast();

  const [status, setStatus] = useState<Exclude<StationStatus, "unknown"> | null>(null);
  const [queue, setQueue] = useState<QueueLevel>("none");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState<"idle" | "success" | "error">("idle");

  if (done === "success") {
    return (
      <div className="py-4 text-center">
        <span className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-status-available-bg text-status-available">
          ✓
        </span>
        <h3 className="mt-3 text-[16px] font-semibold text-ink-900">{t("station.report.success")}</h3>
        <p className="mt-1 text-[13px] text-ink-600">{t("station.report.successBody")}</p>
        <div className="mt-5">
          <Button block size="md" onClick={onClose}>{t("common.done")}</Button>
        </div>
      </div>
    );
  }

  if (done === "error") {
    return (
      <div className="py-4 text-center">
        <h3 className="text-[16px] font-semibold text-ink-900">{t("station.report.failure")}</h3>
        <p className="mt-1 text-[13px] text-ink-600">{t("station.report.failureBody")}</p>
        <div className="mt-5 flex gap-3">
          <Button block variant="secondary" size="md" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button block variant="primary" size="md" onClick={() => setDone("idle")}>
            {t("common.tryAgain")}
          </Button>
        </div>
      </div>
    );
  }

  function submit() {
    if (!status) return;
    setSubmitting(true);
    setTimeout(() => {
      try {
        addReport({ stationId, status, queue, note: note.trim() || undefined });
        setDone("success");
        show("Report submitted");
      } catch {
        setDone("error");
      } finally {
        setSubmitting(false);
      }
    }, 400);
  }

  const statuses: { value: Exclude<StationStatus, "unknown">; label: string; color: string }[] = [
    { value: "available", label: t("station.status.available"), color: "bg-status-available" },
    { value: "busy", label: t("station.status.busy"), color: "bg-status-busy" },
    { value: "broken", label: t("station.status.broken"), color: "bg-status-broken" },
  ];
  const queues: QueueLevel[] = ["none", "short", "medium", "long"];

  return (
    <div className="space-y-5">
      <section>
        <h3 className="text-[13px] font-semibold text-ink-800">{t("station.report.status")}</h3>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {statuses.map((s) => (
            <button
              key={s.value}
              type="button"
              onClick={() => setStatus(s.value)}
              className={cx(
                "flex items-center justify-center gap-2 rounded-[14px] border px-3 py-3 text-[13.5px] font-medium transition-colors",
                status === s.value
                  ? "border-coral-600 bg-coral-50 text-coral-700"
                  : "border-ink-200 bg-white text-ink-800 hover:bg-ink-50"
              )}
            >
              <span className={cx("h-2.5 w-2.5 rounded-full", s.color)} />
              {s.label}
            </button>
          ))}
        </div>
      </section>

      <section>
        <h3 className="text-[13px] font-semibold text-ink-800">{t("station.report.queue")}</h3>
        <div className="mt-2 grid grid-cols-4 gap-2">
          {queues.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => setQueue(q)}
              className={cx(
                "rounded-[12px] border px-2 py-2.5 text-[12.5px] font-medium transition-colors",
                queue === q
                  ? "border-coral-600 bg-coral-50 text-coral-700"
                  : "border-ink-200 bg-white text-ink-700 hover:bg-ink-50"
              )}
            >
              {t(`station.report.queue.${q}` as "station.report.queue.none")}
            </button>
          ))}
        </div>
      </section>

      <section>
        <label className="block">
          <span className="text-[13px] font-semibold text-ink-800">{t("station.report.note")}</span>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            maxLength={300}
            className="mt-2 w-full rounded-[14px] border border-ink-200 bg-white p-3 text-[14px] text-ink-900 placeholder:text-ink-500 focus-visible:border-coral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600/30"
          />
        </label>
      </section>

      <Button block size="lg" variant="primary" loading={submitting} disabled={!status} onClick={submit}>
        {t("station.report.submit")}
      </Button>
    </div>
  );
}
