"use client";

import { useEffect, useRef, useState } from "react";
import { useI18n } from "@/i18n/I18nProvider";
import { Button } from "@/components/Button";
import { Link } from "@/i18n/Link";
import { ChevronLeftIcon } from "@/components/Icon";
import { useSession } from "@/state/SessionProvider";
import { useRouter } from "next/navigation";
import { useToast } from "@/components/Toast";

type Pending = { contact: string; kind: "phone" | "email" };

export function VerifyClient() {
  const { t } = useI18n();
  const router = useRouter();
  const { signIn } = useSession();
  const { show } = useToast();
  const [pending, setPending] = useState<Pending | null>(null);
  const [digits, setDigits] = useState<string[]>(Array(6).fill(""));
  const [error, setError] = useState<string | null>(null);
  const [resendIn, setResendIn] = useState(30);
  const inputsRef = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("chargeplus:otp:pending");
      if (raw) {
        queueMicrotask(() => {
          setPending(JSON.parse(raw));
        });
      }
    } catch {}
  }, []);

  useEffect(() => {
    if (resendIn <= 0) return;
    const id = setInterval(() => setResendIn((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(id);
  }, [resendIn]);

  function setDigit(i: number, v: string) {
    const val = v.replace(/\D/g, "").slice(-1);
    setDigits((prev) => {
      const next = prev.slice();
      next[i] = val;
      return next;
    });
    if (val && i < 5) inputsRef.current[i + 1]?.focus();
  }

  function onKey(i: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && !digits[i] && i > 0) {
      inputsRef.current[i - 1]?.focus();
    }
  }

  function onPaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);
    if (!text) return;
    e.preventDefault();
    const arr = text.split("");
    setDigits((prev) => {
      const next = prev.slice();
      for (let i = 0; i < 6; i++) next[i] = arr[i] ?? "";
      return next;
    });
    inputsRef.current[Math.min(text.length, 5)]?.focus();
  }

  function submit() {
    if (!pending) return;
    const code = digits.join("");
    if (code.length !== 6) {
      setError(t("auth.otp.invalid"));
      return;
    }
    // Accept any 6-digit code in this mock.
    setError(null);
    signIn(pending.contact, pending.kind);
    sessionStorage.removeItem("chargeplus:otp:pending");
    show("Signed in");
    router.push("/profile");
  }

  function resend() {
    setResendIn(30);
    show("Code resent");
  }

  if (!pending) {
    return (
      <div className="mx-auto max-w-md px-4 py-10 sm:px-6">
        <p className="text-[14px] text-ink-700">No pending verification.</p>
        <Link href="/login" className="mt-3 inline-block text-[13.5px] text-coral-700 hover:underline">
          {t("common.continue")}
        </Link>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-md flex-col px-4 pt-3 sm:px-6">
      <Link href="/login" className="inline-flex h-10 items-center gap-1 rounded-full px-2 text-[13.5px] font-medium text-ink-700 hover:bg-ink-100 w-fit">
        <ChevronLeftIcon size={16} />
        {t("common.back")}
      </Link>

      <h1 className="mt-4 text-[clamp(1.5rem,3.5vw,1.9rem)] font-semibold tracking-[-0.01em] text-ink-900">
        {t("auth.otp.title")}
      </h1>
      <p className="mt-1 text-[14px] text-ink-700">
        {t("auth.otp.subtitle", {
          contact: pending.kind === "phone" ? `+91 ${pending.contact}` : pending.contact,
        })}
      </p>

      <div className="mt-7">
        <div className="flex justify-between gap-2">
          {digits.map((d, i) => (
            <input
              key={i}
              ref={(el) => {
                inputsRef.current[i] = el;
              }}
              inputMode="numeric"
              maxLength={1}
              value={d}
              onChange={(e) => setDigit(i, e.target.value)}
              onKeyDown={(e) => onKey(i, e)}
              onPaste={onPaste}
              aria-label={`Digit ${i + 1}`}
              className="h-14 w-12 rounded-[14px] border border-ink-200 bg-white text-center text-[22px] font-semibold text-ink-900 focus-visible:border-coral-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-coral-600/30"
            />
          ))}
        </div>

        {error && (
          <p className="mt-3 text-center text-[12.5px] text-status-broken">{error}</p>
        )}

        <div className="mt-6 flex items-center justify-between text-[13px] text-ink-700">
          <button
            type="button"
            onClick={resend}
            disabled={resendIn > 0}
            className="font-medium text-coral-700 disabled:text-ink-400"
          >
            {t("auth.otp.resend")}
            {resendIn > 0 && <span className="ml-1 text-ink-500">({resendIn}s)</span>}
          </button>
          <Link href="/login" className="text-ink-700 hover:underline">
            {t("auth.otp.change")}
          </Link>
        </div>

        <div className="mt-6">
          <Button block size="lg" variant="primary" onClick={submit} disabled={digits.some((d) => !d)}>
            {t("auth.continue")}
          </Button>
        </div>
      </div>
    </div>
  );
}
