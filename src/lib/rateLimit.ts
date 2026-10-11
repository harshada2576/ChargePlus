/**
 * Minimal in-memory token-bucket rate limiter for API routes (Phase 6.5).
 *
 * Scope: abuse friction on server routes without new infrastructure.
 * Limits: single Node instance (resets on restart/deploy); distributed
 * enforcement belongs to the hosting edge (documented in docs/production.md).
 * Keys live in memory only — never logged, never persisted.
 * Fail-safe: if the store errors, the request is allowed (fail-open on the
 * limiter itself; authorization checks still apply).
 */

export type RateLimit = { limit: number; windowMs: number };

type Bucket = { count: number; resetAt: number };

const buckets = new Map<string, Bucket>();

function prune(now: number): void {
  if (buckets.size < 1000) return;
  for (const [key, bucket] of buckets) {
    if (bucket.resetAt <= now) buckets.delete(key);
  }
}

export function checkRateLimit(
  key: string,
  { limit, windowMs }: RateLimit,
  now: number = Date.now()
): { allowed: boolean; retryAfterMs: number } {
  try {
    prune(now);
    const bucket = buckets.get(key);
    if (!bucket || bucket.resetAt <= now) {
      buckets.set(key, { count: 1, resetAt: now + windowMs });
      return { allowed: true, retryAfterMs: 0 };
    }
    if (bucket.count < limit) {
      bucket.count += 1;
      return { allowed: true, retryAfterMs: 0 };
    }
    return { allowed: false, retryAfterMs: Math.max(0, bucket.resetAt - now) };
  } catch {
    return { allowed: true, retryAfterMs: 0 };
  }
}

/** Test/ops escape hatch: clears in-memory counters. */
export function resetRateLimits(): void {
  buckets.clear();
}

export function clientKey(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const ip = forwarded ? forwarded.split(",")[0].trim() : "unknown-ip";
  return `ip:${ip}`;
}

export function credentialKey(request: Request): string {
  // The raw credential is the correct abuse identity; it never leaves memory.
  const auth = request.headers.get("authorization") ?? "anonymous";
  return `cred:${auth.slice(0, 64)}`;
}
