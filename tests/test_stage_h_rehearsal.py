"""Stage H: the tokened rehearsal (design §11, "Seal"). Steps 4-6 of ``run`` for real, with a
real annotated ``conf-plan-v1`` tag and the runner's real hash commit, in a temporary git
repository, on a synthetic vintage table with real calendar dates (so the seal's windows are
live), and design §8's 21 inputs written as ``prepare --dev-side`` leaves them. Steps 2 and 3
are stubbed: neither has a tokened branch.

``splits`` is pointed at the temporary repository and its log; ``_tag_commit`` and
``_head_commit`` are NOT faked, so the token, the HEAD rule and the logged head come from real
git state, and the first tokened call's HEAD, argv and tree rules (P11) run for real. Only its
import rule is stubbed: the temporary repository imports nhs_ae from this worktree. The
post-run tests keep the real ``splits._post_run`` (conftest's ``real_post_run``) and tag
``conf-run-v1`` in the temporary repository. Tripwires refuse any pandas or pyarrow read of
the real ``data/processed``, ``data/raw`` or ``results/``, and the real worktrees' logs are
checked before and after.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pytest
from scipy import stats as sps
from test_stage_h_pools import MAPPING, REGIONS, _vintages

import nhs_ae.ingest.icb_mapping as im
from nhs_ae.calibrate import online
from nhs_ae.config import PROCESSED_DIR, PROJECT_ROOT
from nhs_ae.evaluate import asof, harness, metrics, seal_rules, splits, stage_d, stage_f
from nhs_ae.evaluate.asof import TARGETS
from nhs_ae.evaluate.stage_h import __main__ as runner
from nhs_ae.evaluate.stage_h import analysis, checks, common, generate, report, seal, steps, store
from nhs_ae.evaluate.stage_h.common import (
    CONF21,
    DEV,
    DEV_SIDE_ORIGINS,
    G1_BASES,
    HASH_FILES,
    K5,
    LEVELS,
    M2_INPUT,
    P5_INPUTS,
    POOL_ORIGINS,
    W5,
    ts,
)
from nhs_ae.ingest.recover import month_range
from nhs_ae.models.base import QUANTILES

M = pd.DateOffset(months=1)
Z = sps.norm.ppf(QUANTILES)
REAL_PROCESSED = Path(PROCESSED_DIR).resolve()
REAL_TREES = (REAL_PROCESSED, (Path(PROJECT_ROOT) / "data" / "raw").resolve(),
              (Path(PROJECT_ROOT) / "results").resolve())
PROVIDER_SERIES = ("RAA", "RBB", "RCC", "RDD", "RXX")
LEVEL_SERIES = {"provider": PROVIDER_SERIES, "icb": ("QAA", "QBB", "QCC"),
                "region": ("LONDON", "MIDLANDS"), "england": ("ENGLAND",)}
NAME = dict(common.NAMES)
# Each model sits at its own distance from the synthetic outturns, and final-mode forecasts
# above as-of ones, so no comparison is 0 by construction and a wiring error changes a number.
OFFSET = {"b0": 0.0, "b1": 0.04, "b2": -0.04, "m1": 0.12, "m1_v3_raw": 0.08, "m2": 0.06}
FINAL = 0.03
SEEDED_SPREAD = 0.1                     # the seeded DEV-side B1: identifiable by its spread
LOG = Path("results") / "unseal_log.jsonl"
CONF_DIR = Path("results") / "H-confirmatory"
GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")
RERUN = "Stage H rerun 1"               # the case-3 test's --amendment and its §10 row's title


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                          check=True).stdout.strip()


def _fc(key: str, level: str, origins, mode: str = "asof", spread: float = 0.08) -> pd.DataFrame:
    """Model ``key``'s forecasts, centred near the synthetic outturns' scale at its own offset,
    9 quantiles, h = 1-6."""
    base = {"att_all": 1200.0, "att_type1": 800.0, "adm_via_ae": 300.0}
    mult = {"provider": 1.0, "icb": 2.0, "region": 3.0, "england": 5.0}[level]
    shift = 1.0 + OFFSET[key] + (FINAL if mode == "final" else 0.0)
    rows = []
    for o in origins:
        o = ts(o)
        for t in TARGETS:
            for s in LEVEL_SERIES[level]:
                centre = base[t] * mult * shift
                for h in range(1, 7):
                    period = o - M + h * M
                    for q, z in zip(QUANTILES, Z):
                        rows.append((o, mode, NAME[key], level, t, s, h, period, float(q),
                                     float(centre * np.exp(spread * z)), 1.0))
    return pd.DataFrame(rows, columns=stage_f.COLS)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A temporary repository: tracked empty unseal log, ignored data/processed, an annotated
    conf-plan-v1 tag pushed to a bare origin; every runner path pointed into it."""
    for var in GIT_VARS:                        # a hook's git environment would name the real repo
        monkeypatch.delenv(var, raising=False)
    r = tmp_path / "repo"
    (r / "results").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / "results" / "unseal_log.jsonl").write_text("")
    (r / ".gitignore").write_text("data/processed/\n")
    (r / "docs" / "preregistration.md").write_text("# prereg\n\n## 10. Amendments\n\n| Date | Change | Why |\n|---|---|---|\n")
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.org")
    _git(r, "config", "user.name", "rehearsal")
    _git(r, "config", "core.excludesFile", "/dev/null")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "plan")
    _git(r, "tag", "-a", "conf-plan-v1", "-m", "plan tag")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(r, "remote", "add", "origin", str(bare))
    _git(r, "push", "-q", "origin", "conf-plan-v1")

    processed = r / "data" / "processed"
    monkeypatch.setattr(splits, "PROJECT_ROOT", r)
    monkeypatch.setattr(splits, "UNSEAL_LOG", r / "results" / "unseal_log.jsonl")
    monkeypatch.setattr(splits, "_logged_tokens", set())
    monkeypatch.setattr(splits, "_unseal_context", {})
    # nhs_ae is imported from this worktree, not the temporary repository's src/
    monkeypatch.setattr(splits, "_import_problems", list)
    for mod in (checks, seal):
        monkeypatch.setattr(mod, "PROJECT_ROOT", r)
    monkeypatch.setattr(common, "RUN_ROOT", processed / "stage_h")
    monkeypatch.setattr(common, "RESULTS", r / "results" / "H-confirmatory")
    monkeypatch.setattr(runner, "RUN_ROOT", processed / "stage_h")
    monkeypatch.setattr(runner, "DRY_ROOT", processed / "stage_h_dry")
    monkeypatch.setattr(runner, "PROJECT_ROOT", r)
    inputs = processed / "stage_h" / "inputs"
    monkeypatch.setattr(steps, "POOL", inputs / "pool")
    monkeypatch.setattr(steps, "DEV_SIDE", inputs / "dev_side" / "forecasts")
    monkeypatch.setattr(steps, "M2_DEV", inputs / M2_INPUT)
    monkeypatch.setattr(steps, "G1_REFERENCE", r / "no_reference.csv")
    monkeypatch.setattr(im, "load_reference", lambda *a, **k: MAPPING)
    monkeypatch.setattr("nhs_ae.features.hierarchy.icb_region_map", lambda *a, **k: REGIONS)
    monkeypatch.setattr(steps, "icb_region_map", lambda *a, **k: REGIONS)
    # forbid_processes() patches these two globally: register them so teardown restores them
    monkeypatch.setattr(multiprocessing.process.BaseProcess, "start",
                        multiprocessing.process.BaseProcess.start)
    monkeypatch.setattr(concurrent.futures.ProcessPoolExecutor, "__init__",
                        concurrent.futures.ProcessPoolExecutor.__init__)
    return r


def _real(path) -> bool:
    """``path`` names a file under the real data/processed, data/raw or results/."""
    if not isinstance(path, (str, os.PathLike)):
        return False                                    # a buffer or an open file
    p = Path(path).resolve()
    return any(p == t or t in p.parents for t in REAL_TREES)


@pytest.fixture
def tripwires(monkeypatch):
    """No pandas or pyarrow read of the real data/processed, data/raw or results/, and no
    vintage table outside the test's tree."""
    def refusing(real):
        def read(path, *a, **k):
            if _real(path):
                raise AssertionError(f"rehearsal read real data: {Path(path).resolve()}")
            return real(path, *a, **k)
        return read
    for mod, name in ((pd, "read_parquet"), (pd, "read_csv"), (pq, "read_table"),
                      (pq, "read_schema")):
        monkeypatch.setattr(mod, name, refusing(getattr(mod, name)))
    real_load = asof.load_vintages

    def load(path=None):
        if path is None or REAL_PROCESSED in Path(path).resolve().parents:
            raise AssertionError(f"rehearsal loaded a real vintage table: {path}")
        return real_load(path)
    monkeypatch.setattr(asof, "load_vintages", load)
    monkeypatch.setattr(runner, "load_vintages", load)


def _stub_steps_2_3(monkeypatch, repo: Path, vint: pd.DataFrame):
    def pre_run(ctx, token_file, amendment=None):
        ctx.vintages_path.parent.mkdir(parents=True, exist_ok=True)
        vint.to_parquet(ctx.vintages_path, index=False)
        return {"head": _git(repo, "rev-parse", "HEAD"), "tag_commit": splits._tag_commit(),
                "inputs": len(P5_INPUTS)}

    def dry_checks(ctx):
        ctx.vintages_path.parent.mkdir(parents=True, exist_ok=True)
        vint.to_parquet(ctx.vintages_path, index=False)
        return {"head": _git(repo, "rev-parse", "HEAD"), "pinned": False}

    def gen(ctx, *, vintage_sha=None):
        assert vintage_sha == common.file_sha(ctx.vintages_path)
        new, files = ctx.new_origins, {}
        for k in common.PROVIDER_MODELS:
            for mode in ("asof", "final"):
                p = generate.forecast_path(ctx, k, "provider", mode)
                p.parent.mkdir(parents=True, exist_ok=True)
                _fc(k, "provider", new, mode).to_parquet(p, index=False)
                files[(k, "provider", mode)] = p
        for k in G1_BASES:
            for lv in ("icb", "region", "england"):
                p = generate.forecast_path(ctx, k, lv, "asof")
                _fc(k, lv, new).to_parquet(p, index=False)
                files[(k, lv, "asof")] = p
        p = generate.forecast_path(ctx, "m2", "all", "asof")
        pd.concat([_fc("m2", lv, new) for lv in ("icb", "region", "england")],
                  ignore_index=True).to_parquet(p, index=False)
        files[("m2", "all", "asof")] = p
        pd.DataFrame({"origin": [str(o) for o in new], "attempt": 0, "shift": 0,
                      "fit_seed": [o.year * 100 + o.month for o in new],
                      "pred_seed": [o.month for o in new], "seconds": 1.0, "rhat_max": 1.02,
                      "ess_bulk_min": 300.0, "ess_tail_min": 300.0, "divergences": 0,
                      "worst_rhat_param": "x", "failed": False, "error": ""}).to_csv(
            ctx.work / "m2_fits.csv", index=False)
        pd.DataFrame({"block": ["stub"], "seconds": [0.0]}).to_csv(ctx.work / "timings.csv", index=False)
        return files

    def tables(ctx, files):
        return {"forecast_hashes.csv": generate.forecast_hashes(files),
                "m2_fits.csv": pd.read_csv(ctx.work / "m2_fits.csv"),
                "timings.csv": pd.read_csv(ctx.work / "timings.csv"),
                "qa_counts.csv": pd.DataFrame({"file": [p.name for p in files.values()], "rows": 0})}

    monkeypatch.setattr(checks, "pre_run", pre_run)
    monkeypatch.setattr(checks, "dry_checks", dry_checks)
    # report --from-scores' checks 7 and 8 would compare the real import and environment with
    # the temporary repository's; its check 6 (the tree) runs for real
    monkeypatch.setattr(checks, "check_import", lambda: None)
    monkeypatch.setattr(checks, "check_environment",
                        lambda lock, pins, head, row=None: {**checks._env(), "env_drift": {}})
    monkeypatch.setattr(generate, "generate", gen)
    monkeypatch.setattr(generate, "step3_tables", tables)
    monkeypatch.setattr(generate, "d7_check", lambda files: pd.DataFrame())
    monkeypatch.setattr(generate, "p13_check", lambda files, q: pd.DataFrame())


def _inputs(repo: Path, vint: pd.DataFrame, dev_side: bool = True) -> Path:
    """Design §8's 21 inputs at their P5 origin sets, as ``prepare --dev-side`` leaves them:
    the 12 pool files, the DEV M2 file (ICB, region, England) and the 8 DEV-side files (the
    seeded B1 with its own spread), read-only, with SHA256SUMS and prepare.json. Without
    ``dev_side``, the 13 files ``prepare`` alone copies."""
    files = {f"pool/{steps.pool_name(k, lv)}": _fc(k, lv, POOL_ORIGINS)
             for k in G1_BASES for lv in LEVELS}
    files[M2_INPUT] = pd.concat([_fc("m2", lv, DEV) for lv in ("icb", "region", "england")],
                                ignore_index=True)
    for (k, lv, mode), origins in DEV_SIDE_ORIGINS.items() if dev_side else ():
        spread = SEEDED_SPREAD if (k, mode) == ("b1", "asof") else 0.08
        files[f"dev_side/forecasts/{k}_{lv}_{mode}.parquet"] = _fc(k, lv, origins, mode, spread)
    inputs = steps.POOL.parent
    assert steps.DEV_SIDE == inputs / "dev_side" / "forecasts" and steps.M2_DEV == inputs / M2_INPUT
    for name, frame in files.items():
        (inputs / name).parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(inputs / name, index=False)
        (inputs / name).chmod(checks.READ_ONLY)
    found = {p.relative_to(inputs).as_posix(): p for p in inputs.rglob("*.parquet")}
    assert set(found) == (P5_INPUTS if dev_side else checks.COPIED_INPUTS)
    sources = {n: common.file_sha(p) for n, p in sorted(found.items())}
    (inputs / "SHA256SUMS").write_text("".join(f"{s}  {n}\n" for n, s in sources.items()))
    record = {"commit": _git(repo, "rev-parse", "HEAD"), "dev_side": dev_side, **checks._env(),
              "sources": sources}
    if dev_side:
        record["vintages"] = {"dev_reach_hash": checks.dev_reach_hash(vint)}
    (inputs / checks.PREPARE_RECORD).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return inputs


def _real_logs() -> dict[Path, int]:
    """Line counts of the real repository's unseal logs, in every worktree, and its witness."""
    here = Path(__file__).parents[1]
    out = {}
    for line in subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=here,
                               capture_output=True, text=True, check=True).stdout.splitlines():
        if line.startswith("worktree "):
            p = Path(line.split(" ", 1)[1]) / "results" / "unseal_log.jsonl"
            out[p] = len(p.read_text().splitlines()) if p.is_file() else 0
    witness = seal.witness_path(here)
    out[witness] = seal.line_count(witness)
    return out


def _setup(repo: Path, monkeypatch, tmp_path: Path) -> tuple[str, Path]:
    """Steps 2-3 stubbed, the inputs written, the token file and argv set: (tag, token file)."""
    vint = _vintages(last=ts("2026-02-01"))
    _stub_steps_2_3(monkeypatch, repo, vint)
    _inputs(repo, vint)
    tag = splits._tag_commit()
    assert tag == _git(repo, "rev-list", "-n", "1", "conf-plan-v1")
    token_file = tmp_path / "token.txt"
    token_file.write_text(tag + "\n")
    monkeypatch.setattr(sys, "argv", [str(Path(runner.__file__)), "run", "--unseal-token-file",
                                      str(token_file)])
    return tag, token_file


def _run(token_file: Path, amendment: str | None = None) -> int:
    return runner.cmd_run(argparse.Namespace(unseal_token_file=str(token_file),
                                             amendment=amendment, jobs=1))


def _lines(repo: Path) -> list[str]:
    return (repo / LOG).read_text().splitlines()


def _has(names, stem: str) -> bool:
    """A table ``stem`` was written, whole or split into slices."""
    return any(n == f"{stem}.csv" or n.startswith(f"{stem}__") for n in names)


def _rel(sc: store.Store, ref: str, tested: str, metric: str, target: str) -> float:
    """rel of ``tested`` against ``ref`` on the W5 winter-h3 rows of one target, computed here
    from the scores store as paired_bootstrap defines it (per-series means, then their mean):
    an oracle for the runner's wiring of H1 and H4."""
    def cut(f):
        keep = (f["winter"].astype(bool) & (f["horizon"] == 3) & (f["target"] == target)
                & pd.to_datetime(f["origin"]).isin(pd.to_datetime(list(W5))))
        return f.loc[keep.to_numpy(), [*K5, metric]]
    m = cut(sc.load(f"{ref}__new")).merge(cut(sc.load(f"{tested}__new")), on=list(K5),
                                          suffixes=("_a", "_b")).dropna()
    per = m.groupby("series")[[f"{metric}_a", f"{metric}_b"]].mean()
    return float(per[f"{metric}_b"].mean() / per[f"{metric}_a"].mean() - 1)


# Tables that carry no slice of their own: fits and diagnostics of the step-3 M2 loop, G1's
# counts, leave-one-origin-out listings, and the per-horizon failed counts.
NO_SLICE = ("m2_fits", "h2_m2.fits", "failed_counts", "failed_count_mismatches")
NO_SLICE_PARTS = (".loo", ".subsets", ".failed.")


def _slice_problems(tables: Path) -> list[str]:
    """Design §7.1 on the written tables: each carries split and origin_set (outside the
    allowlist), none holds a second origin set beside origin_set, and no stat names a level."""
    out = []
    for p in sorted(tables.glob("*.csv")):
        t = pd.read_csv(p)
        if t.columns.tolist() == [report.EMPTY_HEADER]:
            continue
        stem = p.name.removesuffix(".csv").split("__")[0]
        exempt = stem in NO_SLICE or any(x in f"{stem}." for x in NO_SLICE_PARTS)
        if not exempt and not {"split", "origin_set"} <= set(t.columns):
            out.append(f"{p.name}: no split/origin_set")
        if "origin_set" in t.columns and any(c.startswith("origin_set_") for c in t.columns):
            out.append(f"{p.name}: a second origin set")
        if "stat" in t.columns and any(lv in str(s).split("_") for s in t["stat"] for lv in LEVELS):
            out.append(f"{p.name}: a stat names a level")
    return out


def _spy_guard(calls: list):
    """Every alias of splits.assert_not_sealed, in every loaded nhs_ae module, recording whether
    the call held sealed rows (the real rule, asked without a token) and the token it got.
    Returns the function that undoes it."""
    real = splits.assert_not_sealed

    def spy(frame_or_origins, unseal_token=None, **kwargs):
        try:
            real(frame_or_origins, None)
            sealed = False
        except splits.SealedOriginError:
            sealed = True
        arg = (sorted(pd.to_datetime(list(frame_or_origins)))
               if not isinstance(frame_or_origins, pd.DataFrame) else None)
        calls.append((sealed, unseal_token, arg))
        return real(frame_or_origins, unseal_token, **kwargs)
    generate._swap({id(real): (real, spy)})
    return lambda: generate._swap({id(spy): (spy, real)})


def test_tokened_rehearsal_logs_once_scores_with_the_token_commits_and_recomputes(
        repo, tripwires, monkeypatch, tmp_path):
    real_before = _real_logs()
    tag, token_file = _setup(repo, monkeypatch, tmp_path)
    calls = {"score": [], "guard": []}
    real_score = seal.score

    def score(forecasts, truth, split, token=None):
        calls["score"].append((split, token is not None, set(pd.to_datetime(forecasts["origin"]).unique())))
        return real_score(forecasts, truth, split, token)
    monkeypatch.setattr(seal, "score", score)

    computed = []
    real_compute = analysis.compute

    def compute(*a, **k):
        computed.append(real_compute(*a, **k))
        return computed[-1]
    monkeypatch.setattr(analysis, "compute", compute)

    start = _git(repo, "rev-parse", "HEAD")
    undo = _spy_guard(calls["guard"])
    try:
        rc = _run(token_file)
    finally:
        undo()
    assert rc == 0 and len(computed) == 1

    # exactly one log line, whose head is the runner's hash commit (H1), a child of the tag
    lines = _lines(repo)
    assert len(lines) == 1
    entry = json.loads(lines[0])
    h1 = entry["head"]
    assert entry["token"] == tag and entry["sealed_rows"] == 21
    assert entry["origins"] == ["2024-01-01", "2025-09-01"] and seal.names_run(entry["argv"])
    assert _git(repo, "rev-list", "--parents", "-n", "1", h1).split()[1:] == [start]
    assert sorted(_git(repo, "diff", "--name-status", start, h1).splitlines()) == sorted(
        f"A\t{CONF_DIR.as_posix()}/{f}" for f in HASH_FILES)
    witness = repo / ".git" / "nhs_ae" / "unseal_witness.jsonl"
    assert witness.read_text().splitlines() == lines
    results = repo / CONF_DIR
    assert json.loads((results / "unseal_entry.json").read_text()) == entry

    # every call of assert_not_sealed that held sealed rows had the token, the first of them
    # being open_seal's with the 21 CONF origins; CONF frames scored with it, DEV without
    sealed = [(tok, arg) for is_sealed, tok, arg in calls["guard"] if is_sealed]
    assert len(sealed) >= 2 and all(tok == tag for tok, _ in sealed)
    assert sealed[0][1] == list(pd.to_datetime(list(CONF21)))
    conf = {ts(o) for o in CONF21}
    for split, tokened, origins in calls["score"]:
        assert (split == "conf") == tokened
        assert origins <= conf if split == "conf" else not (origins & conf)
    assert any(s == "conf" for s, _, _ in calls["score"]) and any(s == "dev" for s, _, _ in calls["score"])

    # step 6: one commit on top of H1 holding the results and the log, and nothing else
    head = _git(repo, "rev-parse", "HEAD")
    assert _git(repo, "rev-list", "--parents", "-n", "1", head).split()[1:] == [h1]
    changed = _git(repo, "diff", "--name-only", h1, head).splitlines()
    assert LOG.as_posix() in changed and f"{CONF_DIR.as_posix()}/confirmatory_results.md" in changed
    assert all(p == LOG.as_posix() or p.startswith(f"{CONF_DIR.as_posix()}/") for p in changed)
    assert _git(repo, "status", "--porcelain") == ""

    # the progress record, and the real worktrees' logs untouched
    ctx = common.run_context(tag)
    events = [json.loads(x)["event"] for x in (ctx.work / "progress.jsonl").read_text().splitlines()]
    assert events == ["sealing", "unsealed", "scores-about-to-be-written", "scores-written",
                      "results-written", "committed"]
    assert _real_logs() == real_before

    # every statistic ran, the DEV side included (design §8's inputs), and was compared;
    # verdicts.json is strict JSON (n/a as null)
    verdicts = json.loads((results / "verdicts.json").read_text(),
                          parse_constant=lambda c: pytest.fail(f"verdicts.json holds {c}"))
    assert not [k for k in verdicts if "_errors" in k.split(".")]
    assert [p for paths in report.REQUIRED.values() for p in paths
            if report.lookup(computed[0], p) is report._MISSING] == []
    sc = store.Store(ctx.work / "scores")
    assert "raw_b1_provider_asof_seeded__dev" in sc.names()
    names = sorted(p.name for p in (results / "tables").iterdir())
    for stem in ("dev.seasons.h1", "dev.seasons.h3", "dev.seasons.h4", "dev.seasons.h4_original",
                 "dev.seasons.f2_wis", "dev.coverage.h2_m1", "dev.coverage.h2_m2",
                 "dev.coverage.primary", "dev.h4b.table", "dev.f2.table"):
        assert _has(names, stem), stem
    for name in analysis.SEASONS:
        parts = [n for n in names if _has([n], f"dev_flags.{name}")]
        flags = pd.concat([pd.read_csv(results / "tables" / n) for n in parts])
        assert "outside" in flags.columns and flags["dev_min"].notna().all(), name
    for name in analysis.COVERAGE:
        assert _has(names, f"dev_flags.coverage_{name}"), name
    assert _has(names, "primary.alongside.dev_range")

    # known values: rel as paired_bootstrap defines it, from the store, for H1 and H4
    h1_t = pd.read_csv(results / "tables" / "h1.table.csv")
    for target in TARGETS:
        got = h1_t.loc[(h1_t["model"] == NAME["m1"]) & (h1_t["target"] == target), "rel"]
        assert got.item() == pytest.approx(_rel(sc, "raw_b0_provider_asof",
                                                "raw_m1_provider_asof", "mase", target), abs=1e-12)
    rels = h1_t.loc[h1_t["target"] == "att_all"].set_index("model")["rel"]
    assert rels[NAME["m1"]] < rels[NAME["m1_v3_raw"]] < 0             # M1 sits closest
    h4_t = pd.read_csv(results / "tables" / "h4.table.csv")
    got = h4_t.loc[(h4_t["key"] == "b2") & (h4_t["target"] == "att_type1"), "rel"].item()
    assert got == pytest.approx(_rel(sc, "raw_b2_provider_asof", "raw_b2_provider_final", "wis",
                                     "att_type1"), abs=1e-12)
    assert got != 0

    # design §7.1 on every table; the summary and provenance hold everything
    assert _slice_problems(results / "tables") == []
    md = (results / "confirmatory_results.md").read_text()
    for section in ("## CONF against DEV's range (design §7.13)", "## H1 per target",
                    "## H3 per base", "## H4b, CONF and DEV side by side"):
        assert section in md, section
    assert "## Statistics that failed" not in md and "## DEV-side statistics" not in md
    assert all(f"`{p}`" in md for paths in report.REQUIRED.values() for p in paths)
    prov = json.loads((results / report.PROVENANCE).read_text())
    assert prov["extra"]["unseal_entry"] == entry and prov["extra"]["inputs_source"] == "stage_h/inputs"
    assert prov["facts"]["inputs"] == len(P5_INPUTS)

    _recompute(repo, ctx, results, monkeypatch)


def _recompute(repo: Path, ctx, results: Path, monkeypatch) -> None:
    """Design §9 case 3 on the run just made: report --from-scores."""
    args = argparse.Namespace(from_scores=str(ctx.work), jobs=1)
    n, w = len(_lines(repo)), seal.line_count(repo / ".git" / "nhs_ae" / "unseal_witness.jsonl")

    # a statistic that reads outturns trips, and stops the command before anything is written
    with monkeypatch.context() as m:
        m.setattr(analysis.hyp, "h1", lambda *a, **k: stage_f.load_truth(
            asof.load_vintages(ctx.vintages_path)))
        with pytest.raises(generate.SealTripwire, match="load_truth called by report --from-scores"):
            runner.cmd_report(args)
    assert not list(results.glob("recomputed-*"))
    assert stage_f.load_truth is asof.load_truth and not hasattr(asof.load_truth, "tripwire")

    # without it, every table is rebuilt byte for byte, with zero new log or witness lines
    assert runner.cmd_report(args) == 0
    assert len(_lines(repo)) == n
    assert seal.line_count(repo / ".git" / "nhs_ae" / "unseal_witness.jsonl") == w
    rec = next(results.glob("recomputed-*"))
    a = sorted(p.name for p in (results / "tables").iterdir())
    b = sorted(p.name for p in (rec / "tables").iterdir())
    assert a == b
    for name in a:
        assert (results / "tables" / name).read_bytes() == (rec / "tables" / name).read_bytes()
    check = pd.read_csv(rec / report.RECOMPUTATION_CHECK)
    assert sorted(check["table"]) == sorted([*a, report.VERDICTS]) and report.reproduced(check)
    assert report.RECOMPUTED in (rec / "README.md").read_text()
    assert report.RECOMPUTED in (rec / "confirmatory_results.md").read_text()
    prov = json.loads((rec / report.PROVENANCE).read_text())
    assert prov["extra"]["command"] == report.RECOMPUTED and prov["extra"]["unseal_entry"] == \
        json.loads((results / "unseal_entry.json").read_text())
    assert prov["extra"]["run_facts"]["inputs"] == len(P5_INPUTS)      # the run's step-2 facts
    assert prov["facts"]["nhs_ae_file"].endswith("nhs_ae/__init__.py")

    # one recomputation per commit: a second at the same HEAD is refused before any work
    with pytest.raises(checks.RefusedError, match="exists: one recomputation per commit"):
        runner.cmd_report(args)
    shutil.rmtree(rec)

    # a changed score file is refused, not recorded as a failed statistic
    victim = ctx.work / "scores" / "raw_b0_provider_asof__new.parquet"
    victim.chmod(stat.S_IRUSR | stat.S_IWUSR)
    victim.write_bytes(victim.read_bytes() + b"\0")
    with pytest.raises(checks.RefusedError, match="differ from its SHA256SUMS"):
        runner.cmd_report(args)
    assert len(_lines(repo)) == n and not list(results.glob("recomputed-*"))


def test_conf_run_v1_on_the_step6_commit_is_the_post_run_state(
        repo, tripwires, monkeypatch, tmp_path, real_post_run):
    """Design §9's post-run state (P11) on a completed run, with the real ``splits._post_run``
    throughout (the run itself meets the pre-run rules: there is no conf-run-v1). Once an
    annotated conf-run-v1 tags the step-6 commit, as the runner prints it, a later process
    reads sealed rows with token None or the tag commit and writes no log or witness line;
    another token raises. A lightweight tag is not the state, and an undisclosed extra log
    line breaks it until a §10 row quotes the line's timestamp."""
    real_before = _real_logs()
    monkeypatch.setattr(splits, "_post_run_cache", set())
    tag, token_file = _setup(repo, monkeypatch, tmp_path)
    assert _run(token_file) == 0
    step6 = _git(repo, "rev-parse", "HEAD")
    (entry,) = [json.loads(x) for x in _lines(repo)]
    witness = repo / ".git" / "nhs_ae" / "unseal_witness.jsonl"
    log0, w0 = (repo / LOG).read_bytes(), witness.read_bytes()

    # a later process, as a later calibration's (plan §10): nothing logged, another argv
    monkeypatch.setattr(splits, "_logged_tokens", set())
    monkeypatch.setattr(splits, "_unseal_context", {})
    monkeypatch.setattr(sys, "argv", ["nhs_ae/live.py"])
    vint = _vintages(last=ts("2026-02-01"))

    def first_releases():
        fr = online.first_release(vint, month_range(date(2023, 10, 1), date(2024, 3, 1)))
        assert fr["period"].max() >= ts("2024-01-01")                   # sealed periods read
    reads = (lambda: splits.assert_not_sealed(CONF21), first_releases)

    def sealed():
        assert not real_post_run()
        for read in reads:
            with pytest.raises(splits.SealedOriginError, match="sealed confirmatory window"):
                read()

    def lifted():
        assert real_post_run()
        for read in reads:
            read()
        splits.assert_not_sealed(CONF21, tag)
        with pytest.raises(splits.SealedOriginError, match="never another token"):
            splits.assert_not_sealed(CONF21, "0" * 40)
        assert witness.read_bytes() == w0
        assert not splits._logged_tokens and not splits._unseal_context

    sealed()                                                            # no conf-run-v1
    _git(repo, "tag", "conf-run-v1", step6)                             # a lightweight tag
    sealed()
    _git(repo, "tag", "-d", "conf-run-v1")
    _git(repo, "tag", "-a", "conf-run-v1", "-m", "Stage H run", step6)  # as the runner prints
    lifted()
    assert (repo / LOG).read_bytes() == log0

    # an undisclosed extra line breaks the state; a §10 row quoting its timestamp restores it
    stray = {**entry, "timestamp": "2026-11-02T10:00:00+00:00"}
    (repo / LOG).write_text(log0.decode() + json.dumps(stray) + "\n")
    sealed()
    prereg = repo / "docs" / "preregistration.md"
    prereg.write_text(prereg.read_text() + f"| 2026-11-03 | **Stray unseal line**: the line "
                      f"logged at {stray['timestamp']} is not the run's | disclosed |\n")
    _git(repo, "commit", "-q", "-m", "§10: the stray unseal line", "--", "docs/preregistration.md")
    lifted()
    assert [json.loads(x) for x in _lines(repo)] == [entry, stray]
    assert _real_logs() == real_before


def test_a_crash_after_the_scores_leaves_the_line_uncommitted_until_report_is_allowed(
        repo, tripwires, monkeypatch, tmp_path, real_post_run):
    """Design §9 case 3: the analysis raises after scores-written. One new log line beside an
    earlier run's committed one (k = 1), no step-6 commit, and a note saying the line is
    uncommitted. The rerun is the amendment path end to end: the commit carrying the earlier
    line adds the §10 row quoting its timestamp, and the guarded call unseals at the hash
    commit on it under --amendment. report --from-scores refuses until the crash-fix commit
    holds this run's line (the earlier line, with the same token, does not do), naming the
    witness once the line is lost; then it rebuilds every table. conf-run-v1 on the crash-fix
    commit is not the post-run state (P11; no run-mode provenance); on the recomputation's
    commit it is, the earlier line disclosed by the row."""
    monkeypatch.setattr(splits, "_post_run_cache", set())
    tag = splits._tag_commit()
    prior = {"timestamp": "2026-10-01T09:00:00+00:00", "token": tag, "head": tag,
             "origins": ["2024-01-01", "2025-09-01"], "sealed_rows": 21,
             "argv": [str(Path(runner.__file__)), "run"]}
    (repo / LOG).write_text(json.dumps(prior) + "\n")
    prereg = repo / "docs" / "preregistration.md"
    prereg.write_text(prereg.read_text() + f"| 2026-10-02 | **{RERUN}**: the run logged at "
                      f"{prior['timestamp']} crashed; rerun | case 2 |\n")
    _git(repo, "commit", "-qam", "an earlier run's unseal line and its §10 row (k = 1)")
    tag, token_file = _setup(repo, monkeypatch, tmp_path)
    real = analysis.compute
    calls = []

    def compute(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("the analysis crashed")
        return real(*a, **k)
    monkeypatch.setattr(analysis, "compute", compute)
    with pytest.raises(RuntimeError, match="the analysis crashed") as caught:
        _run(token_file, amendment=RERUN)
    notes = getattr(caught.value, "__notes__", [])
    assert any("NOT committed; crash case 3" in n for n in notes)
    assert not any(n.startswith("unseal accounting") for n in notes)
    lines = _lines(repo)
    assert len(lines) == 2 and json.loads(lines[0]) == prior
    h1 = json.loads(lines[1])["head"]
    assert _git(repo, "rev-parse", "HEAD") == h1                         # no step-6 commit
    assert splits._unseal_context[tag]["amendment"] == RERUN             # unsealed under it
    assert _git(repo, "show", f"HEAD:{LOG.as_posix()}").splitlines() == lines[:1]
    ctx = common.run_context(tag)
    assert store.crash_case(ctx.work) == 3

    args = argparse.Namespace(from_scores=str(ctx.work), jobs=1)
    with pytest.raises(checks.RefusedError, match="the working-tree log holds it, uncommitted"):
        runner.cmd_report(args)
    _git(repo, "checkout", "--", LOG.as_posix())         # the slip the witness guards against
    witness = repo / ".git" / "nhs_ae" / "unseal_witness.jsonl"
    assert witness.read_text().splitlines() == lines[1:]
    with pytest.raises(checks.RefusedError, match="the witness .* holds it: restore it"):
        runner.cmd_report(args)
    (repo / LOG).write_text((repo / LOG).read_text() + witness.read_text())

    # the crash fix belongs on H1: one cut beside it, from the start commit S (git carries the
    # log across and drops H1's hash files), is refused, and so is one on H1 that loses a hash
    # file
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    _git(repo, "switch", "-q", "-c", "slip", f"{h1}^")
    _git(repo, "add", LOG.as_posix(), CONF_DIR.as_posix())
    _git(repo, "commit", "-q", "-m", "crash fix on the tag's line")
    with pytest.raises(checks.RefusedError, match="not on top of the hash commit"):
        runner.cmd_report(args)
    _git(repo, "switch", "-q", branch)
    _git(repo, "checkout", "slip", "--", LOG.as_posix(), CONF_DIR.as_posix())
    _git(repo, "rm", "-q", f"{CONF_DIR.as_posix()}/timings.csv")
    _git(repo, "commit", "-q", "-m", "crash fix that drops a hash file")
    with pytest.raises(checks.RefusedError, match="does not hold the hash commit's"):
        runner.cmd_report(args)
    _git(repo, "checkout", h1, "--", f"{CONF_DIR.as_posix()}/timings.csv")
    _git(repo, "commit", "-q", "-m", "Stage H: crash fix (case 3)")

    # it recomputes with HEAD's code: a tracked change or an untracked file is refused
    prereg.write_text(prereg.read_text() + "an uncommitted edit\n")
    with pytest.raises(checks.RefusedError, match="check 6.*commit the crash fix"):
        runner.cmd_report(args)
    _git(repo, "checkout", "--", "docs/preregistration.md")
    (repo / "fix.py").write_text("x = 1\n")
    with pytest.raises(checks.RefusedError, match="check 6"):
        runner.cmd_report(args)
    (repo / "fix.py").unlink()
    assert runner.cmd_report(args) == 0
    assert _lines(repo) == lines and witness.read_text().splitlines() == lines[1:]
    rec = next((repo / CONF_DIR).glob("recomputed-*"))
    check = pd.read_csv(rec / report.RECOMPUTATION_CHECK)
    assert len(check) and not check["in_original"].any() and check["in_recomputed"].all()
    assert not [k for k in json.loads((rec / "verdicts.json").read_text())
                if "_errors" in k.split(".")]
    prov = json.loads((rec / report.PROVENANCE).read_text())["extra"]
    assert prov["run_facts"]["inputs"] == len(P5_INPUTS) and prov["hash_commit"] == h1
    assert "No re-runs" not in (rec / "confirmatory_results.md").read_text()  # no original tables

    # conf-run-v1 (P11): refused as the post-run state on the crash-fix commit, which holds no
    # run-mode provenance; on the commit of the recomputation, as the runner prints it, it holds
    _git(repo, "tag", "-a", "conf-run-v1", "-m", "too early", "HEAD")
    assert not real_post_run()
    assert any("not a completed run" in p
               for p in seal_rules.post_run_problems(repo, [repo / LOG], witness))
    _git(repo, "tag", "-d", "conf-run-v1")
    _git(repo, "add", "--", CONF_DIR.as_posix())
    _git(repo, "commit", "-q", "-m", "Stage H: recomputed results (design §9, case 3)")
    _git(repo, "tag", "-a", "conf-run-v1", "-m", "Stage H run", "HEAD")
    assert real_post_run()
    splits.assert_not_sealed(CONF21)
    assert _lines(repo) == lines and witness.read_text().splitlines() == lines[1:]


@pytest.mark.parametrize("where, case", [("read_token", 1), ("step4", 2)])
def test_a_crash_before_the_scores_is_case_1_or_2(repo, tripwires, monkeypatch, tmp_path,
                                                  where, case):
    """Design §9 cases 1 and 2 through cmd_run: a raise before the guarded call (reading the
    token) leaves no line and no note; a raise after it (in step 4) leaves one uncommitted
    line, a note saying so, and no accounting note. Neither makes the step-6 commit, and
    report --from-scores refuses both."""
    tag, token_file = _setup(repo, monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError(f"{where} crashed")
    monkeypatch.setattr(seal if where == "read_token" else steps, where, boom)
    with pytest.raises(RuntimeError, match=f"{where} crashed") as caught:
        _run(token_file)
    notes = getattr(caught.value, "__notes__", [])
    assert not any(n.startswith("unseal accounting") for n in notes)
    assert any(f"NOT committed; crash case {case}" in n for n in notes) == (case == 2)
    assert len(_lines(repo)) == case - 1
    ctx = common.run_context(tag)
    h1 = json.loads((ctx.work / "progress.jsonl").read_text().splitlines()[0])["hash_commit"]
    assert _git(repo, "rev-parse", "HEAD") == h1 and store.crash_case(ctx.work) == case
    with pytest.raises(checks.RefusedError, match=f"case 3 only .*crash case {case}"):
        runner.cmd_report(argparse.Namespace(from_scores=str(ctx.work), jobs=1))


def test_dry_run_logs_nothing_checks_the_embargo_and_fails_without_the_dev_side(
        repo, tripwires, monkeypatch):
    """Design §10 through cmd_dry_run, on the 13 inputs ``prepare`` alone copies: zero new
    lines in every log and the witness; the embargo checked against the literal rule (15
    pairs, and a moved boundary refused); exit status 1, since the DEV-side statistics cannot
    be computed; and report --from-scores rebuilding every table byte for byte."""
    dry_root, dry_results = repo / "data" / "processed" / "stage_h_dry", repo / "results" / "H-dryrun"
    monkeypatch.setattr(common, "DRY_ROOT", dry_root)
    monkeypatch.setattr(common, "DRY_RESULTS", dry_results)
    vint = _vintages(last=ts("2026-02-01"))
    _stub_steps_2_3(monkeypatch, repo, vint)
    _inputs(repo, vint, dev_side=False)
    logs, witness, real_before = seal.worktree_logs(), seal.witness_path(), _real_logs()
    w0 = seal.line_count(witness)
    head = _git(repo, "rev-parse", "HEAD")
    assert runner.cmd_dry_run(argparse.Namespace(jobs=1)) == 1
    assert seal.worktree_logs() == logs and seal.line_count(witness) == w0
    assert _real_logs() == real_before

    ctx, out = common.dry_context(head[:12]), dry_results / head[:12]
    emb = json.loads((out / report.PROVENANCE).read_text())["extra"]["embargo"]
    assert emb["n_embargoed_pairs"] == 15 and emb["sealed_periods_scored"] == 0
    assert emb["embargoed_rows"]["raw_b0_provider_asof__new"] == 15 * len(TARGETS) * len(PROVIDER_SERIES)
    assert emb["embargoed_rows"]["raw_b1_provider_asof__dev"] == 0
    failed = [k for k in json.loads((out / "verdicts.json").read_text()) if "_errors" in k.split(".")]
    assert "dev._errors.seasons.h1" in failed and all(k.startswith("dev.") for k in failed)
    assert _slice_problems(out / "tables") == []
    assert "## DEV-side statistics that failed or were not computed" in (
        out / "confirmatory_results.md").read_text()

    files, inputs = runner._forecast_files(ctx), steps.load_inputs(ctx)
    s4, sc = store.Store(ctx.work / store.STEP4), store.Store(ctx.work / store.SCORES)
    assert steps.embargo_check(ctx, files, inputs, s4, sc)["n_embargoed_pairs"] == 15
    with monkeypatch.context() as m:
        m.setattr(steps, "EMBARGO_FROM", ts("2023-12-01"))
        with pytest.raises(seal.SealError, match="embargo check .*the seal dropped"):
            steps.embargo_check(ctx, files, inputs, s4, sc)

    args = argparse.Namespace(from_scores=str(ctx.work), jobs=1)
    assert runner.cmd_report(args) == 0
    rec = next(out.glob("recomputed-*"))
    check = pd.read_csv(rec / report.RECOMPUTATION_CHECK)
    assert report.VERDICTS in set(check["table"]) and report.reproduced(check)
    assert json.loads((rec / report.PROVENANCE).read_text())["extra"]["run_facts"]["pinned"] is False
    assert seal.worktree_logs() == logs and seal.line_count(witness) == w0

    # design §10: a crash path that does not reproduce the dry run fails
    shutil.rmtree(rec)
    (out / report.VERDICTS).write_text((out / report.VERDICTS).read_text() + " ")
    assert runner.cmd_report(args) == 1
    assert not report.reproduced(pd.read_csv(next(out.glob("recomputed-*"))
                                             / report.RECOMPUTATION_CHECK))


def test_step6_commits_the_results_and_the_log_and_nothing_else(repo, monkeypatch):
    """Step 6 (design §9): refused, with a note that the line is uncommitted, when the index
    would hold anything beyond results/H-confirmatory and the log (a .DS_Store) or HEAD is not
    H1, and a failed git commit leaves the index as it found it, with the same note; otherwise
    one commit on H1 and a clean tree."""
    ctx = common.run_context(splits._tag_commit())
    h1 = _git(repo, "rev-parse", "HEAD")
    results = repo / CONF_DIR
    (results / "tables").mkdir(parents=True)
    (results / "tables" / "t.csv").write_text("a\n1\n")
    (repo / LOG).write_text('{"token": "t"}\n')
    (results / ".DS_Store").write_bytes(b"\0")
    with pytest.raises(checks.RefusedError, match="beyond results/H-confirmatory/") as caught:
        runner._step6(ctx, h1, repo / LOG)
    assert any("step 6 failed" in n and "uncommitted" in n for n in caught.value.__notes__)
    assert _git(repo, "rev-parse", "HEAD") == h1
    _git(repo, "reset", "-q")
    (results / ".DS_Store").unlink()
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a commit made during the run")
    with pytest.raises(checks.RefusedError, match="not the hash commit"):
        runner._step6(ctx, h1, repo / LOG)
    _git(repo, "reset", "-q", "--soft", h1)
    real_git = checks.git

    def git(*args, **kwargs):
        if "commit" in args:
            raise subprocess.CalledProcessError(1, ["git", *args], stderr="a hook said no")
        return real_git(*args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(checks, "git", git)
        with pytest.raises(subprocess.CalledProcessError) as caught:
            runner._step6(ctx, h1, repo / LOG)
    assert any("step 6 failed" in n and "commit them by hand" in n for n in caught.value.__notes__)
    assert _git(repo, "rev-parse", "HEAD") == h1
    assert _git(repo, "diff", "--cached", "--name-only") == ""
    head = runner._step6(ctx, h1, repo / LOG)
    assert _git(repo, "rev-list", "--parents", "-n", "1", head).split()[1:] == [h1]
    assert sorted(_git(repo, "diff", "--name-only", h1, head).splitlines()) == [
        f"{CONF_DIR.as_posix()}/tables/t.csv", LOG.as_posix()]
    assert _git(repo, "status", "--porcelain") == ""


def test_report_guard_trips_every_alias_and_keeps_the_bootstrap():
    """_no_guarded_calls covers step 3's tripwires in every alias (stage_f's load_truth and
    score_forecasts, stage_d's calibrate and first_release, harness's assert_not_sealed), keeps
    metrics.paired_bootstrap, and undoes itself."""
    before = (stage_f.score_forecasts, stage_d.calibrate, stage_d.first_release,
              stage_f.load_truth, harness.assert_not_sealed, metrics.paired_bootstrap)
    with runner._no_guarded_calls():
        for call in (lambda: stage_f.score_forecasts(None, None), lambda: stage_d.calibrate(None),
                     lambda: stage_d.first_release(None), lambda: stage_f.load_truth(None),
                     lambda: harness.assert_not_sealed([])):
            with pytest.raises(generate.SealTripwire, match="called by report --from-scores"):
                call()
        assert metrics.paired_bootstrap is before[-1]
    assert (stage_f.score_forecasts, stage_d.calibrate, stage_d.first_release,
            stage_f.load_truth, harness.assert_not_sealed, metrics.paired_bootstrap) == before


def test_report_refuses_a_directory_that_is_not_a_work_directory(repo, tmp_path):
    with pytest.raises(checks.RefusedError, match="is not a work directory"):
        runner.cmd_report(argparse.Namespace(from_scores=str(tmp_path / "elsewhere"), jobs=1))


def test_report_refuses_a_run_before_its_scores_were_written(repo):
    """A run whose progress stops at 'unsealed' is case 2: nothing to recompute from."""
    tag = splits._tag_commit()
    work = common.run_context(tag).work
    store.progress(work, "sealing", log=str(repo / LOG), n0=0, witness=str(repo / "w"), w0=0)
    store.progress(work, "unsealed", head=tag)
    with pytest.raises(checks.RefusedError, match="case 3 only .*crash case 2"):
        runner.cmd_report(argparse.Namespace(from_scores=str(work), jobs=1))


def test_run_mode_inputs_are_design_8s_21_files(repo):
    """steps.load_inputs' backstop: run mode refuses a missing input, and either mode one
    outside P5_INPUTS."""
    vint = _vintages(last=ts("2026-02-01"))
    inputs = _inputs(repo, vint)
    ctx = common.run_context(splits._tag_commit())
    got = steps.load_inputs(ctx)
    assert set(got.dev_side) == set(DEV_SIDE_ORIGINS) and got.m2_dev is not None
    assert set(steps.input_paths()) <= P5_INPUTS
    gone = inputs / "dev_side" / "forecasts" / "b1_provider_asof.parquet"
    gone.chmod(stat.S_IRUSR | stat.S_IWUSR)
    gone.rename(inputs / "b1_provider_asof.parquet")
    with pytest.raises(steps.InputError, match="1 of design §8's 21 inputs are missing"):
        steps.load_inputs(ctx)
    (inputs / "b1_provider_asof.parquet").rename(gone)
    (inputs / "dev_side" / "forecasts" / "b1_provider_asof_old.parquet").write_bytes(gone.read_bytes())
    for mode_ctx in (ctx, common.dry_context("abcdef123456")):
        with pytest.raises(steps.InputError, match="outside design §8's permitted set"):
            steps.load_inputs(mode_ctx)


def test_prepare_without_dev_side_records_it_and_pin_refuses(repo, tmp_path, monkeypatch):
    """``prepare`` alone copies the 13 pool and M2 files, verified and read-only, after checks
    6-8, and records dev_side false, which pin refuses (design §8). An M2 file other than
    E-m2-rerun69's is refused before anything is copied, and a copy that differs from its
    source leaves no record."""
    _git(repo, "tag", "-d", "conf-plan-v1")
    src = tmp_path / "sources"
    sources = {}
    for name in sorted(checks.COPIED_INPUTS):
        key, lv = (("m2", None) if name == M2_INPUT else
                   Path(name).stem.removeprefix("base_").rsplit("_", 1))
        frame = (pd.concat([_fc("m2", x, DEV) for x in ("icb", "region", "england")])
                 if key == "m2" else _fc(key, lv, POOL_ORIGINS))
        sources[name] = src / name
        sources[name].parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(sources[name], index=False)
    head = _git(repo, "rev-parse", "HEAD")
    facts = []
    monkeypatch.setattr(checks, "prepare_facts", lambda h: facts.append(h) or {
        "commit": h, **checks._env()})
    monkeypatch.setattr(steps, "input_paths", lambda: dict(sources))
    inputs = repo / checks.INPUTS_REL
    with pytest.raises(checks.RefusedError, match=f"input {M2_INPUT} is not E-m2-rerun69's file"):
        runner.main(["prepare", "--jobs", "1"])
    assert facts == [head] and not inputs.exists()
    monkeypatch.setattr(checks, "M2_DEV_SHA", common.file_sha(sources[M2_INPUT]))
    real_copy = shutil.copy2

    def copy2(a, b, *args, **kwargs):
        out = real_copy(a, b, *args, **kwargs)
        if Path(a).name == "base_b2_icb.parquet":
            Path(b).chmod(stat.S_IRUSR | stat.S_IWUSR)
            Path(b).write_bytes(Path(b).read_bytes() + b"\0")
        return out
    with monkeypatch.context() as m:
        m.setattr(shutil, "copy2", copy2)
        with pytest.raises(checks.RefusedError, match="differs from the SHA-256 taken before"):
            runner.main(["prepare", "--jobs", "1"])
    assert not (inputs / checks.PREPARE_RECORD).exists()
    shutil.rmtree(inputs)
    facts.clear()
    assert runner.main(["prepare", "--jobs", "1"]) == 0
    assert facts == [head]
    record = json.loads((inputs / checks.PREPARE_RECORD).read_text())
    assert record["dev_side"] is False and record["commit"] == head
    assert record["sources"] == {n: common.file_sha(p) for n, p in sources.items()}
    assert {stat.S_IMODE((inputs / n).stat().st_mode) for n in sources} == {checks.READ_ONLY}
    with pytest.raises(checks.RefusedError, match="prepared without --dev-side"):
        checks._prepare_record(inputs)
