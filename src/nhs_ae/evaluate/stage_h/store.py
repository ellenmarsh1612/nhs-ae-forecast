"""Write-then-hash store for step-4 and step-5 outputs, the verifying loader, and the progress
records that decide the crash case (design §9).

Every statistic is computed from frames read back through ``Store.load``, so ``run``,
``dry-run`` and ``report --from-scores`` share one path. Writing ``SHA256SUMS`` seals a
store: nothing more can be put, and every load first checks the file's SHA-256 and its
canonical row hash against it. The scores store's ``SHA256SUMS`` is the crash policy's
"score written" boundary.

Public: ``Store``, ``StoreError``, ``progress``, ``read_progress``, ``crash_case`` and the
constants ``SUMS``, ``STEP4``, ``SCORES``, ``PROGRESS``, ``EVENTS``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.evaluate.stage_h.common import file_sha, row_hash

SUMS = "SHA256SUMS"
STEP4, SCORES = "step4", "scores"        # the two store roots under ctx.work
PROGRESS = "progress.jsonl"
# "sealing" is written just before the try that covers the guarded call, with this
# worktree's log and the witness and their line counts, so a crash between the log write and
# "unsealed" still reads as case 2, even once the log is reverted; the other five are §9's.
EVENTS = ("sealing", "unsealed", "scores-about-to-be-written", "scores-written",
          "results-written", "committed")
_SEALING = ("log", "n0", "witness", "w0")
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.=+-]*")
_BASE = ("name", "kind", "file", "sha256", "row_hash", "rows")
_TYPES = {"float": float, "int": int}


class StoreError(RuntimeError):
    """A store write or read would break write-then-hash."""


# ---- file helpers ------------------------------------------------------------------------
def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic(path: Path, write) -> None:
    """``write(tmp)`` then ``os.replace(tmp, path)``: a reader sees the old file or the new
    one, never a partial one."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        write(tmp)
        _fsync(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync(path.parent)


def _plain(x):
    """JSON form of the few non-JSON types a record may hold. Anything else raises, as json
    does, rather than being stored as its repr (which truncates a long array)."""
    if isinstance(x, np.datetime64):             # .item() gives an int at ns precision
        return pd.Timestamp(x).isoformat()
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, date):                      # datetime and pd.Timestamp too
        return x.isoformat()
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, np.ndarray):                # elements come back through _plain
        return list(x) if x.ndim else x[()]
    raise TypeError(f"{type(x).__name__} is not JSON serialisable: convert it before storing")


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_plain).encode()


def _json_hash(obj) -> str:
    return hashlib.sha256(_canonical(obj)).hexdigest()


def _col_types(frame: pd.DataFrame) -> dict[str, str]:
    """Non-string column names (a scored frame's quantile levels) by their string form, so
    ``load`` can restore them: parquet stores every name as a string."""
    types = {}
    for c in frame.columns:
        if isinstance(c, str):
            continue
        if isinstance(c, (float, np.floating)):
            types[str(c)] = "float"
        elif isinstance(c, (int, np.integer)) and not isinstance(c, bool):
            types[str(c)] = "int"
        else:
            raise TypeError(f"column name {c!r}: only str, int and float names can be stored")
    names = [str(c) for c in frame.columns]
    if len(set(names)) != len(names):
        raise ValueError("column names collide once written as strings")
    return types


def _meta(meta: dict | None) -> dict:
    meta = json.loads(_canonical(meta or {}))
    if not isinstance(meta, dict):
        raise TypeError("meta is a dict")
    clash = set(meta) & {*_BASE, "col_types", "meta"}
    if clash:
        raise ValueError(f"meta keys {sorted(clash)} clash with the record's own fields")
    return meta


# ---- the store ---------------------------------------------------------------------------
class Store:
    """One store root, ``ctx.work / STEP4`` or ``ctx.work / SCORES``. Opening a root that
    already has ``SHA256SUMS`` (``report --from-scores``) reads it; the store is then
    read-only. Nothing is printed: the store holds scores before ``scores-written``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._records: dict[str, dict] = self._read_sums() if self.sealed else {}

    @property
    def sealed(self) -> bool:
        return (self.root / SUMS).exists()

    def _new(self, name: str, ext: str) -> Path:
        if self.sealed:
            raise StoreError(f"{self.root} is sealed: nothing more can be put")
        if not _NAME.fullmatch(name):
            raise ValueError(f"bad store name {name!r}")
        if name in self._records or any((self.root / f"{name}.{e}").exists()
                                        for e in ("parquet", "json")):
            raise StoreError(f"{name} is already in {self.root}: the store never overwrites")
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / f"{name}.{ext}"

    def put(self, name: str, frame: pd.DataFrame, meta: dict | None = None) -> dict:
        """Write ``root/{name}.parquet`` and record its SHA-256, the canonical row hash and row
        count of the frame read back, and ``meta``. The index is not stored, so a named index
        or a MultiIndex (a groupby's keys) is refused. Refuses to overwrite, and refuses once
        the store is sealed."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("put stores a DataFrame; use put_json for small objects")
        if frame.index.nlevels > 1 or frame.index.name is not None:
            raise ValueError(f"the index {list(frame.index.names)} would be dropped: "
                             "reset_index() first")
        col_types, meta = _col_types(frame), _meta(meta)
        path = self._new(name, "parquet")
        out = frame.rename(columns=str) if col_types else frame
        _atomic(path, lambda tmp: out.to_parquet(tmp, index=False))
        back = pd.read_parquet(path)
        rec = {"name": name, "kind": "parquet", "file": path.name, "sha256": file_sha(path),
               "row_hash": row_hash(back), "rows": len(back), "col_types": col_types,
               "meta": meta}
        self._records[name] = rec
        return dict(rec)

    def put_json(self, name: str, obj) -> dict:
        """The same for a small JSON-serialisable object (e.g. a ``dropped`` dict), written in
        canonical form; its row hash is the SHA-256 of the canonical form of the content."""
        data = _canonical(obj)
        path = self._new(name, "json")
        _atomic(path, lambda tmp: tmp.write_bytes(data))
        rec = {"name": name, "kind": "json", "file": path.name, "sha256": file_sha(path),
               "row_hash": _json_hash(json.loads(data)), "rows": None, "col_types": {},
               "meta": {}}
        self._records[name] = rec
        return dict(rec)

    def seal_sums(self) -> Path:
        """Write ``root/SHA256SUMS``, one JSON record per file, after re-hashing every file
        and refusing any file on disk that was not put. The store is read-only from then."""
        if self.sealed:
            raise StoreError(f"{self.root} is already sealed")
        self.root.mkdir(parents=True, exist_ok=True)
        on_disk = {p.name for p in self.root.iterdir() if p.suffix in (".parquet", ".json")}
        recorded = {r["file"] for r in self._records.values()}
        if on_disk != recorded:
            raise StoreError(f"files and records differ in {self.root}: "
                             f"{sorted(on_disk ^ recorded)}")
        for r in self._records.values():
            if file_sha(self.root / r["file"]) != r["sha256"]:
                raise StoreError(f"{r['file']} changed after it was put")
        text = "".join(json.dumps(self._records[n], sort_keys=True) + "\n"
                       for n in sorted(self._records))
        path = self.root / SUMS
        _atomic(path, lambda tmp: tmp.write_text(text, encoding="utf-8"))
        return path

    def _read_sums(self) -> dict[str, dict]:
        lines = (self.root / SUMS).read_text(encoding="utf-8").splitlines()
        recs = [json.loads(line) for line in lines if line]
        return {r["name"]: r for r in recs}

    def _verified(self, name: str, kind: str) -> dict:
        if not self.sealed:
            raise StoreError(f"{self.root} is not sealed: write {SUMS} before reading back")
        recs = self._read_sums()
        if self._records and recs != self._records:
            raise StoreError(f"{self.root / SUMS} changed since this store was sealed or opened")
        if name not in recs:
            raise StoreError(f"{name} is not in {self.root / SUMS}")
        rec = recs[name]
        if rec["kind"] != kind:
            raise StoreError(f"{name} is a {rec['kind']} record")
        if file_sha(self.root / rec["file"]) != rec["sha256"]:
            raise StoreError(f"{name}: SHA-256 differs from {SUMS}")
        return rec

    def load(self, name: str) -> pd.DataFrame:
        """The stored frame, once its file's SHA-256 and then its canonical row hash and row
        count match ``SHA256SUMS``; non-string column names are restored."""
        rec = self._verified(name, "parquet")
        frame = pd.read_parquet(self.root / rec["file"])
        if row_hash(frame) != rec["row_hash"] or len(frame) != rec["rows"]:
            raise StoreError(f"{name}: row hash differs from {SUMS}")
        return frame.rename(columns={c: _TYPES[t](c) for c, t in rec["col_types"].items()})

    def load_json(self, name: str):
        rec = self._verified(name, "json")
        obj = json.loads((self.root / rec["file"]).read_bytes())
        if _json_hash(obj) != rec["row_hash"]:
            raise StoreError(f"{name}: content hash differs from {SUMS}")
        return obj

    def names(self) -> list[str]:
        return sorted(self._records)

    def records(self) -> pd.DataFrame:
        """The ``SHA256SUMS`` table, one row per file with its meta fields as columns (for
        ``score_hashes.csv``). Only a sealed store has one."""
        if not self.sealed:
            raise StoreError(f"{self.root} is not sealed")
        rows = [{**{k: r[k] for k in _BASE}, **r["meta"]} for r in self._read_sums().values()]
        extra = sorted({k for r in rows for k in r} - set(_BASE))
        return pd.DataFrame(rows, columns=[*_BASE, *extra])


# ---- progress and the crash case ---------------------------------------------------------
def progress(work: Path, event: str, **fields) -> None:
    """Append ``{"ts", "event", **fields}`` to ``work/progress.jsonl`` atomically: the whole
    file is rewritten through a temporary file and ``os.replace``. ``event`` must be one of
    ``EVENTS`` (a misspelt event would misread the crash case); "sealing" carries ``log``
    (this worktree's unseal log), ``witness`` (``seal.witness_path()``) and their line counts
    before the guarded call, ``n0`` and ``w0``."""
    if event not in EVENTS:
        raise ValueError(f"unknown progress event {event!r}; expected one of {EVENTS}")
    if "ts" in fields:
        raise ValueError("'ts' is set by progress()")
    if event == "sealing" and not set(_SEALING) <= set(fields):
        raise ValueError("'sealing' records the unseal log and the witness paths (log, "
                         "witness) and their line counts (n0, w0)")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    path = work / PROGRESS
    rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
           "event": event, **fields}
    old = path.read_bytes() if path.exists() else b""
    line = (json.dumps(rec, default=_plain) + "\n").encode()
    _atomic(path, lambda tmp: tmp.write_bytes(old + line))


def read_progress(work: Path) -> list[dict]:
    """The progress records in order; none if the file is absent."""
    path = Path(work) / PROGRESS
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            out.append(json.loads(line))
        except ValueError as e:
            raise StoreError(f"{path} line {i} does not parse") from e
    return out


def _line_count(path: Path) -> int:
    """Lines in a log or witness (0 if absent), as ``seal.line_count`` counts them."""
    path = Path(path)
    if not path.exists():
        return 0
    return len(path.read_bytes().decode("utf-8", errors="replace").splitlines())


def crash_case(work: Path) -> int:
    """The crash case (§9), read from disk.

    3: ``scores-written`` is recorded, or the scores store's ``SHA256SUMS`` exists (the
    "score written" boundary, which a crash can separate from its record). 2: ``unsealed``
    is recorded, or a ``sealing`` record's log has grown past ``n0`` or its witness past
    ``w0`` (a line written but not yet recorded; the witness keeps it if the log has been
    reverted). 1: otherwise: this run wrote no unseal line."""
    work = Path(work)
    recs = read_progress(work)
    events = {r.get("event") for r in recs}
    if "scores-written" in events or (work / SCORES / SUMS).exists():
        return 3
    if "unsealed" in events:
        return 2
    for r in recs:
        if r.get("event") != "sealing":
            continue
        missing = [k for k in _SEALING if k not in r]
        if missing:
            raise StoreError(f"a 'sealing' record lacks {missing}: the crash case is unknown")
        if _line_count(r["log"]) > int(r["n0"]) or _line_count(r["witness"]) > int(r["w0"]):
            return 2
    return 1
