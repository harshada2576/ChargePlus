"""ChargePlus — Warehouse data-quality checks (Phase 4/6, Step 4.5).

Validates warehouse integrity (not ingestion validation — Phase 2 owns
that). Severities: INFO / WARNING / HIGH / CRITICAL. Failed checks are
reported, never hidden; this module writes nothing.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from dotenv import load_dotenv

logger = logging.getLogger("chargeplus.warehouse.quality")


@dataclass
class QualityFinding:
    rule_id: str
    severity: str  # INFO | WARNING | HIGH | CRITICAL
    passed: bool
    detail: str
    offending_count: int = 0


@dataclass
class QualityReport:
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    findings: list[QualityFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at.isoformat(),
            "passed": all(f.passed or f.severity == "INFO" for f in self.findings),
            "findings": [
                {
                    "rule_id": f.rule_id,
                    "severity": f.severity,
                    "passed": f.passed,
                    "detail": f.detail,
                    "offending_count": f.offending_count,
                }
                for f in self.findings
            ],
        }


def _scalar(cur: Any, sql: str, params: tuple = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    if not row:
        return 0
    return int(row[0] if isinstance(row, (tuple, list)) else list(row.values())[0])


def check_referential_integrity(cur: Any) -> list[QualityFinding]:
    """WH-RI-*: every fact dimension key resolves to its dimension."""
    findings = []
    cases = [
        ("WH-RI-OBS-STATION", "analytics.fact_station_observation", "station_key",
         "analytics.dim_station", "station_key"),
        ("WH-RI-OBS-SOURCE", "analytics.fact_station_observation", "source_key",
         "analytics.dim_source", "source_key"),
        ("WH-RI-OBS-DATE", "analytics.fact_station_observation", "date_key",
         "analytics.dim_date", "date_key"),
        ("WH-RI-REP-STATION", "analytics.fact_user_report", "station_key",
         "analytics.dim_station", "station_key"),
        ("WH-RI-REV-STATION", "analytics.fact_review", "station_key",
         "analytics.dim_station", "station_key"),
        ("WH-RI-DAILY-STATION", "analytics.fact_station_daily", "station_key",
         "analytics.dim_station", "station_key"),
    ]
    for rule_id, fact, fk, dim, pk in cases:
        n = _scalar(
            cur,
            f"SELECT count(*) FROM {fact} f LEFT JOIN {dim} d ON d.{pk} = f.{fk}"
            f" WHERE d.{pk} IS NULL",
        )
        findings.append(QualityFinding(
            rule_id=rule_id, severity="CRITICAL", passed=n == 0,
            detail=f"{n} {fact} row(s) with unresolvable {fk}" if n else f"all {fact}.{fk} resolve",
            offending_count=n,
        ))
    return findings


def check_duplicate_grains(cur: Any) -> list[QualityFinding]:
    """WH-DUP-*: no duplicate rows at any defined fact grain."""
    findings = []
    cases = [
        ("WH-DUP-OBS", "analytics.fact_station_observation", "observation_id"),
        ("WH-DUP-REP", "analytics.fact_user_report", "report_id"),
        ("WH-DUP-REV", "analytics.fact_review", "review_id"),
        ("WH-DUP-DAILY", "analytics.fact_station_daily", "station_key, date_key"),
    ]
    for rule_id, table, key in cases:
        n = _scalar(
            cur,
            f"SELECT count(*) FROM (SELECT {key} FROM {table} GROUP BY {key} HAVING count(*) > 1) dup",
        )
        findings.append(QualityFinding(
            rule_id=rule_id, severity="HIGH", passed=n == 0,
            detail=f"{n} duplicate grain(s) in {table}" if n else f"no duplicate grains in {table}",
            offending_count=n,
        ))
    return findings


def check_aggregate_bounds(cur: Any) -> list[QualityFinding]:
    """WH-AGG-*: aggregates never exceed underlying evidence; ratios sane."""
    findings = []
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_daily"
        " WHERE available_count + busy_count + broken_count > observation_count")
    findings.append(QualityFinding("WH-AGG-STATUS", "HIGH", n == 0,
        f"{n} daily row(s) with status counts exceeding observations" if n else "status conservation holds",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_daily"
        " WHERE observation_count = 0 AND report_count = 0 AND review_count = 0")
    findings.append(QualityFinding("WH-AGG-EVIDENCE", "HIGH", n == 0,
        f"{n} daily row(s) with zero evidence of any kind" if n else "every daily row has evidence",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_daily"
        " WHERE (availability_ratio IS NOT NULL AND (availability_ratio < 0 OR availability_ratio > 1))"
        " OR (busy_ratio IS NOT NULL AND (busy_ratio < 0 OR busy_ratio > 1))"
        " OR (broken_ratio IS NOT NULL AND (broken_ratio < 0 OR broken_ratio > 1))")
    findings.append(QualityFinding("WH-AGG-RATIO", "HIGH", n == 0,
        f"{n} daily row(s) with out-of-range ratios" if n else "ratios in [0,1] or NULL",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_daily WHERE has_evidence IS NOT TRUE")
    findings.append(QualityFinding("WH-AGG-FLAG", "HIGH", n == 0,
        f"{n} daily row(s) with has_evidence false" if n else "has_evidence always true",
        n))
    return findings


def check_null_semantics(cur: Any) -> list[QualityFinding]:
    """WH-NULL-*: unknown stays unknown; no impossible combinations."""
    findings = []
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.dim_connector"
        " WHERE power_kw IS NOT NULL AND power_kw <= 0")
    findings.append(QualityFinding("WH-NULL-POWER", "HIGH", n == 0,
        f"{n} dim_connector row(s) with non-positive power" if n else "power NULL-or->0 holds",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_observation"
        " WHERE available_connectors IS NOT NULL"
        " AND (total_connectors = 0 OR available_connectors > total_connectors)")
    findings.append(QualityFinding("WH-NULL-AVAIL", "HIGH", n == 0,
        f"{n} observation fact(s) with impossible availability counts" if n else "availability counts sane",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_observation WHERE source_payload_hash IS NULL")
    findings.append(QualityFinding("WH-NULL-PROV", "INFO", True,
        f"{n} observation fact(s) without payload hash (best-effort provenance)", n))
    return findings


def check_timestamps(cur: Any) -> list[QualityFinding]:
    """WH-TS-*: no future analytical timestamps; causality holds."""
    findings = []
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_observation WHERE observed_at > now() + interval '1 hour'")
    findings.append(QualityFinding("WH-TS-FUTURE", "HIGH", n == 0,
        f"{n} observation fact(s) with future timestamps" if n else "no future observations",
        n))
    n = _scalar(cur,
        "SELECT count(*) FROM analytics.fact_station_observation WHERE received_at < observed_at")
    findings.append(QualityFinding("WH-TS-CAUSAL", "CRITICAL", n == 0,
        f"{n} observation fact(s) violating causality" if n else "causality holds",
        n))
    return findings


def check_reconciliation(cur: Any) -> list[QualityFinding]:
    """WH-REC-*: warehouse fact counts reconcile with eligible OLTP counts."""
    findings = []

    def counts(oltp_sql: str, wh_sql: str) -> tuple[int, int]:
        return _scalar(cur, oltp_sql), _scalar(cur, wh_sql)

    oltp, wh = counts("SELECT count(*) FROM public.station_observations",
                      "SELECT count(*) FROM analytics.fact_station_observation")
    findings.append(QualityFinding("WH-REC-OBS", "CRITICAL", oltp == wh,
        f"observations OLTP={oltp} warehouse={wh}" + ("" if oltp == wh else " MISMATCH"), abs(oltp - wh)))

    oltp, wh = counts("SELECT count(*) FROM public.user_reports WHERE moderation_status='approved' AND moderated_at IS NOT NULL",
                      "SELECT count(*) FROM analytics.fact_user_report")
    findings.append(QualityFinding("WH-REC-REP", "CRITICAL", oltp == wh,
        f"eligible reports OLTP={oltp} warehouse={wh}" + ("" if oltp == wh else " MISMATCH"), abs(oltp - wh)))

    oltp, wh = counts("SELECT count(*) FROM public.reviews WHERE moderation_status='approved' AND moderated_at IS NOT NULL",
                      "SELECT count(*) FROM analytics.fact_review")
    findings.append(QualityFinding("WH-REC-REV", "CRITICAL", oltp == wh,
        f"eligible reviews OLTP={oltp} warehouse={wh}" + ("" if oltp == wh else " MISMATCH"), abs(oltp - wh)))

    oltp, wh = counts("SELECT count(*) FROM public.stations",
                      "SELECT count(DISTINCT station_id) FROM analytics.dim_station")
    findings.append(QualityFinding("WH-REC-STATION", "HIGH", oltp == wh,
        f"stations OLTP={oltp} distinct dim identities={wh}" + ("" if oltp == wh else " MISMATCH"), abs(oltp - wh)))

    oltp, wh = counts("SELECT count(*) FROM public.connectors",
                      "SELECT count(*) FROM analytics.dim_connector")
    findings.append(QualityFinding("WH-REC-CONN", "HIGH", oltp == wh,
        f"connectors OLTP={oltp} dim={wh}" + ("" if oltp == wh else " MISMATCH"), abs(oltp - wh)))
    return findings


ALL_CHECKS: list[Callable[[Any], list[QualityFinding]]] = [
    check_referential_integrity,
    check_duplicate_grains,
    check_aggregate_bounds,
    check_null_semantics,
    check_timestamps,
    check_reconciliation,
]


def run_all_checks(conn: Any) -> QualityReport:
    """Executes every warehouse DQ check in one read-only pass."""
    report = QualityReport()
    with conn.cursor() as cur:
        for check in ALL_CHECKS:
            try:
                report.findings.extend(check(cur))
            except Exception as ex:
                logger.warning("DQ check %s errored: %s", getattr(check, "__name__", check), ex)
                report.findings.append(QualityFinding(
                    rule_id="WH-CHECK-ERROR", severity="WARNING", passed=False,
                    detail=f"{getattr(check, '__name__', check)} errored: {ex}"))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="ChargePlus warehouse data quality checks (Phase 4.5, read-only).")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    args = parser.parse_args()

    load_dotenv(".env.local")
    load_dotenv(".env")
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not configured.", file=sys.stderr)
        sys.exit(1)
    conn = psycopg2.connect(db_url)
    try:
        report = run_all_checks(conn)
    finally:
        conn.close()

    rep_dict = report.to_dict()
    if args.json:
        print(json.dumps(rep_dict, indent=2))
    else:
        status = "PASSED" if rep_dict["passed"] else "FAILED"
        print(f"warehouse data quality: {status} ({len(report.findings)} checks)")
        for f in report.findings:
            mark = "PASS" if f.passed else f"FAIL [{f.severity}]"
            print(f"  {f.rule_id} ({mark}): {f.detail}")

    if not rep_dict["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
