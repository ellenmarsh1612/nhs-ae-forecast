"""The build refuses to run without the Excel readers the archive needs, rather than silently
dropping every workbook-only vintage."""

from __future__ import annotations

import importlib.util

from nhs_ae.ingest import cli


def test_build_refuses_without_xls_readers(monkeypatch):
    monkeypatch.setattr(cli, "read_manifest", lambda _p: [{"ext": "xls", "stored": True}, {"ext": "csv"}])
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None if name == "xlrd" else real(name, *a))

    def boom(*_a, **_k):
        raise AssertionError("parsed despite a missing reader")
    monkeypatch.setattr(cli, "parse_manifest_records", boom)
    assert cli.cmd_build(None) == 1


def test_missing_readers_ignores_unstored_sightings(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a: None)
    assert cli.missing_readers([{"ext": "xls", "stored": False}, {"ext": "csv", "stored": True}]) == []
    assert cli.missing_readers([{"ext": "xlsx", "stored": True}]) == ["openpyxl"]
