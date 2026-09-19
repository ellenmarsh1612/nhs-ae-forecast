"""Provider lineage: which ODS codes succeeded which.

Trust mergers are the main source of genuine cold-start series in this dataset. A merged
trust gets a new (or surviving) code and its history is split across predecessors. We
resolve this with the ODS Organisation Data Service API, which exposes ``Succs``
(successor/predecessor links) for each organisation.

API: https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/{code}

The network call is isolated in ``fetch_org``; everything else is pure so it can be
tested from a cached JSON dump (``data/processed/ods_cache.json``).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from nhs_ae.config import PROCESSED_DIR

log = logging.getLogger(__name__)

ODS_BASE = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations/"
CACHE_PATH = PROCESSED_DIR / "ods_cache.json"


@dataclass(frozen=True)
class Succession:
    predecessor: str
    successor: str
    effective: date | None
    kind: str  # "Successor" | "Predecessor" as reported by ODS


def fetch_org(code: str, session: requests.Session | None = None, timeout: int = 30) -> dict:
    sess = session or requests.Session()
    resp = sess.get(f"{ODS_BASE}{code}", timeout=timeout, headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


def load_cache(path: Path = CACHE_PATH) -> dict[str, dict]:
    return json.loads(path.read_text()) if path.exists() else {}


def save_cache(cache: dict[str, dict], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=1))


def successions_from_record(code: str, record: dict) -> list[Succession]:
    """Extract succession links from one ODS organisation record (pure)."""
    org = record.get("Organisation", record)
    out: list[Succession] = []
    for s in org.get("Succs", {}).get("Succ", []):
        target = s.get("Target", {}).get("OrgId", {}).get("extension")
        kind = s.get("Type", "")
        eff = None
        for d in s.get("Date", []):
            if d.get("Type") == "Legal" and d.get("Start"):
                eff = date.fromisoformat(d["Start"])
        if not target:
            continue
        if kind == "Successor":
            out.append(Succession(predecessor=code, successor=target, effective=eff, kind=kind))
        elif kind == "Predecessor":
            out.append(Succession(predecessor=target, successor=code, effective=eff, kind=kind))
    return out


def build_lineage(codes: list[str], cache: dict[str, dict] | None = None,
                  session: requests.Session | None = None,
                  fetch: bool = True) -> tuple[list[Succession], dict[str, dict]]:
    """Resolve successions for all codes, using/updating the cache.

    Returns (successions, cache). Set ``fetch=False`` to work purely from cache.
    """
    cache = cache if cache is not None else load_cache()
    succs: list[Succession] = []
    for code in sorted(set(codes)):
        if code not in cache:
            if not fetch:
                continue
            try:
                cache[code] = fetch_org(code, session)
            except requests.RequestException as e:
                log.warning("ODS lookup failed for %s: %s", code, e)
                continue
        succs.extend(successions_from_record(code, cache[code]))
    # de-duplicate (a merger appears from both sides)
    uniq = {(s.predecessor, s.successor): s for s in succs}
    return list(uniq.values()), cache


def canonical_code_map(successions: list[Succession]) -> dict[str, str]:
    """Map every predecessor to its *final* successor (follows chains)."""
    nxt = {s.predecessor: s.successor for s in successions}
    out: dict[str, str] = {}
    for start in nxt:
        cur, hops = start, 0
        while cur in nxt and hops < 20:
            cur = nxt[cur]
            hops += 1
        out[start] = cur
    return out
