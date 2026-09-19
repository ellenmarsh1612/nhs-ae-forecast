"""Network-free tests for link parsing on a synthetic year page."""
from datetime import date

from nhs_ae.ingest.discover import extract_file_refs, is_mapping_link, parse_link

FY = "2025-26"
BASE = "https://www.england.nhs.uk/statistics/statistical-work-areas/ae-waiting-times-and-activity/ae-attendances-and-emergency-admissions-2025-26/"

HTML = """
<html><body>
<h3>Monthly A&E data</h3>
<ul>
<li><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/05/Monthly-AE-March-2026-revised-14.05.26.csv">Monthly A&amp;E March 2026 (revised 14.05.26) (CSV, 29KB)</a></li>
<li><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/04/Monthly-AE-March-2026.xls">Monthly A&amp;E March 2026 (XLS, 430KB)</a></li>
<li><a href="/statistics/wp-content/uploads/sites/2/2026/03/Monthly-AE-February-2026.csv">Monthly A&amp;E February 2026 (CSV, 29KB)</a></li>
<li><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/05/Monthly-AE-Time-Series-March-2026.xls">Monthly A&amp;E Time Series March 2026 (XLS, 1MB)</a></li>
<li><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/05/Statistical-commentary-March-2026.pdf">Statistical commentary</a></li>
<li><a href="https://www.england.nhs.uk/statistics/wp-content/uploads/sites/2/2026/05/Quarterly-AE-Q4-2025-26.csv">Quarterly A&amp;E Q4 2025-26 (CSV)</a></li>
</ul>
</body></html>
"""


def test_extract_file_refs_filters_and_parses():
    refs = extract_file_refs(HTML, FY, base_url=BASE)
    names = [r.filename for r in refs]
    assert names == [
        "Monthly-AE-March-2026-revised-14.05.26.csv",
        "Monthly-AE-March-2026.xls",
        "Monthly-AE-February-2026.csv",
    ]
    march_csv = refs[0]
    assert march_csv.period == date(2026, 3, 1)
    assert march_csv.revised is True
    assert march_csv.revised_on == date(2026, 5, 14)
    assert march_csv.ext == "csv"
    feb = refs[2]
    assert feb.url.startswith("https://www.england.nhs.uk/")  # relative href resolved
    assert feb.revised is False and feb.revised_on is None


def test_parse_link_rejects_non_data_links():
    assert parse_link("https://x/Monthly-AE-Time-Series-March-2026.xls", "Monthly A&E Time Series March 2026", FY) is None
    assert parse_link("https://x/page.html", "Monthly A&E March 2026", FY) is None
    assert parse_link("https://x/Monthly-AE-Smarch-2026.csv", "Monthly A&E Smarch 2026", FY) is None


def test_mapping_links_go_to_icb_mapping_not_the_monthly_parser():
    """A link is a monthly file or a mapping/attribution file, never both."""
    up = "https://x/uploads/sites/2/"
    mapping = [(up + "2024/04/March-2024-System-Mapping.xls", "System Mapping File (XLS, 71K)"),
               (up + "2023/02/Trust-ICB-Attribution-File.xls", "System Mapping File (XLS, 71K)"),
               (up + "2026/08/Acute-Trust-Attribution-File.xls", "Type 3 Trust Attribution File")]
    for href, text in mapping:
        assert is_mapping_link(href, text) and parse_link(href, text, FY) is None
    monthly = (up + "2026/04/Monthly-AE-March-2026.csv", "Monthly A&E March 2026 (CSV, 29KB)")
    assert parse_link(*monthly, FY) is not None and not is_mapping_link(*monthly)
    assert not is_mapping_link(up + "2026/04/Mapping-note.pdf", "Mapping note (PDF)")


def test_revision_from_filename_only():
    ref = parse_link("https://x/Monthly-AE-July-2025-revised-13.11.25.csv", "download", FY)
    assert ref.period == date(2025, 7, 1)
    assert ref.revised_on == date(2025, 11, 13)


def test_label_year_typo_is_overridden_by_filename_within_financial_year():
    """NHS England's 2015-16 page labels September 2015 as 'September 2016'."""
    ref = parse_link("https://x/uploads/sites/2/2015/08/September-2015-AE-by-provider-MyuJm.xls",
                     "Monthly A&E September 2016 (XLS, 117K) (Revised 12.05.2016)", "2015-16")
    assert ref.period == date(2015, 9, 1)
    # a consistent label is left alone even though the filename could parse differently
    ref = parse_link("https://x/uploads/sites/2/2020/08/Monthly-AE-July-2019-revised-210720-cd305.csv",
                     "Monthly A&E July 2019 (revised 13.08.20) (CSV, 29KB)", "2019-20")
    assert ref.period == date(2019, 7, 1)
