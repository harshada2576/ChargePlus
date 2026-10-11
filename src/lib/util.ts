/** Compose class names, skipping falsy values. */
export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

/** Returns a friendly relative time string in English (or pre-translated value). */
export function minutesToFriendly(minutes: number | null | undefined): {
  kind: "just" | "min" | "hour" | "day" | "older";
  value: number | null;
} {
  if (minutes == null) return { kind: "older", value: null };
  if (minutes < 1) return { kind: "just", value: null };
  if (minutes < 60) return { kind: "min", value: Math.round(minutes) };
  if (minutes < 60 * 24) return { kind: "hour", value: Math.round(minutes / 60) };
  return { kind: "day", value: Math.round(minutes / (60 * 24)) };
}

export function delay(ms: number) {
  return new Promise<void>((res) => setTimeout(res, ms));
}
