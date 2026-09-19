"""Archive semantics tested with a fake HTTP session – no network."""
from datetime import date
from pathlib import Path

from nhs_ae.ingest.discover import FileRef
from nhs_ae.ingest.download import download_refs, latest_stored_per_period, read_manifest


class _Resp:
    def __init__(self, content: bytes):
        self.content = content
    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads
    def get(self, url, **kw):
        return _Resp(self.payloads[url])


def _ref(url, filename, period, revised=False, revised_on=None):
    return FileRef(url=url, filename=filename, period=period, ext="csv", financial_year="2026-27",
                   link_text=filename, revised=revised, revised_on=revised_on)


def test_dedupe_by_hash_and_asof_lookup(tmp_path: Path):
    raw = tmp_path / "data" / "raw"
    manifest = raw / "manifest.jsonl"
    r1 = _ref("https://x/Monthly-AE-July-2026.csv", "Monthly-AE-July-2026.csv", date(2026, 7, 1))
    r2 = _ref("https://x/Monthly-AE-July-2026-revised-13.11.26.csv",
              "Monthly-AE-July-2026-revised-13.11.26.csv", date(2026, 7, 1), True, date(2026, 11, 13))

    # snapshot 1: original file
    s = FakeSession({r1.url: b"a,b\n1,2\n"})
    w = download_refs([r1], snapshot=date(2026, 9, 10), raw_dir=raw, manifest_path=manifest, session=s)
    assert w[0]["stored"] is True
    assert (raw / "2026-09-10" / r1.filename).exists()

    # snapshot 2: same bytes again -> not stored twice
    w = download_refs([r1], snapshot=date(2026, 10, 8), raw_dir=raw, manifest_path=manifest, session=s)
    assert w[0]["stored"] is False and "identical_to" in w[0]
    assert not (raw / "2026-10-08").exists()

    # snapshot 3: revised file with different bytes -> stored
    s = FakeSession({r2.url: b"a,b\n1,3\n"})
    w = download_refs([r2], snapshot=date(2026, 11, 13), raw_dir=raw, manifest_path=manifest, session=s)
    assert w[0]["stored"] is True

    m = read_manifest(manifest)
    assert len(m) == 3

    # as-of semantics: before the revision we should get the original
    assert latest_stored_per_period(m, as_of=date(2026, 10, 31))["2026-07"]["filename"] == r1.filename
    assert latest_stored_per_period(m)["2026-07"]["filename"] == r2.filename
