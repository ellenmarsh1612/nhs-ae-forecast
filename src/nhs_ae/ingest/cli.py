"""Command-line ingestion.

Examples
--------
Fetch every year page, archive today's vintage, and rebuild the tidy parquet::

    nhs-ae-ingest run

Only the two most recent financial years (what the monthly GitHub Action does)::

    nhs-ae-ingest run --years 2025-26 2026-27

Rebuild parquet from the archive without touching the network::

    nhs-ae-ingest build

Show what a page would yield without downloading::

    nhs-ae-ingest discover --years 2026-27

Recover historical vintages from the Internet Archive's captures of the year pages
(idempotent; cached under data/cache/wayback)::

    nhs-ae-ingest recover --years 2019-20 2020-21

Which forecast origins lack an as-of version of some period (Appendix A)::

    nhs-ae-ingest coverage --origins 2019-09 2025-09
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

import pandas as pd

from nhs_ae.config import FINANCIAL_YEARS, MANIFEST_PATH, PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.ingest import discover as _discover
from nhs_ae.ingest.download import download_refs, read_manifest
from nhs_ae.ingest.parse import parse_manifest_records, validate_long
from nhs_ae.ingest.recover import Wayback, coverage, month_range, recover, second_thursday

log = logging.getLogger("nhs_ae.ingest")


def cmd_discover(args: argparse.Namespace) -> int:
    refs = _discover.discover(args.years, prefer_ext=args.prefer)
    for r in refs:
        flag = f" revised {r.revised_on}" if r.revised else ""
        print(f"{r.period_label}  {r.ext:4s}  {r.filename}{flag}")
    print(f"\n{len(refs)} files", file=sys.stderr)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    refs = _discover.discover(args.years, prefer_ext=args.prefer)
    snapshot = date.fromisoformat(args.snapshot) if args.snapshot else date.today()
    written = download_refs(refs, snapshot=snapshot)
    stored = sum(1 for w in written if w.get("stored"))
    log.info("snapshot %s: %d fetched, %d new/changed files stored", snapshot, len(written), stored)
    return cmd_build(args)


def missing_readers(manifest: list[dict]) -> list[str]:
    """Excel readers the archive needs but this environment lacks. Without them the build drops
    every workbook-only vintage and still exits 0 (it did on 2026-09-12, losing 358,581 rows)."""
    import importlib.util
    exts = {str(r.get("ext", "")).lower() for r in manifest if r.get("stored", True)}
    need = {"xls": "xlrd", "xlsx": "openpyxl"}
    return [mod for ext, mod in need.items() if ext in exts and importlib.util.find_spec(mod) is None]


def dedupe_vintages(long: pd.DataFrame) -> pd.DataFrame:
    """A vintage often exists as both CSV and XLS. Keep one: CSV first, then XLSX, then XLS.
    Shared by ``cmd_build`` and the Stage H rebuild (P4), so both parse to the same table."""
    rank = long["source_file"].str.lower().str.extract(r"\.(csv|xlsx|xls)$")[0].map(
        {"csv": 0, "xlsx": 1, "xls": 2}).fillna(3)
    return (long.assign(_rank=rank).sort_values("_rank", kind="stable")
                .drop_duplicates(["period", "org_code", "metric", "snapshot"], keep="first")
                .drop(columns="_rank").sort_values(["snapshot", "period", "org_code"])
                .reset_index(drop=True))


def cmd_build(args: argparse.Namespace) -> int:
    manifest = read_manifest(MANIFEST_PATH)
    if not manifest:
        log.error("No manifest at %s – run `nhs-ae-ingest run` first", MANIFEST_PATH)
        return 1
    missing = missing_readers(manifest)
    if missing:
        log.error("%s not installed but the archive holds workbooks: refusing to rebuild the parquet "
                  "(install the xls extra: pip install -e '.[xls]')", ", ".join(missing))
        return 1
    long, failures = parse_manifest_records(manifest, PROJECT_ROOT)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    failures.to_csv(PROCESSED_DIR / "parse_failures.csv", index=False)
    if len(failures):
        log.warning("%d archived files could not be parsed; listed in %s",
                    len(failures), PROCESSED_DIR / "parse_failures.csv")
    if long.empty:
        log.error("Nothing parsed")
        return 1
    before = len(long)
    long = dedupe_vintages(long)
    if before != len(long):
        log.info("dropped %d rows duplicated across CSV/XLS copies of the same vintage",
                 before - len(long))
    problems = validate_long(long)
    for p in problems:
        log.warning("validation: %s", p)

    out_dir = PROCESSED_DIR / "vintages"
    out_dir.mkdir(parents=True, exist_ok=True)
    for snap, part in long.groupby("snapshot"):
        part.to_parquet(out_dir / f"{snap}.parquet", index=False)
    long.to_parquet(PROCESSED_DIR / "ae_monthly_all_vintages.parquet", index=False)

    # "latest" view: for each (period, org, metric) take the most recent snapshot.
    latest = (long.sort_values("snapshot")
                  .drop_duplicates(["period", "org_code", "metric"], keep="last"))
    latest.to_parquet(PROCESSED_DIR / "ae_monthly_latest.parquet", index=False)
    log.info("wrote %d rows across %d vintages; latest view %d rows",
             len(long), long["snapshot"].nunique(), len(latest))
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    wb = Wayback(delay=args.delay)
    summary = recover(args.years, wayback=wb, file_history=not args.no_file_history,
                      redo=args.redo)
    log.info("recover: %s", summary)
    if args.build:
        return cmd_build(args)
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    manifest = read_manifest(MANIFEST_PATH)
    if not manifest:
        log.error("No manifest at %s", MANIFEST_PATH)
        return 1
    start, end = (date.fromisoformat(o + "-01") for o in args.origins)
    # each origin at the loader's as-of date, its second Thursday (evaluate.asof.as_of_date): dated to
    # the 1st, this listed the wrong origins in Appendix A (P10)
    rows = coverage(manifest, [second_thursday(o.year, o.month) for o in month_range(start, end)])
    df = pd.DataFrame(rows)
    out = PROCESSED_DIR / "vintage_coverage.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.assign(missing=df["missing"].map(" ".join)).to_csv(out, index=False)
    for r in rows:
        gap = f"  missing: {' '.join(r['missing'][:8])}{' …' if len(r['missing']) > 8 else ''}" \
            if r["missing"] else ""
        print(f"{r['origin']}  {r['periods_expected']:3d} periods published, "
              f"{r['periods_missing']:3d} without an as-of version{gap}")
    clean = sum(1 for r in rows if not r["periods_missing"])
    print(f"\n{clean}/{len(rows)} origins fully covered; table written to {out}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nhs-ae-ingest", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--years", nargs="+", default=list(FINANCIAL_YEARS),
                        help="financial years, e.g. 2025-26 2026-27")
    common.add_argument("--prefer", default="csv", choices=["csv", "xls", "xlsx"])

    p = sub.add_parser("discover", parents=[common], help="list monthly file links")
    p.set_defaults(func=cmd_discover)
    p = sub.add_parser("run", parents=[common], help="download a vintage and rebuild parquet")
    p.add_argument("--snapshot", help="override snapshot date (YYYY-MM-DD); default today")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("build", help="rebuild parquet from the archive (no network)")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("recover", parents=[common],
                       help="recover historical vintages via the Internet Archive")
    p.add_argument("--no-file-history", action="store_true",
                   help="skip per-file CDX lookups (misses in-place replacements; faster)")
    p.add_argument("--redo", action="store_true", help="re-process URLs already in the manifest")
    p.add_argument("--delay", type=float, default=0.5, help="seconds between Wayback calls")
    p.add_argument("--build", action="store_true", help="rebuild parquet afterwards")
    p.set_defaults(func=cmd_recover)
    p = sub.add_parser("coverage", help="per-origin list of periods lacking an as-of version")
    p.add_argument("--origins", nargs=2, default=["2019-09", "2025-09"], metavar="YYYY-MM",
                   help="first and last monthly origin")
    p.set_defaults(func=cmd_coverage)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    pd.set_option("display.width", 200)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
