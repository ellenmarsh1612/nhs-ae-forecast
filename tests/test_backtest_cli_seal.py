"""P11, the backtest command line (spec §5): ``summary --include-sealed`` and ``--unseal-token``
are gone; ``run`` refuses any sealed origin before reading data or fitting, by an explicit
``SEALED_ORIGINS`` check that also holds in the post-run state. Nothing here reads real data:
the data reader, fitting and scoring are replaced before each call, and ``OUT_DIR`` is a
temporary directory."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from nhs_ae.evaluate import cli, splits


class Reached(Exception):
    """A replaced reader, fitter or scorer was called: the command got past its refusal."""


@pytest.fixture
def guarded(monkeypatch, tmp_path):
    """``OUT_DIR`` in ``tmp_path``; loading vintages, fitting and scoring raise ``Reached``.
    Returns the names of those reached, in order."""
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path)
    reached = []

    def stop(name):
        def f(*args, **kwargs):
            reached.append(name)
            raise Reached(name)
        return f
    for name in ("load_vintages", "generate_forecasts", "score_against_truth"):
        monkeypatch.setattr(cli, name, stop(name))
    return reached


def test_the_seal_flags_are_gone(guarded, capsys):
    for argv in (["summary", "--include-sealed"], ["run", "--unseal-token", "a" * 40],
                 ["run", "--split", "conf", "--unseal-token", "a" * 40]):
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == 2, argv                         # argparse: unrecognised argument
    capsys.readouterr()
    for cmd, gone in (("summary", "--include-sealed"), ("run", "--unseal-token")):
        with pytest.raises(SystemExit):
            cli.main([cmd, "--help"])
        assert gone not in capsys.readouterr().out
    assert "unseal-token" not in cli.__doc__ and "include-sealed" not in cli.__doc__
    assert guarded == []


@pytest.mark.parametrize("post_run", [False, True], ids=["pre-run", "post-run"])
@pytest.mark.parametrize("argv, n", [
    (["run", "--split", "conf"], 21),
    (["run", "--origins", "2024-01", "2024-03"], 3),
    (["run", "--origins", "2023-06", "2024-01"], 1),               # one month into CONF
    (["run", "--origins", "2025-09", "2026-01", "--out", "never"], 1),
    (["run", "--split", "conf", "--rescore", "--models", "b1"], 21),
])
def test_run_refuses_sealed_origins_before_reading_anything(argv, n, post_run, guarded, monkeypatch,
                                                            tmp_path, caplog):
    """Refused in the pre-run state and with ``splits._post_run`` holding, where
    ``assert_not_sealed`` lets token-less sealed rows through."""
    monkeypatch.setattr(splits, "_post_run", lambda: post_run, raising=False)
    if post_run:                             # the seal's own check now lets CONF through
        splits.assert_not_sealed(splits.split_origins("conf"))
    with caplog.at_level(logging.ERROR, logger="nhs_ae.evaluate"):
        assert cli.main(argv) == 1
    msg = caplog.text
    assert f"{n} requested origins" in msg and "python -m nhs_ae.evaluate.stage_h" in msg
    assert guarded == [] and cli.OUT_DIR == tmp_path and not any(tmp_path.iterdir())


@pytest.mark.parametrize("argv, n", [(["run"], 69),
                                     (["run", "--origins", "2023-10", "2023-12"], 3)])
def test_dev_origins_pass_and_are_scored_without_a_token(argv, n, guarded, monkeypatch):
    got = {}
    monkeypatch.setattr(cli, "load_vintages", lambda: None)
    monkeypatch.setattr(cli, "generate_forecasts", lambda models, v, cfg, **kw:
                        pd.DataFrame({"origin": pd.to_datetime(cfg.origins)}))

    def score(forecasts, vintages, cfg, **kwargs):
        got.update(origins=list(cfg.origins), kwargs=kwargs)
        raise Reached("score_against_truth")
    monkeypatch.setattr(cli, "score_against_truth", score)
    with pytest.raises(Reached):
        cli.main([*argv, "--models", "b0"])
    assert len(got["origins"]) == n and got["kwargs"] == {"unseal_token": None}


@pytest.mark.parametrize("post_run", [False, True], ids=["pre-run", "post-run"])
def test_summary_always_drops_sealed_rows(post_run, monkeypatch, tmp_path):
    monkeypatch.setattr(splits, "_post_run", lambda: post_run, raising=False)
    monkeypatch.setattr(cli, "OUT_DIR", tmp_path)
    ts = pd.to_datetime
    scores = pd.DataFrame({"origin": ts(["2023-01-01", "2023-12-01", "2024-06-01"]),
                           "period": ts(["2023-03-01", "2024-02-01", "2024-08-01"]),
                           "level": "provider", "wis": [1.0, 2.0, 3.0]})
    scores.to_parquet(tmp_path / "scores.parquet")             # DEV, embargoed target, CONF
    shown = []
    monkeypatch.setattr(cli, "print_summary", shown.append)
    assert cli.main(["summary"]) == 0
    assert len(shown) == 1 and shown[0]["wis"].tolist() == [1.0]
