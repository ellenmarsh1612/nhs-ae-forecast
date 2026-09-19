"""Provider → ICB → region → England hierarchy.

NHS England's ``Parent Org`` column has changed vocabulary three times (four
commissioning regions to March 2018, sub-regional labels to 2020, the seven current
regions since, with inconsistent capitalisation throughout). A provider is therefore
assigned to its *current* region, taken from the most recent file in which it appears.
That is the "restrict the hierarchy to the current mapping" option pre-registered in
section 9, and it is a deliberate, flagged departure from strict as-of purity: the
mapping itself is not reconstructed per origin. Providers that disappeared before the
seven-region era get region ``LEGACY``.

ICB level (``current_icb_map``): each provider gets its ICB in NHS England's latest
"System Mapping File" (``nhs_ae.ingest.icb_mapping``), the same current-mapping
simplification. Since April 2026 that file has **36** ICBs, not the 42 of the
pre-registration; ``load_reference("2025-26")`` gives the 42. Codes absent from the file
(mostly trusts that merged before 2023) take the derived backfill assignment, and whatever
is left goes to ``UNMAPPED``. The ICB map and the region map come from different sources
and are not forced to nest; ``icb_mapping check`` lists the providers where they disagree.
"""

from __future__ import annotations

import re

import pandas as pd

REGIONS: tuple[str, ...] = (
    "EAST OF ENGLAND", "LONDON", "MIDLANDS", "NORTH EAST AND YORKSHIRE",
    "NORTH WEST", "SOUTH EAST", "SOUTH WEST",
)
LEGACY = "LEGACY"
UNMAPPED = "UNMAPPED"   # ICB level: provider code in no mapping and not backfilled
ENGLAND = "ENGLAND"
_PAREN = re.compile(r"\(.*?\)")


def normalise_region(label: str | None) -> str:
    """'NHS England Midlands (West Midlands)' -> 'MIDLANDS'; unknown labels -> LEGACY."""
    if not label or (isinstance(label, float) and pd.isna(label)):
        return LEGACY
    s = _PAREN.sub("", str(label)).upper().replace("NHS ENGLAND", "").strip(" -")
    s = re.sub(r"\s+", " ", s)
    return s if s in REGIONS else LEGACY


def current_region_map(rows: pd.DataFrame) -> pd.Series:
    """org_code -> region, using each provider's most recent ``parent_org``.

    ``rows`` needs columns period, org_code, parent_org, is_total (any long table from
    the ingest stage will do).
    """
    prov = rows.loc[~rows["is_total"], ["period", "org_code", "parent_org"]].dropna(subset=["org_code"])
    latest = prov.sort_values("period").drop_duplicates("org_code", keep="last")
    return latest.set_index("org_code")["parent_org"].map(normalise_region).rename("region")


def _code_key(codes) -> pd.Index:
    """Match codes case- and space-insensitively: the mapping has 'NTV0b', the data 'NTV0B'."""
    return pd.Index(codes).astype(str).str.strip().str.upper()


def current_icb_map(rows: pd.DataFrame | None = None, mapping: pd.DataFrame | None = None,
                    field: str = "icb_code") -> pd.Series:
    """org_code -> ICB (``field`` = ``icb_code`` or ``icb_name``).

    ``mapping`` needs columns org_code and ``field``; by default it is the current NHS
    England mapping plus its backfill (``icb_mapping.load_reference()``). Given ``rows`` (a
    long table as for ``current_region_map``), the result is indexed by every provider
    code in it, spelled as in the data, and codes absent from the mapping get ``UNMAPPED``.
    Without ``rows`` it is the mapping itself.
    """
    if mapping is None:
        from nhs_ae.ingest.icb_mapping import load_reference  # avoids an import cycle
        mapping = load_reference()
    m = mapping.drop_duplicates("org_code")
    lookup = pd.Series(m[field].to_numpy(), index=_code_key(m["org_code"]))
    if rows is None:
        return lookup.rename_axis("org_code").rename("icb")
    codes = rows.loc[~rows["is_total"], "org_code"].dropna().unique()
    out = lookup.reindex(_code_key(codes)).fillna(UNMAPPED).to_numpy()
    return pd.Series(out, index=pd.Index(codes, name="org_code"), name="icb")


def icb_region_map(mapping: pd.DataFrame | None = None) -> pd.Series:
    """icb_code -> region, from the mapping (the ICB → region level of the hierarchy)."""
    if mapping is None:
        from nhs_ae.ingest.icb_mapping import load_reference
        mapping = load_reference()
    return mapping.drop_duplicates("icb_code").set_index("icb_code")["region"].rename("region")
