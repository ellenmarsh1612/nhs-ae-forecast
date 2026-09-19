"""Vintage archive for the raw monthly files.

Why this exists
---------------
NHS England re-publishes monthly files *in place* at the twice-yearly revisions. If you
only ever keep "the latest file", every backtest you run silently uses information that
was not available at forecast time. The archive therefore stores every file under the
date on which we fetched it::

    data/raw/2026-09-10/Monthly-AE-July-2026.csv
    data/raw/2026-11-12/Monthly-AE-July-2026-revised-13.11.26.csv

and records a SHA-256 for each in ``data/raw/manifest.jsonl``. A file whose content hash
is already in the manifest is not stored twice; the manifest simply gains a new line
saying "still identical on <date>", which is itself useful evidence that a period has
stopped revising.

Two dates matter for every stored file:

``snapshot``        the folder the file lives in (the date we fetched it, for live runs)
``available_from``  the date the file became the *current* published version. For live
                    runs this equals ``snapshot``. For vintages recovered after the fact
                    (``nhs_ae.ingest.recover``) it is estimated from the stated revision
                    date, the upload month, or the first Internet Archive sighting, and
                    the record says which.

As-of lookups (``latest_stored_per_period``) use ``available_from`` so that a file
recovered today but published in 2019 is correctly visible to a 2019 origin.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from nhs_ae.config import MANIFEST_PATH, RAW_DIR
from nhs_ae.ingest.discover import USER_AGENT, FileRef

log = logging.getLogger(__name__)


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_manifest(path: Path = MANIFEST_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def _append_manifest(record: dict, path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record, default=str) + "\n")


def known_hashes(manifest: list[dict]) -> dict[str, dict]:
    """Map sha256 -> first manifest record that stored it."""
    out: dict[str, dict] = {}
    for rec in manifest:
        if rec.get("stored") and rec["sha256"] not in out:
            out[rec["sha256"]] = rec
    return out


def download_refs(refs: Iterable[FileRef],
                  snapshot: date | None = None,
                  raw_dir: Path = RAW_DIR,
                  manifest_path: Path = MANIFEST_PATH,
                  session: requests.Session | None = None,
                  timeout: int = 120) -> list[dict]:
    """Download each FileRef into today's snapshot folder and update the manifest.

    Returns the manifest records written in this run (one per ref, stored or not).
    """
    snapshot = snapshot or date.today()
    snap_dir = raw_dir / snapshot.isoformat()
    sess = session or requests.Session()
    manifest = read_manifest(manifest_path)
    seen = known_hashes(manifest)
    written: list[dict] = []

    for ref in refs:
        try:
            resp = sess.get(ref.url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            log.error("Failed %s: %s", ref.url, e)
            rec = {**asdict(ref), "snapshot": snapshot, "error": str(e), "stored": False,
                   "fetched_at": datetime.now(timezone.utc).isoformat()}
            _append_manifest(rec, manifest_path)
            written.append(rec)
            continue

        content = resp.content
        digest = sha256_bytes(content)
        rec = {
            **asdict(ref),
            "snapshot": snapshot,
            "available_from": snapshot,
            "available_from_source": "fetched_live",
            "sha256": digest,
            "bytes": len(content),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        if digest in seen:
            rec.update(stored=False, identical_to=seen[digest]["path"])
            log.info("%s unchanged since %s", ref.filename, seen[digest]["snapshot"])
        else:
            snap_dir.mkdir(parents=True, exist_ok=True)
            out_path = snap_dir / ref.filename
            out_path.write_bytes(content)
            rec.update(stored=True, path=str(out_path.relative_to(raw_dir.parent.parent)))
            seen[digest] = rec
            log.info("stored %s (%d bytes)", out_path, len(content))
        _append_manifest(rec, manifest_path)
        written.append(rec)
    return written


def latest_stored_per_period(manifest: list[dict], as_of: date | None = None) -> dict[str, dict]:
    """For each period, the most recent *stored* version available on or before ``as_of``.

    This is the primitive that as-of backtesting is built on: ask "what did we know
    about July 2026 on 2026-10-01?" and get the file that was current then. "Available"
    means ``available_from`` (falling back to ``snapshot`` for old manifest lines).
    """
    out: dict[str, dict] = {}
    for rec in manifest:
        if not rec.get("stored"):
            continue
        avail = available_from(rec)
        if as_of and avail > as_of:
            continue
        key = str(rec["period"])[:7]
        if key not in out or avail >= available_from(out[key]):
            out[key] = rec
    return out


def available_from(rec: dict) -> date:
    s = rec.get("available_from") or rec["snapshot"]
    return s if isinstance(s, date) else date.fromisoformat(str(s))
