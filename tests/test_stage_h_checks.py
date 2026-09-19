"""Stage H step 2 (design §3, §4): pins, the P4 rebuild, the pre-run checks and the HEAD
rules. Everything runs on temporary git repositories under tmp_path with synthetic data; the
conf-plan-v1 tag is only ever created inside those repositories."""

from __future__ import annotations

import inspect
import json
import multiprocessing
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from nhs_ae.config import PROJECT_ROOT as REAL_ROOT
from nhs_ae.evaluate.asof import load_vintages
from nhs_ae.evaluate.stage_h import checks, seal
from nhs_ae.evaluate.stage_h.checks import RefusedError
from nhs_ae.evaluate.stage_h.common import (
    CONF19,
    CONF21,
    D7_FOLD,
    DEV,
    DEV_SIDE_KEYS,
    DEV_SIDE_ORIGINS,
    DEV_WINTER_H3,
    DRY,
    DRY_END,
    HASH_FILES,
    M2_DEV_SHA,
    M2_INPUT,
    P5_INPUTS,
    P5_ORIGINS,
    POOL_ORIGINS,
    RUN_END,
    TAG,
    Context,
    file_sha,
)
from nhs_ae.ingest import cli

FIXTURE = Path(__file__).parent / "fixtures" / "monthly_ae_sample.csv"
LOCK = "# pip freeze of a test environment\n# Python and platform\nnumpy==2.1.0\npandas==2.2.3\n"
TITLE = "Stage H rerun 1"
TS = "2026-10-01T10:00:00+00:00"
BROKEN = "data/raw/2016-11-10/Monthly-AE-Broken.csv"
GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")
PREREG = """# Pre-registration

## 7. Hypotheses

Text.

## 10. Amendments

| Date | Change | Reason |
|---|---|---|
| 2026-09-08 (pre-freeze) | B0's intervals: empirical quantiles of in-sample errors. | reason |
| 2026-09-10 | **Re-split by origin.** DEV and CONF. | reason |

---

### Appendix A

Text.
"""


class Repo:
    """A throwaway git repository under pytest's tmp_path; it refuses to act anywhere else."""

    base = ""

    def __init__(self, root: Path, tmp: Path):
        real = REAL_ROOT.resolve()
        assert tmp in root.parents and real != root.resolve() and real not in root.resolve().parents
        self.root = root

    def git(self, *args: str) -> str:
        assert (self.root / ".git").exists()
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                              check=True).stdout.strip()

    def write(self, rel: str, text: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def commit(self, msg: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.head()

    def tag(self) -> str:
        self.git("tag", "-a", TAG, "-m", "confirmatory plan")
        return self.git("rev-parse", f"{TAG}^{{commit}}")


def _csv(period: str, bump: int = 0) -> str:
    """The synthetic fixture file relabelled to another month; ``bump`` revises one value."""
    text = FIXTURE.read_text().replace("MSitAE-JULY-2026", f"MSitAE-{period}")
    return text.replace('"13,456"', f'"{13456 + bump:,}"')


def _archive(r: Repo) -> None:
    """Two monthly files, a revision, an unparseable file and a 'still identical' sighting."""
    files = [("2016-07-14", "Monthly-AE-June-2016.csv", "2016-06-01", _csv("JUNE-2016")),
             ("2016-08-11", "Monthly-AE-July-2016.csv", "2016-07-01", _csv("JULY-2016")),
             ("2016-11-10", "Monthly-AE-June-2016-revised.csv", "2016-06-01",
              _csv("JUNE-2016", 44)),
             ("2016-11-10", "Monthly-AE-Broken.csv", "2016-08-01", "not,a,monthly,file\n1,2,3,4\n")]
    records = []
    for snap, name, period, text in files:
        rel = f"data/raw/{snap}/{name}"
        records.append({"filename": name, "period": period, "ext": "csv", "snapshot": snap,
                        "available_from": snap, "revised": "revised" in name, "revised_on": None,
                        "sha256": file_sha(r.write(rel, text)), "stored": True, "path": rel})
    records.append({**records[0], "snapshot": "2016-08-11", "stored": False})
    r.write(checks.MANIFEST_REL, "".join(json.dumps(x) + "\n" for x in records))


def _forecasts(origins) -> pd.DataFrame:
    """A synthetic forecast table with the harness's columns."""
    return pd.DataFrame([
        {"origin": pd.Timestamp(o), "mode": "asof", "model": "b1_ets", "level": "provider",
         "target": "att_all", "series": s, "horizon": h,
         "period": pd.Timestamp(o) + pd.DateOffset(months=h - 1), "quantile": q,
         "value": 100.0 * q + h, "scale": 1.0}
        for o in origins for s in ("RAA", "RBB") for h in (1, 2) for q in (0.05, 0.5, 0.95)])


def _put(r: Repo, name: str, frame: pd.DataFrame) -> Path:
    """Write ``frame`` as the P5 input ``name`` under INPUTS."""
    path = r.root / checks.INPUTS_REL / name
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path


def _record(r: Repo, tmp_path: Path, **change) -> dict:
    """INPUTS/prepare.json as ``prepare --dev-side`` writes it: the commit, the environment,
    the SHA-256 of every input there, and the dev-reach hash of the table rebuilt from r's
    archive; ``change`` overrides fields."""
    inputs = r.root / checks.INPUTS_REL
    rebuilt = checks.rebuild_vintages(tmp_path / "prepare_vintages", r.root / checks.MANIFEST_REL,
                                      r.root)
    record = {"commit": r.base, "dev_side": True, **checks._env(),
              "sources": {p.relative_to(inputs).as_posix(): file_sha(p)
                          for p in sorted(inputs.rglob("*.parquet"))},
              "vintages": {"row_hash": rebuilt["row_hash"],
                           "dev_reach_hash": checks.dev_reach_hash(rebuilt["path"])}, **change}
    (inputs / checks.PREPARE_RECORD).write_text(json.dumps(record))
    return record


def _link_processed(r: Repo, tmp_path: Path) -> Path:
    """data/processed as an ignored symlink out of the worktree, as in the real layout,
    holding the quarantined pre-seal forecasts."""
    store = tmp_path / "processed_store"
    store.mkdir()
    (r.root / "data" / "processed").symlink_to(store, target_is_directory=True)
    quarantine = r.root / checks.QUARANTINE_FILE_REL
    quarantine.parent.mkdir(parents=True)
    _forecasts([date(2019, 10, 1)]).to_parquet(quarantine, index=False)
    return store


def _processed(r: Repo, tmp_path: Path, monkeypatch) -> Path:
    """``_link_processed``, holding the 21 P5 inputs of design §8 at their origin sets (the
    synthetic M2 file stands in for E-m2-rerun69's) and the prepare record."""
    store = _link_processed(r, tmp_path)
    for name, origins in P5_ORIGINS.items():
        _put(r, name, _forecasts(origins))
    monkeypatch.setattr(checks, "M2_DEV_SHA", file_sha(r.root / checks.INPUTS_REL / M2_INPUT))
    _record(r, tmp_path)
    return store


def _fake_env(monkeypatch, r: Repo) -> None:
    """pip freeze and the import location describe the real worktree, not the temporary one."""
    monkeypatch.setattr(checks, "_pip_freeze", lambda: (
        "pandas==2.2.3\nnumpy==2.1.0\n"
        f"-e git+ssh://git@example.invalid/r.git@{r.head()}#egg=nhs_ae_forecast\n"))
    monkeypatch.setattr(checks, "_import_problems", list)


def _run_ctx(r: Repo, tag: str) -> Context:
    work = r.root / checks.RUN_ROOT_REL / tag
    return Context("run", CONF21, CONF19, dict(D7_FOLD), RUN_END, work, r.root / checks.RESULTS_REL,
                   work / "vintages" / "ae_monthly_all_vintages.parquet", 1)


def _hash_commit(r: Repo, extra: dict[str, str] | None = None) -> str:
    """The runner's hash commit (design §4), plus ``extra`` {path: text} edits."""
    for name in HASH_FILES:
        r.write(f"{checks.RESULTS_REL}/{name}", "file,sha256\n")
    for rel, text in (extra or {}).items():
        r.write(rel, text)
    return r.commit("forecast hashes")


def _row(text: str = f"Discloses the unseal line of {TS}.") -> str:
    return f"| 2026-10-02 (crash fix) | **{TITLE}: guard fix.** {text} | a crash after the unseal |"


def _add_row(r: Repo, row: str) -> None:
    path = r.root / checks.PREREG_REL
    path.write_text(path.read_text().replace("\n\n---\n", f"\n{row}\n\n---\n", 1))


def _line(tag: str, at: str, **change) -> dict:
    """An unseal-log line as splits writes it from ``python -m nhs_ae.evaluate.stage_h run``
    at commit ``at``; ``change`` overrides fields."""
    argv = ["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "run", "--unseal-token-file", "t"]
    return {"timestamp": TS, "token": tag, "head": at, "argv": argv, "sealed_rows": 21,
            "origins": ["2024-01-01", "2025-09-01"], **change}


def _append(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")


def _witness(r: Repo) -> Path:
    return r.root / ".git" / "nhs_ae" / "unseal_witness.jsonl"


def _unsealed_then_fixed(r: Repo, tag: str, **change) -> dict:
    """Crash case 2 (design §9): a log line at the hash commit, then the fix on top of it."""
    entry = _line(tag, _hash_commit(r), **change)
    _append(r.root / checks.LOG_REL, entry)
    _append(_witness(r), entry)
    r.git("rm", "-q", "-r", checks.RESULTS_REL)
    _add_row(r, _row())
    r.commit("crash fix")
    return entry


def _files(base: Path) -> set[Path]:
    return {p for p in base.rglob("*") if ".git" not in p.relative_to(base).parts}


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Repo:
    for var in GIT_VARS:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    r = Repo(root, tmp_path)
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("tag.forceSignAnnotated", "false"), ("core.hooksPath", "/dev/null"),
                       ("core.excludesFile", str(tmp_path / "no-global-excludes"))):
        r.git("config", key, value)
    r.write(".gitignore", "data/processed\n")
    r.write(checks.PREREG_REL, PREREG)
    r.write(checks.LOG_REL, "")
    r.write(checks.LOCK_REL, LOCK)
    r.write("data/reference/provider_icb_map.csv", "org_code,icb\nRTH,QU9\n")
    r.write(checks.PINS_REL, json.dumps({"marker": "tag"}) + "\n")
    _archive(r)
    r.base = r.commit("base")
    monkeypatch.setattr(checks, "PROJECT_ROOT", root)
    return r


@pytest.fixture
def tagged(repo) -> tuple[Repo, str]:
    return repo, repo.tag()


@pytest.fixture
def staged(repo, tmp_path, monkeypatch) -> Repo:
    """Inputs, prepare record and quarantine in place, as ``prepare --dev-side`` leaves them."""
    _processed(repo, tmp_path, monkeypatch)
    return repo


@pytest.fixture
def prepared(staged, tmp_path) -> tuple[Repo, dict]:
    """The staged repository with its pins made, written and committed."""
    pins = checks.make_pins(tmp_path / "scratch")
    checks.write_pins(pins, staged.root / checks.PINS_REL)
    staged.commit("pins")
    return staged, pins


@pytest.fixture
def pinned(prepared, tmp_path, monkeypatch):
    """The prepared repository tagged and pushed to a local bare origin, with a token file,
    a run context and a faked environment."""
    r, _ = prepared
    tag = r.tag()
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    r.git("remote", "add", "origin", str(origin))
    r.git("push", "-q", "origin", f"refs/tags/{TAG}")
    token = tmp_path / "token.txt"
    token.write_text(tag + "\n")
    _fake_env(monkeypatch, r)
    return r, tag, token, _run_ctx(r, tag)


# ---- the shared de-duplication (ingest.cli) ----------------------------------------------
def _old_inline(long: pd.DataFrame) -> pd.DataFrame:
    """cmd_build's de-duplication as it stood inline before the refactor."""
    rank = long["source_file"].str.lower().str.extract(r"\.(csv|xlsx|xls)$")[0].map(
        {"csv": 0, "xlsx": 1, "xls": 2}).fillna(3)
    return (long.assign(_rank=rank).sort_values("_rank", kind="stable")
                .drop_duplicates(["period", "org_code", "metric", "snapshot"], keep="first")
                .drop(columns="_rank").sort_values(["snapshot", "period", "org_code"])
                .reset_index(drop=True))


def _long() -> pd.DataFrame:
    """The same vintages held in several formats, shuffled; the value marks the copy."""
    copies = {("2016-07-14", "RAA"): ("xls", "CSV", "xlsx", "ods"),
              ("2016-07-14", "RBB"): ("xls", "xlsx"),
              ("2016-11-10", "RAA"): ("ods", "xls"),
              ("2016-11-10", "RBB"): ("csv",)}
    rows = [{"period": pd.Timestamp("2016-06-01"), "org_code": org, "parent_org": "Q",
             "org_name": f"Trust {org}", "metric": metric, "value": 100.0 + i, "is_total": False,
             "source_file": f"June-2016.{ext}", "snapshot": snap}
            for (snap, org), exts in copies.items()
            for metric in ("att_type1", "adm_via_ae_type1") for i, ext in enumerate(exts)]
    return pd.DataFrame(rows).sample(frac=1, random_state=0).reset_index(drop=True)


def test_dedupe_vintages_matches_the_old_inline_code_and_prefers_csv_then_xlsx_then_xls():
    long = _long()
    new = cli.dedupe_vintages(long)
    pd.testing.assert_frame_equal(new, _old_inline(long))
    kept = new[new["metric"] == "att_type1"].set_index(["snapshot", "org_code"])["source_file"]
    assert kept.str.rsplit(".", n=1).str[1].to_dict() == {
        ("2016-07-14", "RAA"): "CSV", ("2016-07-14", "RBB"): "xlsx",
        ("2016-11-10", "RAA"): "xls", ("2016-11-10", "RBB"): "csv"}
    assert len(new) == 8 and not new.duplicated(["period", "org_code", "metric", "snapshot"]).any()


def test_cmd_build_writes_the_deduplicated_table(monkeypatch, tmp_path):
    long = _long()
    failures = pd.DataFrame(columns=["path", "period", "snapshot", "sha256", "error"])
    monkeypatch.setattr(cli, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(cli, "read_manifest", lambda _p: [{"ext": "csv", "stored": True}])
    monkeypatch.setattr(cli, "parse_manifest_records", lambda _m, _r: (long.copy(), failures))
    assert cli.cmd_build(None) == 0
    got = pd.read_parquet(tmp_path / "processed" / "ae_monthly_all_vintages.parquet")
    pd.testing.assert_frame_equal(got, _old_inline(long), check_dtype=False)


# ---- P4 rebuild and the D7 slices --------------------------------------------------------
def test_rebuild_writes_only_into_its_out_dir(repo, tmp_path):
    before = _files(tmp_path)
    out = tmp_path / "rebuilt"
    res = checks.rebuild_vintages(out, repo.root / checks.MANIFEST_REL, repo.root)
    assert _files(tmp_path) - before == {out, out / "ae_monthly_all_vintages.parquet",
                                         out / "parse_failures.csv"}
    assert res["path"] == out / "ae_monthly_all_vintages.parquet" and res["failures"] == [BROKEN]
    assert res["manifest_sha"] == file_sha(repo.root / checks.MANIFEST_REL)
    v = pd.read_parquet(res["path"])
    assert res["rows"] == len(v) and res["row_hash"] == checks.vintage_hash(v)
    assert checks.vintage_hash(v.sample(frac=1, random_state=1)) == res["row_hash"]
    snapshots = pd.to_datetime(v["snapshot"]).dt.strftime("%Y-%m-%d")
    assert sorted(snapshots.unique()) == ["2016-07-14", "2016-08-11", "2016-11-10"]


def test_defaults_resolve_against_the_patched_project_root_at_call_time(repo, tmp_path,
                                                                        monkeypatch):
    """git(), write_pins() and rebuild_vintages() with their defaults act on the temporary
    repository. The signatures are checked first and tripwires fail any manifest read, file
    hash, parse or text write outside tmp_path, so a regression cannot touch the real tree."""
    params = {f: inspect.signature(getattr(checks, f)).parameters
              for f in ("git", "write_pins", "rebuild_vintages")}
    assert [params["git"]["cwd"].default, params["write_pins"]["path"].default,
            params["rebuild_vintages"]["manifest_path"].default,
            params["rebuild_vintages"]["raw_root"].default] == [None] * 4
    base = tmp_path.resolve()

    def guard(fn, arg: int):
        def guarded(*args, **kwargs):
            target = Path(args[arg]).resolve()
            if target != base and base not in target.parents:
                pytest.fail(f"{fn.__name__} reached {target}, outside tmp_path")
            return fn(*args, **kwargs)
        return guarded

    for name, arg in (("read_manifest", 0), ("file_sha", 0), ("parse_manifest_records", 1)):
        monkeypatch.setattr(checks, name, guard(getattr(checks, name), arg))
    monkeypatch.setattr(Path, "write_text", guard(Path.write_text, 0))
    assert Path(checks.git("rev-parse", "--show-toplevel")).resolve() == repo.root.resolve()
    written = checks.write_pins({"marker": "default path"})
    assert written == repo.root / checks.PINS_REL
    assert json.loads(written.read_text()) == {"marker": "default path"}
    res = checks.rebuild_vintages(tmp_path / "rebuilt")
    assert res["manifest_sha"] == file_sha(repo.root / checks.MANIFEST_REL)
    assert res["failures"] == [BROKEN] and res["path"].parent == tmp_path / "rebuilt"


def test_rebuild_refuses_a_stored_file_that_differs_from_the_manifest(repo, tmp_path):
    repo.write("data/raw/2016-08-11/Monthly-AE-July-2016.csv", _csv("JULY-2016", 1))
    with pytest.raises(RefusedError, match="SHA-256"):
        checks.rebuild_vintages(tmp_path / "rebuilt", repo.root / checks.MANIFEST_REL, repo.root)
    assert not (tmp_path / "rebuilt").exists()
    with pytest.raises(RefusedError, match="check 9"):
        checks.check_raw(None)


def test_rebuild_refuses_without_the_excel_readers(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "missing_readers", lambda _m: ["xlrd"])
    with pytest.raises(RefusedError, match="xlrd"):
        checks.rebuild_vintages(tmp_path / "rebuilt", repo.root / checks.MANIFEST_REL, repo.root)
    assert not (tmp_path / "rebuilt").exists()


def _vintage_rows(rows) -> pd.DataFrame:
    cols = ["period", "org_code", "parent_org", "org_name", "metric", "value", "is_total",
            "snapshot"]
    v = pd.DataFrame(rows, columns=cols)
    return v.assign(period=pd.to_datetime(v["period"]), snapshot=pd.to_datetime(v["snapshot"]))


def test_d7_slice_hashes_differ_only_when_a_version_lands_by_a_later_as_of_date():
    """Synthetic values on real dates; the three as-of dates are 2025-07-10, -08-14, -09-11."""
    rows = [(p, org, "Q", "Trust", "att_type1", 100.0, False, snap)
            for p, snap in (("2025-04-01", "2025-05-08"), ("2025-05-01", "2025-06-12"),
                            ("2025-06-01", "2025-07-10"))
            for org in ("RAA", "RBB")]
    rows += [("2022-10-01", "RAA", "Q", "Trust", "att_type1", 90.0, False, "2022-11-10"),
             ("2025-06-01", "ENGLAND", "-", "England", "att_type1", 200.0, True, "2025-07-10"),
             ("2025-07-01", "RAA", "Q", "Trust", "att_type1", 120.0, False, "2025-11-13")]
    h = checks.d7_slice_hashes(_vintage_rows(rows))
    assert list(h) == ["2025-07", "2025-08", "2025-09"] and len(set(h.values())) == 1
    revised = rows + [("2022-10-01", "RAA", "Q", "Trust", "att_type1", 91.0, False, "2025-09-11")]
    h2 = checks.d7_slice_hashes(_vintage_rows(revised))
    assert h2["2025-07"] == h2["2025-08"] == h["2025-07"] != h2["2025-09"]
    beyond_end = ("2025-08-01", "ENGLAND", "-", "England", "att_type1", 1.0, True, "2025-09-11")
    assert checks.d7_slice_hashes(_vintage_rows([*rows, beyond_end])) == h   # after the as-of end


def test_dev_reach_hash_covers_every_snapshot_of_the_periods_a_dev_slice_reads(tmp_path):
    """Synthetic values on real dates: periods to 2023-11 at any snapshot (a final-mode DEV
    slice reads their latest version), nothing after."""
    rows = [("2023-10-01", "RAA", "Q", "Trust", "att_type1", 100.0, False, "2023-11-09"),
            ("2023-11-01", "RAA", "Q", "Trust", "att_type1", 110.0, False, "2023-12-14")]
    v = _vintage_rows(rows)
    h = checks.dev_reach_hash(v)
    assert checks.DEV_REACH == pd.Timestamp("2023-11-01")
    assert checks.dev_reach_hash(v.iloc[::-1]) == h
    later = ("2023-11-01", "RAA", "Q", "Trust", "att_type1", 111.0, False, "2024-03-14")
    assert checks.dev_reach_hash(_vintage_rows([*rows, later])) != h
    after = ("2023-12-01", "RAA", "Q", "Trust", "att_type1", 120.0, False, "2024-01-11")
    assert checks.dev_reach_hash(_vintage_rows([*rows, after])) == h
    path = tmp_path / "vintages.parquet"
    v.assign(source_file="June.csv").to_parquet(path, index=False)
    assert checks.dev_reach_hash(path) == checks.dev_reach_hash(load_vintages(path)) == h
    with pytest.raises(ValueError, match="load_vintages"):
        checks.dev_reach_hash(pd.read_parquet(path))          # the raw table would hash apart


# ---- the permitted inputs (P5, design §8) ------------------------------------------------
def test_the_permitted_inputs_are_what_prepare_copies_and_dev_side_writes():
    from nhs_ae.evaluate.stage_h import generate, steps
    ctx = Context("dev", DEV, DEV, {}, max(DEV), Path("dev_side"), Path("unused"), Path("v"))
    written = {generate.forecast_path(ctx, *key).as_posix() for key in DEV_SIDE_KEYS}
    assert set(steps.input_paths()) | written == P5_INPUTS and len(P5_INPUTS) == 21
    assert len(written) == 8 and set(P5_ORIGINS) == P5_INPUTS
    assert (POOL_ORIGINS[0], POOL_ORIGINS[-1], len(POOL_ORIGINS)) == (
        date(2017, 7, 1), date(2023, 12, 1), 78)
    assert len(DEV) == 69 and len(DEV_WINTER_H3) == 23
    assert {o.month for o in DEV_WINTER_H3} == {10, 11, 12, 1}
    sizes = {n: len(o) for n, o in P5_ORIGINS.items() if not n.startswith("pool/")}
    as_of = {f"dev_side/forecasts/{k}_provider_asof.parquet" for k in ("b0", "m1")}
    assert sizes == {n: 69 if n in as_of or n == M2_INPUT else 23 for n in sizes}


# ---- pins --------------------------------------------------------------------------------
def test_make_pins_records_design_3_1(prepared, tmp_path):
    r, pins = prepared
    assert pins["manifest_sha"] == file_sha(r.root / checks.MANIFEST_REL)
    assert pins["parse_failures"] == [BROKEN] and pins["gen_commit"] == r.base
    assert pins["reference"] == {"data/reference/provider_icb_map.csv":
                                 file_sha(r.root / "data/reference/provider_icb_map.csv")}
    assert set(pins["inputs"]) == P5_INPUTS
    pool = pins["inputs"]["pool/base_b1_provider.parquet"]
    assert pool["rows"] == 12 * 78 and len(pool["origins"]) == 78
    assert (pool["origins"][0], pool["origins"][-1], pool["model"], pool["level"],
            pool["mode"]) == ("2017-07-01", "2023-12-01", ["b1_ets"], ["provider"], ["asof"])
    assert {n: p["origins"] for n, p in pins["inputs"].items()} == {
        n: [f"{o:%Y-%m-%d}" for o in origins] for n, origins in P5_ORIGINS.items()}
    record = json.loads((r.root / checks.INPUTS_REL / checks.PREPARE_RECORD).read_text())
    assert pins["vintages"]["dev_reach_hash"] == record["vintages"]["dev_reach_hash"]
    assert (pins["python"], pins["platform"]) == (record["python"], record["platform"])
    assert {n: p["sha256"] for n, p in pins["inputs"].items()} == record["sources"]
    assert pins["quarantine"] == {"path": checks.QUARANTINE_FILE_REL,
                                  "sha256": file_sha(r.root / checks.QUARANTINE_FILE_REL)}
    assert list(pins["d7_slices"]) == ["2025-07", "2025-08", "2025-09"]
    assert len(set(pins["d7_slices"].values())) == 1
    assert pins["vintages"]["shared_row_hash"] is None          # no shared table here
    assert {"platform", "python", "head", "row_hash_rule"} <= set(pins)
    assert sorted(p.name for p in (tmp_path / "scratch").iterdir()) == [
        "ae_monthly_all_vintages.parquet", "parse_failures.csv"]
    assert json.loads(r.git("show", f"HEAD:{checks.PINS_REL}")) == pins


def _dev_side(name: str) -> str:
    return f"dev_side/forecasts/{name}.parquet"


def _without_dev_side(r, tmp_path):                     # `prepare` without --dev-side: 13 files
    shutil.rmtree(r.root / checks.INPUTS_REL / "dev_side")
    _record(r, tmp_path)


def _one_lost(r, tmp_path):
    (r.root / checks.INPUTS_REL / _dev_side("b1_provider_asof")).unlink()
    _record(r, tmp_path)


def _one_extra(r, tmp_path):
    _put(r, _dev_side("b1_provider_asof_unseeded"), _forecasts(DEV_WINTER_H3))
    _record(r, tmp_path)


def _final_at_every_dev_origin(r, tmp_path):
    _put(r, _dev_side("b2_provider_final"), _forecasts(DEV))
    _record(r, tmp_path)


def _pool_short_of_its_first_origin(r, tmp_path):
    _put(r, "pool/base_m1_v3_raw_region.parquet", _forecasts(POOL_ORIGINS[1:]))
    _record(r, tmp_path)


def _changed_after_prepare(r, tmp_path):                # same origins, other values
    _put(r, "pool/base_b2_icb.parquet", _forecasts(POOL_ORIGINS).assign(value=1.0))


@pytest.mark.parametrize("change, why", [
    (lambda r, t: _record(r, t, dev_side=False),
     r"records dev_side False: the inputs were prepared without --dev-side"),
    (lambda r, t: (r.root / checks.INPUTS_REL / checks.PREPARE_RECORD).unlink(),
     r"no .*prepare\.json; run prepare --dev-side"),
    (lambda r, t: _record(r, t, commit="f" * 40), "is not a commit"),
    (_without_dev_side, (r"not the 21 permitted files of design §8: missing \['dev_side/"
                         r"forecasts/b0_provider_asof\.parquet', .*run prepare --dev-side")),
    (_one_lost, r"missing \['dev_side/forecasts/b1_provider_asof\.parquet'\], unexpected \[\]"),
    (_one_extra, r"unexpected \['dev_side/forecasts/b1_provider_asof_unseeded\.parquet'\]"),
    (_final_at_every_dev_origin,
     r"input dev_side/forecasts/b2_provider_final\.parquet holds 69 origins, not its 23"),
    (_pool_short_of_its_first_origin, (r"input pool/base_m1_v3_raw_region\.parquet holds 77 "
                                       r"origins, not its 78 \(lacking \['2017-07-01'\]")),
    (_changed_after_prepare,
     r"1 inputs differ from the SHA-256 prepare recorded: \['pool/base_b2_icb\.parquet'\]"),
    (lambda r, t: _record(r, t, sources=None), "records no input hashes"),
    (lambda r, t: _record(r, t, vintages={"row_hash": "0" * 64}), "records no dev_reach_hash"),
    (lambda r, t: _record(r, t, python="3.0.0"),
     r"python is .*, prepare --dev-side ran on 3\.0\.0; re-run prepare --dev-side here"),
    (lambda r, t: _record(r, t, platform="Other-1.0"), "platform is .*ran on Other-1.0"),
])
def test_pin_refuses_inputs_short_of_a_dev_side_prepare(staged, tmp_path, change, why):
    """Design §8 and report-commands:1-2: pin only a ``prepare --dev-side`` of the 21 files at
    their origin sets, unchanged since prepare and on prepare's environment; every refusal
    comes before the rebuild."""
    change(staged, tmp_path)
    with pytest.raises(RefusedError, match=f"pin: .*{why}"):
        checks.make_pins(tmp_path / "scratch")
    assert not (tmp_path / "scratch").exists()


def test_pin_refuses_an_m2_file_other_than_e_m2_rerun69s(staged, tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "M2_DEV_SHA", M2_DEV_SHA)
    with pytest.raises(RefusedError, match=f"pin: input {M2_INPUT} is not E-m2-rerun69's file"):
        checks.make_pins(tmp_path / "scratch")
    assert not (tmp_path / "scratch").exists()


def test_pin_refuses_a_gen_commit_other_than_the_recorded_one(staged, tmp_path):
    staged.write("notes.txt", "x\n")
    later = staged.commit("a later commit")
    with pytest.raises(RefusedError, match="is not the prepare --dev-side commit"):
        checks.make_pins(tmp_path / "scratch", gen_commit=later)
    assert not (tmp_path / "scratch").exists()
    pins = checks.make_pins(tmp_path / "scratch", gen_commit=staged.base)
    assert pins["gen_commit"] == staged.base


def _store(r: Repo, snap: str, name: str, period: str, text: str, revised: bool = True) -> None:
    """Add a stored file to r's archive and its manifest, as the archive bot would."""
    rel = f"data/raw/{snap}/{name}"
    rec = {"filename": name, "period": period, "ext": "csv", "snapshot": snap,
           "available_from": snap, "revised": revised, "revised_on": None,
           "sha256": file_sha(r.write(rel, text)), "stored": True, "path": rel}
    with (r.root / checks.MANIFEST_REL).open("a") as fh:
        fh.write(json.dumps(rec) + "\n")


def test_pin_refuses_a_dev_period_revised_between_prepare_and_pin(staged, tmp_path):
    """The DEV side read the table as prepare rebuilt it. A later version of a DEV-reach period,
    stored before pin, changes what a final-mode DEV slice reads: prepare must run again."""
    _store(staged, "2017-01-12", "Monthly-AE-June-2016-revised-2.csv", "2016-06-01",
           _csv("JUNE-2016", 99))
    staged.commit("a second revision of June 2016")
    with pytest.raises(RefusedError, match="dev_reach_hash differs.*re-run prepare --dev-side"):
        checks.make_pins(tmp_path / "scratch")
    record = _record(staged, tmp_path)                  # prepare --dev-side on the new table
    pins = checks.make_pins(tmp_path / "scratch2")
    assert pins["vintages"]["dev_reach_hash"] == record["vintages"]["dev_reach_hash"]


def test_pin_accepts_a_month_stored_after_prepare_beyond_the_dev_reach(staged, tmp_path):
    """Positive control, at the boundary: the bot stores 2023-12, the first period no DEV-origin
    slice reads, between prepare and pin. The table changes (a full-table rule would force hours
    of regeneration); the rows the DEV side read do not, so pin goes ahead."""
    record = json.loads((staged.root / checks.INPUTS_REL / checks.PREPARE_RECORD).read_text())
    _store(staged, "2024-01-11", "Monthly-AE-December-2023.csv", "2023-12-01",
           _csv("DECEMBER-2023"), revised=False)
    staged.commit("a new month after prepare --dev-side")
    pins = checks.make_pins(tmp_path / "scratch")
    assert pins["vintages"]["row_hash"] != record["vintages"]["row_hash"]
    assert pins["vintages"]["dev_reach_hash"] == record["vintages"]["dev_reach_hash"]
    v = load_vintages(tmp_path / "scratch" / "ae_monthly_all_vintages.parquet")
    assert v["period"].max() == pd.Timestamp("2023-12-01") > checks.DEV_REACH


# ---- prepare --dev-side: the writer of the record pin reads -----------------------------
@dataclass
class Prep:
    """A repository before ``prepare --dev-side``: the processed store, the 13 sources, and the
    stubbed generate.dev_side's calls; ``during(prep, out_dir, vintages_path)`` runs inside
    that stub once it has written its 8 files."""
    repo: Repo
    store: Path
    sources: dict[str, Path]
    calls: list = field(default_factory=list)
    during: Callable | None = None

    @property
    def inputs(self) -> Path:
        return self.repo.root / checks.INPUTS_REL


def _write_forecasts(path: Path, origins) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _forecasts(origins).to_parquet(path, index=False)


def _sources(store: Path) -> dict[str, Path]:
    """The 13 files prepare copies, at their P5 origin sets, where steps.input_paths finds the
    real ones (stage_f/ and stage_h_prep/)."""
    out = {}
    for name in sorted(checks.COPIED_INPUTS):
        out[name] = store / ("stage_h_prep/forecasts_m2d_corr.parquet" if name == M2_INPUT
                             else f"stage_f/{Path(name).name}")
        _write_forecasts(out[name], P5_ORIGINS[name])
    return out


def _fake_dev_side(p: Prep):
    """generate.dev_side's stand-in: its 8 files at their origin sets, named as it names them."""
    from nhs_ae.evaluate.stage_h import generate

    def dev_side(out_dir, jobs, vintages_path):
        out_dir, vintages_path = Path(out_dir), Path(vintages_path)
        p.calls.append((out_dir, jobs, vintages_path))
        ctx = Context("dev", DEV, DEV, {}, max(DEV), out_dir, out_dir, vintages_path, jobs)
        files = {key: generate.forecast_path(ctx, *key) for key in DEV_SIDE_ORIGINS}
        for key, path in files.items():
            _write_forecasts(path, DEV_SIDE_ORIGINS[key])
        if p.during is not None:
            p.during(p, out_dir, vintages_path)
        return files
    return dev_side


@pytest.fixture
def unprepared(repo, tmp_path, monkeypatch) -> Prep:
    """data/processed linked with the quarantine and the 13 sources (the synthetic M2 file
    standing in for E-m2-rerun69's), checks 7-8 faked, and generate.dev_side stubbed."""
    from nhs_ae.evaluate.stage_h import generate
    store = _link_processed(repo, tmp_path)
    p = Prep(repo, store, _sources(store))
    monkeypatch.setattr(checks, "M2_DEV_SHA", file_sha(p.sources[M2_INPUT]))
    _fake_env(monkeypatch, repo)
    monkeypatch.setattr(generate, "dev_side", _fake_dev_side(p))
    return p


def test_prepare_writes_the_record_pin_reads(unprepared, tmp_path):
    """The two sides of prepare.json: prepare --dev-side writes what make_pins reads, so pin
    accepts a fresh prepare as it stands. The DEV side runs on the P4 rebuild outside INPUTS;
    each input is read-only and hashed, in the record and in SHA256SUMS."""
    p = unprepared
    record = checks.prepare_inputs(p.sources, 3)
    vpath = p.repo.root / checks.PREPARE_VINTAGES_REL / "ae_monthly_all_vintages.parquet"
    assert p.calls == [(p.inputs / "dev_side", 3, vpath)]
    assert json.loads((p.inputs / checks.PREPARE_RECORD).read_text()) == record
    assert (record["commit"], record["dev_side"]) == (p.repo.base, True)
    assert {k: record[k] for k in ("python", "platform")} == checks._env()
    files = {q.relative_to(p.inputs).as_posix(): q for q in p.inputs.rglob("*.parquet")}
    assert set(files) == set(record["sources"]) == P5_INPUTS
    assert record["sources"] == {n: file_sha(q) for n, q in files.items()}
    assert all(record["sources"][n] == file_sha(src) for n, src in p.sources.items())
    assert record["vintages"]["dev_reach_hash"] == checks.dev_reach_hash(vpath)
    assert {stat.S_IMODE(q.stat().st_mode) for q in files.values()} == {checks.READ_ONLY}
    assert (p.inputs / "SHA256SUMS").read_text().splitlines() == [
        f"{s}  {n}" for n, s in sorted(record["sources"].items())]
    pins = checks.make_pins(tmp_path / "scratch")
    assert {n: q["sha256"] for n, q in pins["inputs"].items()} == record["sources"]
    assert pins["gen_commit"] == record["commit"]
    assert pins["vintages"]["dev_reach_hash"] == record["vintages"]["dev_reach_hash"]
    assert (pins["python"], pins["platform"]) == (record["python"], record["platform"])


def test_cmd_prepare_writes_what_pin_reads(unprepared, tmp_path, monkeypatch):
    """The command, then pin: ``prepare --dev-side`` must leave what make_pins accepts, so the
    two sides of prepare.json cannot drift apart again (it fails while __main__.cmd_prepare
    writes its own record instead of calling checks.prepare_inputs). Every path the command
    could write is pointed into tmp_path first."""
    from nhs_ae.evaluate.stage_h import __main__ as runner
    from nhs_ae.evaluate.stage_h import steps
    p = unprepared
    vdir = p.repo.root / checks.PREPARE_VINTAGES_REL
    monkeypatch.setattr(runner, "INPUTS", p.inputs, raising=False)
    monkeypatch.setattr(runner, "PREPARE_VINTAGES", vdir, raising=False)
    monkeypatch.setattr(steps, "input_paths", lambda: dict(p.sources))
    assert runner.main(["prepare", "--dev-side", "--jobs", "2"]) == 0
    assert p.calls == [(p.inputs / "dev_side", 2, vdir / "ae_monthly_all_vintages.parquet")]
    record = json.loads((p.inputs / checks.PREPARE_RECORD).read_text())
    pins = checks.make_pins(tmp_path / "scratch")
    assert {n: q["sha256"] for n, q in pins["inputs"].items()} == record["sources"]
    assert pins["gen_commit"] == record["commit"] == p.repo.base


def _stray_input(p: Prep, mp) -> None:
    p.inputs.mkdir(parents=True)
    (p.inputs / "stray.txt").write_text("x\n")


@pytest.mark.parametrize("change, why", [
    (lambda p, mp: p.repo.tag(), f"{TAG} exists"),
    (_stray_input, "is not empty: move it aside first"),
    (lambda p, mp: {"vintages_dir": p.inputs / "vintages"}, "would lie inside"),
    (lambda p, mp: p.sources.pop("pool/base_b2_icb.parquet"),
     r"missing \['pool/base_b2_icb\.parquet'\], unexpected \[\]"),
    (lambda p, mp: p.sources.update({_dev_side("b0_provider_asof"): p.sources[M2_INPUT]}),
     r"missing \[\], unexpected \['dev_side/forecasts/b0_provider_asof\.parquet'\]"),
    (lambda p, mp: p.repo.write("notes.txt", "x\n"), "check 6: the tree is not clean"),
    (lambda p, mp: mp.setattr(checks, "_import_problems", lambda: ["imported from elsewhere"]),
     "check 7: imported from elsewhere"),
    (lambda p, mp: mp.setattr(checks, "M2_DEV_SHA", M2_DEV_SHA),
     f"input {M2_INPUT} is not E-m2-rerun69's file"),
    (lambda p, mp: _write_forecasts(p.sources["pool/base_m1_v3_raw_region.parquet"],
                                    POOL_ORIGINS[1:]),
     r"input pool/base_m1_v3_raw_region\.parquet holds 77 origins, not its 78"),
    (lambda p, mp: _forecasts(DEV).assign(y=1.0).to_parquet(p.sources[M2_INPUT], index=False),
     r"input forecasts_m2d_corr\.parquet is not a forecast file .*carries \['y'\]"),
])
def test_prepare_refuses_before_writing_anything(unprepared, monkeypatch, change, why):
    """The tag, a used INPUTS, a rebuild inside it, the wrong sources, checks 6-8 and a source
    pin would refuse (M2 not E-m2-rerun69's, a wrong origin set, an outturn column) all stop
    prepare before it copies, rebuilds or generates anything."""
    p = unprepared
    kwargs = change(p, monkeypatch)
    kwargs = kwargs if isinstance(kwargs, dict) else {}     # only the rebuild case passes one

    def snapshot() -> dict:
        return {q: q.read_bytes() if q.is_file() else None for q in _files(p.store)}
    before = snapshot()
    with pytest.raises(RefusedError, match=f"prepare: .*{why}"):
        checks.prepare_inputs(p.sources, 1, **kwargs)
    assert snapshot() == before and p.calls == []


def _corrupt_one_copy(p: Prep, mp) -> None:
    real = shutil.copy2

    def copy2(src, dst, *args, **kwargs):
        out = real(src, dst, *args, **kwargs)
        if Path(src).name == "base_b2_icb.parquet":
            with open(dst, "ab") as fh:
                fh.write(b"\0")
        return out
    mp.setattr(shutil, "copy2", copy2)


def _during(fn):
    def change(p: Prep, mp) -> None:
        p.during = fn
    return change


@pytest.mark.parametrize("change, why, generated", [
    (_corrupt_one_copy,
     r"prepare: the copy of .*base_b2_icb\.parquet differs from the SHA-256 taken before", False),
    (_during(lambda p, d, v: _write_forecasts(d / "vintages" / v.name, DEV)),   # the old default
     (r"dev_side left 9 files, not design §8's 8: missing \[\], unexpected "
      r"\['dev_side/vintages/ae_monthly_all_vintages\.parquet'\]"), True),
    (_during(lambda p, d, v: (d / "forecasts" / "b1_provider_asof.parquet").unlink()),
     r"missing \['dev_side/forecasts/b1_provider_asof\.parquet'\], unexpected \[\]", True),
    (_during(lambda p, d, v: _write_forecasts(d / "forecasts" / "b2_provider_final.parquet", DEV)),
     r"input dev_side/forecasts/b2_provider_final\.parquet holds 69 origins, not its 23", True),
    (_during(lambda p, d, v: v.write_bytes(v.read_bytes() + b"\0")),
     "changed while the DEV side was generated", True),
    (_during(lambda p, d, v: (p.repo.write("notes.txt", "x\n"), p.repo.commit("meanwhile"))),
     "HEAD moved from", True),
    (_during(lambda p, d, v: p.repo.write("src/nhs_ae/models/edit.py", "x = 2\n")),
     "prepare, after the DEV side: check 6", True),
])
def test_prepare_writes_no_record_unless_inputs_pin_would_take(unprepared, tmp_path,
                                                               monkeypatch, change, why,
                                                               generated):
    """Once copying has begun, a copy that differs from its source, a DEV side short of or
    beyond design §8's files or origin sets, or a table, HEAD or tree changed meanwhile leaves
    no prepare.json, so pin refuses the partial INPUTS and prepare will not reuse it."""
    p = unprepared
    change(p, monkeypatch)
    with pytest.raises(RefusedError, match=why) as refused:
        checks.prepare_inputs(p.sources, 1)
    assert str(refused.value).startswith("prepare")
    assert len(p.calls) == generated
    assert not (p.inputs / checks.PREPARE_RECORD).exists()
    assert not (p.inputs / "SHA256SUMS").exists()
    with pytest.raises(RefusedError, match=r"pin: no .*prepare\.json; run prepare --dev-side"):
        checks.make_pins(tmp_path / "scratch")
    with pytest.raises(RefusedError, match="is not empty: move it aside first"):
        checks.prepare_inputs(p.sources, 1)


def test_make_pins_refuses_once_the_tag_exists(tagged, tmp_path):
    with pytest.raises(RefusedError, match="exists"):
        checks.make_pins(tmp_path / "scratch")
    assert not (tmp_path / "scratch").exists()
    with pytest.raises(RefusedError, match="exists"):
        checks.write_pins({}, tmp_path / "pins.json")
    assert not (tmp_path / "pins.json").exists()


def test_pins_are_read_from_the_tag_not_the_working_tree(tagged):
    r, _ = tagged
    r.write(checks.PINS_REL, json.dumps({"marker": "later"}) + "\n")
    r.commit("re-pinned after the tag")
    assert checks.read_pins(from_tag=True) == {"marker": "tag"}
    assert checks.read_pins(from_tag=False) == {"marker": "later"}


# ---- HEAD rules --------------------------------------------------------------------------
def test_start_commit_is_the_tag_or_an_amendment_descendant(tagged):
    r, tag = tagged
    assert checks.start_commit_ok(tag)[0]
    assert not checks.start_commit_ok(tag, TITLE)[0]
    r.write("src/nhs_ae/fix.py", "x = 1\n")
    plain = r.commit("a fix without a row")
    assert not checks.start_commit_ok(plain)[0]
    ok, why = checks.start_commit_ok(plain, TITLE)
    assert not ok and "0 §10 rows" in why
    _add_row(r, _row())
    amended = r.commit("the amendment row")
    assert checks.start_commit_ok(amended, TITLE)[0]
    assert checks.start_commit_ok(amended, f"{TITLE}: guard fix")[0]
    assert not checks.start_commit_ok(amended)[0]
    assert not checks.start_commit_ok(amended, "Stage H rerun")[0]
    ok, why = checks.start_commit_ok(amended, "Re-split by origin")
    assert not ok and "already" in why
    _add_row(r, _row("A second row under the same title."))
    assert not checks.start_commit_ok(r.commit("a duplicate title"), TITLE)[0]
    r.git("checkout", "-q", "--orphan", "elsewhere")
    ok, why = checks.start_commit_ok(r.commit("unrelated history"), TITLE)
    assert not ok and "descend" in why


def test_hash_commit_rule(tagged):
    r, tag = tagged
    h1 = _hash_commit(r)
    assert checks.hash_commit_ok(h1, tag)[0]
    r.write(f"{checks.RESULTS_REL}/timings.csv", "changed\n")
    h2 = r.commit("a second runner commit")
    ok, why = checks.hash_commit_ok(h2, tag)
    assert not ok and "parents" in why                           # two stacked commits
    assert not checks.hash_commit_ok(h2, h1)[0]
    r.git("checkout", "-q", "--detach", tag)
    ok, why = checks.hash_commit_ok(_hash_commit(r, {"src/nhs_ae/x.py": "x = 1\n"}), tag)
    assert not ok and "src/nhs_ae/x.py" in why                   # touches another path
    r.git("checkout", "-q", "--detach", tag)
    r.write(f"{checks.RESULTS_REL}/forecast_hashes.csv", "old\n")
    earlier = r.commit("a hash file already there")
    ok, why = checks.hash_commit_ok(_hash_commit(r), earlier)
    assert not ok and f"M {checks.RESULTS_REL}/forecast_hashes.csv" in why   # modifies a file
    assert not checks.hash_commit_ok(earlier, tag)[0]            # adds one of the four only
    r.git("checkout", "-q", "--detach", tag)
    _add_row(r, _row())
    start = r.commit("amendment descendant")
    assert checks.start_commit_ok(start, TITLE)[0]
    assert checks.hash_commit_ok(_hash_commit(r), start)[0]


def test_the_private_git_helpers_main_uses_bind_the_patched_root(tagged):
    """__main__ uses checks' _commit, _tag_commit, _blob(ref, rel, root=None), _descends,
    _rows_titled and _root: since P11, wrappers of evaluate.seal_rules that bind PROJECT_ROOT
    at call time."""
    r, tag = tagged
    assert checks._root() == r.root and checks._tag_commit() == tag == checks._commit(TAG)
    assert checks._commit("HEAD") == r.head() and checks._commit("-h") is None
    assert checks._blob(tag, checks.PREREG_REL) == PREREG.encode()
    assert checks._blob(tag, checks.PREREG_REL, r.root) == PREREG.encode()
    assert checks._blob(tag, "absent.txt") is None
    _add_row(r, _row())
    amended = r.commit("the amendment row")
    assert checks._descends(amended, tag) and not checks._descends(tag, tag)
    assert checks._rows_titled(amended, TITLE) == [_row()]
    assert checks._rows_titled(tag, TITLE) == []


@pytest.mark.parametrize("rel", ["data/raw/manifest.jsonl", "data/reference/provider_icb_map.csv",
                                 checks.PINS_REL, checks.LOCK_REL])
def test_data_pin_or_lock_change_since_the_tag_refuses(tagged, rel):
    r, tag = tagged
    path = r.root / rel
    path.write_text(path.read_text() + "\n")
    with pytest.raises(RefusedError, match="check 5"):
        checks.check_frozen(tag, r.commit(f"edit {rel}"))


def test_code_change_since_the_tag_passes_the_data_check(tagged):
    r, tag = tagged
    r.write("src/nhs_ae/fix.py", "x = 1\n")
    _add_row(r, _row())
    checks.check_frozen(tag, r.commit("fix"))


# ---- checks 1-3, 6-9, 12 -----------------------------------------------------------------
def test_existing_output_directory_refuses_before_any_other_check(repo, tmp_path):
    ctx = _run_ctx(repo, "a" * 40)
    for d in (ctx.results, ctx.work):
        d.mkdir(parents=True)
        with pytest.raises(RefusedError, match="check 1"):
            checks.pre_run(ctx, tmp_path / "absent-token")
        d.rmdir()
    with pytest.raises(RefusedError, match="check 2"):
        checks.pre_run(ctx, tmp_path / "absent-token")


def test_tag_must_be_annotated_and_pushed(repo, tmp_path):
    repo.git("tag", TAG)
    with pytest.raises(RefusedError, match="lightweight"):
        checks.check_tag()
    repo.git("tag", "-d", TAG)
    tag = repo.tag()
    with pytest.raises(RefusedError, match="push the tag"):
        checks.check_tag()
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
    repo.git("remote", "add", "origin", str(origin))
    repo.git("push", "-q", "origin", f"refs/tags/{TAG}")
    assert checks.check_tag()["tag_commit"] == tag


def test_token_file_must_hold_the_tag_commit(tmp_path):
    token = tmp_path / "token.txt"
    token.write_text("b" * 40 + "\n")
    checks.check_token(token, "b" * 40)
    token.write_text("c" * 40 + "\n")
    with pytest.raises(RefusedError, match="check 3") as err:
        checks.check_token(token, "b" * 40)
    assert "c" * 12 not in str(err.value)
    with pytest.raises(RefusedError, match="check 3"):
        checks.check_token(tmp_path / "absent", "b" * 40)
    token.write_text("")
    with pytest.raises(RefusedError, match="check 3: .*empty"):
        checks.check_token(token, "b" * 40)


def test_token_reachable_by_spawn_workers_is_refused_at_check_3(tmp_path, monkeypatch):
    """§2.2: step 2 reads the token as step 4 will, so a token-file path holding the SHA
    fails here rather than after step 3 and the hash commit."""
    tag = "b" * 40
    token = tmp_path / f"{tag}.txt"
    token.write_text(tag + "\n")
    checks.check_token(token, tag)
    argv = ["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "run", "--unseal-token-file", str(token)]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(RefusedError, match=r"check 3: .*sys\.argv") as err:
        checks.check_token(token, tag)
    assert tag not in str(err.value)
    monkeypatch.setattr(sys, "argv", argv[:3] + [str(tmp_path / "token.txt")])
    monkeypatch.setenv("STAGE_H_TOKEN", tag)
    with pytest.raises(RefusedError, match=r"check 3: .*os\.environ"):
        checks.check_token(token, tag)
    monkeypatch.delenv("STAGE_H_TOKEN")
    checks.check_token(token, tag)
    monkeypatch.setattr(multiprocessing, "parent_process", object)
    with pytest.raises(RefusedError, match="check 3: .*parent process"):
        checks.check_token(token, tag)


def test_clean_tree_refuses_untracked_and_modified_files_but_not_ignored_ones(repo):
    checks.check_clean()
    repo.write("data/processed/x.parquet", "ignored")
    checks.check_clean()
    repo.write(".claude/settings.local.json", "{}")
    with pytest.raises(RefusedError, match="check 6"):
        checks.check_clean()
    (repo.root / ".claude/settings.local.json").unlink()
    repo.write(checks.LOCK_REL, LOCK + "scipy==1.14.0\n")
    with pytest.raises(RefusedError, match="check 6"):
        checks.check_clean()


def test_clean_tree_disregards_the_users_global_excludes(repo, tmp_path):
    """A global excludes file (here, as on the development machine, one ignoring
    **/.claude/settings.local.json) must not hide §3.2.6's clutter from check 6."""
    excludes = tmp_path / "global-ignore"
    excludes.write_text("**/.claude/settings.local.json\n.DS_Store\n")
    repo.git("config", "core.excludesFile", str(excludes))
    for rel in (".claude/settings.local.json", "src/.DS_Store"):
        repo.write(rel, "{}")
        assert repo.git("status", "--porcelain", "--untracked-files=all") == ""
        with pytest.raises(RefusedError, match="check 6"):
            checks.check_clean()
        (repo.root / rel).unlink()
    repo.write("data/processed/x.parquet", "ignored")        # the repository's own rule holds
    checks.check_clean()


def test_import_location_rule(tmp_path):
    top = tmp_path / "worktree"
    here = top / "src" / "nhs_ae" / "__init__.py"
    elsewhere = tmp_path / "x" / "src" / "nhs_ae" / "__init__.py"
    assert checks.import_problems(top, here, top) == []
    assert "imported from" in checks.import_problems(top, elsewhere, top)[0]
    assert "PROJECT_ROOT" in checks.import_problems(top, here, tmp_path / "x")[0]


def test_pip_freeze_comparison_drops_comment_lines_and_the_editable_line():
    head = "c" * 40
    freeze = ("## pip may add comment lines\nnumpy==2.1.0\n"
              f"-e git+ssh://git@example.invalid/r.git@{head}#egg=nhs_ae&subdirectory=../x\n"
              "pandas==2.2.3\n")
    assert checks.freeze_problems(freeze, LOCK, head) == []
    drifted = freeze.replace("2.1.0", "2.1.1")
    assert "differs from the lock" in checks.freeze_problems(drifted, LOCK, head)[0]
    assert checks.freeze_problems(freeze + "scipy==1.14.0\n", LOCK, head)
    assert "-e line" in checks.freeze_problems(freeze, LOCK, "d" * 40)[0]
    assert "-e line" in checks.freeze_problems(freeze.replace("-e ", "# -e "), LOCK, head)[0]


def test_environment_check_compares_python_and_platform_with_the_pins(repo, monkeypatch):
    _fake_env(monkeypatch, repo)
    env = checks.check_environment(LOCK.encode(), None, repo.head())
    assert env["env_drift"] == {}
    assert checks.check_environment(LOCK.encode(), env, repo.head()) == env
    with pytest.raises(RefusedError, match="python"):
        checks.check_environment(LOCK.encode(), {**env, "python": "3.0.0"}, repo.head())


PINNED_ENV = {"python": "3.13.12", "platform": "macOS-15.2-arm64-arm-64bit-Mach-O"}
NEW_ENV = {"python": "3.13.13", "platform": "macOS-15.3-arm64-arm-64bit-Mach-O"}


def test_environment_drift_passes_only_under_a_row_quoting_every_new_value(repo, monkeypatch):
    """Design §3.2.8 [default]: drift in Python or the platform needs the --amendment row to
    quote each new value verbatim; the lock and the -e commit stay hard refusals."""
    _fake_env(monkeypatch, repo)
    monkeypatch.setattr(checks, "_env", lambda: dict(NEW_ENV))
    head, lock = repo.head(), LOCK.encode()
    with pytest.raises(RefusedError, match=r"check 8: python is 3\.13\.13, pinned 3\.13\.12; "
                                           r"platform is .*only under --amendment"):
        checks.check_environment(lock, PINNED_ENV, head)
    both = _row(f"Python is now {NEW_ENV['python']} and the platform `{NEW_ENV['platform']}`; "
                "the P0b-style reproduction is reported.")
    facts = checks.check_environment(lock, PINNED_ENV, head, both)
    assert facts == {**NEW_ENV, "env_drift": {k: [PINNED_ENV[k], NEW_ENV[k]] for k in NEW_ENV}}
    with pytest.raises(RefusedError, match=r"check 8: platform is macOS-15\.3") as err:
        checks.check_environment(lock, PINNED_ENV, head, _row(f"Python is {NEW_ENV['python']}."))
    assert "python is" not in str(err.value)
    locked = f"-e git+ssh://git@example.invalid/r.git@{head}#egg=nhs_ae_forecast\n"
    monkeypatch.setattr(checks, "_pip_freeze", lambda: f"numpy==2.1.0\npandas==2.2.4\n{locked}")
    with pytest.raises(RefusedError, match="check 8: pip freeze differs from the lock"):
        checks.check_environment(lock, PINNED_ENV, head, both)
    monkeypatch.setattr(checks, "_pip_freeze",
                        lambda: "numpy==2.1.0\npandas==2.2.3\n" + locked.replace(head, "d" * 40))
    with pytest.raises(RefusedError, match="check 8: the -e line's commit"):
        checks.check_environment(lock, PINNED_ENV, head, both)


def test_a_quoted_value_must_be_whole():
    """A row quoting the pinned Python 3.13.12 does not quote a drifted 3.13.1."""
    assert not checks._quotes("Python moved from 3.13.12 (see P0b).", "3.13.1")
    assert not checks._quotes("Python 3.13.1.5 is not it.", "3.13.1")
    assert not checks._quotes(None, "3.13.1") and not checks._quotes("anything", "")
    for row in ("Python moved from 3.13.12 to 3.13.1.", "now `3.13.1`", "3.13.1, then"):
        assert checks._quotes(row, "3.13.1")
    platform_now = NEW_ENV["platform"]
    assert checks._quotes(f"| **{TITLE}.** macOS is `{platform_now}` |", platform_now)
    assert not checks._quotes(f"{platform_now}-extra", platform_now)


def test_prepare_runs_checks_6_to_8_first_and_returns_what_it_records(repo, monkeypatch):
    """report-commands:2: the DEV side is generated only on a clean tree, from this worktree,
    in the locked environment installed from HEAD."""
    _fake_env(monkeypatch, repo)
    head = repo.head()
    assert checks.prepare_facts(head) == {"commit": head, **checks._env()}
    assert checks.prepare_facts("HEAD")["commit"] == head
    repo.write("notes.txt", "x\n")
    later = repo.commit("a later commit")
    with pytest.raises(RefusedError, match="prepare: .* is not HEAD"):
        checks.prepare_facts(head)
    repo.write("src/nhs_ae/models/edit.py", "x = 2\n")          # an uncommitted model edit
    with pytest.raises(RefusedError, match="prepare: check 6"):
        checks.prepare_facts(later)
    (repo.root / "src/nhs_ae/models/edit.py").unlink()
    monkeypatch.setattr(checks, "_import_problems", lambda: ["nhs_ae is imported from elsewhere"])
    with pytest.raises(RefusedError, match="prepare: check 7"):
        checks.prepare_facts(later)
    monkeypatch.setattr(checks, "_import_problems", list)
    monkeypatch.setattr(checks, "_pip_freeze", lambda: "numpy==2.1.0\n")
    with pytest.raises(RefusedError, match="prepare: check 8"):
        checks.prepare_facts(later)


def test_raw_check_compares_the_manifest_and_reference_files_with_the_pins(repo):
    facts = checks.check_raw(None)
    assert facts["stored_files"] == 4 and facts["reference_files"] == 1
    pins = {"manifest_sha": facts["manifest_sha"],
            "reference": {"data/reference/provider_icb_map.csv":
                          file_sha(repo.root / "data/reference/provider_icb_map.csv")}}
    assert checks.check_raw(pins) == facts
    with pytest.raises(RefusedError, match="manifest"):
        checks.check_raw({**pins, "manifest_sha": "0" * 64})
    with pytest.raises(RefusedError, match="data/reference"):
        checks.check_raw({**pins, "reference": {}})


def test_quarantine_file_is_pinned_ignored_and_untracked(repo, tmp_path, monkeypatch):
    _processed(repo, tmp_path, monkeypatch)
    sha = file_sha(repo.root / checks.QUARANTINE_FILE_REL)
    pins = {"quarantine": {"path": checks.QUARANTINE_FILE_REL, "sha256": sha}}
    assert checks.check_quarantine(pins)["quarantine_sha"] == sha
    for path, digest, why in (
            (checks.QUARANTINE_FILE_REL, "0" * 64, "SHA-256"),
            ("data/quarantine/pre-seal/backtest/forecasts.parquet", sha, "not under"),
            (f"{checks.QUARANTINE_REL}/../../x.parquet", sha, "not under")):
        with pytest.raises(RefusedError, match=why):
            checks.check_quarantine({"quarantine": {"path": path, "sha256": digest}})
    repo.write(".gitignore", "")
    with pytest.raises(RefusedError, match="does not ignore"):
        checks.check_quarantine(pins)
    excludes = tmp_path / "global-ignore"                    # a global rule does not count
    excludes.write_text("data/processed\n")
    repo.git("config", "core.excludesFile", str(excludes))
    with pytest.raises(RefusedError, match="does not ignore"):
        checks.check_quarantine(pins)


def test_inputs_must_match_their_pins_and_the_generation_code_its_commit(prepared):
    r, pins = prepared
    assert checks.check_inputs(pins, r.head())["inputs"] == 21
    r.write("src/nhs_ae/models/new_model.py", "x = 1\n")
    with pytest.raises(RefusedError, match="generation code"):
        checks.check_inputs(pins, r.commit("a model change after prepare --dev-side"))
    inputs = r.root / checks.INPUTS_REL
    _forecasts([date(2017, 9, 1)]).to_parquet(inputs / "extra.parquet", index=False)
    with pytest.raises(RefusedError, match="unpinned"):
        checks.check_inputs(pins, r.base)
    (inputs / "extra.parquet").unlink()
    pool = "pool/base_b1_provider.parquet"
    _put(r, pool, _forecasts([date(2017, 7, 1)]))
    with pytest.raises(RefusedError, match="differs from its pin"):
        checks.check_inputs(pins, r.base)
    _put(r, pool, _forecasts([date(2017, 7, 1), date(2024, 1, 1)]))
    with pytest.raises(RefusedError, match="check 11: input .* origins outside 2017-07..2023-12"):
        checks.check_inputs(pins, r.base)
    _put(r, pool, _forecasts([date(2017, 7, 1)]).assign(wis=1.0))
    with pytest.raises(RefusedError, match=r"check 11: input .* not a forecast file.*\['wis'\]"):
        checks.check_inputs(pins, r.base)


@pytest.mark.parametrize("rel", ["src/nhs_ae/evaluate/splits.py",
                                 "src/nhs_ae/evaluate/stage_h/common.py",
                                 "src/nhs_ae/evaluate/stage_h/generate.py",
                                 "src/nhs_ae/evaluate/metrics.py",
                                 "src/nhs_ae/ingest/recover.py"])
def test_a_change_to_the_dev_origins_code_after_prepare_refuses_check_11(prepared, rel):
    """splits.py and common.py fix the DEV origins the DEV side was generated at; metrics.py
    and recover.py are on the harness's path (the scale column, as-of dates)."""
    r, pins = prepared
    r.write(rel, "x = 1\n")              # the temporary repository's copy, never the real one
    with pytest.raises(RefusedError, match="check 11: the generation code changed"):
        checks.check_inputs(pins, r.commit(f"edit {rel} after prepare --dev-side"))


def test_check_11_refuses_pins_short_of_design_8(prepared, monkeypatch):
    """Report-commands:1: pins from a prepare without --dev-side, or with other origin sets,
    are refused before the run, whatever the files on disk."""
    r, pins = prepared
    thirteen = {n: p for n, p in pins["inputs"].items() if not n.startswith("dev_side/")}
    with pytest.raises(RefusedError, match=r"check 11: the pins: the inputs are not the 21 "
                                           r"permitted files .*missing \['dev_side/"):
        checks.check_inputs({**pins, "inputs": thirteen}, r.head())
    seeded = _dev_side("b1_provider_asof")
    wide = {**pins["inputs"], seeded: {**pins["inputs"][seeded],
                                       "origins": [f"{o:%Y-%m-%d}" for o in DEV]}}
    with pytest.raises(RefusedError, match=f"check 11: the pins: input {seeded} holds 69 "
                                           "origins, not its 23"):
        checks.check_inputs({**pins, "inputs": wide}, r.head())
    monkeypatch.setattr(checks, "M2_DEV_SHA", M2_DEV_SHA)
    with pytest.raises(RefusedError, match=f"check 11: the pins: input {M2_INPUT} is not "
                                           "E-m2-rerun69's file"):
        checks.check_inputs(pins, r.head())


def _one_vintage() -> pd.DataFrame:
    return _vintage_rows([("2016-06-01", "RAA", "Q", "Trust", "att_type1", 1.0, False,
                           "2016-07-14")])


@pytest.mark.parametrize("rel, frame, why", [
    ("pool/base_b2_icb.parquet", lambda: _forecasts([date(2023, 12, 1), date(2024, 1, 1)]),
     r"input pool/base_b2_icb\.parquet has 1 origins outside"),
    ("pool/base_b2_icb.parquet", lambda: _forecasts([date(2017, 6, 1), date(2017, 7, 1)]),
     r"input pool/base_b2_icb\.parquet has 1 origins outside"),
    ("dev_side/forecasts/b0_provider_asof.parquet",
     lambda: _forecasts([date(2019, 1, 1)]).assign(y=1.0),
     (r"input dev_side/forecasts/b0_provider_asof\.parquet is not a forecast file "
      r"\(lacks \[\], carries \['y'\]\)")),
    (M2_INPUT, lambda: _forecasts([date(2019, 1, 1)]).iloc[:0], f"input {M2_INPUT} holds no rows"),
    ("vintages/ae_monthly_all_vintages.parquet", _one_vintage,
     r"unexpected \['vintages/ae_monthly_all_vintages\.parquet'\]"),
])
def test_pin_refuses_an_input_that_is_not_a_dev_forecast_file(repo, tmp_path, monkeypatch, rel,
                                                              frame, why):
    """P5: DEV forecasts at origins 2017-07..2023-12 only. A CONF-origin copy of the pre-seal
    forecasts or an outturn-bearing frame under a permitted name, or the rebuilt vintage table
    left under inputs/, is refused before the rebuild starts."""
    _processed(repo, tmp_path, monkeypatch)
    _put(repo, rel, frame())
    with pytest.raises(RefusedError, match=f"pin: .*{why}"):
        checks.make_pins(tmp_path / "scratch")
    assert not (tmp_path / "scratch").exists()


# ---- check 10: unseal logs and the witness -----------------------------------------------
def test_reverted_log_is_refused_while_the_witness_holds_a_line(tagged):
    r, tag = tagged
    entry = _line(tag, _hash_commit(r))
    _append(r.root / checks.LOG_REL, entry)
    _append(_witness(r), entry)
    r.git("checkout", "--", checks.LOG_REL)
    for args in ((tag,), (tag, TITLE, _row())):
        with pytest.raises(RefusedError, match="witness"):
            checks.check_logs(*args)


def test_fix_branch_cut_from_the_tag_is_refused_while_the_witness_holds_a_line(tagged):
    r, tag = tagged
    entry = _line(tag, _hash_commit(r))
    _append(r.root / checks.LOG_REL, entry)
    _append(_witness(r), entry)
    r.commit("the unseal line committed on the runner's line")
    r.git("checkout", "-q", "-b", "fix", tag)
    _add_row(r, _row())
    assert checks.start_commit_ok(r.commit("a fix branched from the tag"), TITLE)[0]
    with pytest.raises(RefusedError, match="witness"):
        checks.check_logs(tag, TITLE, _row())


def test_one_prior_line_is_accepted_only_with_the_amendment_quoting_its_timestamp(tagged):
    r, tag = tagged
    entry = _unsealed_then_fixed(r, tag)
    assert checks.start_commit_ok(r.head(), TITLE)[0]
    facts = checks.check_logs(tag, TITLE, _row())
    assert (facts["n0"], facts["prior_lines"], facts["witness_lines"]) == (1, [entry], 1)
    with pytest.raises(RefusedError, match="--amendment"):
        checks.check_logs(tag)
    with pytest.raises(RefusedError, match="timestamp"):
        checks.check_logs(tag, TITLE, _row("Discloses nothing."))


@pytest.mark.parametrize("field, value, why", [
    ("token", "0" * 40, "token"),
    ("argv", ["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "report", "--from-scores"], "argv"),
    ("argv", ["/w/.venv/bin/nhs-ae-backtest", "run"], "argv"),
    ("head", "the tag", "head"),
    ("head", "f" * 40, "head"),
])
def test_prior_lines_must_come_from_a_stage_h_run_after_the_tag(tagged, field, value, why):
    r, tag = tagged
    _unsealed_then_fixed(r, tag, **{field: tag if value == "the tag" else value})
    with pytest.raises(RefusedError, match=why):
        checks.check_logs(tag, TITLE, _row())


def test_other_worktrees_logs_must_be_absent_or_empty(tagged, tmp_path):
    r, tag = tagged
    other = tmp_path / "second-worktree"
    r.git("worktree", "add", "-q", "-b", "second", str(other), tag)
    assert checks.check_logs(tag)["n0"] == 0
    assert checks.check_logs(tag, TITLE, _row())["n0"] == 0          # crash case 1: k = 0
    _append(other / checks.LOG_REL, _line(tag, tag))
    with pytest.raises(RefusedError, match="other worktrees"):
        checks.check_logs(tag)
    assert list(checks.log_counts()["other_logs"].values()) == [1]


def test_committed_log_problems_name_an_uncommitted_or_dropped_unseal_line(tagged):
    """Check 10's committed-record rule on its own, as report --from-scores uses it (design
    §9, case 3): a crash leaves the line uncommitted; a branch cut from the tag drops it."""
    r, tag = tagged
    assert checks.committed_log_problems() == [] == checks.committed_log_problems(r.root)
    entry = _line(tag, _hash_commit(r))
    _append(r.root / checks.LOG_REL, entry)
    _append(_witness(r), entry)
    problems = checks.committed_log_problems()
    assert len(problems) == 2 and TS in problems[0] and "HEAD's committed log" in problems[0]
    assert "differs from HEAD's copy" in problems[1]
    with pytest.raises(RefusedError, match="check 10: 1 witness lines .*; the working-tree"):
        checks.check_logs(tag, TITLE, _row())
    r.commit("the crash-fix commit holds the unseal line")
    assert checks.committed_log_problems() == []
    r.git("checkout", "-q", "-b", "fix", tag)
    problems = checks.committed_log_problems(r.root)
    assert len(problems) == 1 and TS in problems[0]
    (r.root / checks.LOG_REL).write_text("{not json\n")
    with pytest.raises(RefusedError, match="check 10: .* do not parse"):
        checks.committed_log_problems()


def test_working_tree_log_must_be_heads_copy_and_parse(tagged):
    r, tag = tagged
    _append(r.root / checks.LOG_REL, _line(tag, tag))
    with pytest.raises(RefusedError, match="differs from HEAD's copy"):
        checks.check_logs(tag, TITLE, _row())
    (r.root / checks.LOG_REL).write_text("{not json\n")
    with pytest.raises(RefusedError, match="do not parse"):
        checks.check_logs(tag)


@pytest.mark.parametrize("content", ["\n", "\n\n", " \n", "{}\n\n", "[1]\n", "﻿{}\n"])
def test_a_committed_log_the_accounting_would_flag_is_refused_at_check_10(tagged, content):
    """P8: empty means 0 bytes. A log an editor saved as a newline, committed, would pass a
    check that skipped blank lines and then make the post-unseal accounting raise."""
    r, tag = tagged
    log = r.root / checks.LOG_REL
    log.write_text(content)
    r.commit("the log saved by an editor")
    assert seal.Accounting({log: seal.line_count(log)}, log).verify(False)
    for args in ((tag,), (tag, TITLE, _row())):
        with pytest.raises(RefusedError, match=r"check 10: line\(s\) \[\d"):
            checks.check_logs(*args)


def test_a_blank_witness_or_other_worktree_log_is_refused_at_check_10(tagged, tmp_path):
    r, tag = tagged
    other = tmp_path / "second-worktree"
    r.git("worktree", "add", "-q", "-b", "second", str(other), tag)
    (other / checks.LOG_REL).write_text("\n\n")
    assert list(checks.log_counts()["other_logs"].values()) == [seal.line_count(
        other / checks.LOG_REL)] == [2]
    with pytest.raises(RefusedError, match="neither absent nor 0 bytes"):
        checks.check_logs(tag)
    (other / checks.LOG_REL).unlink()
    assert checks.check_logs(tag)["n0"] == 0
    _witness(r).parent.mkdir(parents=True)
    _witness(r).write_text("\n")
    assert checks.log_counts()["witness_lines"] == 1
    with pytest.raises(RefusedError, match="check 10: .* of the witness"):
        checks.check_logs(tag)
    _witness(r).write_text("")
    assert checks.check_logs(tag)["witness_lines"] == 0


# ---- the commands, end to end on synthetic data ------------------------------------------
def test_pre_run_passes_all_fourteen_checks_on_a_tagged_repository(pinned):
    _, tag, token, ctx = pinned
    facts = checks.pre_run(ctx, token)
    assert (facts["tag_commit"], facts["head"], facts["n0"]) == (tag, tag, 0)
    assert facts["log_oneline"] == "" and facts["amendment"] is None
    pins = checks.read_pins(from_tag=True)
    assert facts["vintages"]["row_hash"] == pins["vintages"]["row_hash"]
    assert facts["d7_slices"] == pins["d7_slices"] and facts["inputs"] == 21
    assert facts["env_drift"] == {}
    written = sorted(p.relative_to(ctx.work).as_posix() for p in ctx.work.rglob("*"))
    assert written == ["vintages", "vintages/ae_monthly_all_vintages.parquet",
                       "vintages/parse_failures.csv"]
    assert not ctx.results.exists()
    with pytest.raises(RefusedError, match="check 1"):
        checks.pre_run(ctx, token)


def test_pre_run_takes_pins_and_lock_from_the_tag(pinned, monkeypatch):
    r, _, token, ctx = pinned
    r.write(checks.PINS_REL, "{}\n")
    r.write(checks.LOCK_REL, "garbage==0\n")
    monkeypatch.setattr(checks, "check_clean", lambda: None)     # the edits stay uncommitted
    facts = checks.pre_run(ctx, token)
    assert facts["manifest_sha"] == checks.read_pins(from_tag=True)["manifest_sha"]


def test_rerun_after_an_unseal_needs_the_amendment_row(pinned):
    r, tag, token, ctx = pinned
    entry = _unsealed_then_fixed(r, tag)
    with pytest.raises(RefusedError, match="check 4"):
        checks.pre_run(ctx, token)
    facts = checks.pre_run(ctx, token, amendment=TITLE)
    assert (facts["n0"], facts["prior_lines"]) == (1, [entry])
    assert len(facts["log_oneline"].splitlines()) == 2


def test_pre_run_accepts_environment_drift_only_under_an_amendment_quoting_it(pinned,
                                                                              monkeypatch):
    """Report-commands:3: a macOS update after the tag is disclosed and run, not a dead end;
    nothing is unsealed first, so the amendment row is the whole record (k = 0)."""
    r, _, token, ctx = pinned
    pinned_env = checks.read_pins(from_tag=True)
    now = {"python": pinned_env["python"], "platform": pinned_env["platform"] + "-updated"}
    monkeypatch.setattr(checks, "_env", lambda: dict(now))
    with pytest.raises(RefusedError, match="check 8: platform is"):
        checks.pre_run(ctx, token)
    _add_row(r, _row(f"The platform is now `{now['platform']}`; the reproduction is reported."))
    r.commit("the environment amendment")
    facts = checks.pre_run(ctx, token, amendment=TITLE)
    assert facts["env_drift"] == {"platform": [pinned_env["platform"], now["platform"]]}
    assert facts["n0"] == 0 and facts["amendment"] == TITLE


def test_preflight_passes_before_the_tag_and_writes_nothing(prepared, tmp_path, monkeypatch):
    r, pins = prepared
    _fake_env(monkeypatch, r)
    system_tmp = tmp_path / "system-tmp"
    system_tmp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(system_tmp))
    store = tmp_path / "processed_store"
    before = _files(r.root) | _files(store)
    facts = checks.preflight()
    assert facts["vintages"]["row_hash"] == pins["vintages"]["row_hash"] and facts["n0"] == 0
    assert _files(r.root) | _files(store) == before and not any(system_tmp.iterdir())


def test_dry_checks_before_the_pins_rebuild_into_the_dry_directory(repo, monkeypatch):
    (repo.root / checks.PINS_REL).unlink()
    head = repo.commit("before pin")
    _fake_env(monkeypatch, repo)
    work = repo.root / checks.DRY_ROOT_REL / head
    ctx = Context("dry", DRY, DRY, {}, DRY_END, work, repo.root / "results" / "H-dryrun",
                  work / "vintages" / "ae_monthly_all_vintages.parquet", 1)
    facts = checks.dry_checks(ctx)
    assert facts["pinned"] is False and (facts["log_lines"], facts["witness_lines"]) == (0, 0)
    assert facts["vintages"]["failures"] == [BROKEN] and "d7_slices" not in facts
    assert ctx.vintages_path.is_file()
    elsewhere = repo.root / checks.RUN_ROOT_REL / head
    with pytest.raises(RefusedError, match="dry context"):
        checks.dry_checks(Context("dry", DRY, DRY, {}, DRY_END, elsewhere, ctx.results,
                                  elsewhere / "vintages" / "x.parquet", 1))
