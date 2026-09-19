"""The DEV/CONF split and the sealed-origin guard (amendment of 2026-09-10), with P11's
unseal context and post-run state on temporary git repositories (tests/test_seal_rules.py's
builders): conf-plan-v1 and conf-run-v1 are only ever created inside those."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date

import numpy as np
import pandas as pd
import pytest
from test_seal_rules import (
    PLAN,
    RESULTS,
    RUN,
    RUN_ARGV,
    TITLE,
    TS,
    TS_STRAY,
    SealRepo,
    completed,
    make_repo,
    row,
)

from nhs_ae.config import PROJECT_ROOT as REAL_ROOT
from nhs_ae.evaluate import seal_rules, splits
from nhs_ae.evaluate.harness import score_forecasts
from nhs_ae.evaluate.metrics import score_rows
from nhs_ae.evaluate.splits import (
    SealedOriginError,
    assert_not_sealed,
    drop_sealed,
    sealed_mask,
    split_origins,
)
from nhs_ae.models.base import QUANTILES

SEALED = split_origins("conf")
REAL_IMPORT_PROBLEMS = splits._import_problems
REAL_FSYNC = os.fsync


@pytest.fixture
def tag(monkeypatch, tmp_path):
    """Pretend conf-plan-v1 exists at a known commit, with the unseal context granted (the
    seam P11 names); log to a temp file."""
    monkeypatch.setattr(splits, "_tag_commit", lambda tag="conf-plan-v1": "a" * 40)
    monkeypatch.setattr(splits, "_head_commit", lambda: "b" * 40)
    monkeypatch.setattr(splits, "_context_problems", lambda token, amendment: [])
    monkeypatch.setattr(splits, "UNSEAL_LOG", tmp_path / "unseal_log.jsonl")
    monkeypatch.setattr(splits, "_logged_tokens", set())
    monkeypatch.setattr(splits, "_unseal_context", {})
    return "a" * 40


def _scored(origins, periods):
    rows = [{**{q: 90 + 20 * q for q in QUANTILES}, "y": 100.0, "origin": pd.Timestamp(o),
             "period": pd.Timestamp(p)} for o, p in zip(origins, periods)]
    return pd.DataFrame(rows)


def test_split_ranges():
    dev, conf = split_origins("dev"), split_origins("conf")
    assert (dev[0], dev[-1], len(dev)) == (date(2018, 4, 1), date(2023, 12, 1), 69)
    assert (conf[0], conf[-1], len(conf)) == (date(2024, 1, 1), date(2025, 9, 1), 21)
    with pytest.raises(ValueError):
        split_origins("test")


def test_dev_origins_pass_and_conf_origins_raise():
    assert_not_sealed(split_origins("dev"))
    with pytest.raises(SealedOriginError):
        assert_not_sealed([date(2023, 12, 1), date(2024, 1, 1)])


def test_sealed_mask_covers_origins_and_target_periods():
    f = _scored(["2023-06-01", "2023-12-01", "2024-03-01", "2026-10-01"],
                ["2023-08-01", "2024-02-01", "2024-05-01", "2027-01-01"])
    # DEV origin with a 2024 target is sealed; the prospective origin is not
    assert sealed_mask(f).tolist() == [False, True, True, False]
    assert len(drop_sealed(f)) == 2


def test_score_rows_refuses_sealed_rows_without_token():
    with pytest.raises(SealedOriginError):
        score_rows(_scored(["2024-06-01"], ["2024-08-01"]))
    assert len(score_rows(_scored(["2023-06-01"], ["2023-08-01"]))) == 1


def test_unseal_needs_the_tag_commit_and_logs_once(tag):
    f = _scored(["2024-06-01", "2025-09-01"], ["2024-08-01", "2026-02-01"])
    with pytest.raises(SealedOriginError):
        score_rows(f, unseal_token="not-the-tag")
    score_rows(f, unseal_token=tag)
    score_rows(f, unseal_token=tag)                       # second call in the same process
    lines = splits.UNSEAL_LOG.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["token"] == tag and entry["origins"] == ["2024-06-01", "2025-09-01"]


def test_unseal_without_tag_raises(monkeypatch):
    monkeypatch.setattr(splits, "_tag_commit", lambda tag="conf-plan-v1": None)
    with pytest.raises(SealedOriginError, match="does not exist"):
        assert_not_sealed([date(2024, 1, 1)], unseal_token="a" * 40)


def test_score_forecasts_embargoes_dev_targets_in_the_sealed_window():
    rows = []
    for period in ("2023-12-01", "2024-01-01"):          # origin 2023-12, horizons 1 and 2
        for q in QUANTILES:
            rows.append({"origin": pd.Timestamp("2023-12-01"), "mode": "asof", "model": "m",
                         "level": "provider", "target": "att_all", "series": "A",
                         "horizon": 1 if period.startswith("2023") else 2,
                         "period": pd.Timestamp(period), "scale": 5.0, "quantile": q,
                         "value": 90 + 20 * q})
    fc = pd.DataFrame(rows)
    truth = pd.DataFrame({"period": pd.to_datetime(["2023-12-01", "2024-01-01"]),
                          "series": "A", "y": [100.0, 101.0], "target": "att_all",
                          "level": "provider"})
    scored, dropped = score_forecasts(fc, truth)
    assert len(scored) == 1 and dropped["embargoed"] == 1
    assert np.isfinite(scored["wis"]).all()
    with pytest.raises(SealedOriginError):              # a CONF origin is refused outright
        score_forecasts(fc.assign(origin=pd.Timestamp("2024-02-01")), truth)


def test_rows_outside_the_seal_return_before_any_git_call(monkeypatch):
    def never(*args, **kwargs):
        raise AssertionError("rows outside the seal reached a git call or a seam")
    for name in ("_post_run", "_tag_commit", "_head_commit", "_context_problems"):
        monkeypatch.setattr(splits, name, never)
    monkeypatch.setattr(seal_rules, "_git", never)
    assert_not_sealed(split_origins("dev"))
    assert_not_sealed(split_origins("dev"), "a" * 40, amendment=TITLE)
    assert_not_sealed(_scored(["2023-06-01"], ["2023-08-01"]), "a" * 40)


# ---- P11: the unseal context, on a temporary repository ----------------------------------
@pytest.fixture
def repo(tmp_path, monkeypatch) -> SealRepo:
    """splits pointed at a temporary repository (its tags, HEAD, tree and log), argv naming
    the run command, and a fresh process. nhs_ae is imported from this worktree, not the
    temporary one, so the import rule is stubbed; its own test runs it for real."""
    r = make_repo(tmp_path, monkeypatch)
    monkeypatch.setattr(splits, "PROJECT_ROOT", r.root)
    monkeypatch.setattr(splits, "UNSEAL_LOG", r.log)
    monkeypatch.setattr(splits, "_import_problems", list)
    monkeypatch.setattr(sys, "argv", list(RUN_ARGV))
    _new_process(monkeypatch)
    return r


def _new_process(monkeypatch) -> None:
    for name, empty in (("_logged_tokens", set()), ("_unseal_context", {}),
                        ("_post_run_cache", set())):
        monkeypatch.setattr(splits, name, empty)


def _lines(r: SealRepo) -> list[dict]:
    return [json.loads(x) for x in r.log.read_text().splitlines()] if r.log.exists() else []


def _refused(r: SealRepo, token, why: str, amendment: str | None = None) -> None:
    """The first tokened call refuses and leaves no trace: no log line, token or context."""
    before = r.log.read_bytes()
    with pytest.raises(SealedOriginError, match=why):
        assert_not_sealed(SEALED, token, amendment=amendment)
    assert r.log.read_bytes() == before
    assert splits._logged_tokens == set() and splits._unseal_context == {}


def test_the_hash_commit_unseals_once_per_process(repo):
    t = repo.tag(PLAN)
    h1 = repo.hash_commit()
    assert_not_sealed(SEALED, t)
    assert_not_sealed(_scored(["2023-12-01"], ["2024-01-01"]), t)          # a later call
    (entry,) = _lines(repo)
    assert (entry["token"], entry["head"], entry["sealed_rows"]) == (t, h1, 21)
    assert entry["origins"] == ["2024-01-01", "2025-09-01"] and entry["argv"] == RUN_ARGV
    assert splits._logged_tokens == {t}
    assert splits._unseal_context == {t: {"root": repo.root, "head": h1, "amendment": None}}


def _h1_child(r: SealRepo) -> None:
    r.hash_commit()
    r.write("src/fix.py", "x = 1\n")
    r.commit("a commit on the hash commit")


def _unrelated(r: SealRepo) -> None:
    r.git("checkout", "-q", "--orphan", "elsewhere")
    r.commit("unrelated history")
    r.hash_commit()


def _row_without_amendment(r: SealRepo) -> None:
    r.add_row(row())
    r.commit("the amendment row")
    r.hash_commit()


HEADS = {
    "the start commit itself": (lambda r: None, "itself, not the runner's hash commit"),
    "a child of the hash commit": (_h1_child, "HEAD's parent is not a start commit"),
    "a hash commit touching another path": (
        lambda r: r.hash_commit({"src/nhs_ae/x.py": "x = 1\n"}), "does more than add the hash"),
    "an unrelated commit": (_unrelated, "HEAD's parent is not a start commit"),
    "an amendment descendant's hash commit": (_row_without_amendment, "needs --amendment"),
}


@pytest.mark.parametrize("case", list(HEADS))
def test_a_head_other_than_the_hash_commit_on_the_tag_is_refused(repo, case):
    make, why = HEADS[case]
    t = repo.tag(PLAN)
    make(repo)
    _refused(repo, t, why)


def test_an_amendment_descendant_unseals_only_under_its_amendment(repo):
    t = repo.tag(PLAN)
    repo.add_row(row())
    repo.commit("the amendment row")
    _refused(repo, t, "HEAD's parent is not a start commit", amendment=TITLE)     # S itself
    h1 = repo.hash_commit()
    _refused(repo, t, "needs --amendment")
    _refused(repo, t, "0 §10 rows", amendment="Stage H rerun 2")
    _refused(repo, t, "already has a §10 row", amendment="Re-split by origin")
    assert_not_sealed(SEALED, t, amendment=TITLE)
    (entry,) = _lines(repo)
    assert entry["head"] == h1 and splits._unseal_context[t]["amendment"] == TITLE
    assert_not_sealed(SEALED, t)                                   # the amendment is remembered
    assert_not_sealed(SEALED, t, amendment=TITLE)
    with pytest.raises(SealedOriginError, match="is not the 'Stage H rerun 1'"):
        assert_not_sealed(SEALED, t, amendment="Stage H rerun 2")
    assert len(_lines(repo)) == 1 and splits._unseal_context[t]["amendment"] == TITLE


@pytest.mark.parametrize("argv", [["pytest", "tests"], [RUN_ARGV[0], "dry-run"],
                                  ["/w/scripts/stage_h.py", "run"], RUN_ARGV[:1]])
def test_the_process_must_be_the_stage_h_run(repo, monkeypatch, argv):
    t = repo.tag(PLAN)
    repo.hash_commit()
    monkeypatch.setattr(sys, "argv", argv)
    _refused(repo, t, "sys.argv does not name")


def test_the_tree_must_be_clean_outside_results_and_data(repo, tmp_path):
    t = repo.tag(PLAN)
    repo.hash_commit()
    excludes = tmp_path / "global-ignore"                  # the user's global excludes
    excludes.write_text(".DS_Store\n")
    repo.git("config", "core.excludesFile", str(excludes))
    for rel in ("notes.txt", "src/.DS_Store"):
        repo.write(rel, "x\n")
        _refused(repo, t, "not clean outside results/ and data/")
        (repo.root / rel).unlink()
    for rel in (f"{RESULTS}/d7_check.csv", "results/other.txt", "data/processed/x.parquet",
                "data/raw/new.csv"):
        repo.write(rel, "x\n")
    assert_not_sealed(SEALED, t)
    assert len(_lines(repo)) == 1


def test_nhs_ae_must_be_imported_from_project_root(repo, monkeypatch):
    t = repo.tag(PLAN)
    repo.hash_commit()
    monkeypatch.setattr(splits, "_import_problems", REAL_IMPORT_PROBLEMS)
    _refused(repo, t, "nhs_ae is imported from")           # this worktree's, not the repo's
    monkeypatch.setattr(splits, "PROJECT_ROOT", REAL_ROOT)
    assert splits._import_problems() == []                 # as the real run imports it


def test_later_calls_reuse_the_first_calls_context(repo, monkeypatch):
    """After the unseal only HEAD is checked again: clutter such as a .DS_Store appearing
    mid-run must not crash the run."""
    t = repo.tag(PLAN)
    repo.hash_commit()
    assert_not_sealed(SEALED, t)
    repo.write("src/.DS_Store", "x")
    monkeypatch.setattr(sys, "argv", ["pytest"])
    monkeypatch.setattr(splits, "_import_problems", lambda: ["imported from elsewhere"])
    calls = []
    monkeypatch.setattr(splits, "_context_problems", lambda *a: calls.append(a) or ["refused"])
    assert_not_sealed(SEALED, t)
    assert calls == [] and len(_lines(repo)) == 1


def test_a_head_moved_after_the_first_call_is_refused(repo):
    t = repo.tag(PLAN)
    h1 = repo.hash_commit()
    assert_not_sealed(SEALED, t)
    repo.write(f"{RESULTS}/confirmatory_results.md", "x\n")
    moved = repo.commit("a commit after the unseal")
    with pytest.raises(SealedOriginError, match=f"HEAD is {moved}"):
        assert_not_sealed(SEALED, t)
    repo.git("reset", "-q", "--soft", h1)
    assert_not_sealed(SEALED, t)                            # HEAD is the validated head again
    assert len(_lines(repo)) == 1


def test_a_failed_log_write_is_validated_again_never_passed(repo, monkeypatch):
    t = repo.tag(PLAN)
    repo.hash_commit()
    blocked = repo.root / "results" / "blocked"
    blocked.mkdir()
    monkeypatch.setattr(splits, "UNSEAL_LOG", blocked)     # a directory: the append fails
    for _ in range(2):                                     # and so does the retry
        with pytest.raises(IsADirectoryError):
            assert_not_sealed(SEALED, t)
        assert splits._logged_tokens == set() and splits._unseal_context == {}
    monkeypatch.setattr(splits, "UNSEAL_LOG", repo.log)

    def no_fsync(fd):
        raise OSError(5, "Input/output error")
    monkeypatch.setattr(os, "fsync", no_fsync)
    with pytest.raises(OSError, match="Input/output error"):
        assert_not_sealed(SEALED, t)
    monkeypatch.setattr(os, "fsync", REAL_FSYNC)
    assert len(_lines(repo)) == 1 and splits._logged_tokens == set()   # written, not recorded
    repo.write("notes.txt", "x\n")                          # the retry is checked again...
    with pytest.raises(SealedOriginError, match="not clean"):
        assert_not_sealed(SEALED, t)
    (repo.root / "notes.txt").unlink()
    assert_not_sealed(SEALED, t)                            # ...and logged again
    assert len(_lines(repo)) == 2 and splits._logged_tokens == {t}


def test_a_preloaded_logged_token_still_runs_the_context_check(repo):
    t = repo.tag(PLAN)
    splits._logged_tokens.add(t)
    with pytest.raises(SealedOriginError, match="itself"):
        assert_not_sealed(SEALED, t)
    assert splits._unseal_context == {} and _lines(repo) == []
    h1 = repo.hash_commit()
    assert_not_sealed(SEALED, t)
    assert _lines(repo) == [] and splits._unseal_context[t]["head"] == h1


# ---- P11: the post-run state (conf-run-v1) -----------------------------------------------
@pytest.fixture
def post_run(repo, real_post_run) -> SealRepo:
    """The temporary repository, with the real ``splits._post_run``."""
    return repo


def test_without_conf_run_v1_the_pre_run_rules_hold(post_run):
    c = completed(post_run, tag=False)
    assert not splits._post_run()
    with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
        assert_not_sealed(SEALED)
    with pytest.raises(SealedOriginError, match="not the runner's hash commit"):   # HEAD is R
        assert_not_sealed(SEALED, c["t"])
    assert _lines(post_run) == [c["entry"]]
    post_run.tag(RUN, c["run"], annotated=False)
    assert not splits._post_run()                          # a lightweight tag lifts nothing
    with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
        assert_not_sealed(SEALED)


def test_conf_run_v1_on_the_completed_run_passes_sealed_rows_without_a_line(post_run,
                                                                           monkeypatch):
    c = completed(post_run)
    monkeypatch.setattr(sys, "argv", ["/w/.venv/bin/nhs-ae-forecast"])     # a live calibration
    before = (post_run.log.read_bytes(), post_run.witness.read_bytes())
    assert splits._post_run()
    assert_not_sealed(SEALED)
    assert_not_sealed(_scored(["2023-12-01", "2025-09-01"], ["2024-01-01", "2026-02-01"]))
    assert_not_sealed(SEALED, c["t"])
    assert (post_run.log.read_bytes(), post_run.witness.read_bytes()) == before
    assert splits._logged_tokens == set() and splits._unseal_context == {}
    for token in ("f" * 40, c["h1"], c["run"]):
        with pytest.raises(SealedOriginError, match="never another token"):
            assert_not_sealed(SEALED, token)


def test_case_2_then_the_amendment_rerun_through_splits_reaches_the_post_run_state(
        post_run, monkeypatch):
    """Crash case 2 end to end: process 1 unseals at H1a and crashes; the fix commit F
    discloses its line; process 2 reruns from F with --amendment; step 6 commits R and
    conf-run-v1 tags it. The crashed run's line is a genuine hash commit's, and stays."""
    r = post_run
    t = r.tag(PLAN)
    h1a = r.hash_commit()
    assert_not_sealed(SEALED, t)                                            # process 1
    (earlier,) = _lines(r)
    r.append(r.witness, earlier)
    r.crash_fix(earlier["timestamp"])
    _new_process(monkeypatch)
    h1b = r.hash_commit()
    _refused(r, t, "needs --amendment")
    assert_not_sealed(SEALED, t, amendment=TITLE)                          # process 2
    kept, entry = _lines(r)
    assert kept == earlier and entry["head"] == h1b and h1a != h1b
    assert seal_rules.hash_commit_ok(r.root, h1a, t)[0]
    r.append(r.witness, entry)
    run = r.step6(entry)
    _new_process(monkeypatch)
    assert not splits._post_run()                                          # not yet tagged
    r.tag(RUN, run)
    assert splits._post_run()
    assert_not_sealed(SEALED)
    assert len(_lines(r)) == 2


def test_conf_run_v1_on_the_crash_fix_commit_keeps_the_seal(post_run):
    r = post_run
    r.tag(PLAN)
    h1a = r.hash_commit()
    r.unseal(r.line(h1a, TS))
    r.tag(RUN, r.crash_fix(TS))
    assert not splits._post_run()
    with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
        assert_not_sealed(SEALED)


@pytest.mark.parametrize("where", ["another worktree's log", "the witness", "this worktree's log"])
def test_an_undisclosed_line_keeps_the_seal_until_heads_row_discloses_it(post_run, tmp_path,
                                                                          where):
    r = post_run
    c = completed(r)
    other = tmp_path / "second"
    r.git("worktree", "add", "-q", "-b", "second", str(other), c["run"])
    assert splits._post_run() and splits._post_run()      # the second call from the cache
    path = {"another worktree's log": other / seal_rules.LOG_REL, "the witness": r.witness,
            "this worktree's log": r.log}[where]
    r.append(path, r.line(c["h1"], TS_STRAY))
    assert not splits._post_run()                          # the cached key no longer matches
    with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
        assert_not_sealed(SEALED)
    r.add_row(row(TS_STRAY, "Stray unseal line"))
    assert not splits._post_run()                          # a disclosure must be committed
    r.commit("disclose the stray unseal line")
    assert splits._post_run()
    assert_not_sealed(SEALED)


def test_a_git_failure_is_never_the_post_run_state(post_run, monkeypatch, tmp_path):
    completed(post_run)
    real = seal_rules._git

    def failing(root, *args, **kwargs):
        if "ls-tree" in args:
            raise subprocess.CalledProcessError(128, ["git", *args])
        return real(root, *args, **kwargs)

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    for broken in (failing, no_git):
        monkeypatch.setattr(seal_rules, "_git", broken)
        assert not splits._post_run()
        with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
            assert_not_sealed(SEALED)
    monkeypatch.setattr(seal_rules, "_git", real)
    assert splits._post_run()
    for root in (tmp_path / "absent", tmp_path):
        monkeypatch.setattr(splits, "PROJECT_ROOT", root)
        assert not splits._post_run()
        with pytest.raises(SealedOriginError, match="sealed confirmatory window"):
            assert_not_sealed(SEALED)
