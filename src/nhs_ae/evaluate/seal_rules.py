"""The seal's rules on git state (P11), shared by ``splits`` and the Stage H runner.

Standard library only, with no ``nhs_ae`` import, so ``splits`` imports it without a cycle
(``harness`` imports ``splits``; ``stage_h.seal`` imports ``harness``). Deliberately outside
check 11's GEN_PATHS: the seal rules change no forecast. Every git call names the repository
``root`` and runs with ``--no-optional-locks``; ``post_run_problems`` never raises.

- git: ``commit``, ``descends``, ``is_ancestor``, ``blob``, ``tag_is_annotated``, ``parents``,
  ``worktrees``, ``toplevel``;
- the preregistration's §10 rows: ``amendment_rows``, ``titled``, ``rows_titled``;
- the HEAD rules (design §3.2.4, §4): ``start_commit_ok``, ``hash_commit_ok``;
- the unsealing process: ``names_run``, ``import_problems``, ``tree_problems``,
  ``witness_path``;
- the post-run state (``conf-run-v1``, design §9): ``quotes_timestamp``, ``post_run_problems``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

PLAN_TAG = "conf-plan-v1"           # the unseal token is its commit
RUN_TAG = "conf-run-v1"             # tags the completed run's step-6 commit, by hand
TAGS = (PLAN_TAG, RUN_TAG)
PREREG_REL = "docs/preregistration.md"
LOG_REL = "results/unseal_log.jsonl"                    # splits.UNSEAL_LOG, one per worktree
RUN_RESULTS_REL = "results/H-confirmatory"
HASH_FILES = ("forecast_hashes.csv", "m2_fits.csv", "timings.csv", "qa_counts.csv")  # = common's
PROVENANCE = "provenance.json"                          # report.PROVENANCE
UNSEAL_ENTRY = "unseal_entry.json"                      # step 6's copy of the run's log line
WITNESS_REL = Path("nhs_ae") / "unseal_witness.jsonl"   # under the git common directory
NO_EXCLUDES = ("-c", "core.excludesFile=/dev/null")    # the repository's ignore rules only
_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?")
_RECOMPUTED = re.compile(rf"{re.escape(RUN_RESULTS_REL)}/recomputed-[^/]+/{re.escape(PROVENANCE)}")


# ---- git ---------------------------------------------------------------------------------
# git lets these override ``cwd`` (and hooks export GIT_DIR and GIT_INDEX_FILE): dropped, so a
# rule always reads the repository at ``root``
_REDIRECT = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR",
             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def _git(root, *args: str, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in _REDIRECT}
    return subprocess.run(["git", "--no-optional-locks", *args], cwd=Path(root), env=env,
                          capture_output=True, text=text, check=check)


def _out(root, *args: str) -> str:
    """Stripped stdout of ``git args`` at ``root``; raises CalledProcessError on failure."""
    return _git(root, *args).stdout.strip()


def commit(root, rev) -> str | None:
    """Full SHA of the commit ``rev`` names at ``root``, or None. A tag name (``TAGS``) is
    resolved as ``refs/tags/NAME``, never by git's short-name lookup, in which a ref
    ``refs/NAME`` of the same name would win."""
    if not isinstance(rev, str) or not rev or rev.startswith("-"):
        return None
    ref = f"refs/tags/{rev}" if rev in TAGS else rev
    r = _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    return r.stdout.strip() or None


def _is_ancestor(root, a: str, b: str) -> bool:
    return _git(root, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def is_ancestor(root, a, b) -> bool:
    """``a`` is ``b`` or an ancestor of it (both commits)."""
    ca, cb = commit(root, a), commit(root, b)
    return ca is not None and cb is not None and _is_ancestor(root, ca, cb)


def descends(root, rev, ancestor) -> bool:
    """``rev`` is a commit after ``ancestor`` on its line (not ``ancestor`` itself)."""
    c, a = commit(root, rev), commit(root, ancestor)
    return c is not None and a is not None and c != a and _is_ancestor(root, a, c)


def blob(root, ref: str, rel: str) -> bytes | None:
    """The bytes of ``rel`` in commit ``ref`` at ``root``, or None if it is not there."""
    r = _git(root, "cat-file", "blob", f"{ref}:{rel}", check=False, text=False)
    return r.stdout if r.returncode == 0 else None


def tag_is_annotated(root, tag: str) -> bool:
    """``refs/tags/<tag>`` exists and names a tag object, not a commit (a lightweight tag)."""
    r = _git(root, "cat-file", "-t", f"refs/tags/{tag}", check=False)
    return r.returncode == 0 and r.stdout.strip() == "tag"


def parents(root, rev) -> list[str]:
    """The parents of commit ``rev``; raises ValueError if ``rev`` is not a commit."""
    c = commit(root, rev)
    if c is None:
        raise ValueError(f"{rev!r} is not a commit")
    return _out(root, "rev-list", "--parents", "-n", "1", c, "--").split()[1:]


def worktrees(root) -> list[Path]:
    """Every non-bare worktree ``git worktree list --porcelain`` reports, ``root``'s included."""
    out = []
    for block in _out(root, "worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(ln.split(" ", 1) if " " in ln else (ln, "") for ln in block.splitlines())
        if fields.get("worktree") and "bare" not in fields:
            out.append(Path(fields["worktree"]))
    return out


def toplevel(root) -> Path | None:
    """The toplevel of the worktree holding ``root``, or None outside one."""
    r = _git(root, "rev-parse", "--show-toplevel", check=False)
    top = r.stdout.strip()
    return Path(top) if r.returncode == 0 and top else None


# ---- §10 amendment rows ------------------------------------------------------------------
def amendment_rows(text: str) -> list[tuple[str, str]]:
    """(title, row) for every row of the preregistration's §10 table. A row's title is the
    leading bold phrase of its Change cell, or the whole cell in early rows without one."""
    rows, inside = [], False
    for line in text.splitlines():
        if line.startswith("#"):
            inside = line.startswith("## 10.")
        elif inside and line.startswith("|"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line)[1:-1]]
            if len(cells) < 2 or cells[0] == "Date" or not cells[0].strip("-: "):
                continue
            bold = re.match(r"\*\*(.+?)\*\*", cells[1])
            rows.append((" ".join((bold.group(1) if bold else cells[1]).split()), line))
    return rows


def titled(title: str, wanted: str) -> bool:
    """A row titled ``title`` is the row ``wanted`` if ``wanted`` is the whole title or its
    opening phrase up to a colon, comma, full stop or bracket (how the plan cites rows)."""
    t, w = title.rstrip(" .:;,"), " ".join(wanted.split()).rstrip(" .:;,")
    if not w or not t.startswith(w):
        return False
    rest = t[len(w):]
    return rest == "" or rest[0] in ".:;," or rest.startswith(" (")


def rows_titled(root, ref: str, title: str) -> list[str]:
    """The §10 rows titled ``title`` in commit ``ref``'s preregistration."""
    text = blob(root, ref, PREREG_REL)
    if text is None:
        return []
    return [row for t, row in amendment_rows(text.decode()) if titled(t, title)]


def _rows(root, ref: str) -> list[str]:
    text = blob(root, ref, PREREG_REL)
    return [] if text is None else [row for _, row in amendment_rows(text.decode("utf-8"))]


# ---- HEAD rules --------------------------------------------------------------------------
def start_commit_ok(root, head, amendment: str | None = None,
                    tag: str | None = None) -> tuple[bool, str]:
    """§3.2.4: ``head`` is the tag commit or, with ``amendment``, a descendant of it whose
    preregistration has exactly one §10 row titled ``amendment``, a row the tag lacks.
    ``tag``: the tag commit as the caller resolved it (default: ``refs/tags/conf-plan-v1`` at
    ``root``)."""
    tag = commit(root, PLAN_TAG) if tag is None else tag
    h = commit(root, head)
    if tag is None:
        return False, f"tag {PLAN_TAG} does not exist"
    if h is None:
        return False, f"{head!r} is not a commit"
    if amendment is None:
        if h == tag:
            return True, f"HEAD is the {PLAN_TAG} commit"
        return False, (f"HEAD {h[:12]} is not the {PLAN_TAG} commit {tag[:12]}; a crash-fix "
                       "rerun needs --amendment TITLE")
    if not descends(root, h, tag):
        return False, f"with --amendment, HEAD must descend from the {PLAN_TAG} commit"
    if rows_titled(root, tag, amendment):
        return False, (f"the preregistration at {PLAN_TAG} already has a §10 row titled "
                       f"{amendment!r}")
    n = len(rows_titled(root, h, amendment))
    if n != 1:
        return False, f"the preregistration at HEAD has {n} §10 rows titled {amendment!r}, not 1"
    return True, f"HEAD descends from {PLAN_TAG} and adds the §10 row {amendment!r}"


def hash_commit_ok(root, head, start) -> tuple[bool, str]:
    """§4: ``head`` is the runner's hash commit H1: its only parent is ``start``, and its
    diff from ``start`` adds results/H-confirmatory/{HASH_FILES} and does nothing else."""
    h, s = commit(root, head), commit(root, start)
    if h is None or s is None:
        return False, "not a commit"
    ps = parents(root, h)
    if ps != [s]:
        return False, (f"{h[:12]} has parents {[p[:12] for p in ps]}, not only the start "
                       f"commit {s[:12]}")
    diff = [ln.partition("\t")[::2]
            for ln in _out(root, "diff", "--no-renames", "--name-status", s, h).splitlines() if ln]
    want = {f"{RUN_RESULTS_REL}/{f}" for f in HASH_FILES}
    other = [f"{st} {p}" for st, p in diff if st != "A" or p not in want]
    if other:
        return False, f"{h[:12]} does more than add the hash files: {other[:5]}"
    missing = sorted(want - {p for _, p in diff})
    if missing:
        return False, f"{h[:12]} does not add {missing}"
    return True, f"{h[:12]} is the single child of {s[:12]} adding only the {len(want)} hash files"


# ---- the unsealing process ---------------------------------------------------------------
def names_run(argv) -> bool:
    """True if a logged ``argv`` is ``python -m nhs_ae.evaluate.stage_h run ...``: under
    ``-m``, argv[0] is the full path of the package's ``__main__.py``."""
    return (isinstance(argv, (list, tuple)) and len(argv) >= 2
            and Path(str(argv[0])).parts[-4:] == ("nhs_ae", "evaluate", "stage_h", "__main__.py")
            and argv[1] == "run")


def import_problems(toplevel: Path, package_file: Path, project_root: Path) -> list[str]:
    """Check 7's rule: ``nhs_ae`` lies under <toplevel>/src/nhs_ae, and PROJECT_ROOT is the
    toplevel (which fixes the unseal log splits writes to)."""
    top, out = Path(toplevel).resolve(), []
    if not Path(package_file).resolve().is_relative_to(top / "src" / "nhs_ae"):
        out.append(f"nhs_ae is imported from {package_file}, not from {top / 'src' / 'nhs_ae'}")
    if Path(project_root).resolve() != top:
        out.append(f"config.PROJECT_ROOT is {project_root}, not the git toplevel {top}")
    return out


def tree_problems(root) -> list[str]:
    """The tree rule of the first tokened call: nothing modified, staged or untracked outside
    results/ and data/, by the repository's ignore rules only (not the user's global excludes,
    as in check 6). Empty if the tree is clean there."""
    out = _git(root, *NO_EXCLUDES, "status", "--porcelain", "--untracked-files=all", "--", ".",
               ":(exclude)results", ":(exclude)data").stdout
    dirty = [ln for ln in out.splitlines() if ln.strip()]
    if not dirty:
        return []
    return [(f"the tree is not clean outside results/ and data/ ({len(dirty)} entries): "
             f"{dirty[:10]}")]


def witness_path(root) -> Path:
    """``$(git rev-parse --git-common-dir)/nhs_ae/unseal_witness.jsonl`` for the repository
    at ``root``: untracked by construction and shared by every worktree (design §2.7)."""
    root = Path(root)
    common = Path(_out(root, "rev-parse", "--git-common-dir"))
    return (common if common.is_absolute() else root / common).resolve() / WITNESS_REL


# ---- the post-run state (conf-run-v1) ----------------------------------------------------
def quotes_timestamp(row: str | None, ts) -> bool:
    """``row`` quotes the ISO-8601 timestamp ``ts`` verbatim as a whole value, not as part of
    a longer one (as ``checks._quotes`` quotes a version). An empty, non-string or non-ISO
    ``ts`` is never quoted. Check 10 (``checks._prior_line_problem``) applies the same rule, so
    a row that admits an --amendment rerun also discloses its line after the run."""
    if not isinstance(row, str) or not isinstance(ts, str) or not _ISO.fullmatch(ts):
        return False
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    # a longer value would continue with an alphanumeric, '+' or '-', or with '.' or ':' and an
    # alphanumeric; punctuation, Markdown emphasis or a colon before prose ends the value
    return re.search(rf"(?<![A-Za-z0-9.:+-]){re.escape(ts)}(?![A-Za-z0-9+-]|[.:][A-Za-z0-9])",
                     row) is not None


class _NotPostRun(Exception):
    """A post-run rule fails; the message is the problem."""


def _json(data: bytes | None, what: str):
    if data is None:
        raise _NotPostRun(f"{what} is missing")
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as e:                     # UnicodeDecodeError and JSONDecodeError
        raise _NotPostRun(f"{what} does not parse as JSON ({type(e).__name__})") from e


def _log_entries(data: bytes, what: str) -> list[dict]:
    """Every line of a log or witness, each a JSON object (UTF-8, split by
    ``str.splitlines``, as seal's accounting reads it); a blank or unparseable line fails."""
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as e:
        raise _NotPostRun(f"{what} is not UTF-8 text") from e
    out = []
    for i, line in enumerate(lines, 1):
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        if not isinstance(entry, dict):
            raise _NotPostRun(f"line {i} of {what} is blank or not a JSON object")
        out.append(entry)
    return out


def _run_entry(root: Path, run: str) -> dict:
    """Rule 3: E, the unseal entry that R's run-mode provenance files record; each must be
    run-mode, all must agree, and results/H-confirmatory/unseal_entry.json, if present, is E."""
    names = _out(root, "ls-tree", "-r", "-z", "--name-only", run, "--", RUN_RESULTS_REL)
    paths = [n for n in names.split("\0")
             if n == f"{RUN_RESULTS_REL}/{PROVENANCE}" or _RECOMPUTED.fullmatch(n)]
    if not paths:
        raise _NotPostRun(f"{RUN_TAG}'s commit holds no {RUN_RESULTS_REL}/{PROVENANCE} or "
                          f"recomputed-*/{PROVENANCE}: not a completed run")
    entries = []
    for p in sorted(paths):
        doc = _json(blob(root, run, p), f"{p} at {RUN_TAG}")
        extra = doc.get("extra") if isinstance(doc, dict) else None
        entry = extra.get("unseal_entry") if isinstance(extra, dict) else None
        if not isinstance(extra, dict) or extra.get("mode") != "run" or not isinstance(entry, dict):
            raise _NotPostRun(f"{p} at {RUN_TAG} records no run (extra.mode 'run' and an "
                              "extra.unseal_entry object)")
        entries.append(entry)
    if any(e != entries[0] for e in entries):
        raise _NotPostRun(f"the provenance files at {RUN_TAG} record different unseal entries")
    copy = blob(root, run, f"{RUN_RESULTS_REL}/{UNSEAL_ENTRY}")
    if copy is not None and _json(copy, f"{UNSEAL_ENTRY} at {RUN_TAG}") != entries[0]:
        raise _NotPostRun(f"{RUN_RESULTS_REL}/{UNSEAL_ENTRY} at {RUN_TAG} is not the entry its "
                          "provenance records")
    return entries[0]


def _entry_problems(root: Path, tag: str, run: str, entry: dict, lines: list[dict]) -> list[str]:
    """Rule 4: E is the last line of R's committed log and no other line; its token is the tag
    commit, its argv a stage_h run, and its head H a hash commit before R on the tag's line
    whose four hash files R holds byte for byte (``__main__._on_h1``'s relation)."""
    out = []
    n = sum(line == entry for line in lines)
    if not lines or lines[-1] != entry or n != 1:
        out.append(f"{RUN_TAG}'s committed {LOG_REL} does not end with the run's unseal entry, "
                   f"held once (it holds it {n} times in {len(lines)} lines)")
    if entry.get("token") != tag:
        out.append(f"the run's unseal entry: its token is not the {PLAN_TAG} commit")
    if not names_run(entry.get("argv")):
        out.append("the run's unseal entry: its argv is not a stage_h run")
    h = entry.get("head")
    if not (isinstance(h, str) and _SHA.fullmatch(h) and is_ancestor(root, h, run)):
        out.append(f"the run's unseal entry: its head {h!r} is not a commit before {RUN_TAG}'s")
        return out
    ps = parents(root, h)
    if len(ps) != 1:
        out.append(f"the run's unseal entry: its head {h[:12]} has {len(ps)} parents, not 1")
        return out
    ok, why = hash_commit_ok(root, h, ps[0])
    if not ok:
        out.append(f"the run's unseal entry: its head is not the runner's hash commit: {why}")
    if ps[0] != tag and not descends(root, ps[0], tag):
        out.append(f"the run's unseal entry: its head's parent {ps[0][:12]} is neither the "
                   f"{PLAN_TAG} commit nor after it")
    changed = [f for f in HASH_FILES
               if (b := blob(root, h, f"{RUN_RESULTS_REL}/{f}")) is None
               or b != blob(root, run, f"{RUN_RESULTS_REL}/{f}")]
    if changed:
        out.append(f"{RUN_TAG}'s commit does not hold {changed} as the hash commit {h[:12]} "
                   "committed them")
    return out


def _undisclosed(entries: list[dict], entry: dict, rows: list[str]) -> list:
    """The timestamps of the lines that are neither E nor quoted by one of ``rows``."""
    return [e.get("timestamp") for e in entries
            if e != entry and not any(quotes_timestamp(row, e.get("timestamp")) for row in rows)]


def _post_run(root: Path, log_paths: list[Path], witness: Path | None) -> list[str]:
    tag = commit(root, PLAN_TAG)
    if tag is None:
        raise _NotPostRun(f"tag {PLAN_TAG} does not exist")
    run = commit(root, RUN_TAG)
    if run is None:
        raise _NotPostRun(f"tag {RUN_TAG} does not exist")
    if not tag_is_annotated(root, RUN_TAG):
        raise _NotPostRun(f"{RUN_TAG} is a lightweight tag; it must be annotated")
    if not descends(root, run, tag):
        raise _NotPostRun(f"{RUN_TAG} ({run[:12]}) does not descend from {PLAN_TAG} ({tag[:12]})")
    entry = _run_entry(root, run)                                                       # 3
    committed = blob(root, run, LOG_REL)
    if committed is None:
        raise _NotPostRun(f"{RUN_TAG}'s commit holds no {LOG_REL}")
    lines = _log_entries(committed, f"{RUN_TAG}'s committed {LOG_REL}")
    out = _entry_problems(root, tag, run, entry, lines)                                 # 4
    at_tag = set(_rows(root, tag))
    rows = [row for ref in (run, "HEAD") for row in _rows(root, ref) if row not in at_tag]
    bad = _undisclosed(lines, entry, rows)                                              # 5
    if bad:
        out.append(f"{RUN_TAG}'s committed {LOG_REL} holds {len(bad)} lines neither the run's "
                   f"entry nor disclosed in a §10 row (timestamps {bad[:5]})")
    seen = set()
    files = [(Path(p), f"the unseal log {p}") for p in log_paths]                       # 6
    files += [] if witness is None else [(Path(witness), f"the witness {witness}")]
    for path, what in files:
        key = path.resolve()
        if key in seen or not path.exists():                # absent: no lines
            continue
        seen.add(key)
        try:
            if not path.is_file():
                raise _NotPostRun(f"{what} is not a regular file")
            bad = _undisclosed(_log_entries(path.read_bytes(), what), entry, rows)
        except _NotPostRun as e:
            out.append(str(e))
            continue
        if bad:
            out.append(f"{what} holds {len(bad)} lines neither the run's entry nor disclosed in "
                       f"a §10 row (timestamps {bad[:5]})")
    return out


def post_run_problems(root, log_paths, witness) -> list[str]:
    """Why the post-run state (P11, design §9) does not hold for the repository at ``root``;
    empty iff it holds:

    1. ``refs/tags/conf-plan-v1`` exists; T is its commit.
    2. ``refs/tags/conf-run-v1`` is an annotated tag; its commit R descends from T.
    3. R holds a run-mode results/H-confirmatory/provenance.json or recomputed-*/provenance.json
       (extra.mode "run", extra.unseal_entry an object): E is that entry, all agree, and
       results/H-confirmatory/unseal_entry.json, if R holds it, is E (parsed JSON compared).
    4. R's committed log ends with E and holds it once; E's token is T and its argv a stage_h
       run; its head H is a full SHA before R whose only parent S is T or after T, H is the
       runner's hash commit on S, and R holds H's four hash files byte for byte.
    5. Every other line of R's log is disclosed: a §10 row absent at T, in R's or HEAD's
       committed preregistration, quotes its timestamp (``quotes_timestamp``).
    6. Every line of every file in ``log_paths`` (each worktree's log) and of ``witness`` is E
       or disclosed as in 5; an absent or empty file passes.
    7. Any git error, missing object, unreadable or unparseable file is a problem.

    No network call: the push of conf-run-v1 is checked by hand. Never raises."""
    try:
        return _post_run(Path(root), [Path(p) for p in log_paths],
                         None if witness is None else Path(witness))
    except _NotPostRun as e:
        return [str(e)]
    except Exception as e:  # noqa: BLE001 - fail closed: an error means the state does not hold
        return [f"the post-run check could not run: {e!r}"]
