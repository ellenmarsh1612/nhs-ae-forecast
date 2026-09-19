"""``python -m nhs_ae.evaluate.stage_h COMMAND``: the Stage H runner (design §1).

Commands: ``pin``, ``prepare [--dev-side]``, ``preflight``, ``dry-run``,
``run --unseal-token-file PATH [--amendment TITLE]`` and ``report --from-scores WORK``.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
import io
import json
import logging
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import nhs_ae
from nhs_ae.evaluate import splits
from nhs_ae.evaluate.asof import load_vintages
from nhs_ae.evaluate.stage_h import analysis, checks, generate, report, seal, steps
from nhs_ae.evaluate.stage_h.common import (
    CONF21,
    DRY_ROOT,
    HASH_FILES,
    INPUTS,
    PROJECT_ROOT,
    RUN_ROOT,
    TAG,
    Context,
    dry_context,
    file_sha,
    run_context,
)
from nhs_ae.evaluate.stage_h.store import (
    SCORES,
    STEP4,
    Store,
    crash_case,
    progress,
    read_progress,
)

log = logging.getLogger("nhs_ae.evaluate.stage_h")
QUARANTINE_FILE = checks.QUARANTINE_FILE_REL
RUN_MESSAGE = "Stage H: confirmatory results (conf-run-v1 to be tagged by hand)"
# report --from-scores keeps only this of step 3's tripwires: every comparison's bootstrap
REPORT_KEEP = frozenset({"nhs_ae.evaluate.metrics.paired_bootstrap"})


# ---- helpers -----------------------------------------------------------------------------
def _head() -> str:
    return checks.git("rev-parse", "HEAD")


def results_dir(ctx: Context) -> Path:
    """Where this context's results go: results/H-confirmatory, or results/H-dryrun/<head>
    (where ``generate.hash_commit`` puts the dry run's hash files)."""
    return ctx.results if ctx.mode == "run" else ctx.results / ctx.work.name


def _rel(path: Path) -> str:
    """``path`` relative to the repository, as git names it."""
    return Path(path).resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()


def _hash_files_ok(ctx: Context, start: str, h1: str) -> None:
    """§2.3: HEAD is H1, H1's only parent is S, and H1 only adds the four hash files."""
    if _head() != h1:
        raise checks.RefusedError(f"HEAD moved after the hash commit: expected {h1}")
    if ctx.mode == "run":
        ok, why = checks.hash_commit_ok(h1, start)
        if not ok:
            raise checks.RefusedError(f"hash commit: {why}")
        return
    parents = checks.git("rev-list", "--parents", "-n", "1", h1).split()[1:]
    rel = _rel(results_dir(ctx))
    want = {f"A\t{rel}/{f}" for f in HASH_FILES}
    got = set(checks.git("diff", "--name-status", start, h1).splitlines())
    if parents != [start] or got != want:
        raise checks.RefusedError(f"dry hash commit {h1}: parents {parents}, diff {sorted(got)}")


def _h1_copy(ctx: Context, h1: str | None, name: str) -> bytes:
    """A hash-commit table as H1 holds it (the working tree's copy when H1 is not known: an
    older dry run's work directory)."""
    if h1 is None:
        return (results_dir(ctx) / name).read_bytes()
    data = checks._blob(h1, f"{_rel(results_dir(ctx))}/{name}")
    if data is None:
        raise checks.RefusedError(f"the hash commit {h1[:12]} holds no {name}")
    return data


def _rehash(ctx: Context, files: dict, h1: str | None) -> None:
    """The forecast files are those the hash commit recorded, each with its SHA-256."""
    table = pd.read_csv(io.BytesIO(_h1_copy(ctx, h1, "forecast_hashes.csv")))
    want = dict(zip(table["file"], table["sha256"]))
    got = {Path(p).name: p for p in files.values()}
    if set(got) != set(want):
        raise checks.RefusedError(f"the forecast files are not forecast_hashes.csv's: extra "
                                  f"{sorted(set(got) - set(want))[:5]}, missing "
                                  f"{sorted(set(want) - set(got))[:5]}")
    for name, path in sorted(got.items()):
        if want[name] != file_sha(path):
            raise checks.RefusedError(f"{path} no longer matches forecast_hashes.csv")


def _fits(ctx: Context, h1: str | None) -> pd.DataFrame:
    """work/m2_fits.csv, refused unless it is the table the hash commit holds (H2's M2 clause
    reads its evaluability and diagnostics from it)."""
    fits = pd.read_csv(ctx.work / "m2_fits.csv", parse_dates=["origin"])
    committed = pd.read_csv(io.BytesIO(_h1_copy(ctx, h1, "m2_fits.csv")), parse_dates=["origin"])
    if not fits.equals(committed):
        raise checks.RefusedError(f"{ctx.work / 'm2_fits.csv'} differs from the hash commit's "
                                  "m2_fits.csv")
    return fits


def _pre_unseal(ctx: Context, start: str, h1: str, files: dict) -> pd.DataFrame:
    """Design §2.3, run before the try that covers the guarded call. Returns the M2 fits."""
    _hash_files_ok(ctx, start, h1)
    _rehash(ctx, files, h1)
    fits = _fits(ctx, h1)
    checks.check_clean()
    if multiprocessing.active_children():
        raise checks.RefusedError("child processes are alive before step 4")
    if splits._logged_tokens:
        raise checks.RefusedError("a token was logged before step 4")
    return fits


def _load(ctx: Context) -> tuple[steps.Inputs, pd.DataFrame]:
    """The P5 inputs and the run's vintage table. Neither needs the token, so both are read
    before the unseal: a missing or unreadable file is crash case 1, with no log line."""
    return steps.load_inputs(ctx), load_vintages(ctx.vintages_path)


def _forecast_files(ctx: Context) -> dict:
    """Step 3's forecast files by (key, level, mode), as ``generate.forecast_path`` names them."""
    out = {}
    for p in sorted((ctx.work / generate.FORECASTS).glob("*.parquet")):
        key, level, mode = p.stem.rsplit("_", 2)
        out[(key, level, mode)] = p
    return out


def _blob_sha(ref: str, rel: str) -> str | None:
    data = checks._blob(ref, rel)
    return None if data is None else hashlib.sha256(data).hexdigest()


def _blob_id(ref: str, rel: str) -> str | None:
    try:
        return checks.git("rev-parse", "--verify", "--quiet", f"{ref}:{rel}") or None
    except subprocess.CalledProcessError:
        return None


def _provenance(ref: str) -> dict:
    """The lock's SHA-256 and the pins' blob id at ``ref`` (the tag in run mode), if there."""
    return {"lock_sha256": _blob_sha(ref, checks.LOCK_REL),
            "pins_blob": _blob_id(ref, checks.PINS_REL)}


def _uncommitted(work: Path) -> str:
    """The note on an exception that leaves this run's unseal line uncommitted."""
    try:
        case = crash_case(work)
    except Exception as e:  # noqa: BLE001 - the note must not replace the exception it annotates
        case = f"unknown ({e!r})"
    return (f"{checks.LOG_REL} holds this run's unseal line, NOT committed; crash case {case}: "
            "commit it, with any code fix, in the crash-fix commit on top of this run's last "
            "commit, before anything else (design §9)")


def _settle(acct: seal.Accounting, unsealed: bool, exc: BaseException | None, work: Path) -> None:
    """The ``finally`` of the guarded call (§2.7): the accounting, then a note on an exception
    that leaves this run's unseal line uncommitted. Reads files only; runs no git."""
    try:
        acct.settle(unsealed, exc)
    except seal.SealAccountingError as e:
        if unsealed:
            e.add_note(_uncommitted(work))
        raise
    if exc is not None and (unsealed or seal._unsealed(exc)):
        exc.add_note(_uncommitted(work))


def _verify_stores(*stores: Store) -> None:
    """Each sealed store holds exactly the files its SHA256SUMS lists, each with its SHA-256,
    checked before any statistic is computed: a changed file is refused, never recorded as a
    failed statistic."""
    for st in stores:
        if not st.sealed:
            raise checks.RefusedError(f"{st.root} is not sealed")
        recs = st.records()
        on_disk = {p.name for p in st.root.iterdir() if p.suffix in (".parquet", ".json")}
        if on_disk != set(recs["file"]):
            raise checks.RefusedError(f"{st.root}: the files differ from its SHA256SUMS: "
                                      f"{sorted(on_disk ^ set(recs['file']))[:5]}")
        bad = [f for f, s in zip(recs["file"], recs["sha256"]) if file_sha(st.root / f) != s]
        if bad:
            raise checks.RefusedError(f"{st.root}: {len(bad)} files differ from its SHA256SUMS: "
                                      f"{bad[:5]}")


def _report_stub(label: str):
    def tripped(*args, **kwargs):
        raise generate.SealTripwire(f"{label} called by report --from-scores, which reads the "
                                    "sealed stores only (design §9)")
    tripped.tripwire = label
    return tripped


@contextmanager
def _no_guarded_calls():
    """``report --from-scores`` (design §9): step 3's tripwires (``generate.TRIPWIRES``, in
    every alias of each function in a loaded ``nhs_ae`` module) but ``REPORT_KEEP``, so no
    guarded, scoring, outturn or first-release call can run. A trip raises
    ``generate.SealTripwire``, a BaseException that ``analysis._guard`` cannot record as a
    failed statistic: it stops the command. Undone on exit."""
    swaps = {}
    for name, attrs in generate.TRIPWIRES.items():
        mod = importlib.import_module(name)
        if attrs is None:
            attrs = [a for a, f in vars(mod).items()
                     if inspect.isfunction(f) and f.__module__ == name]
        for a in attrs:
            f = getattr(mod, a)
            if f"{name}.{a}" not in REPORT_KEEP and not hasattr(f, "tripwire"):
                swaps[id(f)] = (f, _report_stub(f"{name}.{a}"))
    generate._swap(swaps)
    try:
        yield
    finally:
        generate._swap({id(s): (s, f) for f, s in swaps.values()})


# ---- steps 4-6 ---------------------------------------------------------------------------
def _analyse_and_write(ctx: Context, s4: Store, sc: Store, files: dict, fits: pd.DataFrame,
                       facts: dict, extra: dict, out: Path,
                       original: Path | None = None) -> tuple[dict, str]:
    _verify_stores(s4, sc)
    results = analysis.compute(ctx, s4, sc, files, fits)
    md = report.write(results, facts, out, ctx.mode, extra, score_hashes=_score_hashes(s4, sc),
                      original=original)
    return results, md


def _score_hashes(s4: Store, sc: Store) -> pd.DataFrame:
    return pd.concat([s4.records().assign(store=STEP4), sc.records().assign(store=SCORES)],
                     ignore_index=True)


def _steps_4_5(ctx: Context, token, files: dict, inputs: steps.Inputs, vintages: pd.DataFrame,
               h1: str) -> tuple[Store, Store]:
    s4 = steps.step4(ctx, token, files, inputs, vintages)
    _rehash(ctx, files, h1)
    progress(ctx.work, "scores-about-to-be-written")
    sc = steps.step5(ctx, token, files, inputs, s4, vintages)
    sc.seal_sums()
    progress(ctx.work, "scores-written")
    return s4, sc


def _commit_command(*paths: str, message: str) -> str:
    """The commit a person runs by hand, as the runner commits: hooks off, no other path."""
    return (f"git add -- {' '.join(paths)} && git -c core.hooksPath=/dev/null commit "
            f"--no-verify -m '{message}' -- {' '.join(paths)}")


def _step6(ctx: Context, h1: str, log_path: Path) -> str:
    """Step 6 (design §9): one commit on H1 holding results/H-confirmatory and the unseal log,
    and nothing else. Refused unless HEAD is still H1 and the index then holds only those
    (staged with the repository's ignore rules only, so a dot-file such as .DS_Store is
    refused, not skipped); checked after (H1 the only parent, a clean tree). A refusal before
    the commit unstages what it staged; every failure says whether the unseal line was left
    uncommitted. Returns the new HEAD."""
    rel, log_rel = _rel(results_dir(ctx)), _rel(log_path)
    committed, staged_by_us = None, False
    try:
        head = _head()
        if head != h1:
            raise checks.RefusedError(f"step 6: HEAD is {head[:12]}, not the hash commit {h1[:12]}")
        staged_by_us = True
        checks.git(*checks.NO_EXCLUDES, "add", "--", rel, log_rel)
        staged = checks.git("diff", "--cached", "--name-only").splitlines()
        stray = [p for p in staged if p != log_rel
                 and not (p.startswith(f"{rel}/") and not Path(p).name.startswith("."))]
        if stray or log_rel not in staged:
            raise checks.RefusedError(f"step 6: the index holds {stray[:5]} beyond {rel}/ and "
                                      f"{log_rel}, or lacks the log")
        checks.git("-c", "core.hooksPath=/dev/null", "commit", "--no-verify", "-q", "-m",
                   RUN_MESSAGE)
        committed = _head()
        parents = checks.git("rev-list", "--parents", "-n", "1", committed).split()[1:]
        dirty = checks.git(*checks.NO_EXCLUDES, "status", "--porcelain", "--untracked-files=all")
        if parents != [h1] or dirty:
            raise checks.RefusedError(f"step 6: commit {committed[:12]} has parents {parents}, "
                                      f"not [{h1[:12]}], or the tree is not clean: {dirty[:200]}")
    except BaseException as e:
        if committed:
            e.add_note(f"step 6 committed {committed[:12]}, which needs checking by hand "
                       "(design §9)")
            raise
        if staged_by_us:
            try:
                checks.git("reset", "-q", "--", rel, log_rel)
            except Exception as r:  # noqa: BLE001 - the note must not replace the exception
                e.add_note(f"step 6 could not unstage {rel}/ and {log_rel}: {r!r}")
        e.add_note(f"step 6 failed: {log_rel} holds this run's unseal line and {rel}/ its "
                   "results, uncommitted (crash case 3). Remove anything that is not the run's, "
                   f"then commit them by hand: {_commit_command(rel, log_rel, message=RUN_MESSAGE)}"
                   " (design §9)")
        raise
    return committed


def cmd_dry_run(args) -> int:
    head = _head()
    ctx = dry_context(head[:12], args.jobs)
    if ctx.work.exists() or results_dir(ctx).exists():
        raise checks.RefusedError(f"{ctx.work} or {results_dir(ctx)} exists: move it aside first")
    facts = checks.dry_checks(ctx)                                    # step 2 (dry)
    sha = file_sha(ctx.vintages_path)
    files = generate.generate(ctx, vintage_sha=sha)                   # step 3
    h1 = generate.hash_commit(ctx, generate.step3_tables(ctx, files))
    inputs, vintages = _load(ctx)
    fits = _pre_unseal(ctx, head, h1, files)
    before = seal.worktree_logs()
    witness = seal.witness_path()
    here = Path(splits.UNSEAL_LOG).resolve()
    acct = seal.Accounting({**before, witness: seal.line_count(witness)}, here)
    progress(ctx.work, "sealing", log=str(here), n0=before[here], witness=str(witness),
             w0=seal.line_count(witness), hash_commit=h1, facts=facts)
    exc = None
    try:
        s4, sc = _steps_4_5(ctx, None, files, inputs, vintages, h1)   # steps 4-5, no token
        emb = steps.embargo_check(ctx, files, inputs, s4, sc)
        results, md = _analyse_and_write(
            ctx, s4, sc, files, fits, facts,
            {"mode": "dry", "start": head, "hash_commit": h1, "embargo": emb,
             "inputs_source": inputs.source, **_provenance(head)}, results_dir(ctx))
        progress(ctx.work, "results-written")
    except BaseException as e:
        exc = e
        raise
    finally:
        acct.settle(False, exc)                                       # zero new lines anywhere
    print(md)
    failed = report.errors(results)
    if failed:
        print(f"\nThe dry run fails: {len(failed)} statistics failed or were not computed "
              "(listed above).")
        return 1
    return 0


def cmd_run(args) -> int:
    tag = splits._tag_commit()
    if tag is None:
        raise checks.RefusedError(f"tag {TAG} does not exist")
    ctx = run_context(tag, args.jobs)
    facts = checks.pre_run(ctx, args.unseal_token_file, args.amendment)       # step 2
    start = facts["head"]
    sha = file_sha(ctx.vintages_path)
    files = generate.generate(ctx, vintage_sha=sha)                           # step 3
    pd.DataFrame(generate.d7_check(files)).to_csv(ctx.work / "d7_check.csv", index=False)
    pd.DataFrame(generate.p13_check(files, PROJECT_ROOT / QUARANTINE_FILE)).to_csv(
        ctx.work / "p13_check.csv", index=False)
    h1 = generate.hash_commit(ctx, generate.step3_tables(ctx, files))
    inputs, vintages = _load(ctx)
    fits = _pre_unseal(ctx, start, h1, files)
    before = seal.worktree_logs()
    witness = seal.witness_path()
    here = Path(splits.UNSEAL_LOG).resolve()
    acct = seal.Accounting(before, here)
    progress(ctx.work, "sealing", log=str(here), n0=before[here], witness=str(witness),
             w0=seal.line_count(witness), hash_commit=h1, facts=facts)       # for case 3
    unsealed, exc = False, None
    try:
        token = seal.read_token(args.unseal_token_file)
        entry = seal.open_seal(CONF21, token, expected_head=h1,
                               amendment=args.amendment)                      # step 4
        unsealed = True
        progress(ctx.work, "unsealed", head=h1)
        s4, sc = _steps_4_5(ctx, token, files, inputs, vintages, h1)          # steps 4-5
        del token
        for name in ("d7_check.csv", "p13_check.csv"):
            shutil.copy2(ctx.work / name, results_dir(ctx) / name)
        (results_dir(ctx) / "unseal_entry.json").write_text(json.dumps(entry, indent=1) + "\n")
        _, md = _analyse_and_write(
            ctx, s4, sc, files, fits, facts,
            {"mode": "run", "start": start, "hash_commit": h1, "unseal_entry": entry,
             "inputs_source": inputs.source, **_provenance(tag)}, results_dir(ctx))
        progress(ctx.work, "results-written")
    except BaseException as e:
        exc = e
        raise
    finally:
        _settle(acct, unsealed, exc, ctx.work)
    head = _step6(ctx, h1, here)                                              # step 6
    progress(ctx.work, "committed", head=head)
    print(md)
    print(f"\nNext, by hand, once the summary has been read:\n  git tag -a conf-run-v1 -m "
          f"'Stage H run' {head}\n  git push origin conf-run-v1")
    return 0


def _case3_line(work: Path) -> tuple[str, dict]:
    """Run mode (design §9, case 3): H1 from the 'unsealed' progress record, and this run's
    line in HEAD's committed log. Refused unless the scores were written (crash case 3), the
    line is committed (token the tag commit, head H1) and so is every witness line, with the
    working-tree log HEAD's copy."""
    case = crash_case(work)
    h1 = next((r.get("head") for r in read_progress(work) if r.get("event") == "unsealed"), None)
    if case != 3 or not h1:
        raise checks.RefusedError(f"report --from-scores is design §9's case 3 only (the scores "
                                  f"were written): crash case {case}, 'unsealed' head {h1}")
    tag = checks._tag_commit()
    if work.name != tag:
        raise checks.RefusedError(f"{work.name} is not the {TAG} commit {tag}")

    def mine(lines) -> list[dict]:
        return [e for e in (json.loads(ln) for ln in lines if seal._is_entry(ln))
                if e.get("token") == tag and e.get("head") == h1]

    at_head = mine((checks._blob("HEAD", checks.LOG_REL) or b"").decode().splitlines())
    if not at_head:
        witness = seal.witness_path()
        if mine(seal._lines(Path(splits.UNSEAL_LOG))):
            hint = "; the working-tree log holds it, uncommitted"
        elif mine(seal._lines(witness)):
            hint = (f"; the working-tree log lacks it, and the witness {witness} holds it: "
                    "restore it from there")
        else:
            hint = ""
        raise checks.RefusedError(
            f"HEAD's committed {checks.LOG_REL} lacks this run's unseal line (token {tag[:12]}, "
            f"head {h1[:12]}){hint}. Commit {checks.LOG_REL} and results/H-confirmatory/, as the "
            "crashed run left them, with any code fix, in the crash-fix commit on top of this "
            "run's last commit first (design §9, case 3)")
    problems = checks.committed_log_problems()
    if problems:
        raise checks.RefusedError("; ".join(problems))
    return h1, at_head[-1]


def _on_h1(ctx: Context, h1: str) -> None:
    """Case 3's crash-fix commit sits on top of H1 and keeps its four hash files as H1
    committed them, so the history conf-run-v1 tags carries the proof that the forecasts were
    hashed before the unseal (design §4, §9)."""
    head = _head()
    if not checks._descends(head, h1):
        raise checks.RefusedError(
            f"HEAD {head[:12]} is not on top of the hash commit {h1[:12]}: make the crash-fix "
            f"commit on this run's last commit, not on {TAG} or another line (design §9, case 3)")
    rel = _rel(results_dir(ctx))
    changed = [f for f in HASH_FILES if _blob_id("HEAD", f"{rel}/{f}") != _blob_id(h1, f"{rel}/{f}")]
    if changed:
        raise checks.RefusedError(f"HEAD does not hold the hash commit's {changed} as H1 "
                                  f"{h1[:12]} committed them (design §4, §9)")


def _code_clean(mode: str) -> None:
    """``report --from-scores`` recomputes with HEAD's code (design §9, case 3). Run mode: a
    clean tree (check 6), so the fix, the results and the log are all committed. Dry mode: the
    code, pyproject and lock unchanged; results/H-dryrun/ may be uncommitted."""
    if mode == "run":
        try:
            checks.check_clean()
        except checks.RefusedError as e:
            raise checks.RefusedError(
                f"{e}. report --from-scores recomputes with HEAD's code: commit the crash fix, "
                "results/H-confirmatory/ (with any earlier recomputed-*/) and the log first "
                "(design §9, case 3)") from e
        return
    dirty = checks.git(*checks.NO_EXCLUDES, "status", "--porcelain", "--untracked-files=all",
                       "--", "src", "pyproject.toml", checks.LOCK_REL)
    if dirty:
        raise checks.RefusedError(f"the code differs from HEAD's: {dirty.splitlines()[:10]}; "
                                  "commit it before recomputing")


def cmd_report(args) -> int:
    """Design §9, case 3: rebuild every table from the sealed stores, with no guarded call,
    into recomputed-<HEAD>/, and compare each with the original run's."""
    work = Path(args.from_scores).resolve()
    roots = {"run": Path(RUN_ROOT).resolve(), "dry": Path(DRY_ROOT).resolve()}
    mode = next((m for m, root in roots.items() if work.parent == root), None)
    if mode is None:
        raise checks.RefusedError(f"{work} is not a work directory: {roots['run']}/<tag commit> "
                                  f"or {roots['dry']}/<head>")
    ctx = (run_context if mode == "run" else dry_context)(work.name, args.jobs)
    if Path(ctx.work).resolve() != work:
        raise checks.RefusedError(f"{work} is not the {mode} context's {ctx.work}")
    head = _head()
    extra: dict = {"mode": mode, "command": report.RECOMPUTED, "head": head,
                   "recomputed_from": str(work)}
    if mode == "run":
        h1, entry = _case3_line(work)
        _on_h1(ctx, h1)
        extra.update(tag_commit=work.name, hash_commit=h1, unseal_entry=entry)
    else:
        h1 = next((r.get("hash_commit") for r in read_progress(work)
                   if r.get("event") == "sealing"), None)
        extra["hash_commit"] = h1
    if h1 is not None:
        extra.update(log_oneline=checks.git("log", "--oneline", f"{h1}..{head}"),
                     diff_stat=checks.git("diff", "--stat", f"{h1}..{head}"))
    sealing = next((r for r in read_progress(work) if r.get("event") == "sealing"), {})
    if mode == "run" and "facts" not in sealing:
        raise checks.RefusedError(f"{work}'s 'sealing' record holds no step-2 facts")
    extra["run_facts"] = sealing.get("facts")
    original = results_dir(ctx)
    out = original / f"recomputed-{head[:12]}"
    if out.exists():
        raise checks.RefusedError(f"{out} exists: one recomputation per commit, never overwritten")
    _code_clean(mode)                                                   # check 6, or the code
    checks.check_import()                                               # check 7
    env = checks.check_environment(checks._blob(head, checks.LOCK_REL), None, head)   # check 8
    s4, sc = Store(work / STEP4), Store(work / SCORES)
    if not (s4.sealed and sc.sealed):
        raise checks.RefusedError("both stores must be sealed before a recomputation")
    files = _forecast_files(ctx)
    _rehash(ctx, files, h1)
    fits = _fits(ctx, h1)
    facts = {**env, "nhs_ae_file": str(Path(nhs_ae.__file__).resolve()), **_provenance(head)}
    before = seal.worktree_logs()
    witness = seal.witness_path()
    acct = seal.Accounting({**before, witness: seal.line_count(witness)},
                           Path(splits.UNSEAL_LOG).resolve())
    exc = None
    try:
        with _no_guarded_calls():
            _, md = _analyse_and_write(ctx, s4, sc, files, fits, facts, extra, out,
                                       original=original / report.TABLES)
    except BaseException as e:
        exc = e
        raise
    finally:
        acct.settle(False, exc)                                       # zero new lines anywhere
    print(md)
    if mode == "dry" and not report.reproduced(pd.read_csv(out / report.RECOMPUTATION_CHECK)):
        print(f"\n{report.RECOMPUTED} does not reproduce the dry run byte for byte (design §10); "
              f"see {out / report.RECOMPUTATION_CHECK}")
        return 1
    if mode == "run":
        msg = f"Stage H: recomputed results, {report.RECOMPUTED} (design §9, case 3)"
        print(f"\nNext, by hand, once the summary has been read (design §9, case 3):\n"
              f"  {_commit_command(_rel(original), message=msg)}\n"
              "  git tag -a conf-run-v1 -m 'Stage H run' <that commit>\n"
              "  git push origin conf-run-v1")
    return 0


# ---- pre-tag commands --------------------------------------------------------------------
def cmd_pin(args) -> int:
    with tempfile.TemporaryDirectory(prefix="stage_h_pin_") as tmp:
        pins = checks.make_pins(tmp)
    path = checks.write_pins(pins)
    print(f"wrote {path}; commit it before the tag and copy the hashes into the plan's P5 row")
    return 0


def _prepare_copies(sources: dict) -> dict:
    """``prepare`` without --dev-side: checks 6-8 first (``checks.prepare_facts``), then the 13
    pool and M2 files, each checked against its P5 origin set (M2's against E-m2-rerun69's
    SHA-256), copied read-only and hashed before and after. prepare.json records dev_side
    false, which pin refuses (design §8); the dry run can read the copies."""
    inputs = checks._root() / checks.INPUTS_REL
    if checks._tag_commit() is not None:
        raise checks.RefusedError(f"prepare: {TAG} exists; inputs are prepared before the tag")
    if inputs.exists() and any(inputs.iterdir()):
        raise checks.RefusedError(f"prepare: {inputs} is not empty: move it aside first")
    sources = {str(n): Path(p) for n, p in sources.items()}
    if set(sources) != checks.COPIED_INPUTS:
        raise checks.RefusedError(f"prepare: the sources are not design §8's "
                                  f"{len(checks.COPIED_INPUTS)} pool and M2 inputs")
    facts = checks.prepare_facts(_head())                                       # checks 6-8
    pins = {n: checks._input_pin(src.parent, src.name, "prepare") for n, src in sorted(sources.items())}
    problems = checks._p5_problems(pins)                            # origin sets, M2's SHA-256
    if problems:
        raise checks.RefusedError(f"prepare: {'; '.join(problems)}")
    for n, src in sorted(sources.items()):
        dst = inputs / n
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        os.chmod(dst, checks.READ_ONLY)
        if file_sha(dst) != pins[n]["sha256"]:
            raise checks.RefusedError(f"prepare: the copy of {src} differs from the SHA-256 "
                                      "taken before copying it")
    record = {**facts, "dev_side": False, "sources": {n: pins[n]["sha256"] for n in sorted(pins)},
              "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (inputs / "SHA256SUMS").write_text("".join(f"{s}  {n}\n" for n, s in record["sources"].items()))
    (inputs / checks.PREPARE_RECORD).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    for name in ("SHA256SUMS", checks.PREPARE_RECORD):
        os.chmod(inputs / name, checks.READ_ONLY)
    return record


def cmd_prepare(args) -> int:
    """Design §8. With --dev-side, ``checks.prepare_inputs`` in full: checks 6-8, the 13 copies
    verified, the DEV side generated on a P4 rebuild, and the prepare.json pin reads. Without
    it, the copies alone, and a prepare.json that pin refuses."""
    sources = steps.input_paths()
    record = (checks.prepare_inputs(sources, args.jobs) if args.dev_side
              else _prepare_copies(sources))
    print(f"prepared {len(record['sources'])} input files in {INPUTS} at {record['commit'][:12]}"
          + ("" if record["dev_side"] else ", without the DEV side: pin refuses them (design §8)"))
    return 0


def cmd_preflight(args) -> int:
    facts = checks.preflight()
    print(json.dumps(facts, indent=1, default=str))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m nhs_ae.evaluate.stage_h")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pin")
    pp = sub.add_parser("prepare")
    pp.add_argument("--dev-side", action="store_true")
    sub.add_parser("preflight")
    for name in ("dry-run", "run", "report", "prepare"):
        sp = sub.choices.get(name) or sub.add_parser(name)
        sp.add_argument("--jobs", type=int, default=8)
    sub.choices["run"].add_argument("--unseal-token-file", required=True)
    sub.choices["run"].add_argument("--amendment", default=None)
    sub.choices["report"].add_argument("--from-scores", required=True)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return {"pin": cmd_pin, "prepare": cmd_prepare, "preflight": cmd_preflight,
            "dry-run": cmd_dry_run, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
