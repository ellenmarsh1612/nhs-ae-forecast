"""Stage H seal mechanics (design §2.2, §2.3, §2.6, §2.7): token handling, the guarded call,
split-checked scoring, log and witness accounting, and the post-unseal process tripwire.

Uses ``evaluate/splits.py``'s public behaviour and its module state (``UNSEAL_LOG``,
``_logged_tokens``, ``_tag_commit``, ``_head_commit``), always looked up at call time, so
tests can point them at a temporary log and a faked tag. ``names_run`` and ``witness_path``
delegate to ``evaluate.seal_rules``, which ``splits`` shares (P11).

Public: ``read_token``, ``worktree_logs``, ``witness_path``, ``line_count``, ``names_run``,
``Accounting``, ``open_seal``, ``forbid_processes``, ``score``, ``embargo_pairs``, and the
errors ``SealError`` and ``SealAccountingError``.
"""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import multiprocessing.process
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from nhs_ae.config import PROJECT_ROOT
from nhs_ae.evaluate import harness, seal_rules, splits
from nhs_ae.evaluate.stage_h.common import CONF21, DEV

WITNESS = seal_rules.WITNESS_REL                      # under the git common directory


class SealError(RuntimeError):
    """A Stage H seal rule is broken."""


class SealAccountingError(SealError):
    """The unseal log or the witness does not hold what the run expects."""


# ---- token -------------------------------------------------------------------------------
def read_token(path) -> str:
    """The token file's first line, stripped, read in the parent process.

    Refuses if the token is already in ``sys.argv`` or ``os.environ``: spawn workers copy
    both, so a token there reaches every worker (§2.2). Callers hold the token in a local,
    pass it to no initargs or task, and drop it after use."""
    if multiprocessing.parent_process() is not None:
        raise SealError("the token is read only in the parent process")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    token = lines[0].strip() if lines else ""
    if not token:
        raise SealError(f"token file {path} is empty")
    if any(token in str(a) for a in sys.argv) or any(token in v for v in os.environ.values()):
        raise SealError("the token is in sys.argv or os.environ, which every spawn worker "
                        "inherits; pass it only through the token file")
    return token


# ---- logs and witness --------------------------------------------------------------------
def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          check=True).stdout


def _decode(data: bytes) -> list[str]:
    """Lines of a log's bytes; an undecodable byte is replaced, so its line is flagged as
    unparsable rather than raising."""
    return data.decode("utf-8", errors="replace").splitlines()


def _lines(path: Path) -> list[str]:
    path = Path(path)
    return _decode(path.read_bytes()) if path.exists() else []


def line_count(path) -> int:
    """Lines in a log or witness file (0 if absent)."""
    return len(_lines(path))


def worktree_logs(root: Path | None = None) -> dict[Path, int]:
    """Line count of ``results/unseal_log.jsonl`` in every worktree that
    ``git worktree list --porcelain`` reports from ``root`` (default: the project root),
    plus ``splits.UNSEAL_LOG`` itself. Keys are resolved log paths; an absent log counts 0."""
    root = Path(PROJECT_ROOT if root is None else root)
    out = _git("worktree", "list", "--porcelain", cwd=root)
    trees = [Path(line.removeprefix("worktree ")) for line in out.splitlines()
             if line.startswith("worktree ")]
    logs = [t / "results" / "unseal_log.jsonl" for t in trees] + [Path(splits.UNSEAL_LOG)]
    return {p.resolve(): line_count(p) for p in logs}


def witness_path(root: Path | None = None) -> Path:
    """``$(git rev-parse --git-common-dir)/nhs_ae/unseal_witness.jsonl`` of the repository at
    ``root`` (default: the project root): untracked by construction and shared by every
    worktree of the repository (§2.7). ``seal_rules.witness_path``."""
    return seal_rules.witness_path(Path(PROJECT_ROOT if root is None else root))


def _is_entry(line: str) -> bool:
    try:
        return isinstance(json.loads(line), dict)
    except ValueError:
        return False


def names_run(argv) -> bool:
    """True if a logged ``argv`` is ``python -m nhs_ae.evaluate.stage_h run ...``: under
    ``-m``, argv[0] is the full path of the package's ``__main__.py``. ``seal_rules.names_run``."""
    return seal_rules.names_run(argv)


def _unsealed(exc: BaseException | None) -> bool:
    """True if ``exc``, or an exception it was raised from or during, left ``open_seal`` after
    the guarded call returned."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if getattr(exc, "unsealed", False) is True:
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class Accounting:
    """Log accounting for the ``finally`` block that covers the guarded call (§2.7).

    ``before``: line counts taken before the ``try`` (``worktree_logs()``; the dry run adds
    ``witness_path()`` with its ``line_count``). ``here``: this worktree's log,
    ``splits.UNSEAL_LOG``. Runs no git operation. The caller's pattern::

        unsealed, exc = False, None
        try:
            open_seal(...)
            unsealed = True
            ...
        except BaseException as e:
            exc = e
            raise
        finally:
            acct.settle(unsealed, exc)
    """

    def __init__(self, before: dict[Path, int], here: Path):
        self.before = {Path(p).resolve(): int(n) for p, n in before.items()}
        self.here = Path(here).resolve()
        if self.here not in self.before:
            raise ValueError(f"{here} is not among the counted logs")

    def verify(self, unsealed: bool) -> list[str]:
        """Problems, if any: ``here`` must hold before[here] + 1 lines if the guarded call
        returned (``unsealed``) and before[here] otherwise; every other file is unchanged;
        every line is a JSON object."""
        problems = []
        for path, n0 in self.before.items():
            lines = _lines(path)
            want = n0 + int(unsealed and path == self.here)
            if len(lines) != want:
                problems.append(f"{path}: {len(lines)} lines, expected {want}")
            bad = [i for i, line in enumerate(lines, 1) if not _is_entry(line)]
            if bad:
                problems.append(f"{path}: line(s) {bad} do not parse as a JSON object")
        return problems

    def settle(self, unsealed: bool, exc: BaseException | None = None) -> list[str]:
        """``verify`` as the ``finally`` block applies it; ``exc`` is the exception in
        flight, if any. An exception that left ``open_seal`` after the guarded call returned
        carries ``unsealed = True`` (in its chain), which stands for the caller's flag, not
        yet set then. With an exception in flight, the problems, or the accounting's own
        failure, are attached to it as a note and the original propagates; otherwise any
        problem raises ``SealAccountingError``."""
        try:
            problems = self.verify(unsealed or _unsealed(exc))
        except Exception as e:
            if exc is None:
                raise SealAccountingError(f"unseal accounting could not run: {e!r}") from e
            exc.add_note(f"unseal accounting could not run: {e!r}")
            return [f"could not run: {e!r}"]
        if problems and exc is not None:
            exc.add_note("unseal accounting: " + "; ".join(problems))
        elif problems:
            raise SealAccountingError("; ".join(problems))
        return problems


def _append(path: Path, lines: list[str]) -> None:
    """Append ``lines`` and fsync. A file whose last line lacks its newline gets one first, so
    no appended line joins it."""
    if not lines:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as fh:
        if fh.seek(0, os.SEEK_END):
            fh.seek(-1, os.SEEK_END)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        fh.write("".join(line + "\n" for line in lines).encode("utf-8"))
        fh.flush()
        os.fsync(fh.fileno())


# ---- the guarded call --------------------------------------------------------------------
def open_seal(origins, token: str, expected_head: str, amendment: str | None = None) -> dict:
    """The step-4 guarded call (§2.3, §2.7): ``splits.assert_not_sealed(origins, token,
    amendment=amendment)``, the first tokened call of the process, where ``splits`` checks
    the unseal context (P11: HEAD the hash commit on the tag or, with ``amendment``, on the
    descendant adding that §10 row; argv; tree; import) and keeps it, with ``amendment``, for
    every later tokened call. Returns the new log entry.

    Refuses, writing nothing, in a child process, with live children, once any token has
    been logged, unless ``origins`` are exactly the 21 CONF origins, HEAD is
    ``expected_head``, ``sys.argv`` names ``stage_h run``, and this worktree's log ends with
    a newline and holds only JSON objects. Once the call returns: installs
    ``forbid_processes()``, appends the new bytes of the log to the witness, and checks the
    new line (token = tag commit, head = ``expected_head``, origins = first and last CONF
    origins, sealed_rows = 21, argv names ``stage_h run``), raising ``SealAccountingError`` on
    any difference. The line is witnessed before it is checked, so a wrong line is recorded
    too. Any exception raised after the call returned carries ``unsealed = True``, which
    ``Accounting.settle`` reads.
    """
    origins = list(origins)
    if multiprocessing.parent_process() is not None:
        raise SealError("the guarded call runs only in the parent process")
    if multiprocessing.active_children():
        raise SealError("child processes are alive at the guarded call")
    if splits._logged_tokens:
        raise SealError("a token was logged before the guarded call")
    if not token:
        raise SealError("the guarded call needs the token")
    if sorted(pd.to_datetime(origins)) != list(pd.to_datetime(list(CONF21))):
        raise SealError(f"the guarded call takes exactly the {len(CONF21)} CONF origins, "
                        f"not {len(origins)} others")
    head = splits._head_commit()
    if head != expected_head:
        raise SealError(f"HEAD is {head}, expected {expected_head}")
    if not names_run(sys.argv):
        raise SealError("sys.argv does not name `python -m nhs_ae.evaluate.stage_h run`")
    witness = witness_path()                  # resolved first: a git failure unseals nothing
    log_path = Path(splits.UNSEAL_LOG)
    old = log_path.read_bytes() if log_path.exists() else b""
    if old and not old.endswith(b"\n"):
        raise SealError(f"{log_path} does not end with a newline: the new entry would join "
                        "its last line")
    bad = [i for i, line in enumerate(_decode(old), 1) if not _is_entry(line)]
    if bad:
        raise SealError(f"{log_path}: line(s) {bad} do not parse as a JSON object")

    splits.assert_not_sealed(origins, token, amendment=amendment)
    try:
        return _witness_and_check(log_path, old, witness, expected_head)
    except BaseException as exc:
        exc.unsealed = True
        raise


def _witness_and_check(log_path: Path, old: bytes, witness: Path, expected_head: str) -> dict:
    forbid_processes()
    data = log_path.read_bytes() if log_path.exists() else b""
    new = _decode(data[len(old):])
    _append(witness, new)
    if not data.startswith(old):
        raise SealAccountingError(f"{log_path} changed other than by an append during the "
                                  "guarded call")
    if len(new) != 1 or not _is_entry(new[0]):
        raise SealAccountingError(f"the guarded call added {len(new)} log lines, expected one "
                                  "JSON entry")
    entry = json.loads(new[0])
    want = {"token": splits._tag_commit(), "head": expected_head,
            "origins": [str(CONF21[0]), str(CONF21[-1])], "sealed_rows": len(CONF21)}
    wrong = [k for k, v in want.items() if entry.get(k) != v]
    if not names_run(entry.get("argv")):
        wrong.append("argv")
    if wrong:
        raise SealAccountingError(f"the new log line differs in {', '.join(wrong)}")
    return entry


def _refuse(*args, **kwargs):
    raise SealError("no process may start after the guarded call (design §2.2)")


def forbid_processes() -> None:
    """The post-unseal tripwire: starting any multiprocessing process (every Pool and
    ProcessPoolExecutor worker is one) or creating a ProcessPoolExecutor raises. Plain
    subprocesses stay possible: step 6 commits with git."""
    multiprocessing.process.BaseProcess.start = _refuse
    concurrent.futures.ProcessPoolExecutor.__init__ = _refuse


# ---- scoring -----------------------------------------------------------------------------
def _months(values) -> pd.PeriodIndex:
    return pd.PeriodIndex(pd.to_datetime(pd.Index(list(values))), freq="M")


def score(forecasts: pd.DataFrame, truth: pd.DataFrame, split: str,
          token: str | None = None) -> tuple[pd.DataFrame, dict]:
    """``harness.score_forecasts`` in the parent process, on one split (§2.6).

    "dev": no token and every origin in DEV (burn-in origins are refused, as Stage D never
    scores them); the output must hold no sealed target period. "conf": the token, every
    origin in CONF, and only after ``open_seal``, so that the explicit call stays the first
    guarded call. A tokened call skips the embargo, so a DEV origin in a CONF frame would
    score a sealed target."""
    if multiprocessing.parent_process() is not None:
        raise SealError("scoring runs only in the parent process")
    if split not in ("dev", "conf"):
        raise ValueError(f"split must be 'dev' or 'conf', not {split!r}")
    if split == "dev" and token is not None:
        raise SealError("DEV frames are scored without the token")
    if split == "conf" and token is None:
        raise SealError("CONF frames are scored with the token")
    if split == "conf" and token not in splits._logged_tokens:
        raise SealError("CONF scoring before open_seal: the explicit guarded call comes first")
    months = _months(forecasts["origin"].unique())
    outside = months[~months.isin(_months(DEV if split == "dev" else CONF21))]
    if len(outside):
        raise SealError(f"{len(outside)} origins outside {split.upper()} "
                        f"({outside.min()} to {outside.max()})")
    scored, dropped = harness.score_forecasts(forecasts, truth, token)
    if split == "dev" and len(scored) and _months(scored["period"]).isin(
            splits.SEALED_TARGETS).any():
        raise SealError("DEV scoring returned a sealed target period")
    return scored, dropped


def embargo_pairs(forecasts: pd.DataFrame) -> set[tuple[pd.Timestamp, int]]:
    """The (origin, horizon) pairs whose target period is sealed (``SEALED_TARGETS``), that
    is, the pairs token-less scoring drops as embargoed. For the dry run's check that they
    are exactly the pairs with period 2024-01 or later (§2.6, §10: 15 of 36)."""
    sealed = _months(forecasts["period"]).isin(splits.SEALED_TARGETS)
    pairs = forecasts.loc[sealed, ["origin", "horizon"]].drop_duplicates()
    return {(pd.Timestamp(o), int(h)) for o, h in pairs.itertuples(index=False)}
