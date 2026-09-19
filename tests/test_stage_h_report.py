"""Stage H report writer (design §7.1, §9, §11 "Report"): one file per slice, every registered
verdict path rendered (None as n/a), nested failures listed, provenance in full, and the
recomputation compared with the original byte for byte. Synthetic results only."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.stage_h import report


def _mixed() -> pd.DataFrame:
    """A table mixing two levels and two origin sets, with a column that is not a slice."""
    return pd.DataFrame({"split": "conf", "origin_set": ["CONF19", "CONF19", "CONF21", "CONF21"] * 2,
                         "level": ["provider"] * 4 + ["icb"] * 4, "horizon": [1, 2] * 4,
                         "value": np.arange(8.0)})


def test_a_mixed_frame_is_written_as_one_file_per_slice_each_holding_one_value(tmp_path):
    parts = report.split_slices("t", _mixed())
    assert sorted(parts) == ["t__origin_set=CONF19__level=icb", "t__origin_set=CONF19__level=provider",
                             "t__origin_set=CONF21__level=icb", "t__origin_set=CONF21__level=provider"]
    written = report.write_tables({"t": _mixed(), "whole": _mixed().iloc[:2]}, tmp_path)
    assert len(written) == 5 and "whole.csv" in written
    rows = 0
    for name in written:
        f = pd.read_csv(tmp_path / name)
        assert all(f[c].nunique() == 1 for c in report.SLICE_COLS if c in f.columns), name
        rows += len(f) if name != "whole.csv" else 0
    assert rows == len(_mixed())
    with pytest.raises(FileExistsError, match="never overwritten"):
        report.write_tables({"whole": _mixed().iloc[:2]}, tmp_path)


def test_a_table_without_columns_is_written_with_a_header(tmp_path):
    report.write_tables({"h1.loo": pd.DataFrame()}, tmp_path)
    assert pd.read_csv(tmp_path / "h1.loo.csv").columns.tolist() == [report.EMPTY_HEADER]


def _results() -> dict:
    """A run's results with an n/a fragility, a failed statistic and nested DEV failures."""
    return {"context": {"mode": "run", "counted": ["2024-01-01"], "new_origins": ["2024-01-01"]},
            "primary": {"table": pd.DataFrame({"split": ["conf"], "horizon": [1], "point": [0.9]}),
                        "verdict": {"verdict": "within tolerance", "outside": {}},
                        "alongside": {"failed_dropped": None}},
            "h1": {"overall": {"verdict": "not confirmed (refuted, as registered)", "fragile": None,
                               "flips": [], "caveat": "a caveat", "by_model": {}},
                   "table": pd.DataFrame({"model": ["m"], "target": ["att_all"], "rel": [np.nan],
                                          "verdict": ["not evaluable"]}),
                   "failed_dropped": None},
            "h2_m1": {"verdict": {"verdict": "refuted", "fragile": False}, "conf21": None},
            "h5": "H5 line",
            "dev": {"_errors": {"seasons.h1": "not computed: DEV rows absent"},
                    "coverage": {"_errors": {"h2_m2": "ValueError: nested"}}},
            "dev_flags": {"h1": pd.DataFrame({"model": ["m"], "stat": ["rel"], "conf": [0.1],
                                              "dev_min": [0.0], "dev_max": [0.05],
                                              "outside": [True], "reason": [""]}),
                          "outside": {"h1": {"n": 1, "n_outside": 1, "n_unflagged": 0,
                                             "flagged": ["m rel"]}}},
            "_errors": {"h2_m2": "not evaluable: origins ['2024-01'] missing"}}


def test_every_registered_verdict_path_is_rendered_with_none_as_n_a():
    md = report.markdown(_results(), {}, "run")
    for paths in report.REQUIRED.values():
        for path in paths:
            assert f"- `{path}`: " in md, path
    assert "- `h1.overall.fragile`: n/a" in md
    assert "- `h2_m1.conf21.verdict.verdict`: n/a" in md
    assert "- `h1.overall.verdict`: \"not confirmed (refuted, as registered)\"" in md
    assert "- `h2_m2.verdict.verdict`: not computed (h2_m2: not evaluable" in md
    assert "- `h3.headline.verdict`: not computed" in md
    assert "## H1 per target (design §7.3)" in md and "| n/a |" in md
    assert "1 of 1 outside DEV's range; 0 not flagged. Outside: m rel." in md


def test_nested_failures_are_listed_and_none_is_kept_in_the_verdicts(tmp_path):
    R = _results()
    assert report.errors(R) == {"dev.seasons.h1": "not computed: DEV rows absent",
                                "dev.coverage.h2_m2": "ValueError: nested",
                                "h2_m2": "not evaluable: origins ['2024-01'] missing"}
    md = report.write(R, {"inputs": 21}, tmp_path, "run", {"inputs_source": "stage_h/inputs"})
    assert "`dev.coverage.h2_m2`: ValueError: nested" in md
    verdicts = json.loads((tmp_path / "verdicts.json").read_text())
    assert verdicts["h1.overall.fragile"] is None and verdicts["h1.failed_dropped"] is None


def test_provenance_holds_every_fact_in_full(tmp_path):
    long = "x" * 5000
    report.write(_results(), {"inputs": 21, "diff_stat": long, "head": "fact-head"}, tmp_path,
                 "run", {"inputs_source": "stage_h/inputs", "unseal_entry": {"argv": [long]},
                         "head": "extra-head"})
    prov = json.loads((tmp_path / report.PROVENANCE).read_text())
    assert prov["facts"] == {"inputs": 21, "diff_stat": long, "head": "fact-head"}
    assert prov["extra"]["unseal_entry"] == {"argv": [long]}
    assert prov["extra"]["inputs_source"] == "stage_h/inputs"
    readme = (tmp_path / "README.md").read_text()
    assert long in readme and "python -m nhs_ae.evaluate.stage_h run`" in readme
    assert "fact-head" in readme and "extra-head" in readme        # no key hides another


def test_a_recomputation_is_compared_with_the_original_byte_for_byte(tmp_path):
    original = tmp_path / "original"
    report.write(_results(), {}, original, "run")
    changed = pd.read_csv(original / report.TABLES / "h1.table.csv").assign(verdict="changed")
    changed.to_csv(original / report.TABLES / "h1.table.csv", index=False)
    pd.DataFrame({"a": [1]}).to_csv(original / report.TABLES / "gone.csv", index=False)
    out = tmp_path / "recomputed-abc"
    md = report.write(_results(), {}, out, "run", original=original / report.TABLES)
    check = pd.read_csv(out / report.RECOMPUTATION_CHECK).set_index("table")
    assert not check.loc["h1.table.csv", "identical"]
    assert check.loc["primary.table.csv", "identical"]
    assert not check.loc["gone.csv", "in_recomputed"]
    assert "**1 tables differ from the original run's**: h1.table.csv" in md
    assert "Not rebuilt: gone.csv." in md
    assert report.RECOMPUTED in md and report.RECOMPUTED in (out / "README.md").read_text()
    assert check.loc[report.VERDICTS, "identical"]                  # the non-table results too
    assert "**No re-runs: not met** if a difference" in md
    assert not report.reproduced(check.reset_index())


def test_a_changed_verdict_is_a_difference_and_a_clean_recomputation_reproduces(tmp_path):
    original = tmp_path / "original"
    report.write(_results(), {}, original, "dry")
    out = tmp_path / "recomputed-abc"
    md = report.write(_results(), {}, out, "dry", original=original / report.TABLES)
    check = pd.read_csv(out / report.RECOMPUTATION_CHECK)
    assert report.reproduced(check) and "No re-runs" not in md
    (original / report.VERDICTS).write_text((original / report.VERDICTS).read_text() + " ")
    again = tmp_path / "recomputed-def"
    md = report.write(_results(), {}, again, "dry", original=original / report.TABLES)
    check = pd.read_csv(again / report.RECOMPUTATION_CHECK).set_index("table")
    assert not check.loc[report.VERDICTS, "identical"] and not report.reproduced(check.reset_index())
    assert "does not reproduce the dry run" in md and "No re-runs" not in md
