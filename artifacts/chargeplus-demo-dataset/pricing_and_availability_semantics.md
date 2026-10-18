# Pricing and Availability Semantics

## Pricing
- Verified demo per-kWh: price_per_kwh populated, price_per_session null, estimate null.
- Per-session: price_per_session populated.
- Estimate only: price_estimate_per_kwh populated with raw text and source 'ocm_usage_cost'; verified price null.
- Free: price_per_kwh = 0 with pricing_type 'free'.
- Unavailable: all price fields null.
- Synthetic prices are labeled demo via operator names and provenance, not real operator verification.

## Availability
- Observations include available, busy, broken, unknown.
- Fresh/stale determined by observed_at and frontend freshness rules.
- Connectors with no observations remain unknown.
- Synthetic observations are demo data, not live telemetry.
EOF