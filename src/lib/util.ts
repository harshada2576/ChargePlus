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

/** Safely escape untrusted text content before inserting into HTML strings. */
export function escapeHtml(str: string | null | undefined): string {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/** Validate geographic coordinates, rejecting non-numbers, NaN, Null Island (0,0), and out-of-range coordinates. */
export function isValidCoordinate(lat: unknown, lng: unknown): boolean {
  if (typeof lat !== "number" || typeof lng !== "number") return false;
  if (isNaN(lat) || isNaN(lng)) return false;
  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) return false;
  if (lat === 0 && lng === 0) return false;
  return true;
}

