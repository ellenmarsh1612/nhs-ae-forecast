"""Stage H outputs (plan §5; design §7.1, §9): one CSV per table and slice, the verdicts,
``confirmatory_results.md``, the README and ``provenance.json``, and the printed summary.

The writer splits a table rather than refusing it (design §7.1, §11): a table whose split,
origin set, level, mode, G1 variant, months or horizons column holds more than one value is
written as one file per combination of those values, so every written file holds one value
of each. A slice encoded any other way (in a stat name, or as a pair of columns) is not
detected here: the statistics are built so that none is, and the rehearsal checks the run's
tables for it before the tag. A table without columns is written with the header
``EMPTY_HEADER``, so every file loads.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from nhs_ae.evaluate.stage_h.common import NAMES

SLICE_COLS = ("split", "origin_set", "level", "mode", "g1", "months", "horizons")
TAG_COLS = (*SLICE_COLS, "n_origins", "model", "stat", "metric")   # printed once, above a table
TABLES = "tables"
EMPTY_HEADER = "no_columns"
PROVENANCE = "provenance.json"
RECOMPUTATION_CHECK = "recomputation_check.csv"
VERDICTS = "verdicts.json"
RECOMPUTED = "report --from-scores (recomputed)"
NA = "n/a"
_MISSING = object()

# Every registered verdict, label, caveat and count, per hypothesis (design §7): each path is
# rendered, None as n/a, and a path whose statistic failed as not computed.
V3 = NAMES["m1_v3_raw"]
REQUIRED: dict[str, tuple[str, ...]] = {
    "Primary (§7.5)": ("primary.verdict.verdict", "primary.verdict.outside",
                       "primary.alongside.failed_dropped.verdict.verdict",
                       "primary.alongside.failed_dropped.verdict.outside"),
    "H1 (§7.3)": ("h1.overall.verdict", "h1.overall.fragile", "h1.overall.flips",
                  f"h1.overall.by_model.{V3}.verdict", f"h1.overall.by_model.{V3}.fragile",
                  "h1.failed_dropped.overall.verdict", "h1.failed_dropped.overall.fragile",
                  "h1.overall.caveat"),
    "H2, M1 clause (§7.5)": ("h2_m1.verdict.verdict", "h2_m1.verdict.directions",
                             "h2_m1.verdict.crossings", "h2_m1.verdict.fragile",
                             "h2_m1.conf21.verdict.verdict",
                             "h2_m1.failed_dropped.verdict.verdict", "h2_m1.caveat"),
    "H2, M2 clause (§7.5)": ("h2_m2.verdict.verdict", "h2_m2.verdict.directions",
                             "h2_m2.verdict.crossings", "h2_m2.verdict.fragile",
                             "h2_m2.evaluable", "h2_m2.fail_limit", "h2_m2.n_failed_counted",
                             "h2_m2.n_counted", "h2_m2.n_failed_full", "h2_m2.n_full",
                             "h2_m2.failed_units", "h2_m2.conf21.verdict.verdict",
                             "h2_m2.failed_dropped.verdict.verdict", "h2_m2.phase",
                             "h2_m2.limitation", "h2_m2.limitation_notes", "h2_m2.caveat"),
    "H3 (§7.7)": ("h3.headline.verdict", "h3.headline.fragile", "h3.headline.flips",
                  "h3.failed_dropped.headline.verdict", "h3.failed_dropped.headline.fragile",
                  "h3.notes"),
    "H4 (§7.8)": ("h4.verdict.verdict", "h4.verdict.refuting", "h4.verdict.fragile",
                  "h4.verdict.flips", "h4.verdict.elements", "h4.verdict.ranking_holds",
                  "h4.failed_dropped.verdict.verdict", "h4.verdict.note"),
    "H4-original (§7.9)": ("h4_original.verdict.verdict", "h4_original.verdict.exceeds",
                           "h4_original.verdict.ranking_changes",
                           "h4_original.failed_dropped.verdict.verdict"),
    "H4b (§7.10)": ("h4b.overall.verdict", "h4b.overall.per_target", "h4b.overall.verdict_full",
                    "h4b.overall.per_target_full", "h4b.overall.label"),
    "H5 (§7.11)": ("h5",),
    "F2 (§7.12)": ("f2.notes",),
}
H1_COLS = ("model", "role", "target", "rel", "rel_lo", "rel_hi", "verdict", "qualifier", "fragile",
           "qualifier_fragile")
H3_COLS = ("base", "H3", "icb_rel_hi", "provider_rel", "fragile", "flips")
H4B_COLS = ("target", "late_larger", "need", "share", "verdict", "role")


def _plain(x):
    if isinstance(x, (np.generic,)):
        return x.item()
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return x.isoformat()
    if isinstance(x, Path):
        return str(x)
    if isinstance(x, float) and math.isnan(x):
        return None
    if isinstance(x, (set, frozenset, tuple)):
        return list(x)
    if isinstance(x, pd.DataFrame):
        return f"<table {x.shape[0]}x{x.shape[1]}>"
    return str(x)


def _is_na(x) -> bool:
    if x is None or x is pd.NA or x is pd.NaT:
        return True
    return isinstance(x, (float, np.floating)) and math.isnan(x)


def _strict(x):
    """``x`` with every NaN (a float, a numpy float, pd.NA, pd.NaT) as None, at any depth, so
    verdicts.json is strict JSON with n/a as null."""
    if isinstance(x, dict):
        return {k: _strict(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set, frozenset)):
        return [_strict(v) for v in x]
    return None if _is_na(x) else x


def flatten(obj, prefix: str = "") -> tuple[dict[str, pd.DataFrame], dict]:
    """Every DataFrame in a nested result, keyed by its path ("h1.table"), and everything else,
    None included (an n/a label is kept, not dropped)."""
    tables, other = {}, {}
    if isinstance(obj, pd.DataFrame):
        tables[prefix or "table"] = obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            t, o = flatten(v, f"{prefix}.{k}" if prefix else str(k))
            tables.update(t)
            other.update(o)
    elif isinstance(obj, (list, tuple)) and any(isinstance(v, (pd.DataFrame, dict)) for v in obj):
        for i, v in enumerate(obj):
            t, o = flatten(v, f"{prefix}.{i}")
            tables.update(t)
            other.update(o)
    elif prefix:
        other[prefix] = obj
    return tables, other


def split_slices(name: str, frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """One frame per combination of the slice columns that hold more than one value."""
    mixed = [c for c in SLICE_COLS if c in frame.columns and frame[c].nunique(dropna=False) > 1]
    if not mixed:
        return {name: frame}
    out = {}
    for vals, g in frame.groupby(mixed, dropna=False, sort=True):
        vals = vals if isinstance(vals, tuple) else (vals,)
        suffix = "__".join(f"{c}={v}" for c, v in zip(mixed, vals))
        out[f"{name}__{suffix}"] = g.reset_index(drop=True)
    return out


def write_tables(tables: dict[str, pd.DataFrame], out: Path) -> list[str]:
    """Each table as one CSV per slice (``split_slices``); never overwrites."""
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in sorted(tables.items()):
        for part, f in split_slices(name, frame).items():
            path = out / f"{_safe(part)}.csv"
            if path.exists():
                raise FileExistsError(f"{path} exists: results are never overwritten")
            (f if len(f.columns) else pd.DataFrame(columns=[EMPTY_HEADER])).to_csv(path, index=False)
            written.append(path.name)
    return written


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._=-+" else "_" for ch in name)


# ---- lookups -----------------------------------------------------------------------------
def lookup(results: dict, path: str):
    """The value at a dotted path; None where a step is None; ``_MISSING`` where a key is."""
    obj = results
    for key in path.split("."):
        if obj is None:
            return None
        if not isinstance(obj, dict) or key not in obj:
            return _MISSING
        obj = obj[key]
    return obj


def errors(results: dict) -> dict[str, str]:
    """Every statistic that failed or was not computed, by path: each ``_errors`` dict at any
    depth ("h1", "dev_flags.h1", "dev.seasons.h4"), so a nested one is never lost."""
    out: dict[str, str] = {}

    def walk(obj, prefix: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "_errors" and isinstance(v, dict):
                    out.update({f"{prefix}{name}": str(msg) for name, msg in v.items()})
                else:
                    walk(v, f"{prefix}{k}.")

    walk(results, "")
    return out


def _render(v) -> str:
    return NA if _is_na(v) else json.dumps(v, default=_plain, ensure_ascii=False)


def required_lines(results: dict) -> list[str]:
    """Every path of ``REQUIRED``, one line each, under its hypothesis."""
    errs = results.get("_errors") or {}
    lines = []
    for title, paths in REQUIRED.items():
        lines += [f"### {title}", ""]
        for path in paths:
            top = path.split(".")[0]
            v = lookup(results, path)
            if v is _MISSING:
                text = (f"not computed ({top}: {errs[top]})" if top in errs
                        else NA if top in results else "not computed")
            else:
                text = _render(v)
            lines.append(f"- `{path}`: {text}")
        lines.append("")
    return lines


# ---- Markdown ----------------------------------------------------------------------------
def _cell(x) -> str:
    if _is_na(x):
        return NA
    if isinstance(x, (float, np.floating)):
        x = float(x)
        return f"{x:.0f}" if x.is_integer() and abs(x) >= 10 else f"{x:.3g}"
    return str(x)


def md_table(df: pd.DataFrame) -> str:
    """A GitHub Markdown table, None and NaN shown as n/a."""
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    rule = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(_cell(x) for x in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, rule, *body])


def _sliced(t: pd.DataFrame, cols=None) -> list[str]:
    """A table's single-valued slice columns as one line, then the table without them."""
    tags = {c: t[c].iloc[0] for c in TAG_COLS
            if c in t.columns and len(t) and t[c].nunique(dropna=False) == 1}
    body = t.drop(columns=list(tags))
    if cols is not None:
        body = body[[c for c in cols if c in body.columns]]
    line = ", ".join(f"{k} {_cell(v)}" for k, v in tags.items())
    return ([f"Slice: {line}.", ""] if line else []) + [md_table(body), ""]


def _dev_section(results: dict) -> list[str]:
    """Design §7.13: each CONF value against DEV's range, k of n outside, and the rows."""
    flags = results.get("dev_flags")
    if not isinstance(flags, dict):
        return ["## CONF against DEV's range (design §7.13)", "", "Not computed.", ""]
    counts = flags.get("outside") or {}
    parts = ["## CONF against DEV's range (design §7.13)", "",
             ("Each CONF value is flagged outside DEV's range [min, max] (winter-h3 statistics: "
              "DEV's seasons, the 2023/24 fragment left out; coverage: DEV's origin-year cells "
              "at the same horizon). A flag decides nothing. None means not flagged, with its "
              "reason."), ""]
    for name, t in flags.items():
        if not isinstance(t, pd.DataFrame):
            continue
        c = counts.get(name) or {}
        parts += [f"### {name}", "",
                  (f"{c.get('n_outside', NA)} of {c.get('n', NA)} outside DEV's range; "
                   f"{c.get('n_unflagged', NA)} not flagged."
                   + (f" Outside: {', '.join(c['flagged'])}." if c.get("flagged") else "")), "",
                  *_sliced(t)]
    return parts


def _h4b_section(results: dict) -> list[str]:
    """H4b's late_larger counts, CONF (CONF19, then CONF21) and DEV side by side (§7.10)."""
    conf = results.get("h4b") if isinstance(results.get("h4b"), dict) else {}
    dev = (results.get("dev") or {}).get("h4b")
    dev = dev if isinstance(dev, dict) else {}
    tables = [t for t in (conf.get("table"), (conf.get("conf21") or {}).get("table"),
                          dev.get("table")) if isinstance(t, pd.DataFrame)]
    if not tables:
        return []
    parts = ["## H4b, CONF and DEV side by side (design §7.10)", "",
             ("Labelled *seen*. H4b has no registered DEV range, so the DEV side is shown, not "
              "flagged (§7.13)."), ""]
    for t in tables:
        parts += _sliced(t, H4B_COLS)
    return parts


def _verdict_line(v) -> str:
    """The primary's verdict, with the horizons outside tolerance named."""
    if not isinstance(v, dict):
        return f"Verdict: **{_cell(v)}**"
    outside = v.get("outside") or {}
    named = ", ".join(f"h{h} {d}" for h, d in outside.items())
    return f"Verdict: **{_cell(v.get('verdict'))}**" + (f" (outside: {named})" if named else "")


def markdown(results: dict, facts: dict, mode: str, check: pd.DataFrame | None = None) -> str:
    """``confirmatory_results.md``, which ``run`` also prints as the step-6 summary: any
    failures first, then the primary comparison, every registered verdict path, the H1 and H3
    tables, H4b and the DEV side by side, and each CONF value against DEV's range."""
    title = "Stage H: confirmatory results" if mode == "run" else "Stage H dry run (DEV, no token)"
    if check is not None:
        title += f", {RECOMPUTED}"
    ctx = results.get("context") or {}
    counted = list(ctx.get("counted") or [])
    parts = [f"# {title}", "",
             (f"Mode: **{mode}**. Origins counted: {', '.join(counted[:3])} … ({len(counted)}). "
              f"New origins generated: {len(ctx.get('new_origins') or [])}."), ""]
    if mode != "run":
        parts += [("Every number here is DEV: the dry run treats DEV origins 2023-07 to 2023-12 "
                   "as CONF-like and scores without a token, so the seal drops their 2024 "
                   "targets. Nothing here is a confirmatory result."), ""]
    if check is not None:
        parts += _check_lines(check, mode)
    errs = errors(results)
    conf = {k: v for k, v in errs.items() if not k.startswith("dev.")}
    dev = {k: v for k, v in errs.items() if k.startswith("dev.")}
    if conf:
        parts += ["## Statistics that failed or are not evaluable", "",
                  *[f"- `{k}`: {v}" for k, v in conf.items()], ""]
    if dev:
        parts += ["## DEV-side statistics that failed or were not computed", "",
                  *[f"- `{k}`: {v}" for k, v in dev.items()], ""]
    prim = results.get("primary")
    if isinstance(prim, dict) and isinstance(prim.get("table"), pd.DataFrame):
        parts += ["## Primary comparison (design §7.5)", "", _verdict_line(prim.get("verdict")),
                  "", *_sliced(prim["table"])]
        dev_range = (prim.get("alongside") or {}).get("dev_range")
        if isinstance(dev_range, pd.DataFrame):
            parts += ["The DEV range (design §7.5, §7.13):", "", *_sliced(dev_range)]
    parts += ["## Verdicts (every registered path; None is n/a)", "", *required_lines(results)]
    h1 = (results.get("h1") or {}).get("table")
    if isinstance(h1, pd.DataFrame):
        parts += ["## H1 per target (design §7.3)", "", *_sliced(h1, H1_COLS)]
    h3 = (results.get("h3") or {}).get("verdicts")
    if isinstance(h3, pd.DataFrame):
        parts += ["## H3 per base (design §7.7)", "", *_sliced(h3, H3_COLS)]
    parts += _h4b_section(results)
    parts += _dev_section(results)
    parts += [f"H5: {results.get('h5', '')}", ""]
    return "\n".join(parts)


# ---- recomputation (design §9, case 3) ---------------------------------------------------
def recomputation_check(new: Path, original: Path) -> pd.DataFrame:
    """Each table of the recomputation ``new`` against the original run's ``original``, byte
    for byte where both exist, and ``verdicts.json`` beside each (every non-table result)."""
    pairs = {p.name: (Path(original) / p.name, p) for p in Path(new).glob("*.csv")}
    if Path(original).is_dir():
        pairs |= {p.name: (p, Path(new) / p.name) for p in Path(original).glob("*.csv")}
    pairs[VERDICTS] = (Path(original).parent / VERDICTS, Path(new).parent / VERDICTS)
    rows = []
    for n, (a, b) in sorted(pairs.items()):
        rows.append({"table": n, "in_original": a.is_file(), "in_recomputed": b.is_file(),
                     "identical": a.read_bytes() == b.read_bytes()
                     if a.is_file() and b.is_file() else None})
    return pd.DataFrame(rows, columns=["table", "in_original", "in_recomputed", "identical"])


def reproduced(check: pd.DataFrame) -> bool:
    """Every table and ``verdicts.json`` is on both sides and identical byte for byte: design
    §10's condition on the dry run's crash path."""
    same = [not _is_na(x) and bool(x) for x in check["identical"]]
    return bool(len(check)) and bool(check["in_original"].astype(bool).all()
                                     and check["in_recomputed"].astype(bool).all() and all(same))


def _check_lines(check: pd.DataFrame, mode: str) -> list[str]:
    orig = check["in_original"].astype(bool).to_numpy()
    new = check["in_recomputed"].astype(bool).to_numpy()
    same = np.array([not _is_na(x) and bool(x) for x in check["identical"]], dtype=bool)
    both = check[orig & new]
    differ = check.loc[orig & new & ~same, "table"].tolist()
    new_only = check.loc[~orig, "table"].tolist()
    old_only = check.loc[~new, "table"].tolist()
    lines = [f"## Recomputation (design §9, case 3{'' if mode == 'run' else '; §10'})", "",
             (f"Rebuilt by `{RECOMPUTED}` from the sealed step-4 and step-5 stores, with no "
              f"guarded call. {len(both) - len(differ)} of {len(both)} tables the original run "
              f"wrote are identical byte for byte; {len(new_only)} have no original; "
              f"{len(old_only)} of the original's were not rebuilt (`{RECOMPUTATION_CHECK}`)."),
             ""]
    if differ:
        rule = ("Plan §6: no change may alter a written number; each difference is disclosed as "
                "corrected after unsealing (design §9)." if mode == "run" else
                "Design §10 requires byte-identical tables, so the crash path does not "
                "reproduce the dry run.")
        lines += [(f"**{len(differ)} tables differ from the original run's**: "
                   f"{', '.join(differ[:10])}{' …' if len(differ) > 10 else ''}. {rule}"), ""]
    if old_only:
        lines += [f"Not rebuilt: {', '.join(old_only[:10])}{' …' if len(old_only) > 10 else ''}.",
                  ""]
    if mode == "run" and (differ or old_only):
        lines += [("**No re-runs: not met** if a difference above comes from a change to the code "
                   "after unsealing (plan §6, design §9); a byte difference with the same "
                   "numbers is listed, not labelled."), ""]
    return lines


# ---- README and provenance ---------------------------------------------------------------
def readme(facts: dict, mode: str, extra: dict, command: str | None = None) -> str:
    """The README: what wrote the directory, every fact and field (in full, as in
    ``provenance.json``) and the files. ``command`` is RECOMPUTED for ``report
    --from-scores``."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    recomputed = command == RECOMPUTED
    if recomputed:
        why = ("after a crash (design §9, case 3)" if mode == "run"
               else "as the dry run's check of the crash path (design §10)")
        wrote = (f"`python -m nhs_ae.evaluate.stage_h report --from-scores "
                 f"{extra.get('recomputed_from', 'WORK')}`, {RECOMPUTED}: every table rebuilt "
                 f"from the sealed step-4 and step-5 stores with no guarded call, {why}, and "
                 f"compared with the original's in `{RECOMPUTATION_CHECK}`")
        what = ("\"facts\": this process's environment and checks 6-8; \"extra\": the "
                "recomputation's, with \"run_facts\" the crashed run's step-2 checks (design "
                "§3.2.4, §3.2.8)")
    else:
        wrote = f"`python -m nhs_ae.evaluate.stage_h {command or ('run' if mode == 'run' else 'dry-run')}`"
        what = "\"facts\": step 2's checks; \"extra\": the run's"
    lines = [f"# results/{'H-confirmatory' if mode == 'run' else 'H-dryrun'}"
             + (" (recomputed)" if recomputed else ""), "",
             f"Written {now} by {wrote} (design: `docs/stage_h_design.md`).", "",
             "## Provenance", "", f"In full in `{PROVENANCE}` ({what}).", ""]
    for title, fields in (("Facts", facts), ("Extra", extra)):     # apart: no key hides another
        lines += [f"### {title}", ""]
        lines += [f"- **{k}**: `{json.dumps(_strict(v), default=_plain, ensure_ascii=False)}`"
                  for k, v in fields.items()]
        lines.append("")
    lines += ["## Files", "",
              "- `confirmatory_results.md`: the verdicts, the primary comparison and every label",
              "- `verdicts.json`: every non-table result, None as null",
              (f"- `{TABLES}/`: one CSV per table and slice; a table whose slice columns hold "
               "several values is written as one file per value (plan §5, design §7.1)"),
              "- `score_hashes.csv`: the store's SHA-256s and row hashes (the crash policy's score files)",
              f"- `{PROVENANCE}`: every fact and field above, in full"]
    if recomputed:
        lines.append(f"- `{RECOMPUTATION_CHECK}`: each table against the original run's, byte for byte")
    return "\n".join(lines) + "\n"


def write(results: dict, facts: dict, out: Path, mode: str, extra: dict | None = None,
          score_hashes: pd.DataFrame | None = None, original: Path | None = None) -> str:
    """Write every output under ``out`` and return the summary text. ``original``: the
    original run's tables directory, for ``report --from-scores``; each rebuilt table is then
    compared with it byte for byte (``recomputation_check.csv``) and the outputs say so."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    tables, other = flatten(results)
    written = write_tables(tables, out / TABLES)
    (out / VERDICTS).write_text(json.dumps(_strict(other), indent=1, sort_keys=True,
                                           default=_plain) + "\n")
    check = None
    if original is not None:
        check = recomputation_check(out / TABLES, Path(original))
        check.to_csv(out / RECOMPUTATION_CHECK, index=False)
    md = markdown(results, facts, mode, check)
    (out / "confirmatory_results.md").write_text(md + "\n")
    if score_hashes is not None:
        score_hashes.to_csv(out / "score_hashes.csv", index=False)
    extra = {**(extra or {}), "tables_written": len(written)}
    (out / PROVENANCE).write_text(json.dumps(_strict({"facts": facts, "extra": extra}), indent=1,
                                             sort_keys=True, default=_plain) + "\n")
    (out / "README.md").write_text(readme(facts, mode, extra, RECOMPUTED if check is not None
                                          else None))
    return md
