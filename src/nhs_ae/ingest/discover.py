"""Discover monthly A&E file links on the NHS England statistics pages.

Two responsibilities, kept separate so the parsing half is unit-testable without network:

1. ``fetch_year_page`` – download the HTML for one financial-year page.
2. ``extract_file_refs`` / ``parse_link`` – turn anchor tags into ``FileRef`` records that
   carry the period the file covers, whether it is a revised re-publication, and the
   revision date if one is stated in the link text or filename.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from nhs_ae.config import FINANCIAL_YEARS, MONTHS, year_page_url

log = logging.getLogger(__name__)

USER_AGENT = "nhs-ae-forecast/0.1 (+https://github.com/; research; contact via repo)"

# "Monthly A&E March 2026 (revised 14.05.26) (CSV, 29KB)"
# "Monthly-AE-March-2026-revised-14.05.26.csv"
_MONTH_RE = re.compile(
    r"monthly[\s\-_]*a&?e[\s\-_]*(?P<month>[a-z]+)[\s\-_]*(?P<year>20\d\d)",
    re.IGNORECASE,
)
# "September-2015-AE-by-provider-MyuJm.xls", "December-2019-CSV-hjd8h.csv"
_FILENAME_MONTH_RE = re.compile(r"(?<![a-z])(?P<month>[a-z]+)[\s\-_]*(?P<year>20\d\d)", re.IGNORECASE)
_REVISED_RE = re.compile(r"revised[\s\-_]*(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})[.\-/](?P<y>\d{2,4})", re.IGNORECASE)
_EXT_RE = re.compile(r"\.(?P<ext>csv|xlsx?|xlsm)(\?.*)?$", re.IGNORECASE)

# Spreadsheets that share the year page but are not monthly provider files. The
# provider-to-system mapping ("System Mapping File") and the Type 3 attribution workbook
# are ingested by ``nhs_ae.ingest.icb_mapping``; the rest are out of scope.
MAPPING_KEYWORDS: tuple[str, ...] = ("mapping", "attribution")
_NON_MONTHLY_KEYWORDS: tuple[str, ...] = (
    "time series", "timeseries", "quarter", "non-elective", "non elective", "ecds",
    "commentary", *MAPPING_KEYWORDS)


def is_mapping_link(href: str, text: str) -> bool:
    """True for a mapping/attribution spreadsheet link (routed to ``icb_mapping``)."""
    if not href or not _EXT_RE.search(href.split("#", 1)[0]):
        return False
    lowered = (text + " " + href.rsplit("/", 1)[-1]).lower()
    return any(k in lowered for k in MAPPING_KEYWORDS)


@dataclass(frozen=True)
class FileRef:
    """One downloadable monthly file as advertised on an NHS England page."""

    url: str
    filename: str
    period: date  # first day of the month the data covers
    ext: str  # csv | xls | xlsx
    financial_year: str
    link_text: str
    revised: bool = False
    revised_on: date | None = None
    extra: dict = field(default_factory=dict)

    @property
    def period_label(self) -> str:
        return self.period.strftime("%Y-%m")


def _parse_revised(text: str) -> date | None:
    m = _REVISED_RE.search(text)
    if not m:
        return None
    d, mo, y = int(m["d"]), int(m["m"]), int(m["y"])
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        log.warning("Unparseable revision date in %r", text)
        return None


def _period_from(s: str, rx: re.Pattern) -> date | None:
    m = rx.search(s)
    if not m or m["month"].lower() not in MONTHS:
        return None
    return date(int(m["year"]), MONTHS[m["month"].lower()], 1)


def _in_financial_year(period: date, financial_year: str) -> bool:
    """Financial year 'YYYY-YY' runs April YYYY to March YYYY+1."""
    try:
        start = int(financial_year[:4])
    except ValueError:
        return True  # unknown label: don't second-guess
    return date(start, 4, 1) <= period <= date(start + 1, 3, 1)


def parse_link(href: str, text: str, financial_year: str, base_url: str = "") -> FileRef | None:
    """Return a FileRef if this anchor looks like a monthly A&E data file, else None.

    Pure function – no network – so it is covered by unit tests.
    """
    if not href:
        return None
    url = urljoin(base_url, href)
    ext_m = _EXT_RE.search(url)
    if not ext_m:
        return None
    ext = ext_m["ext"].lower()
    filename = url.rsplit("/", 1)[-1].split("?", 1)[0]

    # Prefer the link text for month/year (it is the human-facing label); fall back to the
    # filename. When both parse but disagree, trust whichever lies inside the financial
    # year: NHS England's 2015-16 page labels September–December 2015 as "2016".
    candidates = [_period_from(text, _MONTH_RE), _period_from(filename, _MONTH_RE),
                  _period_from(filename, _FILENAME_MONTH_RE)]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    period = candidates[0]
    if len(candidates) > 1 and not _in_financial_year(period, financial_year):
        for c in candidates[1:]:
            if _in_financial_year(c, financial_year):
                log.warning("%s: label says %s but filename says %s; using filename",
                            filename, period, c)
                period = c
                break

    revised_on = _parse_revised(text) or _parse_revised(filename)
    revised = revised_on is not None or "revised" in (text + filename).lower()

    # Skip time-series / quarterly / non-elective / ECDS workbooks that share the page, and
    # the mapping/attribution workbooks (see ``is_mapping_link``).
    lowered = (text + " " + filename).lower()
    if any(k in lowered for k in _NON_MONTHLY_KEYWORDS):
        return None

    return FileRef(
        url=url,
        filename=filename,
        period=period,
        ext=ext,
        financial_year=financial_year,
        link_text=text.strip(),
        revised=revised,
        revised_on=revised_on,
    )


def extract_file_refs(html: str, financial_year: str, base_url: str = "") -> list[FileRef]:
    """Parse a year page and return every monthly file link found."""
    soup = BeautifulSoup(html, "lxml")
    refs: list[FileRef] = []
    for a in soup.find_all("a", href=True):
        ref = parse_link(a["href"], a.get_text(" ", strip=True), financial_year, base_url)
        if ref:
            refs.append(ref)
    # De-duplicate on URL while keeping first occurrence order.
    seen: set[str] = set()
    out = []
    for r in refs:
        if r.url not in seen:
            seen.add(r.url)
            out.append(r)
    return out


def fetch_year_page(financial_year: str, session: requests.Session | None = None,
                    timeout: int = 60) -> str:
    sess = session or requests.Session()
    url = year_page_url(financial_year)
    resp = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def discover(financial_years: Iterable[str] = FINANCIAL_YEARS,
             prefer_ext: str = "csv",
             session: requests.Session | None = None) -> list[FileRef]:
    """Discover monthly files across the requested financial years.

    When both CSV and XLS versions of the same period exist, keep ``prefer_ext`` and
    only fall back to the other format if the preferred one is absent (older years
    sometimes only offer XLS).
    """
    sess = session or requests.Session()
    refs: list[FileRef] = []
    for fy in financial_years:
        try:
            html = fetch_year_page(fy, sess)
        except requests.HTTPError as e:  # a future year page may not exist yet
            log.warning("Skipping %s: %s", fy, e)
            continue
        found = extract_file_refs(html, fy, base_url=year_page_url(fy))
        log.info("%s: %d monthly file links", fy, len(found))
        refs.extend(found)

    by_period: dict[date, list[FileRef]] = {}
    for r in refs:
        by_period.setdefault(r.period, []).append(r)
    chosen: list[FileRef] = []
    for period, group in sorted(by_period.items()):
        preferred = [g for g in group if g.ext == prefer_ext]
        chosen.extend(preferred or group[:1])
    return chosen
