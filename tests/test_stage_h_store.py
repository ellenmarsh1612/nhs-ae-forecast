"""Stage H write-then-hash store, progress records and crash cases (design §9), on synthetic
frames under tmp_path."""

from __future__ import annotations

import json
import os
from datetime import date

import numpy as np
import pandas as pd
import pytest

from nhs_ae.evaluate.stage_h import store
from nhs_ae.evaluate.stage_h.common import file_sha, row_hash
from nhs_ae.evaluate.stage_h.store import Store, StoreError, crash_case, progress, read_progress


def _frame(n: int = 6) -> pd.DataFrame:
    """A small scored-like frame with float quantile columns, as harness.score_forecasts gives."""
    return pd.DataFrame({"origin": pd.date_range("2023-07-01", periods=n, freq="MS"),
                         "series": [f"S{i % 2}" for i in range(n)], "horizon": np.arange(1, n + 1),
                         0.05: np.linspace(1.0, 2.0, n), 0.5: np.linspace(2.0, 3.0, n),
                         0.95: np.linspace(3.0, 4.0, n), "cov90": [True, False] * (n // 2)})


def _sums(root):
    return [json.loads(line) for line in (root / store.SUMS).read_text().splitlines()]


def _write_sums(root, recs):
    (root / store.SUMS).write_text("".join(json.dumps(r) + "\n" for r in recs))


# ---- store -----------------------------------------------------------------------------
def test_put_load_round_trip(tmp_path):
    root = tmp_path / store.SCORES
    s, f = Store(root), _frame()
    rec = s.put("b1_provider_asof_raw", f, {"model": "b1", "split": "dev", "origins": 6})
    s.put_json("dropped_b1", {"embargoed": np.int64(15), "no_outturn": 0})
    assert rec["sha256"] == file_sha(root / "b1_provider_asof_raw.parquet")
    assert rec["row_hash"] == row_hash(f) and rec["rows"] == 6
    with pytest.raises(StoreError, match="not sealed"):      # nothing is read back unhashed
        s.load("b1_provider_asof_raw")
    s.seal_sums()
    pd.testing.assert_frame_equal(s.load("b1_provider_asof_raw"), f)
    assert s.load_json("dropped_b1") == {"embargoed": 15, "no_outturn": 0}

    reopened = Store(root)                                   # report --from-scores
    assert reopened.sealed and reopened.names() == ["b1_provider_asof_raw", "dropped_b1"]
    pd.testing.assert_frame_equal(reopened.load("b1_provider_asof_raw"), f)
    table = reopened.records()
    assert list(table["name"]) == ["b1_provider_asof_raw", "dropped_b1"]
    assert table.loc[0, "model"] == "b1" and table.loc[0, "sha256"] == rec["sha256"]
    with pytest.raises(StoreError, match="json record"):
        reopened.load("dropped_b1")


def test_load_refuses_a_tampered_file(tmp_path):
    s = Store(tmp_path)
    s.put("x", _frame())
    s.put_json("d", {"embargoed": 15})
    s.seal_sums()
    path = tmp_path / "x.parquet"

    f = pd.read_parquet(path)
    f.loc[0, "0.5"] = 99.0
    f.to_parquet(path, index=False)
    with pytest.raises(StoreError, match="SHA-256"):
        s.load("x")
    recs = _sums(tmp_path)                    # the SHA-256 in SHA256SUMS rewritten as well
    recs[1]["sha256"] = file_sha(path)
    _write_sums(tmp_path, recs)
    with pytest.raises(StoreError, match="changed since"):
        s.load("x")
    with pytest.raises(StoreError, match="row hash"):
        Store(tmp_path).load("x")

    _frame().to_parquet(path, index=False, compression="gzip")     # same rows, re-encoded
    recs[1]["sha256"] = file_sha(path)
    _write_sums(tmp_path, recs)
    pd.testing.assert_frame_equal(Store(tmp_path).load("x"), _frame())

    (tmp_path / "d.json").write_text('{"embargoed": 16}')
    with pytest.raises(StoreError, match="SHA-256"):
        Store(tmp_path).load_json("d")


def test_put_refuses_to_overwrite_and_after_sealing(tmp_path):
    s = Store(tmp_path)
    s.put("x", _frame())
    with pytest.raises(StoreError, match="never overwrites"):
        s.put("x", _frame(4))
    with pytest.raises(StoreError, match="never overwrites"):
        s.put_json("x", {})
    with pytest.raises(StoreError, match="never overwrites"):      # a second instance too
        Store(tmp_path).put("x", _frame(4))
    with pytest.raises(ValueError):
        s.put("../x", _frame())
    s.seal_sums()
    for put in (lambda: s.put("y", _frame()), lambda: s.put_json("y", {}),
                lambda: Store(tmp_path).put("y", _frame()), s.seal_sums):
        with pytest.raises(StoreError, match="sealed"):
            put()
    assert sorted(p.name for p in tmp_path.iterdir()) == [store.SUMS, "x.parquet"]
    pd.testing.assert_frame_equal(s.load("x"), _frame())


def test_put_refuses_an_index_it_would_drop(tmp_path):
    s, f = Store(tmp_path), _frame()
    keyed = f.set_index(["series", "horizon"])                       # a groupby's keys
    for frame in (f.set_index("series"), keyed, keyed.rename_axis([None, None])):
        with pytest.raises(ValueError, match="reset_index"):
            s.put("keyed", frame)
    assert list(tmp_path.iterdir()) == []
    kept = f[f["horizon"] > 2]                                       # an unnamed index: dropped
    s.put("kept", kept)
    s.seal_sums()
    pd.testing.assert_frame_equal(s.load("kept"), kept.reset_index(drop=True))


def test_records_hold_json_or_refuse(tmp_path):
    s = Store(tmp_path / "store")
    origins = pd.date_range("2021-01-01", periods=40, freq="MS")
    ns = origins.to_numpy().astype("datetime64[ns]")               # whose .item() is an int
    rec = s.put("x", _frame(), {"origins": ns, "input": tmp_path / "in.parquet",
                                "since": date(2017, 7, 1), "e": pd.Timestamp("2023-12-01"),
                                "n": np.int64(3), "ok": np.bool_(True)})
    assert rec["meta"] == {"origins": [d.isoformat() for d in origins],   # all 40, untruncated
                           "input": str(tmp_path / "in.parquet"), "since": "2017-07-01",
                           "e": "2023-12-01T00:00:00", "n": 3, "ok": True}
    for bad in ({"frame": _frame()}, {"s": {1, 2}}, {"i": pd.Index([1, 2])}):
        with pytest.raises(TypeError):
            s.put_json("y", bad)
        with pytest.raises(TypeError):
            s.put("z", _frame(), bad)
        with pytest.raises(TypeError):
            progress(tmp_path / "work", "unsealed", **bad)
    assert s.names() == ["x"] and not (tmp_path / "work" / store.PROGRESS).exists()


def test_seal_sums_refuses_unrecorded_or_changed_files(tmp_path):
    s = Store(tmp_path)
    s.put("x", _frame())
    (tmp_path / "stray.parquet").write_bytes(b"")
    with pytest.raises(StoreError, match="stray.parquet"):
        s.seal_sums()
    (tmp_path / "stray.parquet").unlink()
    _frame(4).to_parquet(tmp_path / "x.parquet", index=False)
    with pytest.raises(StoreError, match="changed after it was put"):
        s.seal_sums()
    assert not (tmp_path / store.SUMS).exists()


# ---- progress and crash cases ----------------------------------------------------------
def test_progress_appends_atomically(tmp_path, monkeypatch):
    progress(tmp_path, "unsealed", head="b" * 40)
    progress(tmp_path, "scores-about-to-be-written", files=3)
    recs = read_progress(tmp_path)
    assert [r["event"] for r in recs] == ["unsealed", "scores-about-to-be-written"]
    assert recs[0]["head"] == "b" * 40 and recs[1]["files"] == 3 and "ts" in recs[0]

    before = (tmp_path / store.PROGRESS).read_bytes()
    replaced = []

    def fail(src, dst):
        replaced.append((os.path.basename(src), os.path.basename(dst)))
        raise OSError("disk full")

    monkeypatch.setattr(store.os, "replace", fail)
    with pytest.raises(OSError):
        progress(tmp_path, "scores-written")
    monkeypatch.undo()
    assert replaced == [(".progress.jsonl.tmp", "progress.jsonl")]     # whole-file replace
    assert (tmp_path / store.PROGRESS).read_bytes() == before          # the old file is whole
    assert sorted(p.name for p in tmp_path.iterdir()) == [store.PROGRESS]

    with pytest.raises(ValueError, match="unknown"):
        progress(tmp_path, "score-written")                           # a misspelt event
    with pytest.raises(ValueError):
        progress(tmp_path, "sealing", log="unseal_log.jsonl", n0=0)     # no witness or w0
    with pytest.raises(ValueError):
        progress(tmp_path, "unsealed", ts="yesterday")
    assert read_progress(tmp_path) == recs


def _synthetic(work, *events, **fields):
    work.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": f"2026-10-01T10:0{i}:00+00:00", "event": e, **fields})
             for i, e in enumerate(events)]
    (work / store.PROGRESS).write_text("".join(line + "\n" for line in lines))
    return work


def test_crash_case_from_progress_files(tmp_path):
    log, witness = tmp_path / "unseal_log.jsonl", tmp_path / "unseal_witness.jsonl"
    at, line = {"log": str(log), "witness": str(witness)}, '{"token": "x"}\n'
    assert crash_case(tmp_path / "none") == 1                          # no progress at all
    sealing = _synthetic(tmp_path / "a", "sealing", **at, n0=0, w0=0)
    assert crash_case(sealing) == 1                                    # the call wrote nothing
    log.write_text(line)
    assert crash_case(sealing) == 2                                    # a line, not yet recorded
    witness.write_text(line)
    log.write_text("")                                                 # the log reverted
    assert crash_case(sealing) == 2                                    # the witness keeps it
    log.write_bytes(b"\xff\n")
    witness.write_text(line + line)
    assert crash_case(_synthetic(tmp_path / "b", "sealing", **at, n0=1, w0=2)) == 1
    with pytest.raises(StoreError, match="lacks"):
        crash_case(_synthetic(tmp_path / "i", "sealing", log=str(log), n0=0))
    assert crash_case(_synthetic(tmp_path / "c", "unsealed")) == 2
    assert crash_case(_synthetic(tmp_path / "d", "unsealed", "scores-about-to-be-written")) == 2
    assert crash_case(_synthetic(tmp_path / "e", "unsealed", "scores-about-to-be-written",
                                 "scores-written")) == 3
    assert crash_case(_synthetic(tmp_path / "f", "unsealed", "scores-written",
                                 "results-written", "committed")) == 3
    hashed = _synthetic(tmp_path / "g", "unsealed", "scores-about-to-be-written")
    (hashed / store.SCORES).mkdir()
    (hashed / store.SCORES / store.SUMS).write_text("")               # hashed, not yet recorded
    assert crash_case(hashed) == 3
    (tmp_path / "h").mkdir()
    (tmp_path / "h" / store.PROGRESS).write_text('{"event": "unsealed"}\n{trunc\n')
    with pytest.raises(StoreError, match="line 2"):
        crash_case(tmp_path / "h")
