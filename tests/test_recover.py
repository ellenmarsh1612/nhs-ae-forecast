"""Vintage recovery: pure helpers, dating rules, and an end-to-end run against fakes."""
from datetime import date
from pathlib import Path

from nhs_ae.ingest.discover import FileRef
from nhs_ae.ingest.download import latest_stored_per_period, read_manifest
from nhs_ae.ingest.recover import (
    _PAGE_PREFIX,
    _UPLOAD_PREFIX,
    PageCapture,
    Sighting,
    Wayback,
    assign_available_from,
    collect_sightings,
    coverage,
    publication_date,
    recover,
    second_thursday,
    wayback_digest,
)

FY = "2019-20"
PAGE = ("https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/"
        "ae-attendances-and-emergency-admissions-2019-20/")
UP = "https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/"
ORIG = UP + "2020/01/December-2019-CSV-hjd8h.csv"
REV = UP + "2020/08/Monthly-AE-December-2019-revised-220720-fd675.csv"
OLD = UP + "2016/06/April-2016-AE-by-provider-1Ez1q.xls"  # replaced in place


def _page(links):
    lis = "".join(f'<li><a href="{u}">{t}</a></li>' for u, t in links)
    return f"<html><body><ul>{lis}</ul></body></html>"


def test_second_thursday_matches_known_publication_dates():
    assert second_thursday(2017, 5) == date(2017, 5, 11)    # "(Revised 11/05/2017)"
    assert second_thursday(2017, 9) == date(2017, 9, 14)    # "(Revised 14/09/2017)"
    assert second_thursday(2026, 5) == date(2026, 5, 14)    # "(revised 14.05.26)"
    assert publication_date(date(2026, 7, 1)) == date(2026, 8, 13)


def test_wayback_digest_is_base32_sha1():
    assert wayback_digest(b"") == "3I42H3S6NNFQ2MSVX7XZKYAYSCX5QBYJ"


def _sighting(url, first_seen, revised=()):
    ref = FileRef(url=url, filename=url.rsplit("/", 1)[-1], period=date(2019, 12, 1), ext="csv",
                  financial_year=FY, link_text="x", revised=bool(revised),
                  revised_on=min(revised) if revised else None)
    return Sighting(ref=ref, first_seen=first_seen, last_seen=first_seen,
                    revised_dates=sorted(revised))


def test_assign_available_from_rules():
    # original, seen on the page a week after publication, live copy observed today
    s = _sighting(ORIG, date(2020, 1, 17))
    assert assign_available_from(s, [date(2026, 9, 8)]) == [(date(2020, 1, 9), "upload_month_second_thursday")]
    # revised file with a stated date wins over the upload month
    s = _sighting(REV, date(2020, 9, 1), revised=[date(2020, 8, 13)])
    assert assign_available_from(s, [date(2026, 9, 8)]) == [(date(2020, 8, 13), "stated_revision_date")]
    # in-place replacement: two content versions, one captured before the revision, one after
    s = _sighting(OLD, date(2016, 7, 1), revised=[date(2017, 5, 11)])
    got = assign_available_from(s, [date(2016, 8, 3), date(2023, 10, 11)])
    assert got == [(date(2016, 6, 9), "upload_month_second_thursday"),
                   (date(2017, 5, 11), "stated_revision_date")]
    # two versions with no event between them: the second gets its observation date
    s = _sighting(ORIG, date(2020, 1, 17))
    got = assign_available_from(s, [date(2020, 2, 1), date(2020, 3, 1)])
    assert got[1] == (date(2020, 3, 1), "observed_upper_bound")


def test_collect_sightings_unions_urls_and_labels():
    c1 = PageCapture(FY, "20200117000000", PAGE, "d1")
    c2 = PageCapture(FY, "20200901000000", PAGE, "d2")
    p1 = _page([(ORIG, "Monthly A&E December 2019 (CSV, 29KB)")])
    p2 = _page([(REV, "Monthly A&E December 2019 (revised 13.08.20) (CSV, 29KB)")])
    s = collect_sightings([(c2, p2), (c1, p1)], FY)
    assert set(s) == {ORIG, REV}
    assert s[ORIG].first_seen == date(2020, 1, 17) and s[ORIG].revised_dates == []
    assert s[REV].first_seen == date(2020, 9, 1) and s[REV].revised_dates == [date(2020, 8, 13)]


# ---- end-to-end with fakes ------------------------------------------------------------
class _Resp:
    def __init__(self, content=b"", status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code), response=self)


class FakeWaybackSession:
    """Routes CDX queries (keyed by their ``url`` parameter) and raw captures to canned answers."""

    def __init__(self, cdx: dict, raw: dict):
        self.cdx, self.raw = cdx, raw

    def get(self, url, params=None, **kw):
        if url.startswith("https://web.archive.org/cdx"):
            return _Resp(self.cdx.get(params["url"], "").encode())
        return _Resp(self.raw[url]) if url in self.raw else _Resp(b"", 404)


class FakeNhsSession:
    def __init__(self, live: dict):
        self.live = live

    def get(self, url, **kw):
        return _Resp(self.live[url]) if url in self.live else _Resp(b"", 404)


def test_recover_end_to_end(tmp_path: Path):
    raw_dir = tmp_path / "data" / "raw"
    manifest = raw_dir / "manifest.jsonl"
    orig_bytes, rev_bytes = b"orig\n", b"rev\n"
    p1 = _page([(ORIG, "Monthly A&E December 2019 (CSV, 29KB)")])
    p2 = _page([(REV, "Monthly A&E December 2019 (revised 13.08.20) (CSV, 29KB)")])
    wb = Wayback(session=FakeWaybackSession(
        cdx={
            _PAGE_PREFIX: f"20200117000000 {PAGE} d1\n20200901000000 {PAGE} d2\n",
            # bulk file history for the 2020 upload folder: ORIG captured once, REV never
            _UPLOAD_PREFIX + "2020/": f"20200201000000 {ORIG} {wayback_digest(orig_bytes)}\n",
        },
        raw={f"https://web.archive.org/web/20200117000000id_/{PAGE}": p1.encode(),
             f"https://web.archive.org/web/20200901000000id_/{PAGE}": p2.encode(),
             f"https://web.archive.org/web/20200201000000id_/{ORIG}": orig_bytes},
    ), cache_dir=tmp_path / "cache", delay=0)
    NEW = UP + "2020/05/April-2020-CSV-zz9.csv"  # on the live page only
    p_live = _page([(REV, "Monthly A&E December 2019 (revised 13.08.20) (CSV, 29KB)"),
                    (NEW, "Monthly A&E April 2020 (CSV, 29KB)")])
    nhs = FakeNhsSession({ORIG: orig_bytes, REV: rev_bytes, NEW: b"new\n",
                          PAGE: p_live.encode()})  # files still live; live page served too

    summary = recover([FY], wayback=wb, nhs_session=nhs, raw_dir=raw_dir,
                      manifest_path=manifest, today=date(2026, 9, 8))
    assert summary == {"captures": 2, "urls": 3, "skipped": 0, "stored": 3, "duplicates": 0,
                       "failed": 0}
    new = next(r for r in read_manifest(manifest) if r["url"] == NEW)
    assert new["available_from"] == "2020-05-14"  # upload month, not today
    m = read_manifest(manifest)
    orig = next(r for r in m if r["url"] == ORIG)
    rev = next(r for r in m if r["url"] == REV)
    # original: live bytes match the Wayback digest, so fetched from NHS, dated by upload month
    assert orig["fetched_from"] == "nhs" and orig["wayback_timestamp"] == "20200201000000"
    assert orig["available_from"] == "2020-01-09" and orig["available_from_source"] == "upload_month_second_thursday"
    assert (raw_dir / "2020-01-09" / "December-2019-CSV-hjd8h.csv").read_bytes() == orig_bytes
    # revised: no capture, live only, dated by the label
    assert rev["available_from"] == "2020-08-13" and rev["available_from_source"] == "stated_revision_date"
    assert rev["path"].endswith("2020-08-13/Monthly-AE-December-2019-revised-220720-fd675.csv")

    # as-of semantics now work from available_from, not from today's fetch date
    assert latest_stored_per_period(m, as_of=date(2020, 6, 1))["2019-12"]["url"] == ORIG
    assert latest_stored_per_period(m, as_of=date(2021, 1, 1))["2019-12"]["url"] == REV

    # idempotent: a second run skips both URLs
    again = recover([FY], wayback=wb, nhs_session=nhs, raw_dir=raw_dir, manifest_path=manifest,
                    today=date(2026, 9, 8))
    assert again["skipped"] == 3 and again["stored"] == 0

    # coverage: at 2020-06 the Dec-2019 original is available; nothing else is archived,
    # so every other published period is missing
    rows = coverage(m, [date(2020, 6, 1)], first_period=date(2019, 11, 1))
    assert rows[0]["periods_expected"] == 6            # 2019-11 .. 2020-04
    assert rows[0]["missing"] == ["2019-11", "2020-01", "2020-02", "2020-03"]  # 2020-04 came from the live page
    # at the loader's as-of date (the second Thursday, as `nhs-ae-ingest coverage` dates it),
    # 2020-05 has been published too, and nothing holds a version of it
    rows = coverage(m, [second_thursday(2020, 6)], first_period=date(2019, 11, 1))
    assert rows[0]["origin"] == "2020-06" and rows[0]["periods_expected"] == 7
    assert rows[0]["missing"] == ["2019-11", "2020-01", "2020-02", "2020-03", "2020-05"]


def test_recover_in_place_replacement_recovers_both_versions(tmp_path: Path):
    """Old XLS replaced at the same URL: two Wayback digests, live == latest."""
    raw_dir = tmp_path / "data" / "raw"
    manifest = raw_dir / "manifest.jsonl"
    v1, v2 = b"xls-v1", b"xls-v2"
    fy, page = "2016-17", PAGE.replace("2019-20", "2016-17")
    p1 = _page([(OLD, "Monthly A&E April 2016 (XLS, 117K)")])
    p2 = _page([(OLD, "Monthly A&E April 2016 (XLS, 117K) (Revised 11/05/2017)")])
    wb = Wayback(session=FakeWaybackSession(
        cdx={_PAGE_PREFIX: f"20160701000000 {page} a\n20170801000000 {page} b\n",
             _UPLOAD_PREFIX + "2016/": (f"20160803000000 {OLD} {wayback_digest(v1)}\n"
                                        f"20231011000000 {OLD} {wayback_digest(v2)}\n")},
        raw={f"https://web.archive.org/web/20160701000000id_/{page}": p1.encode(),
             f"https://web.archive.org/web/20170801000000id_/{page}": p2.encode(),
             f"https://web.archive.org/web/20160803000000id_/{OLD}": v1},
    ), cache_dir=tmp_path / "cache", delay=0)
    nhs = FakeNhsSession({OLD: v2})
    summary = recover([fy], wayback=wb, nhs_session=nhs, raw_dir=raw_dir, manifest_path=manifest,
                      today=date(2026, 9, 8))
    assert summary["stored"] == 2
    m = read_manifest(manifest)
    a, b = sorted((r for r in m if r["stored"]), key=lambda r: r["available_from"])
    assert a["available_from"] == "2016-06-09" and a["fetched_from"] == "wayback"
    assert b["available_from"] == "2017-05-11" and b["fetched_from"] == "nhs"
    assert latest_stored_per_period(m, as_of=date(2017, 1, 1))["2016-04"]["sha256"] == a["sha256"]
