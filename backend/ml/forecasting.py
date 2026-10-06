"""ChargePlus — Forecasting specifications (Phase 5/6, Step 5.6).

No historical target exists today, so this step establishes the forecast
contract (target / horizon / frequency / cutoffs / windows) plus naive
forecasters that run on real sequences when they arrive. Forecasting
without a historical target is refused, not approximated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence


@dataclass(frozen=True)
class ForecastSpec:
    task: str
    target: str
    horizon: str  # e.g. "next 24h in 15-min steps"
    frequency: str  # e.g. "15min"
    feature_cutoff: str  # e.g. "T (no future inputs)"
    training_window: str
    evaluation_window: str
    embargo: str = "none"


FORECAST_SPECS: dict[str, ForecastSpec] = {
    "availability": ForecastSpec(
        task="availability forecasting", target="availability_status per station",
        horizon="next 24h in 15-min steps", frequency="15min",
        feature_cutoff="T: only observations with observed_at <= T",
        training_window="trailing 90 days before cutoff",
        evaluation_window="trailing 14 days, step-24h rolling"),
    "demand": ForecastSpec(
        task="demand forecasting", target="sessions per station-day",
        horizon="next 7 days", frequency="daily",
        feature_cutoff="T: only sessions ending <= T",
        training_window="trailing 8 full weeks",
        evaluation_window="trailing 2 weeks"),
}


def seasonal_naive(history: Sequence[float], seasonality: int, steps: int) -> Optional[list[float]]:
    """Seasonal-naive forecast: repeat the value from one season ago."""
    if seasonality < 1 or steps < 1 or len(history) < seasonality:
        return None  # insufficient history: no forecast, not a zero forecast
    return [history[len(history) - seasonality + (i % seasonality)]
            if len(history) - seasonality + (i % seasonality) >= 0
            else history[-seasonality]
            for i in range(steps)]


def forecast_window(events: list[dict[str, Any]], cutoff: datetime,
                    horizon: timedelta) -> tuple[list[dict[str, Any]], tuple[datetime, datetime]]:
    """Splits events into history (<= cutoff) and target window (cutoff, cutoff+horizon].

    Naive timestamps rejected (awareness required for correct windowing).
    """
    if cutoff.tzinfo is None:
        raise ValueError("cutoff must be timezone-aware")
    end = cutoff + horizon
    for e in events:
        ts = e.get("ts")
        if not isinstance(ts, datetime) or ts.tzinfo is None:
            raise ValueError("event timestamps must be timezone-aware datetimes")
    history = [e for e in events if e["ts"] <= cutoff]
    window = [e for e in events if cutoff < e["ts"] <= end]
    return history, (cutoff, end)
