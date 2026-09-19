"""The rendered amendment log must hold every §10 row, and stay in step with it."""
from __future__ import annotations

import importlib.util
import re
import sys

import pytest

from nhs_ae.config import PROJECT_ROOT

SPEC = importlib.util.spec_from_file_location(
    "render_amendment_log", PROJECT_ROOT / "tools" / "render_amendment_log.py")
render_amendment_log = importlib.util.module_from_spec(SPEC)
sys.modules["render_amendment_log"] = render_amendment_log
SPEC.loader.exec_module(render_amendment_log)


def _source_rows() -> list[str]:
    """§10's data rows, counted independently of the renderer's own parser."""
    lines = (PROJECT_ROOT / "docs" / "preregistration.md").read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip() == "## 10. Amendments")
    end = next(i for i, l in enumerate(lines[start + 1:], start + 1) if re.match(r"#{1,6} ", l))
    return [l for l in lines[start:end]
            if l.startswith("|") and not l.startswith("| Date") and not set(l) <= set("|-: ")]


def test_every_amendment_row_is_parsed():
    assert len(render_amendment_log.rows(
        (PROJECT_ROOT / "docs" / "preregistration.md").read_text())) == len(_source_rows())


def test_a_row_with_unescaped_pipes_keeps_its_whole_change_cell():
    # §10 writes |x - y| in places, which splits the row on a naive parser (the
    # ensemble row of 2026-09-11 has seven cells, not three).
    rows = render_amendment_log.rows((PROJECT_ROOT / "docs" / "preregistration.md").read_text())
    ensemble = [c for _, c, _ in rows if "aggregate median − sum" in c]
    assert len(ensemble) == 1
    assert "aggregate median − sum of its children's medians" in ensemble[0]
    assert "coverage − nominal" in ensemble[0]


def test_rendered_log_holds_every_row_verbatim():
    rendered = (PROJECT_ROOT / "docs" / "amendment_log.md").read_text()
    for stamp, change, reason in render_amendment_log.rows(
            (PROJECT_ROOT / "docs" / "preregistration.md").read_text()):
        title, body = render_amendment_log.split_title(change)
        flat = lambda s: re.sub(r"\s+", " ", s)
        for cell in (body, reason):
            probe = flat(cell)[-80:]                          # the tail: hardest to keep
            assert probe in flat(rendered), f"{stamp}: missing {probe!r}"
        if title:
            assert flat(title.strip().rstrip(".")) in flat(rendered), f"{stamp}: title lost"


def test_the_title_split_loses_nothing():
    for _, change, _ in render_amendment_log.rows(
            (PROJECT_ROOT / "docs" / "preregistration.md").read_text()):
        title, body = render_amendment_log.split_title(change)
        if title is not None:
            assert f"**{title}**{body}" == change.strip()


def test_committed_log_is_up_to_date():
    if render_amendment_log.main(["--check"]) != 0:
        pytest.fail("docs/amendment_log.md is stale; run `make amendments`")
