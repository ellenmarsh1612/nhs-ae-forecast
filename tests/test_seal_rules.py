"""The seal's rules on git state (``evaluate.seal_rules``, P11). Everything runs on temporary
git repositories under tmp_path with synthetic files; conf-plan-v1 and conf-run-v1 are only
ever created inside those repositories. ``SealRepo``, ``make_repo`` and the run builders are
shared with tests/test_splits.py."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from nhs_ae.config import PROJECT_ROOT as REAL_ROOT
from nhs_ae.evaluate import seal_rules
from nhs_ae.evaluate.stage_h import checks, common, report, seal

PLAN, RUN = seal_rules.PLAN_TAG, seal_rules.RUN_TAG
RESULTS = seal_rules.RUN_RESULTS_REL
TITLE = "Stage H rerun 1"
TS = "2026-10-01T10:00:00+00:00"            # the crashed run's line (crash case 2)
TS_RUN = "2026-10-02T09:30:00+00:00"        # the completed run's line
TS_STRAY = "2026-11-05T12:00:00+00:00"      # a line found after the run
RUN_ARGV = ["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "run", "--unseal-token-file", "t"]
GIT_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY")
PREREG = """# Pre-registration

## 10. Amendments

| Date | Change | Reason |
|---|---|---|
| 2026-09-10 | **Re-split by origin.** DEV and CONF. | reason |

---

### Appendix A
"""


def row(ts: str = TS, title: str = TITLE) -> str:
    return (f"| 2026-10-02 (crash fix) | **{title}: guard fix.** Discloses the unseal line of "
            f"{ts}. | a crash |")


class SealRepo:
    """A throwaway git repository under pytest's tmp_path, laid out as the Stage H runner leaves
    it (the tracked unseal log, the preregistration's §10 table); it refuses to act anywhere
    else."""

    def __init__(self, root: Path, tmp: Path):
        real = REAL_ROOT.resolve()
        assert tmp in root.parents and real != root.resolve() and real not in root.resolve().parents
        self.root, self.t = root, None

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
        self.git("commit", "-q", "--allow-empty", "-m", msg)
        return self.head()

    def tag(self, name: str = PLAN, rev: str = "HEAD", annotated: bool = True) -> str:
        self.git("tag", *(("-a", "-m", f"{name}") if annotated else ()), name, rev)
        commit = self.git("rev-parse", f"refs/tags/{name}^{{commit}}")
        if name == PLAN:
            self.t = commit
        return commit

    @property
    def log(self) -> Path:
        return self.root / seal_rules.LOG_REL

    @property
    def witness(self) -> Path:
        return (self.root / ".git").resolve() / seal_rules.WITNESS_REL

    def add_row(self, text: str) -> None:
        path = self.root / seal_rules.PREREG_REL
        path.write_text(path.read_text().replace("\n\n---\n", f"\n{text}\n\n---\n", 1))

    def hash_commit(self, extra: dict[str, str] | None = None) -> str:
        """The runner's hash commit (design §4) on HEAD, plus ``extra`` {path: text} edits;
        each hash file names its parent, so no two hash commits hold the same bytes."""
        parent = self.head()
        for name in seal_rules.HASH_FILES:
            self.write(f"{RESULTS}/{name}", f"file,sha256\n{name},{parent}\n")
        for rel, text in (extra or {}).items():
            self.write(rel, text)
        return self.commit("Stage H: forecast hashes before the unseal (run)")

    def line(self, at: str, ts: str = TS_RUN, **change) -> dict:
        """An unseal-log line as splits writes it from ``python -m nhs_ae.evaluate.stage_h run``
        at commit ``at``; ``change`` overrides fields."""
        return {"timestamp": ts, "token": self.t, "head": at, "argv": RUN_ARGV,
                "sealed_rows": 21, "origins": ["2024-01-01", "2025-09-01"], **change}

    def append(self, path: Path, entry: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")

    def unseal(self, entry: dict) -> None:
        """What splits and open_seal leave: the line in this worktree's log and the witness."""
        self.append(self.log, entry)
        self.append(self.witness, entry)

    def step6(self, entry: dict, provenance=None, copy=None) -> str:
        """Step 6's commit: results/H-confirmatory with provenance.json (``provenance``: the
        document, or its text; default run mode with ``entry``) and unseal_entry.json (``copy``,
        default ``entry``), and the unseal log as it stands."""
        doc = {"facts": {"head": entry.get("head")},
               "extra": {"mode": "run", "start": self.t, "hash_commit": entry.get("head"),
                         "unseal_entry": entry, "tables_written": 1}}
        doc = doc if provenance is None else provenance
        self.write(f"{RESULTS}/{seal_rules.PROVENANCE}",
                   doc if isinstance(doc, str) else json.dumps(doc, indent=1, sort_keys=True))
        self.write(f"{RESULTS}/{seal_rules.UNSEAL_ENTRY}",
                   json.dumps(entry if copy is None else copy, indent=1) + "\n")
        self.write(f"{RESULTS}/confirmatory_results.md", "# Stage H\n")
        return self.commit("Stage H: confirmatory results (conf-run-v1 to be tagged by hand)")

    def crash_fix(self, ts: str = TS) -> str:
        """Crash case 1 or 2's fix commit (design §9): results/H-confirmatory removed, the log
        committed, and the §10 row TITLE quoting the crashed run's line."""
        self.git("rm", "-q", "-r", RESULTS)
        self.add_row(row(ts))
        return self.commit("crash fix")


def make_repo(tmp_path: Path, monkeypatch) -> SealRepo:
    """A repository with the preregistration and an empty tracked log, committed, and the git
    environment variables that would redirect git elsewhere removed."""
    for var in GIT_VARS:
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True, capture_output=True)
    r = SealRepo(root, tmp_path)
    for key, value in (("user.name", "Test"), ("user.email", "test@example.invalid"),
                       ("commit.gpgsign", "false"), ("tag.gpgsign", "false"),
                       ("tag.forceSignAnnotated", "false"), ("core.hooksPath", "/dev/null"),
                       ("core.excludesFile", str(tmp_path / "no-global-excludes"))):
        r.git("config", key, value)
    r.write(".gitignore", "data/processed\n")
    r.write(seal_rules.PREREG_REL, PREREG)
    r.write(seal_rules.LOG_REL, "")
    r.write("src/nhs_ae/__init__.py", "")
    r.commit("base")
    return r


def completed(r: SealRepo, rerun: bool = False, tag: bool = True) -> dict:
    """A completed run: T tagged; with ``rerun``, crash case 2 at H1a, its fix F disclosing the
    line, and the --amendment rerun from S = F; then H1 on S, its unseal line E, step 6's
    commit R, and R tagged conf-run-v1 (annotated) when ``tag``."""
    t = r.tag(PLAN)
    out = {"t": t, "s": t, "earlier": None}
    if rerun:
        h1a = r.hash_commit()
        earlier = r.line(h1a, TS)
        r.unseal(earlier)
        out.update(h1a=h1a, earlier=earlier, s=r.crash_fix(TS))
    h1 = r.hash_commit()
    entry = r.line(h1)
    r.unseal(entry)
    out.update(h1=h1, entry=entry, run=r.step6(entry))
    if tag:
        r.tag(RUN, out["run"])
    return out


def case3(r: SealRepo) -> dict:
    """Crash case 3 (design §9): the scores were written but step 6 did not commit. The fix
    commit F on H1 holds the log and results/H-confirmatory as left (no provenance.json), and
    R adds report --from-scores' recomputed-<F>/provenance.json."""
    t = r.tag(PLAN)
    h1 = r.hash_commit()
    entry = r.line(h1)
    r.unseal(entry)
    r.write(f"{RESULTS}/score_hashes.csv", "file,sha256\n")
    f = r.commit("crash fix: the run's line and results as the crashed run left them")
    doc = {"facts": {}, "extra": {"mode": "run", "command": report.RECOMPUTED, "head": f,
                                  "hash_commit": h1, "unseal_entry": entry}}
    r.write(f"{RESULTS}/recomputed-{f[:12]}/{seal_rules.PROVENANCE}", json.dumps(doc))
    return {"t": t, "h1": h1, "entry": entry, "f": f,
            "run": r.commit("Stage H: recomputed results (design §9, case 3)")}


def problems(r: SealRepo, *logs: Path) -> list[str]:
    return seal_rules.post_run_problems(r.root, [r.log, *logs], r.witness)


@pytest.fixture
def repo(tmp_path, monkeypatch) -> SealRepo:
    return make_repo(tmp_path, monkeypatch)


# ---- the module --------------------------------------------------------------------------
def test_the_constants_are_the_runners():
    assert seal_rules.HASH_FILES == common.HASH_FILES
    assert seal_rules.RUN_RESULTS_REL == checks.RESULTS_REL
    assert (seal_rules.LOG_REL, seal_rules.PREREG_REL) == (checks.LOG_REL, checks.PREREG_REL)
    assert seal_rules.PLAN_TAG == common.TAG and seal_rules.PROVENANCE == report.PROVENANCE
    assert seal.WITNESS == seal_rules.WITNESS_REL and seal_rules.NO_EXCLUDES == checks.NO_EXCLUDES


def test_seal_rules_imports_the_standard_library_only():
    """So splits imports it with no cycle (harness imports splits; seal imports harness) and
    no weight: a cold import loads no pandas and no other nhs_ae module."""
    tree = ast.parse(Path(seal_rules.__file__).read_text())
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)
             for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert names <= {"__future__", "json", "os", "re", "subprocess", "pathlib", "datetime"}, names
    src = str(Path(seal_rules.__file__).resolve().parents[2])
    code = ("import sys, nhs_ae.evaluate.seal_rules; "
            "print(sorted(m for m in sys.modules if m.startswith(('nhs_ae', 'pandas'))))")
    out = subprocess.run([sys.executable, "-c", code], env={"PYTHONPATH": src}, check=True,
                         capture_output=True, text=True).stdout
    assert out.strip() == "['nhs_ae', 'nhs_ae.evaluate', 'nhs_ae.evaluate.seal_rules']"
    subprocess.run([sys.executable, "-c", "import nhs_ae.evaluate.splits"],
                   env={"PYTHONPATH": src}, check=True, capture_output=True)


# ---- git ---------------------------------------------------------------------------------
def test_tag_names_resolve_under_refs_tags_only(repo):
    """A ref refs/conf-plan-v1 would win git's short-name lookup; the rules never use it."""
    t = repo.tag(PLAN)
    repo.write("notes.txt", "x\n")
    other = repo.commit("later")
    repo.git("update-ref", f"refs/{PLAN}", other)
    repo.git("branch", RUN, other)                                  # a branch, not a tag
    assert repo.git("rev-parse", f"{PLAN}^{{commit}}") == other     # the lookup the rules avoid
    assert seal_rules.commit(repo.root, PLAN) == t == checks_tag(repo)
    assert seal_rules.commit(repo.root, RUN) is None
    assert not seal_rules.tag_is_annotated(repo.root, RUN)
    assert seal_rules.commit(repo.root, "-h") is None and seal_rules.commit(repo.root, None) is None


def checks_tag(r: SealRepo) -> str | None:
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(checks, "PROJECT_ROOT", r.root)
        return checks._tag_commit()


def test_git_helpers(repo, tmp_path):
    base = repo.head()
    t = repo.tag(PLAN)
    assert seal_rules.tag_is_annotated(repo.root, PLAN)
    h1 = repo.hash_commit()
    assert seal_rules.parents(repo.root, h1) == [t] and seal_rules.parents(repo.root, base) == []
    with pytest.raises(ValueError):
        seal_rules.parents(repo.root, "f" * 40)
    assert seal_rules.descends(repo.root, h1, t) and not seal_rules.descends(repo.root, t, t)
    assert seal_rules.is_ancestor(repo.root, t, t) and not seal_rules.is_ancestor(repo.root, h1, t)
    assert seal_rules.blob(repo.root, t, seal_rules.PREREG_REL) == PREREG.encode()
    assert seal_rules.blob(repo.root, t, f"{RESULTS}/timings.csv") is None
    other = tmp_path / "second"
    repo.git("worktree", "add", "-q", "-b", "second", str(other), t)
    trees = [p.resolve() for p in seal_rules.worktrees(repo.root)]
    assert trees == [repo.root.resolve(), other.resolve()] == \
        [p.resolve() for p in seal_rules.worktrees(other)]
    assert seal_rules.witness_path(other) == seal_rules.witness_path(repo.root) == repo.witness
    assert seal_rules.toplevel(repo.root / "src").resolve() == repo.root.resolve()
    assert seal_rules.toplevel(tmp_path) is None


# ---- the HEAD rules (moved from checks, unchanged) ---------------------------------------
def test_start_and_hash_commit_rules(repo):
    t = repo.tag(PLAN)
    assert seal_rules.start_commit_ok(repo.root, t)[0]
    assert seal_rules.start_commit_ok(repo.root, t, tag=t)[0]
    assert not seal_rules.start_commit_ok(repo.root, t, tag="f" * 40)[0]     # the caller's tag
    h1 = repo.hash_commit()
    assert seal_rules.hash_commit_ok(repo.root, h1, t)[0]
    ok, why = seal_rules.hash_commit_ok(repo.root, repo.hash_commit(), t)
    assert not ok and "parents" in why
    repo.git("checkout", "-q", "--detach", t)
    repo.add_row(row())
    s = repo.commit("the amendment row")
    assert seal_rules.start_commit_ok(repo.root, s, TITLE)[0]
    assert not seal_rules.start_commit_ok(repo.root, s)[0]
    ok, why = seal_rules.hash_commit_ok(repo.root, repo.hash_commit({"src/x.py": "x = 1\n"}), s)
    assert not ok and "src/x.py" in why
    assert seal_rules.rows_titled(repo.root, s, TITLE) == [row()]
    assert seal_rules.rows_titled(repo.root, t, TITLE) == []


# ---- the unsealing process ---------------------------------------------------------------
def test_tree_rule_ignores_results_and_data_but_not_the_rest(repo, tmp_path):
    root = repo.root
    assert seal_rules.tree_problems(root) == []
    for rel in (f"{RESULTS}/d7_check.csv", "results/other.txt", "data/processed/x.parquet",
                "data/raw/new.csv"):
        repo.write(rel, "x\n")
    repo.write(seal_rules.LOG_REL, json.dumps({"n": 1}) + "\n")          # a modified log
    assert seal_rules.tree_problems(root) == []
    excludes = tmp_path / "global-ignore"                  # the user's global excludes
    excludes.write_text(".DS_Store\n.claude/\n")
    repo.git("config", "core.excludesFile", str(excludes))
    for rel in ("src/.DS_Store", ".claude/settings.local.json", "notes.txt"):
        repo.write(rel, "{}")
        (problem,) = seal_rules.tree_problems(root)
        assert "not clean outside results/ and data/ (1 entries)" in problem and rel in problem
        (root / rel).unlink()
    repo.write(seal_rules.PREREG_REL, PREREG + "edited\n")
    assert "M docs/preregistration.md" in seal_rules.tree_problems(root)[0]
    repo.git("checkout", "--", seal_rules.PREREG_REL)
    repo.git("add", "--", f"{RESULTS}/d7_check.csv")                   # staged under results/
    assert seal_rules.tree_problems(root) == []


def test_import_rule(tmp_path):
    top = tmp_path / "worktree"
    here = top / "src" / "nhs_ae" / "__init__.py"
    assert seal_rules.import_problems(top, here, top) == []
    elsewhere = tmp_path / "x" / "src" / "nhs_ae" / "__init__.py"
    assert "imported from" in seal_rules.import_problems(top, elsewhere, top)[0]
    assert "PROJECT_ROOT" in seal_rules.import_problems(top, here, tmp_path)[0]
    assert checks.import_problems(top, here, tmp_path) == seal_rules.import_problems(top, here,
                                                                                     tmp_path)


def test_names_run_is_shared():
    cases = {True: (RUN_ARGV, tuple(RUN_ARGV[:2])),
             False: (["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "dry-run"],
                     ["scripts/stage_h.py", "run"], RUN_ARGV[:1], "run", None)}
    for want, argvs in cases.items():
        for argv in argvs:
            assert seal.names_run(argv) is seal_rules.names_run(argv) is want, argv


# ---- disclosure --------------------------------------------------------------------------
def test_a_timestamp_is_quoted_only_whole_and_only_if_iso():
    assert seal_rules.quotes_timestamp(row(TS), TS)
    assert seal_rules.quotes_timestamp(f"| line `{TS}` |", TS)
    assert seal_rules.quotes_timestamp(f"lines of {TS}, {TS_RUN}.", TS_RUN)
    assert not seal_rules.quotes_timestamp(row(TS), TS_RUN)
    for ts in ("", None, 17, "2026-10-01", "yesterday", "2026-13-01T10:00:00+00:00", " " + TS):
        assert not seal_rules.quotes_timestamp(row(TS) + f" {ts}", ts), ts
    assert not seal_rules.quotes_timestamp(row(TS), "2026-10-01T10:00:00")      # a prefix of TS
    assert not seal_rules.quotes_timestamp(row(TS), "2026-10-01T10:00")
    assert not seal_rules.quotes_timestamp(f"x{TS}", TS)
    assert not seal_rules.quotes_timestamp(f"{TS}:01", TS)
    assert not seal_rules.quotes_timestamp(None, TS)
    assert seal_rules.quotes_timestamp("at 2026-10-01T10:00:00Z.", "2026-10-01T10:00:00Z")
    for text in (f"unsealed at {TS}: it crashed in step 4", f"the line _{TS}_", f"**{TS}**",
                 f"({TS})", f"at {TS}; rerun"):
        assert seal_rules.quotes_timestamp(text, TS), text
    for text in (f"{TS}5", f"{TS}:05", f"{TS}.5", f"{TS}-01", f"1{TS}", f"+{TS}"):
        assert not seal_rules.quotes_timestamp(text, TS), text


def test_check_10_and_the_post_run_state_read_a_disclosure_alike(monkeypatch):
    """A row that admits the --amendment rerun at step 2 (check 10) also discloses its line
    once conf-run-v1 exists, and a row check 10 refuses discloses nothing."""
    monkeypatch.setattr(checks, "_descends", lambda head, tag: True)
    tag, line = "a" * 40, {"timestamp": TS, "token": "a" * 40, "argv": RUN_ARGV, "head": "b" * 40}
    for text in (row(TS), f"| x | **{TITLE}.** unsealed at {TS}: it crashed | y |",
                 f"| x | **{TITLE}.** _{TS}_ | y |", f"| x | **{TITLE}.** {TS}5 | y |",
                 f"| x | **{TITLE}.** {TS[:-6]} | y |", f"| x | **{TITLE}.** none | y |"):
        admitted = checks._prior_line_problem(line, tag, text) is None
        assert admitted == seal_rules.quotes_timestamp(text, TS), text


# ---- the post-run state ------------------------------------------------------------------
def test_a_completed_run_is_the_post_run_state(repo):
    c = completed(repo)
    assert problems(repo) == []
    assert [json.loads(x) for x in repo.log.read_text().splitlines()] == [c["entry"]]
    assert seal_rules.post_run_problems(repo.root, [], None) == []       # no working logs


def test_before_conf_run_v1_or_with_a_lightweight_one(repo):
    assert problems(repo) == [f"tag {PLAN} does not exist"]
    c = completed(repo, tag=False)
    assert problems(repo) == [f"tag {RUN} does not exist"]
    repo.tag(RUN, c["run"], annotated=False)
    assert problems(repo) == [f"{RUN} is a lightweight tag; it must be annotated"]


def test_case_2_then_an_amendment_rerun_is_the_post_run_state(repo):
    """The crashed run's line is a genuine hash commit's, before R: only its disclosure lets it
    stand beside the run's entry."""
    c = completed(repo, rerun=True)
    assert seal_rules.hash_commit_ok(repo.root, c["h1a"], c["t"])[0]
    assert seal_rules.is_ancestor(repo.root, c["h1a"], c["run"])
    lines = [json.loads(x) for x in repo.log.read_text().splitlines()]
    assert lines == [c["earlier"], c["entry"]] and c["s"] != c["t"]
    assert problems(repo) == []


def test_case_3_recomputed_provenance_is_the_post_run_state(repo):
    c = case3(repo)
    repo.tag(RUN, c["run"])
    assert problems(repo) == []


@pytest.mark.parametrize("at", ["t", "h1", "f"])
def test_conf_run_v1_before_the_completed_run_is_not_the_post_run_state(repo, at):
    """On the plan tag itself (not after it), on H1, or on case 3's fix commit before report
    --from-scores: no run-mode provenance, or not after T."""
    c = case3(repo)
    repo.tag(RUN, c[at])
    (problem,) = problems(repo)
    assert ("does not descend" if at == "t" else "not a completed run") in problem


def test_conf_run_v1_on_the_case_2_crash_fix_commit_is_not_the_post_run_state(repo):
    t = repo.tag(PLAN)
    h1a = repo.hash_commit()
    repo.unseal(repo.line(h1a, TS))
    f = repo.crash_fix(TS)
    repo.tag(RUN, f)
    assert seal_rules.descends(repo.root, f, t)
    (problem,) = problems(repo)
    assert "not a completed run" in problem


def test_conf_run_v1_off_the_plan_tags_line_is_not_the_post_run_state(repo):
    c = completed(repo, tag=False)
    repo.git("checkout", "-q", "--orphan", "elsewhere")
    repo.tag(RUN, repo.step6(c["entry"]))
    (problem,) = problems(repo)
    assert "does not descend" in problem


def _dry(r, c):
    return r.step6(c["entry"], provenance={"extra": {"mode": "dry", "unseal_entry": c["entry"]}})


def _twice(r, c):
    r.append(r.log, c["entry"])
    return r.step6(c["entry"])


def _after(r, c):                    # a disclosed line after E: E is no longer the last line
    stray = r.line(c["h1"], TS_STRAY)
    r.append(r.log, stray)
    r.add_row(row(TS_STRAY))
    return r.step6(c["entry"])


def _hash_file(r, c):
    r.write(f"{RESULTS}/timings.csv", "edited after the unseal\n")
    return r.step6(c["entry"])


def _recomputed(r, c):
    other = {**c["entry"], "sealed_rows": 20}
    r.write(f"{RESULTS}/recomputed-abc/{seal_rules.PROVENANCE}",
            json.dumps({"extra": {"mode": "run", "unseal_entry": other}}))
    return r.step6(c["entry"])


BROKEN = {
    "dry provenance": (_dry, "records no run"),
    "no unseal entry": (lambda r, c: r.step6(c["entry"], provenance={"extra": {"mode": "run"}}),
                        "records no run"),
    "unparseable provenance": (lambda r, c: r.step6(c["entry"], provenance="{not json"),
                               "does not parse"),
    "entry copy differs": (lambda r, c: r.step6(c["entry"], copy={**c["entry"], "head": c["t"]}),
                           "unseal_entry.json"),
    "provenances disagree": (_recomputed, "different unseal entries"),
    "entry held twice": (_twice, "held once"),
    "entry not last": (_after, "does not end with the run's unseal entry"),
    "hash file changed at R": (_hash_file, "does not hold ['timings.csv']"),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_a_run_whose_record_is_broken_is_not_the_post_run_state(repo, case):
    make, why = BROKEN[case]
    t = repo.tag(PLAN)
    h1 = repo.hash_commit()
    entry = repo.line(h1)
    repo.unseal(entry)
    repo.tag(RUN, make(repo, {"t": t, "h1": h1, "entry": entry}))
    found = problems(repo)
    assert found and any(why in p for p in found), found


@pytest.mark.parametrize("field, value, why", [
    ("token", "0" * 40, "token"),
    ("argv", ["/w/src/nhs_ae/evaluate/stage_h/__main__.py", "report", "--from-scores"], "argv"),
    ("head", "the tag", "has 0 parents"),                  # make_repo's T is the root commit
    ("head", "f" * 40, "is not a commit before"),
    ("head", "HEAD", "is not a commit before"),
])
def test_the_runs_entry_must_be_a_stage_h_run_at_a_hash_commit(repo, field, value, why):
    t = repo.tag(PLAN)
    h1 = repo.hash_commit()
    entry = repo.line(h1, **{field: t if value == "the tag" else value})
    repo.unseal(entry)
    repo.tag(RUN, repo.step6(entry))
    found = problems(repo)
    assert found and any(re.search(why, p) for p in found), found


def test_the_runs_entry_head_must_be_the_hash_commit_itself(repo):
    """A later commit on H1 that keeps the four hash files is not the runner's hash commit."""
    repo.tag(PLAN)
    repo.hash_commit()
    repo.write(f"{RESULTS}/notes.md", "n\n")
    entry = repo.line(repo.commit("after H1"))
    repo.unseal(entry)
    repo.tag(RUN, repo.step6(entry))
    (problem,) = problems(repo)
    assert "is not the runner's hash commit" in problem


def test_an_undisclosed_line_only_in_the_runs_committed_log_keeps_the_seal(repo):
    """Rule 5 alone: the stray line is in R's committed log but deleted from the working log
    afterwards, and there is no witness (a fresh clone). Disclosing it, not deleting it, is
    what lifts the seal."""
    repo.tag(PLAN)
    h1 = repo.hash_commit()
    repo.append(repo.log, repo.line(h1, TS_STRAY))
    entry = repo.line(h1)
    repo.append(repo.log, entry)
    repo.tag(RUN, repo.step6(entry))
    repo.write(seal_rules.LOG_REL, json.dumps(entry) + "\n")
    repo.commit("delete the stray line")
    assert not repo.witness.exists()
    (problem,) = problems(repo)
    assert f"{RUN}'s committed {seal_rules.LOG_REL}" in problem and TS_STRAY in problem
    repo.add_row(row(TS_STRAY, "Stray unseal line"))
    repo.commit("disclose it")
    assert problems(repo) == []


def test_rs_own_rows_disclose_when_head_lacks_them(repo):
    """Crash fixes never go on main (design §3.2.4): after a case-2 rerun, work that carries on
    from T lacks F's row, and R's own row still discloses the crashed run's line."""
    completed(repo, rerun=True)
    repo.git("checkout", "-q", "-b", "live", repo.t)
    repo.write("archive/note.txt", "a\n")
    repo.commit("archive bot")
    assert seal_rules.rows_titled(repo.root, "HEAD", TITLE) == []
    assert problems(repo) == []


def test_an_undisclosed_line_anywhere_breaks_the_state_until_a_heads_row_discloses_it(repo,
                                                                                    tmp_path):
    c = completed(repo)
    other = tmp_path / "second"
    repo.git("worktree", "add", "-q", "-b", "second", str(other), c["run"])
    other_log = other / seal_rules.LOG_REL
    assert problems(repo, other_log) == []
    stray = repo.line(c["h1"], TS_STRAY, argv=["/w/.venv/bin/some-script", "run"])
    for path in (other_log, repo.witness):
        repo.append(path, stray)
        found = problems(repo, other_log)
        assert any(str(path) in p and TS_STRAY in p for p in found), found
    repo.add_row(row(TS_STRAY, "Stray unseal line"))
    repo.commit("disclose the stray line")                     # on HEAD, after the tag
    assert repo.head() != c["run"] and problems(repo, other_log) == []
    repo.git("reset", "-q", "--hard", c["run"])                # a disclosure must be committed
    repo.add_row(row(TS_STRAY, "Stray unseal line"))
    assert problems(repo, other_log)


@pytest.mark.parametrize("ts", ["", None, "2026-11-05", "later"])
def test_a_line_without_an_iso_timestamp_is_never_disclosed(repo, ts):
    completed(repo)
    stray = {"timestamp": ts, "token": repo.t} if ts is not None else {"token": repo.t}
    repo.append(repo.witness, stray)
    repo.add_row(row(TS_STRAY, f"Discloses {ts} and every line"))
    repo.commit("an attempted disclosure")
    (problem,) = problems(repo)
    assert "the witness" in problem


@pytest.mark.parametrize("content", ["\n", "{}\n\n", "[1]\n", "﻿{}\n", "{truncated\n"])
def test_an_unparseable_log_or_witness_is_not_the_post_run_state(repo, content):
    completed(repo)
    repo.witness.write_text(repo.witness.read_text() + content)
    (problem,) = problems(repo)
    assert "the witness" in problem and "not a JSON object" in problem


def test_a_git_failure_is_a_problem_never_an_exception(repo, monkeypatch, tmp_path):
    completed(repo)
    real = seal_rules._git

    def failing(root, *args, **kwargs):
        if "ls-tree" in args:
            raise subprocess.CalledProcessError(128, ["git", *args], stderr="fatal: bad object")
        return real(root, *args, **kwargs)
    monkeypatch.setattr(seal_rules, "_git", failing)
    (problem,) = problems(repo)
    assert "could not run" in problem and "CalledProcessError" in problem
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")
    monkeypatch.setattr(seal_rules, "_git", no_git)
    assert "could not run" in problems(repo)[0]
    monkeypatch.setattr(seal_rules, "_git", real)
    assert problems(repo) == []
    assert seal_rules.post_run_problems(tmp_path / "absent", [], None)
    not_a_repo = tmp_path / "not-a-repo"
    not_a_repo.mkdir()
    assert seal_rules.post_run_problems(not_a_repo, [], None) == [f"tag {PLAN} does not exist"]


def test_git_redirecting_variables_cannot_point_a_rule_at_another_repository(tmp_path, monkeypatch):
    """A git hook exports GIT_DIR; the rules still read the repository at ``root``."""
    a, b = tmp_path / "a", tmp_path / "b"
    for r in (a, b):
        r.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
        subprocess.run(["git", "-c", "user.email=t@example.org", "-c", "user.name=t", "commit",
                        "-q", "--allow-empty", "-m", r.name], cwd=r, check=True,
                       env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")})
    head_a = subprocess.run(["git", "rev-parse", "HEAD"], cwd=a, capture_output=True, text=True,
                            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
                            check=True).stdout.strip()
    monkeypatch.setenv("GIT_DIR", str(b / ".git"))
    assert seal_rules.commit(a, "HEAD") == head_a
