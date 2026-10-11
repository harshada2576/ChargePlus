"use client";

import { useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { Button } from "@/components/Button";
import { Link } from "@/i18n/Link";
import { BrandMark } from "@/components/BrandMark";
import { ChevronLeftIcon } from "@/components/Icon";
import { useSession } from "@/state/SessionProvider";
import { useToast } from "@/components/Toast";
import { useRouter } from "next/navigation";

export function LoginClient() {
  const { t } = useI18n();
  const router = useRouter();
  const { signIn } = useSession();
  const { show } = useToast();
  const [mode, setMode] = useState<"phone" | "email">("phone");
  const [value, setValue] = useState("");
  const [submitting, setSubmitting] = useState(false);

  function submit() {
    setSubmitting(true);
    setTimeout(() => {
      // Mock "send code"
      const normalized = mode === "phone" ? value.replace(/\D/g, "") : value.trim();
      sessionStorage.setItem(
        "chargeplus:otp:pending",
        JSON.stringify({ contact: normalized, kind: mode })
      );
      show("Code sent");
      router.push(`/verify?kind=${mode}`);
      setSubmitting(false);
    }, 400);
  }

  const valid =
    (mode === "phone" && value.replace(/\D/g, "").length >= 10) ||
    (mode === "email" && /\S+@\S+\.\S+/.test(value));

  return (
    <div className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-md flex-col px-4 pt-3 sm:px-6">
      <Link href="/" className="inline-flex h-10 items-center gap-1 rounded-full px-2 text-[13.5px] font-medium text-ink-700 hover:bg-ink-100 w-fit">
        <ChevronLeftIcon size={16} />
        {t("common.back")}
      </Link>

      <div className="mt-4 flex flex-1 flex-col">
        <div className="mx-auto mb-6"><BrandMark size="lg" /></div>
        <h1 className="text-[clamp(1.6rem,4vw,2rem)] font-semibold tracking-[-0.01em] text-ink-900">
          {t("auth.welcome")}
        </h1>
        <p className="mt-1 text-[14px] text-ink-700">{t("auth.subtitle")}</p>

        <div className="mt-7 space-y-3">
          <button
            type="button"
            onClick={() => setMode("phone")}
            className={`flex w-full items-center justify-between rounded-[16px] border px-4 py-3.5 text-left text-[14px] font-medium transition-colors ${
              mode === "phone" ? "border-coral-600 bg-coral-50 text-coral-700" : "border-ink-200 bg-white text-ink-700"
            }`}
          >
            <span>{t("auth.continuePhone")}</span>
            {mode === "phone" && <span className="text-coral-600">●</span>}
          </button>

          {mode === "phone" ? (
            <label className="block">
              <span className="sr-only">{t("auth.continuePhone")}</span>
              <div className="flex items-stretch overflow-hidden rounded-[16px] border border-ink-200 bg-white focus-within:border-coral-600 focus-within:ring-2 focus-within:ring-coral-600/20">
                <span className="inline-flex items-center bg-ink-50 px-3 text-[14.5px] font-medium text-ink-700">
                  +91
                </span>
                <input
                  inputMode="numeric"
                  autoComplete="tel"
                  placeholder="98765 43210"
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="h-12 flex-1 bg-white px-3 text-[15px] text-ink-900 placeholder:text-ink-400 focus:outline-none"
                />
              </div>
            </label>
          ) : (
            <label className="block">
              <span className="sr-only">{t("auth.continueEmail")}</span>
              <div className="flex items-center overflow-hidden rounded-[16px] border border-ink-200 bg-white focus-within:border-coral-600 focus-within:ring-2 focus-within:ring-coral-600/20">
                <input
                  type="email"
                  autoComplete="email"
                  placeholder={t("auth.emailPlaceholder")}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  className="h-12 flex-1 bg-white px-4 text-[15px] text-ink-900 placeholder:text-ink-400 focus:outline-none"
                />
              </div>
            </label>
          )}

          <div className="flex items-center gap-2 text-[12px] text-ink-500">
            <span className="h-px flex-1 bg-ink-200" />
            <span>{t("auth.or")}</span>
            <span className="h-px flex-1 bg-ink-200" />
          </div>

          <button
            type="button"
            onClick={() => {
              setMode((m) => (m === "phone" ? "email" : "phone"));
              setValue("");
            }}
            className="flex w-full items-center justify-between rounded-[16px] border border-ink-200 bg-white px-4 py-3.5 text-left text-[14px] font-medium text-ink-700 hover:bg-ink-50"
          >
            <span>{mode === "phone" ? t("auth.continueEmail") : t("auth.continuePhone")}</span>
            <span className="text-ink-400">→</span>
          </button>
        </div>

        <div className="mt-7">
          <Button block size="lg" variant="primary" onClick={submit} loading={submitting} disabled={!valid}>
            {t("auth.continue")}
          </Button>
          <p className="mt-3 text-center text-[12.5px] text-ink-600">{t("auth.noPassword")}</p>
        </div>

        <div className="mt-8 text-center text-[12px] text-ink-500">
          {t("auth.createAccount")} <Link href="/login" className="text-coral-700 hover:underline">{t("auth.continue")}</Link>
        </div>
      </div>
    </div>
  );
}
