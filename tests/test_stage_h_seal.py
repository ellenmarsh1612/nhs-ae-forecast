"""Stage H seal mechanics (design §2.2, §2.3, §2.6, §2.7, §11 "Seal"), on synthetic frames with
a faked tag: no real token, tag, log or outturn is used."""

from __future__ import annotations

import concurrent.futures
import json
import multiprocessing
import multiprocessing.process
import os
import subprocess
import sys
import time

import pandas as pd
import pytest

from nhs_ae.evaluate import harness, splits
from nhs_ae.evaluate.splits import SealedOriginError
from nhs_ae.evaluate.stage_h import seal
from nhs_ae.evaluate.stage_h.common import CONF21, DEV, DRY
from nhs_ae.models.base import QUANTILES

TAG, H1 = "a" * 40, "b" * 40
RUN_ARGV = ["/repo/src/nhs_ae/evaluate/stage_h/__main__.py", "run", "--unseal-token-file", "tok"]


@pytest.fixture(autouse=True)
def processes_restored(monkeypatch):
    """open_seal installs the post-unseal tripwire; every test here undoes it afterwards."""
    monkeypatch.setattr(multiprocessing.process.BaseProcess, "start",
                        multiprocessing.process.BaseProcess.start)
    monkeypatch.setattr(concurrent.futures.ProcessPoolExecutor, "__init__",
                        concurrent.futures.ProcessPoolExecutor.__init__)


@pytest.fixture
def tag(monkeypatch, tmp_path):
    """The tests/test_splits.py pattern: conf-plan-v1 faked at a known commit with the unseal
    context granted (splits' P11 seam; tests/test_splits.py runs it for real), the log in
    tmp_path; also the witness in tmp_path and argv naming the run command."""
    monkeypatch.setattr(splits, "_tag_commit", lambda tag="conf-plan-v1": TAG)
    monkeypatch.setattr(splits, "_head_commit", lambda: H1)
    monkeypatch.setattr(splits, "_context_problems", lambda token, amendment: [])
    monkeypatch.setattr(splits, "UNSEAL_LOG", tmp_path / "unseal_log.jsonl")
    monkeypatch.setattr(splits, "_logged_tokens", set())
    monkeypatch.setattr(splits, "_unseal_context", {})
    witness = tmp_path / "common" / "nhs_ae" / "unseal_witness.jsonl"
    monkeypatch.setattr(seal, "witness_path", lambda: witness)
    monkeypatch.setattr(sys, "argv", RUN_ARGV)
    return TAG


def _log():
    return splits.UNSEAL_LOG.read_text().splitlines() if splits.UNSEAL_LOG.exists() else []


def _forecasts(origins, horizons=range(1, 7)) -> pd.DataFrame:
    """Long synthetic forecasts for one series: period = origin + h - 1 months."""
    rows = []
    for o in origins:
        for h in horizons:
            period = pd.Timestamp(o) + pd.DateOffset(months=h - 1)
            rows += [{"origin": pd.Timestamp(o), "mode": "asof", "model": "m",
                      "level": "provider", "target": "att_all", "series": "A", "horizon": h,
                      "period": period, "scale": 5.0, "quantile": q, "value": 90 + 20 * q}
                     for q in QUANTILES]
    return pd.DataFrame(rows)


# ---- open_seal -------------------------------------------------------------------------
def test_open_seal_writes_one_line_witnesses_it_and_trips(tag):
    entry = seal.open_seal(CONF21, tag, H1)
    lines = _log()
    assert len(lines) == 1 and json.loads(lines[0]) == entry
    assert (entry["token"], entry["head"], entry["sealed_rows"]) == (TAG, H1, 21)
    assert entry["origins"] == ["2024-01-01", "2025-09-01"] and seal.names_run(entry["argv"])
    assert seal.witness_path().read_text().splitlines() == lines
    with pytest.raises(seal.SealError, match="no process may start"):
        multiprocessing.get_context("spawn").Process(target=time.sleep, args=(0,)).start()
    with pytest.raises(seal.SealError, match="logged before"):     # a second guarded call
        seal.open_seal(CONF21, tag, H1)
    assert len(_log()) == 1


PRIOR = json.dumps({"timestamp": "2026-10-01T10:00:00+00:00", "token": TAG})
REFUSALS = {"head": "HEAD is", "origins": "exactly the 21 CONF origins",
            "dev_origins": "exactly the 21 CONF origins", "argv": "sys.argv",
            "logged": "logged before", "none": "needs the token",
            "unterminated": "does not end with a newline", "garbled": r"\[2\] do not parse"}


@pytest.mark.parametrize("change", list(REFUSALS))
def test_open_seal_refuses_before_writing(tag, monkeypatch, change):
    head, origins, token, prior = H1, CONF21, tag, ""
    if change == "head":
        head = "c" * 40
    elif change == "origins":
        origins = CONF21[:-1]
    elif change == "dev_origins":
        origins = DEV[-21:]
    elif change == "argv":
        monkeypatch.setattr(sys, "argv", ["pytest", "tests"])
    elif change == "logged":
        splits._logged_tokens.add("x" * 40)
    elif change == "none":
        token = None
    elif change == "unterminated":               # a hand-edited log: the entry would join it
        prior = PRIOR
    else:
        prior = PRIOR + "\n{truncated\n"
    if prior:
        splits.UNSEAL_LOG.write_text(prior)
    with pytest.raises(seal.SealError, match=REFUSALS[change]) as info:
        seal.open_seal(origins, token, head)
    assert type(info.value) is seal.SealError and not hasattr(info.value, "unsealed")
    assert "\n".join(_log()) == prior.rstrip("\n") and not seal.witness_path().exists()
    assert splits._logged_tokens == ({"x" * 40} if change == "logged" else set())
    assert splits._unseal_context == {}


def test_open_seal_passes_the_amendment_to_splits(tag, monkeypatch):
    """The guarded call hands --amendment to splits' context check, which keeps it, with the
    validated head, for every later tokened call of the run."""
    calls = []
    monkeypatch.setattr(splits, "_context_problems",
                        lambda token, amendment: calls.append((token, amendment)) or [])
    entry = seal.open_seal(CONF21, tag, H1, amendment="Stage H rerun 1")
    assert calls == [(TAG, "Stage H rerun 1")] and entry["head"] == H1
    assert splits._unseal_context[TAG]["head"] == H1
    assert splits._unseal_context[TAG]["amendment"] == "Stage H rerun 1"
    splits.assert_not_sealed(CONF21, tag)                  # a later call: the context holds
    assert calls == [(TAG, "Stage H rerun 1")] and len(_log()) == 1


def test_open_seal_writes_nothing_when_splits_refuses_the_context(tag, monkeypatch):
    monkeypatch.setattr(splits, "_context_problems", lambda token, amendment: ["HEAD is not H1"])
    with pytest.raises(SealedOriginError, match="HEAD is not H1") as info:
        seal.open_seal(CONF21, tag, H1)
    assert not hasattr(info.value, "unsealed") and _log() == []
    assert not seal.witness_path().exists()
    assert splits._logged_tokens == set() and splits._unseal_context == {}


def test_open_seal_checks_the_logged_line(tag, monkeypatch):
    heads = iter([H1, "d" * 40])            # HEAD moves between the pre-check and the call
    monkeypatch.setattr(splits, "_head_commit", lambda: next(heads))
    acct = seal.Accounting({splits.UNSEAL_LOG: 0}, splits.UNSEAL_LOG)
    unsealed = False
    with pytest.raises(seal.SealAccountingError, match="head") as info:
        try:
            seal.open_seal(CONF21, tag, H1)
            unsealed = True
        except BaseException as exc:
            acct.settle(unsealed, exc)
            raise
    lines = _log()
    assert len(lines) == 1 and json.loads(lines[0])["head"] == "d" * 40
    assert seal.witness_path().read_text().splitlines() == lines     # witnessed all the same
    # the call returned, so its one line is expected although the caller's flag was never set
    assert info.value.unsealed is True and not getattr(info.value, "__notes__", None)
    assert len(acct.verify(False)) == 1
    wrapped = RuntimeError("step 4 failed")                  # re-raised from it: still read
    wrapped.__cause__ = info.value
    assert acct.settle(False, wrapped) == [] and not getattr(wrapped, "__notes__", None)


def test_open_seal_after_prior_lines(tag):
    """An --amendment rerun, k = 1: only the new bytes reach the witness, and a witness whose
    last line lacks its newline gets one first."""
    splits.UNSEAL_LOG.write_text(PRIOR + "\n")
    witness = seal.witness_path()
    witness.parent.mkdir(parents=True)
    witness.write_text(PRIOR)
    entry = seal.open_seal(CONF21, tag, H1)
    lines = _log()
    assert lines[0] == PRIOR and len(lines) == 2 and json.loads(lines[1]) == entry
    assert witness.read_text() == PRIOR + "\n" + lines[1] + "\n"


def test_names_run():
    assert seal.names_run(RUN_ARGV) and seal.names_run(tuple(RUN_ARGV[:2]))
    for argv in (["tests/test_stage_h_seal.py", "run"], ["scripts/stage_h_debug.py", "run"],
                 ["/repo/src/nhs_ae/evaluate/stage_h/__main__.py", "dry-run"],
                 ["/repo/src/nhs_ae/evaluate/stage_h_run/__main__.py", "run"],
                 ["/repo/src/other/evaluate/stage_h/__main__.py", "run"],
                 RUN_ARGV[:1], "run", None):
        assert not seal.names_run(argv), argv


def test_open_seal_refuses_in_a_child_process(tag, monkeypatch, tmp_path):
    monkeypatch.setattr(multiprocessing, "parent_process", lambda: object())
    with pytest.raises(seal.SealError, match="parent process"):
        seal.open_seal(CONF21, tag, H1)
    (tmp_path / "token").write_text(TAG)
    with pytest.raises(seal.SealError, match="parent process"):
        seal.read_token(tmp_path / "token")
    with pytest.raises(seal.SealError, match="parent process"):
        seal.score(_forecasts([DEV[0]], [1]), pd.DataFrame(), "dev")
    assert _log() == []


def test_open_seal_refuses_with_live_children(tag):
    child = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(60,))
    child.start()
    try:
        with pytest.raises(seal.SealError, match="alive"):
            seal.open_seal(CONF21, tag, H1)
    finally:
        child.terminate()
        child.join()
    assert _log() == []


# ---- accounting ------------------------------------------------------------------------
def test_accounting(tag, tmp_path):
    here, other = splits.UNSEAL_LOG, tmp_path / "other" / "results" / "unseal_log.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("")
    acct = seal.Accounting({here: 0, other: 0}, here)

    # the guarded call raises before writing: n0 lines are accepted, the original surfaces
    unsealed = False
    with pytest.raises(SealedOriginError) as info:
        try:
            seal.open_seal(CONF21, "f" * 40, H1)
            unsealed = True
        except BaseException as exc:
            acct.settle(unsealed, exc)
            raise
    assert not getattr(info.value, "__notes__", None) and not hasattr(info.value, "unsealed")
    assert acct.verify(False) == [] and len(acct.verify(True)) == 1

    seal.open_seal(CONF21, tag, H1)                    # n0 + 1 after an unseal
    assert acct.verify(True) == [] and len(acct.verify(False)) == 1
    with pytest.raises(seal.SealAccountingError):     # body succeeded: accounting raises
        acct.settle(False)
    crash = RuntimeError("crash in step 5")           # exception in flight: a note instead
    assert acct.settle(False, crash) and "unseal accounting" in crash.__notes__[0]

    other.write_text(json.dumps({"token": TAG}) + "\n")         # another worktree's log changes
    assert [p for p in acct.verify(True) if str(other.resolve()) in p]
    other.write_text("")
    with here.open("a") as fh:
        fh.write("{truncated\n")
    problems = acct.verify(True)
    assert any("do not parse" in p for p in problems) and any("2 lines" in p for p in problems)


def test_accounting_needs_here_among_the_counted_logs(tmp_path):
    with pytest.raises(ValueError):
        seal.Accounting({tmp_path / "a.jsonl": 0}, tmp_path / "b.jsonl")


def test_accounting_never_replaces_the_exception_in_flight(tag, tmp_path):
    here = splits.UNSEAL_LOG
    here.write_bytes(PRIOR.encode() + b"\n\xff\xfe\n")        # a byte that is not UTF-8
    acct = seal.Accounting({here: 2}, here)
    assert [p for p in acct.verify(False) if "[2] do not parse" in p]    # flagged, not raised

    unreadable = tmp_path / "a_directory"
    unreadable.mkdir()
    acct = seal.Accounting({here: 2, unreadable: 0}, here)
    with pytest.raises(RuntimeError, match="original crash") as info:
        try:
            raise RuntimeError("original crash in step 5")
        except BaseException as exc:
            acct.settle(False, exc)
            raise
    assert "unseal accounting could not run" in info.value.__notes__[0]
    with pytest.raises(seal.SealAccountingError, match="could not run"):
        acct.settle(False)


def _git(cwd, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                   cwd=cwd, env=env, check=True, capture_output=True)


def test_worktree_logs_and_witness_path(tmp_path, monkeypatch):
    for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
                "GIT_OBJECT_DIRECTORY"):          # git must act on the temporary repository
        monkeypatch.delenv(var, raising=False)
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    _git(main, "init", "-q")
    _git(main, "commit", "-q", "--allow-empty", "-m", "start")
    _git(main, "worktree", "add", "-q", str(wt))
    log = main / "results" / "unseal_log.jsonl"
    log.parent.mkdir()
    log.write_text('{"n": 1}\n{"n": 2}\n')
    monkeypatch.setattr(splits, "UNSEAL_LOG", log)
    expected = {log.resolve(): 2, (wt / "results" / "unseal_log.jsonl").resolve(): 0}
    assert seal.worktree_logs(main) == seal.worktree_logs(wt) == expected
    common = (main / ".git").resolve() / "nhs_ae" / "unseal_witness.jsonl"
    assert seal.witness_path(main) == seal.witness_path(wt) == common


# ---- token and processes ---------------------------------------------------------------
def test_read_token(tmp_path, monkeypatch):
    f = tmp_path / "token"
    f.write_text(f"  {TAG}  \nignored\n")
    assert seal.read_token(f) == TAG
    (tmp_path / "empty").write_text("")
    with pytest.raises(seal.SealError, match="empty"):
        seal.read_token(tmp_path / "empty")
    monkeypatch.setenv("SOME_VARIABLE", TAG)
    with pytest.raises(seal.SealError, match="os.environ"):
        seal.read_token(f)
    monkeypatch.delenv("SOME_VARIABLE")
    monkeypatch.setattr(sys, "argv", ["prog", f"--token={TAG}"])
    with pytest.raises(seal.SealError, match="sys.argv"):
        seal.read_token(f)


def test_forbid_processes():
    seal.forbid_processes()
    with pytest.raises(seal.SealError):
        concurrent.futures.ProcessPoolExecutor(1)
    with pytest.raises(seal.SealError):       # the name harness imported before the tripwire
        harness.ProcessPoolExecutor(1)
    with pytest.raises(seal.SealError):
        multiprocessing.Process(target=time.sleep, args=(0,)).start()
    with pytest.raises(seal.SealError):
        multiprocessing.get_context("spawn").Process(target=time.sleep, args=(0,)).start()


def _worker_view():
    return list(sys.argv), dict(os.environ)


def test_spawned_worker_sees_no_token(tmp_path, monkeypatch):
    (tmp_path / "token").write_text(TAG + "\n")
    monkeypatch.setattr(sys, "argv", [*sys.argv, "--canary-argv"])
    monkeypatch.setenv("NHS_AE_CANARY", "canary-env")
    token = seal.read_token(tmp_path / "token")
    ctx = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(1, mp_context=ctx) as pool:
        argv, env = pool.submit(_worker_view).result()
    assert "--canary-argv" in argv and env["NHS_AE_CANARY"] == "canary-env"   # channels live
    assert not any(token in a for a in argv) and not any(token in v for v in env.values())


# ---- scoring ---------------------------------------------------------------------------
@pytest.fixture
def spy(monkeypatch):
    """harness.score_forecasts replaced: nothing is scored, calls are recorded."""
    calls = []

    def fake(forecasts, truth, unseal_token=None):
        calls.append((len(forecasts), unseal_token))
        return forecasts.iloc[:0], {}

    monkeypatch.setattr(harness, "score_forecasts", fake)
    return calls


def test_score_checks_split_token_and_origins(tag, spy):
    dev, conf, truth = _forecasts([DEV[-1]], [1]), _forecasts([CONF21[0]], [1]), pd.DataFrame()
    mixed = pd.concat([conf, dev], ignore_index=True)
    with pytest.raises(seal.SealError, match="outside DEV"):
        seal.score(conf, truth, "dev")
    with pytest.raises(seal.SealError, match="without the token"):
        seal.score(dev, truth, "dev", tag)
    with pytest.raises(seal.SealError, match="with the token"):
        seal.score(conf, truth, "conf")
    with pytest.raises(seal.SealError, match="before open_seal"):
        seal.score(conf, truth, "conf", tag)
    with pytest.raises(seal.SealError, match="outside DEV"):          # burn-in is never scored
        seal.score(_forecasts(["2017-07-01"], [1]), truth, "dev")
    with pytest.raises(ValueError):
        seal.score(dev, truth, "prospective")
    assert spy == [] and _log() == []

    seal.open_seal(CONF21, tag, H1)
    with pytest.raises(seal.SealError, match="outside CONF"):
        seal.score(dev, truth, "conf", tag)
    with pytest.raises(seal.SealError, match="outside CONF"):
        seal.score(mixed, truth, "conf", tag)
    assert spy == []
    seal.score(dev, truth, "dev")
    seal.score(conf, truth, "conf", tag)
    assert spy == [(9, None), (9, tag)]


def test_score_refuses_a_sealed_period_in_dev_output(monkeypatch):
    monkeypatch.setattr(harness, "score_forecasts", lambda f, t, u=None: (f, {}))
    with pytest.raises(seal.SealError, match="sealed target period"):
        seal.score(_forecasts([DEV[-1]], [2]), pd.DataFrame(), "dev")


def test_dry_run_embargo_pairs():
    fc = _forecasts(DRY)
    pairs = seal.embargo_pairs(fc)
    later = {(pd.Timestamp(o), h) for o in DRY for h in range(1, 7)
             if pd.Timestamp(o) + pd.DateOffset(months=h - 1) >= pd.Timestamp("2024-01-01")}
    assert pairs == later and len(pairs) == 15 and len(fc[["origin", "horizon"]].drop_duplicates()) == 36
    # the real harness on synthetic outturns drops exactly those pairs
    periods = pd.date_range("2023-07-01", "2024-06-01", freq="MS")
    truth = pd.DataFrame({"period": periods, "series": "A", "target": "att_all",
                          "level": "provider", "y": 100.0})
    scored, dropped = seal.score(fc, truth, "dev")
    assert dropped["embargoed"] == 15 and len(scored) == 21
    assert not set(zip(scored["origin"], scored["horizon"])) & pairs
    assert scored["period"].max() < pd.Timestamp("2024-01-01")
