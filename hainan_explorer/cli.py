"""Command-line interface: python -m hainan_explorer <command>."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import PROJECT_ROOT
from .pipelines import register_handlers
from .services.context import AppContext
from .services.export import BackupService, ExportService
from .services.importer import import_corridor, import_csv, import_legacy_catalog
from .services.jobs import JobService
from .services.places import PlaceService


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hainan_explorer", description="Hainan Explorer local tools")
    parser.add_argument("--config", help="path to sources.yaml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="create/upgrade the database")
    sub.add_parser("serve", help="run the local web app")
    sub.add_parser("summary", help="print catalogue statistics")

    p = sub.add_parser("import-legacy", help="import data/attractions.json leads")
    p.add_argument("path", nargs="?", default=str(PROJECT_ROOT / "data" / "attractions.json"))

    p = sub.add_parser("import-csv", help="import a CSV of places")
    p.add_argument("path")
    p.add_argument("--apply", action="store_true", help="write (default is dry-run preview)")

    p = sub.add_parser("import-corridor", help="import GPX/GeoJSON as the route corridor")
    p.add_argument("path")

    p = sub.add_parser("enqueue", help="queue a job")
    p.add_argument("job_type")
    p.add_argument("--payload", default="{}", help="JSON payload")
    p.add_argument("--priority", type=int, default=5)

    p = sub.add_parser("run-jobs", help="run queued jobs synchronously")
    p.add_argument("--max", type=int, default=None)

    p = sub.add_parser("run", help="enqueue and run one job synchronously")
    p.add_argument("job_type")
    p.add_argument("--payload", default="{}")

    p = sub.add_parser("jobs", help="list jobs")
    p.add_argument("--status")

    p = sub.add_parser("export", help="export places")
    p.add_argument("--format", default="json", choices=["json", "csv", "geojson"])
    p.add_argument("--interest", nargs="*", default=None)
    p.add_argument("--include-seeds", action="store_true")

    p = sub.add_parser("backup", help="back up the database")
    p.add_argument("--label")
    sub.add_parser("backups", help="list backups")
    p = sub.add_parser("restore", help="restore a backup (current DB is backed up first)")
    p.add_argument("name")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if args.command == "serve":
        from .main import run

        run()
        return 0

    from .config import load_config

    ctx = AppContext(load_config(args.config) if args.config else None)
    jobs = JobService(ctx)
    register_handlers(jobs)

    if args.command == "migrate":
        _print({"applied": ctx.db.migrate(), "db": str(ctx.db.db_path)})
    elif args.command == "summary":
        _print(PlaceService(ctx).summary())
    elif args.command == "import-legacy":
        _print(import_legacy_catalog(ctx, Path(args.path)))
    elif args.command == "import-csv":
        _print(import_csv(ctx, Path(args.path), dry_run=not args.apply))
    elif args.command == "import-corridor":
        _print(import_corridor(ctx, Path(args.path)))
    elif args.command == "enqueue":
        _print({"job_id": jobs.enqueue(args.job_type, json.loads(args.payload), priority=args.priority)})
    elif args.command == "run-jobs":
        _print({"ran": jobs.run_pending(args.max)})
    elif args.command == "run":
        job_id = jobs.enqueue(args.job_type, json.loads(args.payload))
        _print(jobs.run_one(job_id))
    elif args.command == "jobs":
        _print(jobs.list_jobs(args.status))
    elif args.command == "export":
        _print({"path": str(ExportService(ctx).write_export(args.format, args.interest, args.include_seeds))})
    elif args.command == "backup":
        _print({"path": str(BackupService(ctx).backup(args.label))})
    elif args.command == "backups":
        _print(BackupService(ctx).list_backups())
    elif args.command == "restore":
        _print({"pre_restore_backup": str(BackupService(ctx).restore(args.name))})
    return 0


if __name__ == "__main__":
    sys.exit(main())
