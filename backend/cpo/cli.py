"""ChargePlus — CPO Partner Operator CLI.

Safe manual execution for partner configuration status and synchronization:

    # Local lifecycle state + activation checklist (no network)
    python -m backend.cpo.cli status --partner demo --protocol ocpi --env sandbox

    # Dry-run sync against a partner (zero database writes by default)
    python -m backend.cpo.cli sync --partner demo --protocol ocpi --env sandbox --dry-run

    # Live sync (requires configured credentials; refused when NOT_CONFIGURED)
    python -m backend.cpo.cli sync --partner demo --protocol ocpi --env production

Credentials come from <ENV_PREFIX>_ENDPOINT/_TOKEN(/_TOKEN_EXPIRES_AT), where
ENV_PREFIX defaults to {PROTOCOL}_{PARTNER}_{ENV} (uppercased). Use --prefix
to override (e.g. separate vault-mapped names). Secrets are never printed:
status output shows presence only.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from backend.cpo.partners import (
    PartnerConfig,
    PartnerCredentialError,
    activation_checklist,
)
from backend.cpo.sync import PartnerSync
from backend.ingestion.persistence import IngestionPersistenceService


def _make_config(args: argparse.Namespace) -> PartnerConfig:
    prefix = args.prefix or f"{args.protocol}_{args.partner}_{args.env}".upper()
    return PartnerConfig.from_env(
        partner_name=args.partner,
        protocol=args.protocol,
        environment=args.env,
        env_prefix=prefix,
    )


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        config = _make_config(args)
    except PartnerCredentialError as exc:
        print(json.dumps({"configured": False, "error": str(exc)}, indent=2))
        return 2
    print(json.dumps({
        "configured": True,
        "summary": config.safe_summary(),
        "checklist": activation_checklist(config),
    }, indent=2))
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    try:
        config = _make_config(args)
        config.require_usable()
    except (PartnerCredentialError, ValueError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2))
        return 2

    persistence: Any = None
    if not args.dry_run:
        import os

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            print(json.dumps(
                {"success": False, "error": "DATABASE_URL not set; refusing live sync"}, indent=2))
            return 2
        persistence = IngestionPersistenceService(db_url)
    try:
        from backend.ingestion.runner import IngestionRunner

        if persistence is not None:
            runner = IngestionRunner(persistence_service=persistence)
        elif args.dry_run:
            # Explicit offline service: dry-runs never touch the database,
            # even when a (possibly placeholder) DATABASE_URL is configured.
            runner = IngestionRunner(
                persistence_service=IngestionPersistenceService(None)
            )
        else:
            runner = IngestionRunner()
        report = PartnerSync(runner=runner).sync(
            config,
            dry_run=args.dry_run,
            limit=args.limit,
            full=args.full,
            state_path=args.state_path,
            provider_id=args.provider_id,
        )
    finally:
        if persistence is not None:
            try:
                persistence.close()
            except Exception:
                pass
    print(json.dumps(report.to_dict(), indent=2, default=str))
    return 0 if not report.errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ChargePlus CPO partner CLI")
    parser.add_argument("--partner", required=True, help="Partner short name (e.g. tatapower)")
    parser.add_argument("--protocol", required=True, choices=("ocpi", "oicp"))
    parser.add_argument("--env", required=True, choices=("sandbox", "production"))
    parser.add_argument("--prefix", default=None,
                        help="Env var prefix override (default {PROTOCOL}_{PARTNER}_{ENV})")
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Local lifecycle state + checklist")
    p_status.set_defaults(func=_cmd_status)

    p_sync = sub.add_parser("sync", help="Pull partner inventory through the canonical pipeline")
    p_sync.add_argument("--dry-run", action="store_true", default=True,
                        help="Zero database writes (default on)")
    p_sync.add_argument("--live", dest="dry_run", action="store_false",
                        help="Actually persist (requires DATABASE_URL + usable credentials)")
    p_sync.add_argument("--limit", type=int, default=1000)
    p_sync.add_argument("--full", action="store_true",
                        help="Ignore the incremental cursor and re-pull everything")
    p_sync.add_argument("--state-path", default=None)
    p_sync.add_argument("--provider-id", default=None,
                        help="OICP eRoaming provider identifier (oicp only)")
    p_sync.set_defaults(func=_cmd_sync)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
