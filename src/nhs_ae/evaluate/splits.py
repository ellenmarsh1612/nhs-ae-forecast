"""Data splits and the sealed confirmatory window (amendment of 2026-09-10).

The 2019-09 to 2025-09 evaluation window was inspected while M1 v2 and v3 were being
designed, so it can no longer carry confirmatory claims. It is re-split by origin:

    DEV          origins 2018-04 .. 2023-12   all development, searches and selection
    CONF         origins 2024-01 .. 2025-09   sealed; scored once, in the confirmatory run
    PROSPECTIVE  origins from 2026-10         the live forecasts, scored as outturns arrive

The seal covers target periods as well as origins. A DEV origin late in 2023 forecasts
months in 2024, and those outturns are exactly what CONF scores, so selecting on them
would leak CONF into development. Any forecast whose origin lies in CONF, or whose target
period lies in CONF's target window (2024-01 .. 2026-02, the months CONF forecasts reach
at horizons 1–6), is sealed. DEV scoring therefore simply omits the 2024 targets of its
last few origins.

The seal is enforced in code, not by discipline. ``score_rows`` (which every scoring path
goes through) calls ``assert_not_sealed``; it raises unless it is given the unseal token,
which is the commit that the ``conf-plan-v1`` tag points to. So CONF cannot be scored
before the confirmatory plan has been written, committed and tagged. Since P11 the token
alone is not enough: the first tokened call of a process must come from ``python -m
nhs_ae.evaluate.stage_h run`` at the runner's hash commit, with a clean tree and ``nhs_ae``
imported from this worktree (``seal_rules``). Every successful unseal is appended to
``results/unseal_log.jsonl`` (once per process). Once ``conf-run-v1`` tags the completed run
and every log line is its entry or disclosed in a §10 row (the post-run state), sealed rows
pass without the token and without a new line, so the live forecast adds no entry.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from nhs_ae.config import PROJECT_ROOT
from nhs_ae.evaluate import seal_rules
from nhs_ae.ingest.recover import month_range

DEV = (date(2018, 4, 1), date(2023, 12, 1))
CONF = (date(2024, 1, 1), date(2025, 9, 1))
SEALED_ORIGINS = pd.period_range("2024-01", "2025-09", freq="M")
SEALED_TARGETS = pd.period_range("2024-01", "2026-02", freq="M")
SPLITS = {"dev": DEV, "conf": CONF}
CONF_TAG = seal_rules.PLAN_TAG                  # "conf-plan-v1"
RUN_TAG = seal_rules.RUN_TAG                    # "conf-run-v1": the post-run state
UNSEAL_LOG = PROJECT_ROOT / "results" / "unseal_log.jsonl"

_logged_tokens: set[str] = set()
# token -> {"root", "head", "amendment"} of the first tokened call, recorded only once its log
# line is written and fsynced; every later tokened call of the process reuses it
_unseal_context: dict[str, dict] = {}
_post_run_cache: set[tuple] = set()             # keys for which the post-run state held


class SealedOriginError(RuntimeError):
    """Raised when sealed (CONF) forecasts would be scored without the unseal token."""


def split_origins(split: str) -> list[date]:
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {sorted(SPLITS)}")
    return month_range(*SPLITS[split])


def _months(values: Iterable) -> pd.PeriodIndex:
    return pd.PeriodIndex(pd.to_datetime(pd.Index(list(values))), freq="M")


def sealed_mask(frame: pd.DataFrame) -> pd.Series:
    """True for rows whose origin or target period falls inside the seal."""
    mask = pd.Series(False, index=frame.index)
    for col, sealed in (("origin", SEALED_ORIGINS), ("period", SEALED_TARGETS)):
        if col in frame.columns:
            mask |= pd.Series(_months(frame[col]).isin(sealed), index=frame.index)
    return mask


def _tag_commit(tag: str = CONF_TAG) -> str | None:
    """The commit ``refs/tags/<tag>`` names at PROJECT_ROOT, or None."""
    return seal_rules.commit(PROJECT_ROOT, f"refs/tags/{tag}")


def _head_commit() -> str | None:
    return seal_rules.commit(PROJECT_ROOT, "HEAD")


# ---- the unseal context (P11) ------------------------------------------------------------
def _import_problems() -> list[str]:
    """Rule 4d: PROJECT_ROOT is its own git toplevel and ``nhs_ae`` is imported from
    PROJECT_ROOT/src/nhs_ae, which fixes the log this module writes. A seam: tests whose
    temporary repository stands in for PROJECT_ROOT stub it."""
    import nhs_ae
    root = Path(PROJECT_ROOT)
    top = seal_rules.toplevel(root)
    if top is None:
        return [f"PROJECT_ROOT {root} is not in a git worktree"]
    return seal_rules.import_problems(top, Path(nhs_ae.__file__), root)


def _head_problems(root: Path, tag: str, head: str, amendment: str | None) -> list[str]:
    """Rule 4a: HEAD is the runner's hash commit H1, whose only parent S is a start commit
    (the tag or, with ``amendment``, a descendant adding that §10 row). S itself is refused:
    the runner never unseals before the forecasts are hashed."""
    if head == tag:
        return [f"HEAD is the {CONF_TAG} commit itself, not the runner's hash commit on it"]
    ps = seal_rules.parents(root, head)
    if len(ps) != 1:
        return [f"HEAD {head[:12]} has {len(ps)} parents, not the runner's hash commit's one"]
    out = []
    ok, why = seal_rules.start_commit_ok(root, ps[0], amendment, tag=tag)
    if not ok:
        out.append(f"HEAD's parent is not a start commit ({why})")
    ok, why = seal_rules.hash_commit_ok(root, head, ps[0])
    if not ok:
        out.append(f"HEAD is not the runner's hash commit ({why})")
    return out


def _context_problems(token: str, amendment: str | None) -> list[str]:
    """Why the first tokened call of this process may not unseal with ``token``; empty if it
    may (P11). The seam tests patch where the tag is faked. With the tag commit and HEAD from
    ``_tag_commit()`` and ``_head_commit()``, one rev-parse each, passed to ``seal_rules``:
    a. HEAD is the runner's hash commit on the start commit (``_head_problems``);
    b. ``sys.argv`` names ``python -m nhs_ae.evaluate.stage_h run``;
    c. the tree is clean outside results/ and data/ (``seal_rules.tree_problems``);
    d. ``nhs_ae`` is imported from PROJECT_ROOT (``_import_problems``).
    A git error is a problem, never a pass."""
    root = Path(PROJECT_ROOT)
    try:
        tag, head = _tag_commit(), _head_commit()
        if tag is None or token != tag:
            return [f"the token is not the commit of '{CONF_TAG}'"]
        if head is None:
            return ["HEAD is not a commit"]
        out = _head_problems(root, tag, head, amendment)
        if not seal_rules.names_run(sys.argv):
            out.append("sys.argv does not name `python -m nhs_ae.evaluate.stage_h run`")
        out += seal_rules.tree_problems(root)
        out += _import_problems()
    except Exception as e:  # noqa: BLE001 - fail closed
        return [f"the unseal context could not be checked: {e!r}"]
    return out


# ---- the post-run state (P11) ------------------------------------------------------------
def _post_run_files(root: Path) -> tuple[list[Path], Path]:
    """Every worktree's log, this process's UNSEAL_LOG and the witness."""
    logs = [t / seal_rules.LOG_REL for t in seal_rules.worktrees(root)] + [Path(UNSEAL_LOG)]
    return list({p.resolve(): p for p in logs}.values()), seal_rules.witness_path(root)


def _post_run_key(root: Path, logs: list[Path], witness: Path) -> tuple:
    refs = tuple(seal_rules.commit(root, r) for r in (CONF_TAG, RUN_TAG, "HEAD"))
    files = tuple((str(p), p.read_bytes() if p.exists() else None) for p in (*logs, witness))
    return str(root.resolve()), refs, files


def _post_run() -> bool:
    """Whether the post-run state holds at PROJECT_ROOT (``seal_rules.post_run_problems``
    over every worktree's log and the witness). A True result is cached for the process,
    keyed by the tag commits, HEAD and the bytes of every file read, and kept only if the key
    is the same after the check; False is recomputed. Never raises: an error means False."""
    root = Path(PROJECT_ROOT)
    try:
        if seal_rules.commit(root, RUN_TAG) is None:           # before the run: one rev-parse
            return False
        logs, witness = _post_run_files(root)
        key = _post_run_key(root, logs, witness)
        if key in _post_run_cache:
            return True
        if seal_rules.post_run_problems(root, logs, witness):
            return False
        if _post_run_key(root, logs, witness) == key:
            _post_run_cache.add(key)
        return True
    except Exception:  # noqa: BLE001 - fail closed
        return False


def _append_entry(entry: dict) -> None:
    """Append ``entry`` to UNSEAL_LOG and fsync before returning."""
    path = Path(UNSEAL_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def assert_not_sealed(frame_or_origins, unseal_token: str | None = None, *,
                      amendment: str | None = None) -> None:
    """Raise unless nothing sealed is present or this call may unseal.

    Accepts a frame with ``origin`` and/or ``period`` columns, or an iterable of origins.
    Nothing sealed returns before any git call. Otherwise, in order (P11):

    1. In the post-run state (``_post_run``), token None or the ``conf-plan-v1`` commit
       returns without a log line; any other token raises.
    2. A valid token is the full commit SHA that the ``conf-plan-v1`` tag points to.
    3. The first tokened call of the process for the token refuses, writing nothing, unless
       ``_context_problems(token, amendment)`` is empty. Later calls refuse unless HEAD is
       the head it validated; ``amendment`` None reuses its amendment, another one refuses.
    4. Once per process per token the unseal is appended to ``UNSEAL_LOG`` and fsynced; only
       then are ``_logged_tokens`` and ``_unseal_context`` updated, so after a failed write a
       retry is validated again, never passed.
    """
    if isinstance(frame_or_origins, pd.DataFrame):
        mask = sealed_mask(frame_or_origins)
        n_sealed = int(mask.sum())
        origins = frame_or_origins.loc[mask, "origin"] if "origin" in frame_or_origins else []
    else:
        months = _months(frame_or_origins)
        n_sealed = int(months.isin(SEALED_ORIGINS).sum())
        origins = months[months.isin(SEALED_ORIGINS)].to_timestamp()
    if n_sealed == 0:
        return
    if _post_run():
        if unseal_token is None or unseal_token == _tag_commit():
            return
        raise SealedOriginError(f"after '{RUN_TAG}', sealed rows are read without a token or "
                                f"with the commit of '{CONF_TAG}', never another token")
    if unseal_token is None:
        raise SealedOriginError(
            f"{n_sealed} forecast rows fall in the sealed confirmatory window (origins "
            f"2024-01..2025-09 or target periods 2024-01..2026-02). Score DEV only, or unseal "
            f"with the commit of the '{CONF_TAG}' tag (Stage H of the work order).")
    expected = _tag_commit()
    if expected is None:
        raise SealedOriginError(f"tag '{CONF_TAG}' does not exist: write, commit and tag "
                                "docs/confirmatory_plan.md before unsealing")
    if unseal_token != expected:
        raise SealedOriginError(f"unseal token does not match the commit of '{CONF_TAG}'")
    context = _unseal_context.get(unseal_token)
    if context is None:
        problems = _context_problems(unseal_token, amendment)
        if problems:
            raise SealedOriginError(
                "the first tokened call of a process unseals only from `python -m "
                "nhs_ae.evaluate.stage_h run` at its hash commit, with a clean tree and nhs_ae "
                f"imported from PROJECT_ROOT (P11): {'; '.join(problems)}")
        head = _head_commit()
    else:
        head = _head_commit()
        if Path(PROJECT_ROOT) != context["root"] or head != context["head"]:
            raise SealedOriginError(f"HEAD is {head} at {PROJECT_ROOT}, not the head "
                                    f"{context['head']} this process unsealed at")
        if amendment is not None and amendment != context["amendment"]:
            raise SealedOriginError(f"amendment {amendment!r} is not the "
                                    f"{context['amendment']!r} this process unsealed under")
    if unseal_token not in _logged_tokens:
        o = pd.to_datetime(pd.Index(list(origins))) if len(origins) else pd.DatetimeIndex([])
        _append_entry({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       "token": unseal_token, "head": head, "argv": sys.argv,
                       "sealed_rows": n_sealed,
                       "origins": [str(o.min().date()), str(o.max().date())] if len(o) else []})
        _logged_tokens.add(unseal_token)
    if context is None:
        _unseal_context[unseal_token] = {"root": Path(PROJECT_ROOT), "head": head,
                                         "amendment": amendment}


def drop_sealed(frame: pd.DataFrame) -> pd.DataFrame:
    """The rows of a scored or forecast frame that DEV work may look at."""
    return frame[~sealed_mask(frame)]
