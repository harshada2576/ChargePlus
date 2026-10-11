/**
 * Structured server logging (Phase 6.6). JSON lines to stdout for the
 * hosting platform to collect. Never logs credentials, tokens, cookies,
 * or raw authorization headers — callers pass only safe context.
 */

export type LogLevel = "info" | "warn" | "error";

let requestCounter = 0;

export function newRequestId(): string {
  requestCounter = (requestCounter + 1) % 1_000_000;
  return `${Date.now().toString(36)}-${requestCounter.toString(36)}`;
}

export function serverLog(
  level: LogLevel,
  event: string,
  context: Record<string, string | number | boolean | null> = {}
): void {
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      level,
      service: "chargeplus-web",
      event,
      ...context,
    });
    if (level === "error") console.error(line);
    else console.log(line);
  } catch {
    // Logging must never break request handling.
  }
}
