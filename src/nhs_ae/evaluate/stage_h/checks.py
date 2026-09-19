"""Stage H step 2 and the pre-tag commands: pins, the P4 rebuild, pre-run checks, preflight
(design §3). Reads git state and files; never touches outturns beyond hashing the vintage
table and its as-of slices.

CONTRACT (skeleton; the implementation must keep these signatures):

git(*args, cwd=None) -> str          stdout of a git command in cwd, default PROJECT_ROOT
    (raises on failure).

rebuild_vintages(out_dir, manifest_path=None, raw_root=None) -> dict
    P4: read the manifest (default PROJECT_ROOT's data/raw/manifest.jsonl), verify every stored
    file's bytes (under raw_root, default PROJECT_ROOT) against its manifest sha256, refuse if
    ingest.cli.missing_readers(manifest), parse with parse_manifest_records, apply the shared
    de-duplication (ingest.cli.dedupe_vintages, refactored out of cmd_build), and write
    out_dir/ae_monthly_all_vintages.parquet and out_dir/parse_failures.csv. Returns
    {"path", "row_hash", "failures": [source files], "manifest_sha", "rows"}.

d7_slice_hashes(vintages) -> dict[str, str]
    row_hash of asof.slice_vintages at the as-of dates of 2025-07, 2025-08, 2025-09 (periods
    up to each origin's as-of end month); only the hashes leave the function.
dev_reach_hash(vintages) -> str
    vintage_hash of the rows with period <= last_period(max(DEV)) (2023-11), every snapshot:
    all a DEV-origin slice can read. ``vintages``: a load_vintages table or a path.

prepare_facts(head) -> dict   ``prepare``'s checks 6-8 before it copies or generates anything;
    returns {"commit", "python", "platform"} for prepare.json.
prepare_inputs(sources, jobs, vintages_dir=None) -> dict   ``prepare --dev-side`` in full, the
    one writer of INPUTS/prepare.json (``__main__.cmd_prepare`` only calls it): checks 6-8, the
    13 ``sources`` ({P5 name: file}, ``steps.input_paths()``) checked against P5 and M2's
    SHA-256, the P4 rebuild outside INPUTS, the copies (hashed before, verified after),
    ``generate.dev_side`` on the rebuild, and the record ``make_pins`` reads; returns it.
make_pins(scratch_dir, gen_commit=None) -> dict   everything in design §3.1; refuses if the
    tag exists, or unless INPUTS/prepare.json, which ``prepare --dev-side`` writes as
    {"commit", "dev_side": true, "python", "platform", "sources": {P5 name: sha256} for all
    21, "vintages": {"dev_reach_hash", ...}}, matches: the inputs are P5_INPUTS with their
    P5_ORIGINS sets and recorded hashes (M2's is M2_DEV_SHA), the environment is the one
    prepare ran on, and the rebuild's dev_reach_hash is prepare's. ``gen_commit`` defaults to
    the record's "commit" and must name it.
write_pins(pins, path=None)   (default PROJECT_ROOT/docs/stage_h_pins.json)
read_pins(from_tag: bool) -> dict   (from_tag: git show TAG:docs/...)

start_commit_ok(head, amendment=None) -> tuple[bool, str]
    §3.2.4: HEAD is the tag commit, or (with amendment) a descendant of the tag whose
    docs/preregistration.md has a §10 row titled ``amendment`` that the tag's copy lacks.
hash_commit_ok(head, start) -> tuple[bool, str]
    §4: head's only parent is ``start`` and ``git diff --name-status start head`` lists only
    "A" entries for results/H-confirmatory/{HASH_FILES}.
    Both are ``evaluate.seal_rules``' rules, which ``splits`` applies too (P11), bound here
    to PROJECT_ROOT, as are ``_commit``, ``_tag_commit``, ``_blob``, ``_descends`` and
    ``_rows_titled``.

check_environment(lock, pins, head, row=None) -> dict   check 8; Python or platform drift
    passes only if ``row`` (the --amendment's §10 row) quotes each new value; returns
    {"python", "platform", "env_drift": {name: [pinned, now]}}.
committed_log_problems(root=None) -> list[str]   check 10's committed-record rule (every
    witness line in HEAD's log; the working-tree log is HEAD's), for report --from-scores.

pre_run(ctx, token_file, amendment=None) -> dict     run-mode checks 1-14, in order; raises
    RefusedError at the first failure; returns the recorded facts for the README.
preflight() -> dict      every check that does not need the tag, HEAD standing in for it.
dry_checks(ctx) -> dict  checks 6-9, 11, 13 (counts for 10), and the rebuild.

class RefusedError(RuntimeError)

Every git command and repository path, defaults included, resolves against this module's
PROJECT_ROOT when a function is called, so the tests can point the checks at a temporary
repository. Git status and ignore rules disregard the user's global excludes file.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import NoReturn

import pandas as pd
import pyarrow.parquet as pq

from nhs_ae import config
from nhs_ae.config import MANIFEST_PATH, PROJECT_ROOT
from nhs_ae.evaluate import seal_rules
from nhs_ae.evaluate.asof import (
    VINTAGES_PATH,
    as_of_date,
    last_period,
    load_vintages,
    slice_vintages,
)
from nhs_ae.evaluate.stage_h.common import (
    D7_FOLD,
    DEV,
    DRY_ROOT,
    INPUT_START,
    INPUTS,
    M2_DEV_SHA,
    M2_INPUT,
    P5_INPUTS,
    P5_ORIGINS,
    PINS,
    QUARANTINE,
    RESULTS,
    RUN_ROOT,
    TAG,
    Context,
    file_sha,
    row_hash,
)
from nhs_ae.evaluate.stage_h.seal import (
    SealError,
    _is_entry,
    line_count,
    names_run,
    read_token,
    witness_path,
)
from nhs_ae.ingest.cli import dedupe_vintages, missing_readers
from nhs_ae.ingest.download import read_manifest
from nhs_ae.ingest.parse import parse_manifest_records

log = logging.getLogger(__name__)


def _rel(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


# Repository paths relative to the project root; joined to PROJECT_ROOT at call time.
PINS_REL, RESULTS_REL, INPUTS_REL = _rel(PINS), _rel(RESULTS), _rel(INPUTS)
QUARANTINE_REL, RUN_ROOT_REL, DRY_ROOT_REL = _rel(QUARANTINE), _rel(RUN_ROOT), _rel(DRY_ROOT)
MANIFEST_REL, SHARED_VINTAGES_REL = _rel(MANIFEST_PATH), _rel(VINTAGES_PATH)
LOCK_REL = "requirements-lock.txt"
PREREG_REL = "docs/preregistration.md"
REFERENCE_REL = "data/reference"
LOG_REL = "results/unseal_log.jsonl"                # splits.UNSEAL_LOG, one per worktree
QUARANTINE_FILE_REL = f"{QUARANTINE_REL}/backtest/forecasts.parquet"   # the file P13's check reads
PREPARE_RECORD = "prepare.json"     # in INPUTS: prepare --dev-side's commit, environment, hashes
PREPARE_VINTAGES_REL = f"{RUN_ROOT_REL}/prepare_vintages"   # prepare's P4 rebuild, outside INPUTS
DEV_SIDE_INPUTS = frozenset(n for n in P5_INPUTS if n.startswith("dev_side/"))  # dev_side's 8
COPIED_INPUTS = P5_INPUTS - DEV_SIDE_INPUTS         # the 12 pool files and M2, copied by prepare
READ_ONLY = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
FROZEN_PATHS = ("data/raw", REFERENCE_REL, PINS_REL, LOCK_REL)                          # check 5
GEN_PATHS = ("src/nhs_ae/models", "src/nhs_ae/features", "src/nhs_ae/evaluate/harness.py",
             "src/nhs_ae/evaluate/asof.py", "src/nhs_ae/evaluate/metrics.py",
             "src/nhs_ae/ingest/recover.py", "src/nhs_ae/evaluate/splits.py",
             "src/nhs_ae/evaluate/stage_h/common.py", "src/nhs_ae/evaluate/stage_h/generate.py",
             LOCK_REL)   # check 11. splits and common fix the DEV origins; metrics (mase_scale)
                         # and recover (as-of dates, month ranges) are on the harness's path
D7_ORIGINS = (min(D7_FOLD.values()), *sorted(D7_FOLD))   # 2025-07 and the two origins it duplicates
DEV_REACH = last_period(max(DEV))       # 2023-11: the last period a DEV-origin slice reads
VINTAGE_KEY = ("snapshot", "period", "org_code", "metric", "source_file")
FORECAST_COLS = ("origin", "model", "level", "target", "series", "horizon", "period", "quantile",
                 "value")                                   # every P5 input carries these
OUTTURN_COLS = ("y", "y_first", "resolved", "wis", "abs_err", "mase", "cov50", "cov90", "pit")
NO_EXCLUDES = ("-c", "core.excludesFile=/dev/null")    # the repository's ignore rules only
ROW_HASH_RULE = ("common.row_hash: SHA-256 of pd.util.hash_pandas_object over every column in "
                 "sorted name order; vintage rows sorted by snapshot, period, org_code, metric, "
                 "source_file; forecast rows by every column; dev_reach_hash: the vintage rule "
                 f"over the asof.load_vintages rows with period <= {DEV_REACH:%Y-%m}")
LOAD_WARN = 2.0
_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")


class RefusedError(RuntimeError):
    """A Stage H check failed; the command must not go on."""


def _refuse(check: int | str, msg: str) -> NoReturn:
    raise RefusedError(f"check {check}: {msg}")


# ---- git ---------------------------------------------------------------------------------
def _root() -> Path:
    return Path(PROJECT_ROOT)


def git(*args: str, cwd: Path | str | None = None) -> str:
    """Stripped stdout of ``git args`` run in ``cwd`` (default: PROJECT_ROOT, looked up at
    call time); raises CalledProcessError on failure."""
    return subprocess.run(["git", *args], cwd=_root() if cwd is None else cwd,
                          capture_output=True, text=True, check=True).stdout.strip()


def _rc(*args: str) -> int:
    return subprocess.run(["git", *args], cwd=_root(), capture_output=True, check=False).returncode


# The git helpers, §10 rows and HEAD rules live in ``seal_rules`` (P11), which ``splits``
# shares; these wrappers bind PROJECT_ROOT at call time.
def _commit(rev: str | None) -> str | None:
    """Full SHA of the commit ``rev`` names, or None."""
    return seal_rules.commit(_root(), rev)


def _tag_commit() -> str | None:
    return _commit(f"refs/tags/{TAG}")


def _blob(ref: str, rel: str, root: Path | None = None) -> bytes | None:
    """The bytes of ``rel`` in commit ``ref`` of the repository at ``root`` (default:
    PROJECT_ROOT), or None if it is not there."""
    return seal_rules.blob(_root() if root is None else root, ref, rel)


def _descends(rev: str | None, ancestor: str) -> bool:
    """``rev`` is a commit after ``ancestor`` on its line (not ``ancestor`` itself)."""
    return seal_rules.descends(_root(), rev, ancestor)


def _rows_titled(ref: str, title: str) -> list[str]:
    """The §10 rows titled ``title`` in commit ``ref``'s preregistration."""
    return seal_rules.rows_titled(_root(), ref, title)


# ---- HEAD rules --------------------------------------------------------------------------
def start_commit_ok(head: str, amendment: str | None = None) -> tuple[bool, str]:
    """§3.2.4: ``head`` is the tag commit or, with ``amendment``, a descendant of it whose
    preregistration has exactly one §10 row titled ``amendment``, a row the tag lacks."""
    return seal_rules.start_commit_ok(_root(), head, amendment)


def hash_commit_ok(head: str, start: str) -> tuple[bool, str]:
    """§4: ``head`` is the runner's hash commit H1: its only parent is ``start``, and its
    diff from ``start`` adds results/H-confirmatory/{HASH_FILES} and does nothing else."""
    return seal_rules.hash_commit_ok(_root(), head, start)


# ---- P4 rebuild and hashes ---------------------------------------------------------------
def vintage_hash(frame: pd.DataFrame) -> str:
    """Canonical row hash of a vintage table or an as-of slice (design §3.1)."""
    return row_hash(frame, [c for c in VINTAGE_KEY if c in frame.columns])


def _stored_mismatches(manifest: list[dict], raw_root: Path) -> list[str]:
    """Stored manifest records whose file is missing or differs from its SHA-256."""
    bad = []
    for rec in manifest:
        if rec.get("stored"):
            p = raw_root / rec["path"]
            if not p.is_file() or file_sha(p) != rec.get("sha256"):
                bad.append(rec["path"])
    return bad


def rebuild_vintages(out_dir, manifest_path=None, raw_root=None) -> dict:
    """P4: the vintage table rebuilt from the archive into ``out_dir``, and nowhere else. The
    manifest and the stored files default to PROJECT_ROOT's, looked up at call time. The row
    hash is taken from the written file read back, as it is for the shared table."""
    root = _root()
    out_dir = Path(out_dir)
    manifest_path = Path(root / MANIFEST_REL if manifest_path is None else manifest_path)
    raw_root = Path(root if raw_root is None else raw_root)
    manifest = read_manifest(manifest_path)
    if not manifest:
        raise RefusedError(f"P4: no manifest at {manifest_path}")
    bad = _stored_mismatches(manifest, raw_root)
    if bad:
        raise RefusedError(f"P4: {len(bad)} stored files do not match their manifest SHA-256: "
                           f"{bad[:5]}")
    missing = missing_readers(manifest)
    if missing:
        raise RefusedError(f"P4: {', '.join(missing)} not installed but the archive holds "
                           "workbooks")
    long, failures = parse_manifest_records(manifest, raw_root)
    if long.empty:
        raise RefusedError("P4: nothing parsed")
    long = dedupe_vintages(long)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "ae_monthly_all_vintages.parquet"
    long.to_parquet(path, index=False)
    failures.to_csv(out_dir / "parse_failures.csv", index=False)
    rows = len(long)
    del long
    out = {"path": path, "row_hash": vintage_hash(pd.read_parquet(path)), "rows": rows,
           "failures": sorted(failures["path"].astype(str)),
           "manifest_sha": file_sha(manifest_path)}
    log.info("P4 rebuild: %d rows from %d stored files, %d parse failures", rows,
             sum(bool(r.get("stored")) for r in manifest), len(out["failures"]))
    return out


def d7_slice_hashes(vintages: pd.DataFrame) -> dict[str, str]:
    """Row hash of the as-of slice at each D7 origin, periods up to the origin's as-of end
    month (design §3.2.14). ``vintages`` is an ``asof.load_vintages`` table. Only the hashes
    leave the function."""
    v = vintages.assign(period=pd.to_datetime(vintages["period"]),
                        snapshot=pd.to_datetime(vintages["snapshot"]))
    out = {}
    for o in D7_ORIGINS:
        s = slice_vintages(v, as_of_date(o), last_period(o))
        end = s.loc[~s["is_total"].astype(bool), "period"].max()
        out[f"{o:%Y-%m}"] = vintage_hash(s[s["period"] <= end] if pd.notna(end) else s)
    return out


def dev_reach_hash(vintages) -> str:
    """Row hash (``vintage_hash``) of every vintage row an as-of or final slice at a DEV origin
    can read: periods up to ``DEV_REACH``, at every snapshot. ``prepare --dev-side`` records it
    for the table it generated on, and ``pin`` refuses a rebuild whose hash differs (design §8).
    ``vintages``: an ``asof.load_vintages`` table, or the path of a vintage table, loaded with
    it. The raw table (it carries ``source_file``) is refused, since its hash would differ."""
    v = vintages if isinstance(vintages, pd.DataFrame) else load_vintages(vintages)
    if "source_file" in v.columns:
        raise ValueError("dev_reach_hash takes an asof.load_vintages table or a path, not the "
                         "raw vintage table")
    return vintage_hash(v[pd.to_datetime(v["period"]) <= DEV_REACH])


def _reference_hashes() -> dict[str, str]:
    root = _root()
    return {p.relative_to(root).as_posix(): file_sha(p)
            for p in sorted((root / REFERENCE_REL).rglob("*")) if p.is_file()}


def _input_pin(inputs: Path, name: str, where: str) -> dict:
    """SHA-256, canonical row hash, rows, origin set, model, level and mode of the P5 input
    ``inputs/name``. Refused (``where`` names the command or check) unless it is a forecast
    file, with no outturn or score column, whose origins all lie in INPUT_START..max(DEV) (P5).
    Schema and origins are checked before the rows are read."""
    path = inputs / name
    cols = set(pq.read_schema(path).names)
    lacking, outturn = sorted(set(FORECAST_COLS) - cols), sorted(cols & set(OUTTURN_COLS))
    if lacking or outturn:
        raise RefusedError(f"{where}: input {name} is not a forecast file (lacks {lacking}, "
                           f"carries {outturn})")
    origin = pd.read_parquet(path, columns=["origin"])["origin"]
    if origin.empty:
        raise RefusedError(f"{where}: input {name} holds no rows")
    months = pd.PeriodIndex(pd.to_datetime(origin.unique()), freq="M")
    lo, hi = pd.Period(INPUT_START, "M"), pd.Period(max(DEV), "M")
    outside = months[~((months >= lo) & (months <= hi))]       # NaT counts as outside
    if len(outside):
        raise RefusedError(f"{where}: input {name} has {len(outside)} origins outside "
                           f"{lo}..{hi} (P5: DEV forecasts only)")
    f = pd.read_parquet(path)
    origins = sorted({f"{pd.Timestamp(o):%Y-%m-%d}" for o in f["origin"].unique()})
    labels = {c: sorted(map(str, f[c].unique())) if c in f else []
              for c in ("model", "level", "mode")}
    return {"sha256": file_sha(path), "row_hash": row_hash(f), "rows": len(f), "origins": origins,
            **labels}


# ---- the permitted inputs (P5, design §8) ------------------------------------------------
def _p5_name_problem(names) -> str | None:
    """How the input names differ from design §8's ``P5_INPUTS``, or None."""
    missing, extra = sorted(P5_INPUTS - set(names)), sorted(set(names) - P5_INPUTS)
    if not missing and not extra:
        return None
    return (f"the inputs are not the {len(P5_INPUTS)} permitted files of design §8: missing "
            f"{missing[:8]}, unexpected {extra[:5]}; run prepare --dev-side (without it the DEV "
            "sides of H1, H4 and H2's M1 clause are lost)")


def _p5_problems(input_pins: dict) -> list[str]:
    """Pinned inputs that break design §8: an origin set other than ``P5_ORIGINS``' (the pool
    at 2017-07..2023-12; M2 and as-of B0 and M1 at the 69 DEV origins; the final-mode files
    and the seeded B1 at the DEV winter-h3 origins), or an M2 file other than E-m2-rerun69's."""
    out = []
    for name, pin in sorted(input_pins.items()):
        want = [f"{o:%Y-%m-%d}" for o in sorted(P5_ORIGINS.get(name, ()))]
        got = list(pin.get("origins") or [])
        if got != want:
            lack, extra = sorted(set(want) - set(got)), sorted(set(got) - set(want))
            out.append(f"input {name} holds {len(got)} origins, not its {len(want)} (lacking "
                       f"{lack[:3]}, beyond them {extra[:3]})")
    sha = (input_pins.get(M2_INPUT) or {}).get("sha256")
    if sha != M2_DEV_SHA:
        out.append(f"input {M2_INPUT} is not E-m2-rerun69's file (SHA-256 {str(sha)[:12]}, not "
                   f"{M2_DEV_SHA[:12]})")
    return out


def _prepare_record(inputs: Path) -> dict:
    """INPUTS/prepare.json, refused unless it records a ``prepare --dev-side``."""
    path = inputs / PREPARE_RECORD
    if not path.is_file():
        raise RefusedError(f"pin: no {path}; run prepare --dev-side")
    try:
        record = json.loads(path.read_text())
    except ValueError:
        record = None
    if not isinstance(record, dict):
        raise RefusedError(f"pin: {path} is not a JSON object")
    if record.get("dev_side") is not True:
        raise RefusedError(f"pin: {path} records dev_side {record.get('dev_side')!r}: the inputs "
                           "were prepared without --dev-side (design §8); run prepare --dev-side")
    return record


def _source_problems(input_pins: dict, record: dict) -> list[str]:
    """Inputs whose SHA-256 is not the one ``prepare`` recorded (prepare.json "sources")."""
    sources = record.get("sources")
    if not isinstance(sources, dict):
        return [f"{PREPARE_RECORD} records no input hashes; re-run prepare --dev-side"]
    bad = sorted(n for n, pin in input_pins.items() if sources.get(n) != pin["sha256"])
    return [f"{len(bad)} inputs differ from the SHA-256 prepare recorded: {bad[:5]}"] if bad else []


def _env() -> dict[str, str]:
    """This process's Python version and platform string (design §3.1)."""
    return {"python": platform.python_version(), "platform": platform.platform()}


# ---- prepare --dev-side (design §8): the writer of what pin reads ------------------------
def prepare_inputs(sources: dict, jobs: int, vintages_dir=None) -> dict:
    """``prepare --dev-side``, and the one writer of the record ``make_pins`` reads.

    Refused before anything is written: once the tag exists; unless INPUTS is absent or empty;
    unless ``sources`` ({P5 name: file}, ``steps.input_paths()``) names exactly the 13 pool
    and M2 inputs; unless checks 6-8 pass (``prepare_facts``); and unless each source is a DEV
    forecast file at its ``P5_ORIGINS`` set, M2's being E-m2-rerun69's (``_p5_problems``).
    Then rebuilds the vintage table into ``vintages_dir`` (default RUN_ROOT/prepare_vintages,
    which must lie outside INPUTS: pin refuses any other file there), copies each source
    read-only and checks the copy against the SHA-256 taken before, and runs
    ``generate.dev_side`` on the rebuild into INPUTS/dev_side. Refused unless that leaves
    exactly ``P5_INPUTS``, each at its origin set, with the table, HEAD and the tree as they
    were. Only then writes SHA256SUMS and prepare.json: {"commit", "dev_side": true, "python",
    "platform", "sources": {name: sha256} for all 21, "vintages": {"row_hash", "rows",
    "manifest_sha", "dev_reach_hash"}, "created"}. Returns the record."""
    from nhs_ae.evaluate.stage_h import generate  # the models; only prepare needs them here
    root = _root()
    inputs = root / INPUTS_REL
    vdir = Path(root / PREPARE_VINTAGES_REL if vintages_dir is None else vintages_dir)
    if _tag_commit() is not None:
        raise RefusedError(f"prepare: {TAG} exists; inputs are prepared before the tag")
    if inputs.exists() and any(inputs.iterdir()):
        raise RefusedError(f"prepare: {inputs} is not empty: move it aside first (a refused or "
                           f"interrupted prepare leaves it without {PREPARE_RECORD})")
    if vdir.resolve().is_relative_to(inputs.resolve()):
        raise RefusedError(f"prepare: the vintage rebuild {vdir} would lie inside {inputs}")
    sources = {str(n): Path(p) for n, p in sources.items()}
    if set(sources) != COPIED_INPUTS:
        raise RefusedError(f"prepare: the sources are not design §8's {len(COPIED_INPUTS)} pool "
                           f"and M2 inputs: missing {sorted(COPIED_INPUTS - set(sources))[:5]}, "
                           f"unexpected {sorted(set(sources) - COPIED_INPUTS)[:5]}")
    facts = prepare_facts(git("rev-parse", "HEAD"))                             # checks 6-8
    pins = {n: _input_pin(src.parent, src.name, "prepare") for n, src in sorted(sources.items())}
    problems = _p5_problems(pins)                                   # origin sets, M2's SHA-256
    if problems:
        raise RefusedError(f"prepare: {'; '.join(problems)}")
    rebuilt = rebuild_vintages(vdir, root / MANIFEST_REL, root)
    vpath = Path(rebuilt["path"])
    vsha, reach = file_sha(vpath), dev_reach_hash(vpath)
    for n, src in sorted(sources.items()):
        dst = inputs / n
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        os.chmod(dst, READ_ONLY)
        if file_sha(dst) != pins[n]["sha256"]:
            raise RefusedError(f"prepare: the copy of {src} differs from the SHA-256 taken "
                               "before copying it")
    generate.dev_side(inputs / "dev_side", jobs, vintages_path=vpath)
    made = {p.relative_to(inputs).as_posix() for p in inputs.rglob("*.parquet")} - set(pins)
    if made != DEV_SIDE_INPUTS:
        raise RefusedError(f"prepare: generate.dev_side left {len(made)} files, not design §8's "
                           f"{len(DEV_SIDE_INPUTS)}: missing {sorted(DEV_SIDE_INPUTS - made)[:5]}, "
                           f"unexpected {sorted(made - DEV_SIDE_INPUTS)[:5]}")
    for n in sorted(made):
        os.chmod(inputs / n, READ_ONLY)
        pins[n] = _input_pin(inputs, n, "prepare")
    problems = _p5_problems(pins)
    if file_sha(vpath) != vsha:
        problems.append(f"the vintage table {vpath} changed while the DEV side was generated")
    head = _commit("HEAD")
    if head != facts["commit"]:
        problems.append(f"HEAD moved from {facts['commit'][:12]} to {str(head)[:12]} while the "
                        "DEV side was generated")
    if problems:
        raise RefusedError(f"prepare: {'; '.join(problems)}")
    try:
        check_clean()
    except RefusedError as e:
        raise RefusedError(f"prepare, after the DEV side: {e}") from e
    record = {**facts, "dev_side": True,
              "sources": {n: pins[n]["sha256"] for n in sorted(pins)},
              "vintages": {"row_hash": rebuilt["row_hash"], "rows": rebuilt["rows"],
                           "manifest_sha": rebuilt["manifest_sha"], "dev_reach_hash": reach},
              "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (inputs / "SHA256SUMS").write_text("".join(f"{s}  {n}\n" for n, s in record["sources"].items()))
    (inputs / PREPARE_RECORD).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    for name in ("SHA256SUMS", PREPARE_RECORD):
        os.chmod(inputs / name, READ_ONLY)
    log.info("prepared %d inputs in %s at %s", len(record["sources"]), inputs, facts["commit"][:12])
    return record


# ---- pins --------------------------------------------------------------------------------
def make_pins(scratch_dir, gen_commit: str | None = None) -> dict:
    """Everything in design §3.1, made before the tag and refused once it exists. Refused too
    unless INPUTS/prepare.json records a ``prepare --dev-side`` run on this Python and platform;
    the inputs are exactly ``P5_INPUTS``, each with its ``P5_ORIGINS`` set and the SHA-256
    prepare recorded, M2's being E-m2-rerun69's; and the rebuilt table's ``dev_reach_hash`` is
    the one prepare recorded, so the DEV side was generated on the rows the run reads. The
    cheap refusals come before the rebuild into ``scratch_dir``. ``gen_commit``, the commit
    that ran ``prepare --dev-side``, defaults to the record's "commit" and must name it."""
    if _tag_commit() is not None:
        raise RefusedError(f"pin: {TAG} exists; pins are made only before the tag")
    root = _root()
    dirty = git(*NO_EXCLUDES, "status", "--porcelain", "--untracked-files=all", "--", "data/raw",
                REFERENCE_REL)
    if dirty:
        raise RefusedError(f"pin: data/raw or data/reference has uncommitted changes:\n{dirty}")
    inputs = root / INPUTS_REL
    record = _prepare_record(inputs)
    recorded = _commit(record.get("commit"))
    if recorded is None:
        raise RefusedError(f"pin: the prepare --dev-side commit {record.get('commit')!r} is not "
                           "a commit")
    gen = recorded if gen_commit is None else _commit(gen_commit)
    if gen != recorded:
        raise RefusedError(f"pin: {gen_commit!r} is not the prepare --dev-side commit "
                           f"{recorded[:12]} that {PREPARE_RECORD} records")
    names = sorted(p.relative_to(inputs).as_posix() for p in inputs.rglob("*.parquet"))
    problem = _p5_name_problem(names)
    if problem:
        raise RefusedError(f"pin: {problem}")
    input_pins = {name: _input_pin(inputs, name, "pin") for name in names}
    problems = _p5_problems(input_pins) + _source_problems(input_pins, record)
    prepared = record.get("vintages")
    prepared_reach = prepared.get("dev_reach_hash") if isinstance(prepared, dict) else None
    if not isinstance(prepared_reach, str):
        problems.append(f"{PREPARE_RECORD} records no dev_reach_hash; re-run prepare --dev-side")
    if problems:
        raise RefusedError(f"pin: {'; '.join(problems)}")
    env = _env()
    drift = [f"{k} is {v}, prepare --dev-side ran on {record.get(k)}"
             for k, v in env.items() if v != record.get(k)]
    if drift:
        raise RefusedError(f"pin: {'; '.join(drift)}; re-run prepare --dev-side here")
    quarantine = root / QUARANTINE_FILE_REL
    if not quarantine.is_file():
        raise RefusedError(f"pin: no quarantined pre-seal forecast file at {quarantine} (P13)")
    rebuilt = rebuild_vintages(scratch_dir, root / MANIFEST_REL, root)
    v = load_vintages(rebuilt["path"])
    reach = dev_reach_hash(v)
    if reach != prepared_reach:
        raise RefusedError(f"pin: the vintage rows a DEV-origin slice reads (periods to "
                           f"{DEV_REACH:%Y-%m}) are not those prepare --dev-side generated on "
                           "(dev_reach_hash differs): re-run prepare --dev-side")
    d7 = d7_slice_hashes(v)
    del v
    if len(set(d7.values())) != 1:
        raise RefusedError(f"pin: the D7 as-of slices {sorted(d7)} differ, so the premise of the "
                           "19 information sets fails; this needs Ellie's decision")
    shared = root / SHARED_VINTAGES_REL
    shared_hash, shared_rows = None, None
    if shared.is_file():
        frame = pd.read_parquet(shared)
        shared_hash, shared_rows = vintage_hash(frame), len(frame)
        del frame
    return {
        "tag": TAG,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "head": _commit("HEAD"),
        "row_hash_rule": ROW_HASH_RULE,
        "manifest_sha": rebuilt["manifest_sha"],
        "vintages": {"row_hash": rebuilt["row_hash"], "rows": rebuilt["rows"],
                     "dev_reach_hash": reach, "shared_row_hash": shared_hash,
                     "shared_rows": shared_rows},
        "parse_failures": rebuilt["failures"],
        "reference": _reference_hashes(),
        "inputs": input_pins,
        "quarantine": {"path": QUARANTINE_FILE_REL, "sha256": file_sha(quarantine)},
        "d7_slices": d7,
        **env,
        "gen_commit": gen,
    }


def write_pins(pins: dict, path=None) -> Path:
    """Write the pins as sorted JSON (default: PROJECT_ROOT's docs/stage_h_pins.json), to be
    committed before the tag; refused after it."""
    if _tag_commit() is not None:
        raise RefusedError(f"pin: {TAG} exists; the pins are frozen at the tag")
    path = Path(_root() / PINS_REL if path is None else path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pins, indent=1, sort_keys=True) + "\n")
    return path


def _pins_at(ref: str) -> dict:
    data = _blob(ref, PINS_REL)
    if data is None:
        raise RefusedError(f"commit {ref[:12]} holds no {PINS_REL}")
    return json.loads(data)


def read_pins(from_tag: bool) -> dict:
    """The pins: the tag's copy (``git show TAG:docs/stage_h_pins.json``) or the working tree's."""
    if from_tag:
        tag = _tag_commit()
        if tag is None:
            raise RefusedError(f"tag {TAG} does not exist")
        return _pins_at(tag)
    path = _root() / PINS_REL
    if not path.is_file():
        raise RefusedError(f"no pins at {path}")
    return json.loads(path.read_text())


# ---- checks 1-14 (design §3.2) -----------------------------------------------------------
def check_outputs(*dirs: Path) -> None:
    """Check 1: no output directory exists."""
    there = [str(d) for d in dirs if Path(d).exists() or Path(d).is_symlink()]
    if there:
        _refuse(1, f"output directory exists: {there}")


def check_tag() -> dict:
    """Check 2: the tag is annotated, and origin holds the same tag object (P9's push)."""
    ref = f"refs/tags/{TAG}"
    r = subprocess.run(["git", "cat-file", "-t", ref], cwd=_root(), capture_output=True,
                       text=True, check=False)
    if r.returncode:
        _refuse(2, f"tag {TAG} does not exist")
    if r.stdout.strip() != "tag":
        _refuse(2, f"{TAG} is a lightweight tag; it must be annotated")
    obj = git("rev-parse", ref)
    try:
        r = subprocess.run(["git", "ls-remote", "origin", ref], cwd=_root(), capture_output=True,
                           text=True, check=False, timeout=120)
    except subprocess.TimeoutExpired:
        _refuse(2, "git ls-remote origin timed out")
    remote = [ln.split("\t")[0] for ln in r.stdout.splitlines() if ln.endswith(f"\t{ref}")]
    if r.returncode or remote != [obj]:
        _refuse(2, f"origin's {ref} is {[x[:12] for x in remote] or 'absent'}, not the local tag "
                   f"object {obj[:12]}: push the tag (P9)")
    return {"tag_object": obj, "tag_commit": _tag_commit()}


def _check_run_paths(ctx: Context, tag: str) -> None:
    """The run context writes where design §2.8 says, under the tag commit."""
    root = _root()
    want = (root / RUN_ROOT_REL / tag, root / RESULTS_REL, root / RUN_ROOT_REL / tag / "vintages")
    got = (Path(ctx.work), Path(ctx.results), Path(ctx.vintages_path).parent)
    if got != want:
        raise RefusedError(f"the run context's paths {[str(p) for p in got]} are not the tag's "
                           f"{[str(p) for p in want]}")


def check_token(token_file, tag_commit: str) -> None:
    """Check 3: the token file's first line is the tag commit, read as step 4 will read it
    (``seal.read_token``): in the parent process only, and refused if the token is in
    ``sys.argv`` or ``os.environ``, which spawn workers inherit (§2.2). The token is not kept."""
    try:
        ok = read_token(token_file) == tag_commit
    except SealError as e:
        _refuse(3, str(e))
    except (OSError, UnicodeDecodeError) as e:
        _refuse(3, f"cannot read the token file ({type(e).__name__})")
    if not ok:
        _refuse(3, f"the token file does not hold the {TAG} commit")


def check_frozen(base: str, head: str = "HEAD") -> None:
    """Check 5: data/raw, data/reference, the pins and the lock are unchanged since ``base``."""
    rc = _rc("diff", "--quiet", base, head, "--", *FROZEN_PATHS)
    if rc:
        changed = git("diff", "--name-only", base, head, "--", *FROZEN_PATHS).splitlines() \
            if rc == 1 else []
        _refuse(5, f"data, pins or lock changed since {TAG}: {changed[:10]}; put crash fixes on "
                   "top of the runner's last commit, never on main")


def check_clean() -> None:
    """Check 6: ``git status --porcelain`` is empty, untracked files included. The user's global
    excludes file is disregarded, so it cannot hide clutter such as .claude/ (§3.2.6)."""
    dirty = git(*NO_EXCLUDES, "status", "--porcelain", "--untracked-files=all").splitlines()
    if dirty:
        _refuse(6, f"the tree is not clean ({len(dirty)} entries): {dirty[:10]}")


def import_problems(toplevel: Path, package_file: Path, project_root: Path) -> list[str]:
    """Check 7's rule: ``nhs_ae`` lies under <toplevel>/src/nhs_ae, and PROJECT_ROOT is the
    toplevel (which fixes the unseal log splits writes to). ``seal_rules.import_problems``."""
    return seal_rules.import_problems(toplevel, package_file, project_root)


def _import_problems() -> list[str]:
    """Check 7 for this process: the toplevel of the working directory the run started in."""
    import nhs_ae
    try:
        top = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))
    except subprocess.CalledProcessError:
        return [f"the working directory {Path.cwd()} is not in a git worktree"]
    return import_problems(top, Path(nhs_ae.__file__), config.PROJECT_ROOT)


def check_import() -> None:
    """Check 7: ``nhs_ae`` imports from this worktree."""
    problems = _import_problems()
    if problems:
        _refuse(7, "; ".join(problems))


def _requirements(text: str) -> list[str]:
    lines = (ln.strip() for ln in text.splitlines())
    return sorted(ln for ln in lines if ln and not ln.startswith(("#", "-e ")))


def freeze_problems(freeze: str, lock: str, head: str) -> list[str]:
    """Check 8's rule: ``pip freeze`` without comment lines and the -e line equals the lock,
    read the same way, and the -e line's commit is ``head``."""
    got, want = _requirements(freeze), _requirements(lock)
    out = []
    if got != want:
        out.append(f"pip freeze differs from the lock: unlocked {sorted(set(got) - set(want))[:5]}"
                   f", not installed {sorted(set(want) - set(got))[:5]}")
    editable = [ln.strip() for ln in freeze.splitlines() if ln.strip().startswith("-e ")]
    commits = [m.group(1) for ln in editable
               for m in [re.search(r"@([0-9a-f]{40})(?:#|$)", ln)] if m]
    if len(editable) != 1 or commits != [head]:
        out.append(f"the -e line's commit is {[c[:12] for c in commits] or 'missing'}, "
                   f"not HEAD {head[:12]}")
    return out


def _pip_freeze() -> str:
    return subprocess.run([sys.executable, "-m", "pip", "freeze"], capture_output=True, text=True,
                          check=True).stdout


def _quotes(row: str | None, value: str) -> bool:
    """``row`` quotes ``value`` verbatim as a whole value, not inside a longer one (a row
    quoting Python 3.13.12 does not quote 3.13.1)."""
    if not row or not value:
        return False
    return re.search(rf"(?<![\w.-]){re.escape(value)}(?![\w-]|\.\w)", row) is not None


def check_environment(lock: bytes | None, pins: dict | None, head: str,
                      row: str | None = None) -> dict:
    """Check 8: the locked environment, installed from HEAD, on the pinned Python and platform
    (not compared when there are no pins yet). A ``pip freeze`` or -e commit mismatch is always
    refused. Python or platform drift is refused unless ``row``, the --amendment's §10 row at
    HEAD, quotes every new value verbatim (design §3.2.8 [default]). Returns the environment and
    ``env_drift``, {name: [pinned, now]} for the drift accepted, for the README."""
    if lock is None:
        _refuse(8, f"no {LOCK_REL} to compare with")
    problems = freeze_problems(_pip_freeze(), lock.decode(), head)
    env = _env()
    drift = {} if pins is None else {k: [pins.get(k), v] for k, v in env.items()
                                     if v != pins.get(k)}
    unquoted = [k for k, (_, now) in drift.items() if not _quotes(row, now)]
    if unquoted:
        problems += [f"{k} is {drift[k][1]}, pinned {drift[k][0]}" for k in unquoted]
        problems.append("Python or platform drift is accepted only under --amendment, with a §10 "
                        "row quoting every new value verbatim (design §3.2.8)")
    if problems:
        _refuse(8, "; ".join(problems))
    return {**env, "env_drift": drift}


def prepare_facts(head: str) -> dict:
    """``prepare``'s checks, run before anything is copied or generated: ``head`` is HEAD, and
    checks 6-8 hold (a clean tree, ``nhs_ae`` imported from this worktree, the locked
    environment installed from HEAD). Returns what prepare.json records and ``pin`` compares:
    {"commit", "python", "platform"}."""
    commit = _commit(head)
    if commit is None or commit != _commit("HEAD"):
        raise RefusedError(f"prepare: {head!r} is not HEAD")
    try:
        check_clean()
        check_import()
        env = check_environment(_blob(commit, LOCK_REL), None, commit)
    except RefusedError as e:
        raise RefusedError(f"prepare: {e}") from e
    return {"commit": commit, "python": env["python"], "platform": env["platform"]}


def check_raw(pins: dict | None) -> dict:
    """Check 9: the manifest, every stored file, the Excel readers and data/reference."""
    root = _root()
    path = root / MANIFEST_REL
    manifest = read_manifest(path)
    if not manifest:
        _refuse(9, f"no manifest at {path}")
    sha = file_sha(path)
    if pins is not None and sha != pins.get("manifest_sha"):
        _refuse(9, "the manifest SHA-256 differs from the pin")
    bad = _stored_mismatches(manifest, root)
    if bad:
        _refuse(9, f"{len(bad)} stored files do not match their manifest SHA-256: {bad[:5]}")
    missing = missing_readers(manifest)
    if missing:
        _refuse(9, f"{', '.join(missing)} not installed but the archive holds workbooks")
    ref = _reference_hashes()
    pinned = None if pins is None else pins.get("reference") or {}
    if pinned is not None and ref != pinned:
        diff = sorted(k for k in ref.keys() | pinned.keys() if ref.get(k) != pinned.get(k))
        _refuse(9, f"data/reference differs from the pins: {diff[:10]}")
    return {"manifest_sha": sha, "stored_files": sum(bool(r.get("stored")) for r in manifest),
            "reference_files": len(ref)}


def _log_bytes(path: Path, what: str) -> bytes:
    """The bytes of a log or witness file; b"" if it is absent, as seal counts it."""
    if not path.exists():
        return b""
    if not path.is_file():
        _refuse(10, f"{what} ({path}) is not a regular file")
    return path.read_bytes()


def _entries(data: bytes, what: str) -> list[dict]:
    """Every line of a log or witness read as seal's accounting reads it (UTF-8, split by
    ``str.splitlines``, each line a JSON object by ``seal._is_entry``). A blank or unparseable
    line is refused here, since the accounting would flag it after the guarded call; so a file
    with no entries is absent or 0 bytes (P8)."""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        _refuse(10, f"{what} is not UTF-8 text")
    bad = [i for i, ln in enumerate(lines, 1) if not _is_entry(ln)]
    if bad:
        _refuse(10, f"line(s) {bad[:10]} of {what} are blank or do not parse as a JSON object")
    return [json.loads(ln) for ln in lines]


def _other_trees() -> list[Path]:
    """Every other non-bare worktree that ``git worktree list --porcelain`` reports."""
    here = Path(git("rev-parse", "--show-toplevel")).resolve()
    out = []
    for block in git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(ln.split(" ", 1) if " " in ln else (ln, "") for ln in block.splitlines())
        path = fields.get("worktree")
        if path and "bare" not in fields and Path(path).resolve() != here:
            out.append(Path(path))
    return out


def _other_logs() -> dict[str, int]:
    """Line count of the unseal log in every other worktree (``seal.line_count``: absent 0)."""
    return {str(t): line_count(t / LOG_REL) for t in _other_trees()}


def _prior_line_problem(entry: dict, tag: str | None, row: str | None) -> str | None:
    if tag is None or entry.get("token") != tag:
        return "its token is not the tag commit"
    if not names_run(entry.get("argv")):
        return "its argv is not a stage_h run"
    head = entry.get("head")
    if not (isinstance(head, str) and _SHA.fullmatch(head) and _descends(head, tag)):
        return "its head does not descend from the tag"
    if not seal_rules.quotes_timestamp(row, entry.get("timestamp")):     # the post-run rule too
        return "its timestamp is not quoted in the amendment's §10 row"
    return None


def committed_log_problems(root: Path | None = None) -> list[str]:
    """Check 10's rule that every unseal record is committed, shared with ``report
    --from-scores`` (design §9, case 3), for the repository at ``root`` (default:
    PROJECT_ROOT): every witness line is in HEAD's committed log, and the working-tree log is
    HEAD's copy. Returns the problems, none if both hold. A line of this worktree's log, the
    witness or HEAD's log that does not parse is refused, as check 10 refuses it."""
    root = _root() if root is None else Path(root)
    text = _log_bytes(root / LOG_REL, "this worktree's log")
    committed = _blob("HEAD", LOG_REL, root) or b""
    _entries(text, "this worktree's log")
    witness = _entries(_log_bytes(witness_path(root), "the witness"), "the witness")
    at_head = _entries(committed, "HEAD's log")
    out = []
    missing = [w.get("timestamp") for w in witness if w not in at_head]
    if missing:
        out.append(f"{len(missing)} witness lines (timestamps {missing}) are missing from HEAD's "
                   "committed log: an unseal record was reverted or left off this branch")
    if text != committed:
        out.append(f"the working-tree {LOG_REL} differs from HEAD's copy")
    return out


def check_logs(tag_commit: str | None, amendment: str | None = None,
               row: str | None = None) -> dict:
    """Check 10: the unseal logs and the witness, held at least as strictly as the accounting
    after the guarded call (``seal.Accounting``): every line of this worktree's log, HEAD's
    log and the witness is a JSON object. Every witness line is in HEAD's committed log, the
    working-tree log is HEAD's copy (``committed_log_problems``), and every other worktree's
    log is absent or 0 bytes. Without ``amendment`` this worktree's log and the witness are
    absent or 0 bytes; with it the log may hold k prior lines, each with the tag commit as
    token, a ``stage_h run`` argv, a head after the tag, and its timestamp quoted in ``row``
    (the amendment's §10 row)."""
    root = _root()
    problems = committed_log_problems(root)
    if problems:
        _refuse(10, "; ".join(problems))
    lines = _entries(_log_bytes(root / LOG_REL, "this worktree's log"), "this worktree's log")
    witness = _entries(_log_bytes(witness_path(root), "the witness"), "the witness")
    others = [str(t / LOG_REL) for t in _other_trees()
              if _log_bytes(t / LOG_REL, f"the unseal log in {t}")]
    if others:
        _refuse(10, f"other worktrees' unseal logs are neither absent nor 0 bytes: {others}")
    if amendment is None:
        if lines or witness:
            _refuse(10, f"this worktree's log holds {len(lines)} lines and the witness "
                        f"{len(witness)}; a rerun needs --amendment and a §10 row")
    else:
        for entry in lines:
            problem = _prior_line_problem(entry, tag_commit, row)
            if problem:
                _refuse(10, f"prior unseal line {entry.get('timestamp')}: {problem}")
    return {"n0": len(lines), "prior_lines": lines, "witness_lines": len(witness)}


def log_counts() -> dict:
    """Check 10 in the dry run: line counts only, as ``seal.line_count`` counts them."""
    root = _root()
    return {"log_lines": line_count(root / LOG_REL),
            "witness_lines": line_count(witness_path(root)), "other_logs": _other_logs()}


def check_inputs(pins: dict, code_ref: str) -> dict:
    """Check 11: the pinned inputs are design §8's (``P5_INPUTS``, each pinned with its
    ``P5_ORIGINS`` set, M2's the E-m2-rerun69 file); the files on disk are exactly those, each
    a DEV forecast file matching its pinned SHA-256, row hash and origin set; and the
    generation code is unchanged from the ``prepare --dev-side`` commit to ``code_ref``."""
    inputs = _root() / INPUTS_REL
    pinned = pins.get("inputs") or {}
    problem = _p5_name_problem(pinned)
    if problem:
        _refuse(11, f"the pins: {problem}")
    found = {p.relative_to(inputs).as_posix() for p in inputs.rglob("*.parquet")} \
        if inputs.is_dir() else set()
    if found != set(pinned):
        _refuse(11, f"the inputs are not the pinned set: unpinned {sorted(found - set(pinned))[:5]}"
                    f", missing {sorted(set(pinned) - found)[:5]}")
    problems = _p5_problems(pinned)
    if problems:
        _refuse(11, f"the pins: {'; '.join(problems)}")
    for name, pin in sorted(pinned.items()):
        got = _input_pin(inputs, name, "check 11")
        bad = [k for k in ("sha256", "row_hash", "origins") if got[k] != pin.get(k)]
        if bad:
            _refuse(11, f"input {name} differs from its pin in {bad}")
    gen = pins.get("gen_commit")
    if not gen or _rc("diff", "--quiet", gen, code_ref, "--", *GEN_PATHS):
        _refuse(11, f"the generation code changed between the prepare --dev-side commit "
                    f"{str(gen)[:12]} and {code_ref[:12]}")
    return {"inputs": len(pinned), "gen_commit": gen}


def _ignored(rel: str) -> bool:
    """Whether the repository's ignore rules (not the user's global excludes, as in check 6)
    ignore ``rel`` or a directory or symlink above it."""
    parts = PurePosixPath(rel).parts
    for i in range(1, len(parts) + 1):
        rc = _rc(*NO_EXCLUDES, "check-ignore", "-q", "--", "/".join(parts[:i]))
        if rc == 0:
            return True
        if rc != 1:         # e.g. beyond a symbolic link that is itself not ignored
            return False
    return False


def check_quarantine(pins: dict) -> dict:
    """Check 12 (P13): the pre-seal forecast file lies at its pinned path in the quarantine,
    matches its hash, is ignored by git, and nothing under the quarantine is tracked."""
    q = pins.get("quarantine") or {}
    rel = str(q.get("path", ""))
    inside = rel == QUARANTINE_REL or rel.startswith(QUARANTINE_REL + "/")
    if not inside or ".." in PurePosixPath(rel).parts:
        _refuse(12, f"the pinned quarantine file {rel!r} is not under {QUARANTINE_REL}")
    path = _root() / rel
    if not path.is_file() or file_sha(path) != q.get("sha256"):
        _refuse(12, f"{rel} is missing or differs from its pinned SHA-256")
    if not _ignored(rel):
        _refuse(12, f"git does not ignore {rel}")
    tracked = git("ls-files", "--", QUARANTINE_REL).splitlines()
    if tracked:
        _refuse(12, f"git tracks files under {QUARANTINE_REL}: {tracked[:5]}")
    return {"quarantine": rel, "quarantine_sha": q.get("sha256")}


def check_load() -> dict:
    """Check 13: the load average, recorded, with a warning above 2. It never refuses."""
    load = [round(x, 2) for x in os.getloadavg()]
    if load[0] > LOAD_WARN:
        log.warning("load average %.2f is above %.0f: other work would contend with the run",
                    load[0], LOAD_WARN)
    return {"loadavg": load}


def check_rebuild(out_dir: Path, pins: dict | None, d7: bool = True) -> dict:
    """Check 14 (P4): rebuild into ``out_dir``. The row hash and the parse failures must equal
    the pins and, with ``d7``, the D7 slice hashes must equal each other and the pins."""
    root = _root()
    try:
        res = rebuild_vintages(out_dir, root / MANIFEST_REL, root)
    except RefusedError as e:
        raise RefusedError(f"check 14: {e}") from e
    facts = {"vintages": {**res, "path": str(res["path"])}}
    if pins is not None:
        if res["row_hash"] != (pins.get("vintages") or {}).get("row_hash"):
            _refuse(14, "the rebuilt vintage table's row hash differs from the pin")
        if res["failures"] != sorted(pins.get("parse_failures") or []):
            _refuse(14, f"the parse failures differ from the pins: {res['failures'][:5]}")
    if d7:
        hashes = d7_slice_hashes(load_vintages(res["path"]))
        if len(set(hashes.values())) != 1:
            _refuse(14, f"the D7 as-of slices {sorted(hashes)} differ: the premise of the 19 "
                        "information sets fails")
        if pins is not None and hashes != pins.get("d7_slices"):
            _refuse(14, "the D7 slice hashes differ from the pins")
        facts["d7_slices"] = hashes
    return facts


# ---- commands ----------------------------------------------------------------------------
def pre_run(ctx: Context, token_file, amendment: str | None = None) -> dict:
    """Run-mode step 2: checks 1-14 in design order, refusing at the first failure. Pins and
    lock come from the tag. Returns the facts the README records."""
    if ctx.mode != "run":
        raise ValueError("pre_run is for run mode; the dry run uses dry_checks")
    check_outputs(ctx.work, ctx.results)                                            # 1
    facts = check_tag()                                                             # 2
    tag = facts["tag_commit"]
    _check_run_paths(ctx, tag)
    check_token(token_file, tag)                                                    # 3
    head = _commit("HEAD")
    ok, why = start_commit_ok(head, amendment)                                      # 4
    if not ok:
        _refuse(4, why)
    row = _rows_titled(head, amendment)[0] if amendment else None     # checks 8 and 10
    facts.update(head=head, amendment=amendment,
                 log_oneline=git("log", "--oneline", f"{tag}..{head}"),
                 diff_stat=git("diff", "--stat", f"{tag}..{head}"))
    print(f"git log --oneline {TAG}..HEAD:\n{facts['log_oneline'] or '(none)'}\n"
          f"git diff --stat {TAG}..HEAD:\n{facts['diff_stat'] or '(none)'}")
    check_frozen(tag, head)                                                         # 5
    check_clean()                                                                   # 6
    check_import()                                                                  # 7
    pins = _pins_at(tag)
    facts.update(check_environment(_blob(tag, LOCK_REL), pins, head, row))          # 8
    facts.update(check_raw(pins))                                                   # 9
    facts.update(check_logs(tag, amendment, row))                                   # 10
    facts.update(check_inputs(pins, tag))                                           # 11
    facts.update(check_quarantine(pins))                                            # 12
    facts.update(check_load())                                                      # 13
    facts.update(check_rebuild(ctx.vintages_path.parent, pins, d7=True))            # 14
    return facts


def preflight() -> dict:
    """Every step-2 check that does not need the tag, with HEAD standing in for it: checks 1
    and 6-14, pins and lock from HEAD, and check 10's rule without --amendment. Writes
    nothing: the rebuild goes to a temporary directory that is removed afterwards."""
    root = _root()
    head = _commit("HEAD")
    check_outputs(root / RUN_ROOT_REL / head, root / RESULTS_REL)                   # 1
    check_clean()                                                                   # 6
    check_import()                                                                  # 7
    pins = _pins_at(head)
    facts: dict = {"head": head}
    facts.update(check_environment(_blob(head, LOCK_REL), pins, head))              # 8
    facts.update(check_raw(pins))                                                   # 9
    facts.update(check_logs(None))                                                  # 10
    facts.update(check_inputs(pins, head))                                          # 11
    facts.update(check_quarantine(pins))                                            # 12
    facts.update(check_load())                                                      # 13
    with tempfile.TemporaryDirectory(prefix="stage_h_preflight_") as tmp:           # 14
        facts.update(check_rebuild(Path(tmp), pins, d7=True))
    facts["vintages"].pop("path")
    return facts


def dry_checks(ctx: Context) -> dict:
    """Dry-run step 2: checks 6-9, 11 and 13, counts for check 10, and the rebuild into the
    dry directory (no D7 slices: they concern CONF origins). Pins and lock come from the
    working tree; before ``pin`` has run there are none, and the comparisons with them are
    skipped and recorded as such."""
    if ctx.mode != "dry":
        raise ValueError("dry_checks is for the dry run")
    root = _root()
    head = _commit("HEAD")
    work = Path(ctx.work)
    if (work.parent != root / DRY_ROOT_REL or len(work.name) < 7 or not head.startswith(work.name)
            or Path(ctx.vintages_path).parent != work / "vintages"):
        raise RefusedError(f"the dry context's directory {work} is not "
                           f"{root / DRY_ROOT_REL}/<HEAD>")
    pins = read_pins(False) if (root / PINS_REL).is_file() else None
    if pins is None:
        log.warning("no %s yet: the dry run skips its pin comparisons", PINS_REL)
    lock = root / LOCK_REL
    facts: dict = {"head": head, "pinned": pins is not None}
    check_clean()                                                                   # 6
    check_import()                                                                  # 7
    facts.update(check_environment(lock.read_bytes() if lock.is_file() else None, pins, head))  # 8
    facts.update(check_raw(pins))                                                   # 9
    facts.update(log_counts())                                                      # 10
    if pins is not None:
        facts.update(check_inputs(pins, head))                                      # 11
    facts.update(check_load())                                                      # 13
    facts.update(check_rebuild(ctx.vintages_path.parent, pins, d7=False))
    return facts
