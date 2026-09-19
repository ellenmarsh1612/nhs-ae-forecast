"""Stage H statistics primitives (design §7.2-§7.5, §7.13). Pure functions on scored frames.

CONTRACT (skeleton; the implementation must keep these signatures):

compare(ref, tested, metric="wis", keys=K5, n=N_BOOT, seed=SEED) -> dict
    The one two-forecast comparison (§7.2): ``metrics.paired_bootstrap(a=ref, b=tested,
    metric, unit="series", n, seed, keys)``. Asserts each frame holds one model, one mode and
    one level (when those columns exist) and unique ``keys``. Returns paired_bootstrap's dict
    (n_units, n_pairs, diff, diff_lo, diff_hi, rel, rel_lo, rel_hi) plus n_ref and n_tested
    (rows with a non-NaN metric), unpaired_ref, unpaired_tested, and evaluable (False, with
    NaN statistics, when the join is empty).

origin_units(origins, fold) -> dict[pd.Timestamp, pd.Timestamp]
    Map each origin to its bootstrap unit: itself, or fold[origin] (D7: 2025-08/09 -> 2025-07).

@dataclass Draws: series (list), units (list of unit labels, calendar order),
    W (n x S int multiplicities), V (n x U int multiplicities); optional starts (n x k) and
    slots (n x U), the moving blocks behind V.
make_draws(series, units, n=N_BOOT, seed=SEED, block=BLOCK) -> Draws
    §7.4: rng = default_rng(seed); series indices first (n x S, uniform with replacement,
    turned into multiplicities W), then Kuensch moving-block starts (n x k, uniform on
    0..U-l, l = min(block, U), k = ceil(U / l)); slots = start + 0..l-1, concatenated and
    truncated to U, turned into multiplicities V. U == 0 or S == 0 -> ValueError.

two_way(rows, cells, stat, draws, unit_of, series_col="series") -> DataFrame
    Row-weighted two-way bootstrap of the share ``rows[stat]`` (boolean) per cell (§7.4).
    ``cells``: columns defining a cell (e.g. ["horizon"] or ["model", "target", "horizon"]).
    ``unit_of``: origin -> unit (origin_units). For each cell: K[s,u] covered rows, N[s,u]
    scored rows; resample b: sum(W[b,s] V[b,u] K) / sum(W[b,s] V[b,u] N). One row per cell with
    point (row-weighted share, unrounded), lo, hi (2.5/97.5 percentiles, numpy linear),
    lo_within, hi_within (same W, V = 1), boot_mean_minus_point, n_rows, n_series, n_units
    (origin units with rows in the cell), zero_den (resamples dropped; zero_den_within for
    the within-period ones), degenerate (n_units < 3: lo/hi set to lo_within/hi_within and
    flagged). Keyword ``partial=False``: a series or unit in the draws without a row in the
    table raises (draws are built from the series and origin units present, §7.4), and so
    does an empty table; True for a per-model call on a table's shared draws (an empty table
    then gives an empty frame). A frame holding more than one model, mode or level outside
    ``cells``, or duplicate rows on (series_col, target, origin, horizon, *cells), raises
    (§7.1).

two_way_diff(rows_a, rows_b, cells, stat, draws, unit_of, series_col="series") -> DataFrame
    Paired difference of shares, b - a, per cell, using the same draws for both (e.g. pooled
    minus raw in the headline). Columns: point, lo, hi, lo_within, hi_within,
    boot_mean_minus_point, n_units (the smaller side's), zero_den, zero_den_within,
    degenerate. ``partial`` as in two_way, over the rows of both frames (both empty raises
    unless partial); the slice and duplicate checks apply to each frame.

band_status(x, band=BAND) -> "inside" | "under" | "over"  (inclusive edges, unrounded)
crosses(lo, hi, band=BAND) -> bool   True if [lo, hi] contains either band edge.

verdict_primary(tab) -> dict
    tab: one row per horizon with lo, hi. {"verdict": "within tolerance" | "outside tolerance"
    | "inconclusive", "outside": {h: "under"|"over"}}  (§7.5).
verdict_h2_m1(tab) -> dict
    tab: per horizon point, lo, hi. Point estimates decide (confirmed / refuted / neither),
    "directions": {h: status}, "crossings": {h: bool}, "fragile": per the §7.5 table.
verdict_h2_m2(tab, evaluable=True) -> dict   likewise (confirmed / refuted / not evaluable).

range_fragile(values, threshold) -> bool   min(values) <= threshold <= max(values), inclusive;
    False for fewer than 2 values; a NaN value raises.
loo(fn, rows, origins) -> DataFrame
    Leave-one-origin-out: for each o in origins, fn(rows[rows.origin != o]) -> dict; returns
    one row per dropped origin (column "dropped"). Fewer than 2 origins -> empty frame. An
    origin without rows raises: pass the origins present in the slice.
season(period) -> str   DEV winter season label: "2018/19" for Dec 2018..Mar 2019.
dev_range(values) -> tuple[float, float]   (min, max), NaN-safe.
outside(x, lo, hi) -> bool
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from nhs_ae.evaluate.metrics import paired_bootstrap
from nhs_ae.evaluate.stage_h.common import BAND, BLOCK, K5, N_BOOT, SEED

# Copies of models.base.HORIZONS and harness.WINTER_MONTHS: importing either pulls in the
# forecasting models. A test checks they agree.
HORIZONS: tuple[int, ...] = tuple(range(1, 7))
WINTER_MONTHS: tuple[int, ...] = (12, 1, 2, 3)
MIN_UNITS = 3               # fewer contributing origin units: the cell is origin-degenerate
H2_LATE = 4                 # H2's M1 clause: horizons >= 4 decide "confirmed"
_STATS = ("diff", "diff_lo", "diff_hi", "rel", "rel_lo", "rel_hi")
_SLICES = ("model", "mode", "level")     # one value per frame unless a cell (§7.1, §7.2)
_CHUNK = 1 << 24            # float64 cap per resampling product (128 MB)


def _one_slice(f: pd.DataFrame, side: str, keys: list[str], cells: Iterable[str] = ()) -> None:
    """Refuse a frame holding more than one model, mode or level outside ``cells``, or
    duplicate rows on ``keys``: either would be pooled or counted twice without trace."""
    cells = list(cells)
    for col in _SLICES:
        if col in f.columns and col not in cells and f[col].nunique(dropna=False) > 1:
            where = f" outside the cells {cells}" if cells else ""
            raise ValueError(f"{side} frame holds {f[col].nunique(dropna=False)} {col}s{where}")
    dup = int(f.duplicated(keys).sum())
    if dup:
        raise ValueError(f"{side} frame has {dup} duplicate rows on {tuple(keys)}")


# ---- two-forecast comparisons (§7.2) -----------------------------------------------------
def compare(ref: pd.DataFrame, tested: pd.DataFrame, metric: str = "wis",
            keys: tuple[str, ...] = K5, n: int = N_BOOT, seed: int = SEED) -> dict:
    """Reference ``ref`` against ``tested``, bootstrap over series; negative rel means the
    tested forecast is better. Raises ValueError on a frame holding more than one model, mode
    or level, or with duplicate ``keys``."""
    keys = tuple(keys)
    for side, f in (("reference", ref), ("tested", tested)):
        _one_slice(f, side, list(keys))
    res = paired_bootstrap(ref, tested, metric=metric, unit="series", n=n, seed=seed, keys=keys)
    n_pairs = int(res.get("n_pairs", 0))
    n_ref, n_tested = int(ref[metric].notna().sum()), int(tested[metric].notna().sum())
    return {"n_units": int(res["n_units"]), "n_pairs": n_pairs,
            **{k: float(res.get(k, np.nan)) for k in _STATS},
            "n_ref": n_ref, "n_tested": n_tested,
            "unpaired_ref": n_ref - n_pairs, "unpaired_tested": n_tested - n_pairs,
            "evaluable": res["n_units"] > 0}


# ---- two-way coverage bootstrap (§7.4) ---------------------------------------------------
def origin_units(origins: Iterable, fold: Mapping | None) -> dict[pd.Timestamp, pd.Timestamp]:
    """Each origin's bootstrap unit: itself, or ``fold[origin]`` (D7)."""
    f = {pd.Timestamp(k): pd.Timestamp(v) for k, v in (fold or {}).items()}
    return {o: f.get(o, o) for o in map(pd.Timestamp, origins)}


@dataclass
class Draws:
    """One table's resampling draws. ``starts`` (n x k) and ``slots`` (n x U) record the
    moving blocks behind V; the statistics use only W and V."""
    series: list
    units: list
    W: np.ndarray
    V: np.ndarray
    starts: np.ndarray | None = None
    slots: np.ndarray | None = None


def _multiplicities(idx: np.ndarray, m: int) -> np.ndarray:
    """Row-wise counts of 0..m-1 in an index matrix, as an (n x m) int matrix."""
    n = idx.shape[0]
    flat = (idx + m * np.arange(n)[:, None]).ravel()
    return np.bincount(flat, minlength=n * m).reshape(n, m)


def _block_slots(starts: np.ndarray, n_units: int, length: int) -> np.ndarray:
    """Slots start + 0..length-1 of each block, concatenated per row and truncated to n_units."""
    return (starts[..., None] + np.arange(length)).reshape(len(starts), -1)[:, :n_units]


def make_draws(series: Iterable, units: Iterable, n: int = N_BOOT, seed: int = SEED,
               block: int = BLOCK) -> Draws:
    """Series and origin-unit draws shared by every cell of one table. Series and units are
    de-duplicated and sorted (units into calendar order), so the draws do not depend on row
    order."""
    series, units = sorted(set(series)), sorted(set(map(pd.Timestamp, units)))
    S, U = len(series), len(units)
    if S == 0 or U == 0:
        raise ValueError(f"two-way bootstrap needs series and origin units (S={S}, U={U})")
    if n < 1 or block < 1:
        raise ValueError(f"n={n} and block={block} must be positive")
    rng = np.random.default_rng(seed)
    W = _multiplicities(rng.integers(0, S, size=(n, S)), S)
    length = min(block, U)
    starts = rng.integers(0, U - length + 1, size=(n, -(-U // length)))
    slots = _block_slots(starts, U, length)
    return Draws(series, units, W, _multiplicities(slots, U), starts, slots)


def _prepare(frames: list[pd.DataFrame], cells: list[str], stat: str, draws: Draws,
             unit_of: Mapping, series_col: str, partial: bool = False) -> tuple[pd.DataFrame, list]:
    """Sorted cell keys over all ``frames``, and per frame the C x S x U covered (K) and
    scored (N) row counts. Each frame must hold one model, mode and level outside ``cells``
    and no duplicate rows; unless ``partial``, every series and unit in the draws must have
    a row in some frame."""
    for i, f in enumerate(frames):
        key = [c for c in dict.fromkeys([series_col, "target", "origin", "horizon", *cells])
               if c in f.columns]
        _one_slice(f, f"rows_{'ab'[i]}" if len(frames) > 1 else "rows", key, cells)
    sizes = [len(f) for f in frames]
    if cells:
        both = pd.concat([f[cells] for f in frames], ignore_index=True)
        if both.isna().any().any():
            raise ValueError(f"NaN in cell columns {cells}")
        g = both.groupby(cells, sort=True)
        keys = g.size().index.to_frame(index=False)
        codes = np.split(g.ngroup().to_numpy(), np.cumsum(sizes)[:-1])
    else:
        keys, codes = pd.DataFrame(index=range(1)), [np.zeros(s, dtype=np.int64) for s in sizes]
    uo = pd.Series({pd.Timestamp(k): pd.Timestamp(v) for k, v in unit_of.items()},
                   dtype="datetime64[ns]")
    s_index, u_index = pd.Index(draws.series), pd.DatetimeIndex(draws.units)
    C, S, U = len(keys), len(draws.series), len(draws.units)
    counts = []
    for f, code in zip(frames, codes):
        s = s_index.get_indexer(f[series_col])
        pos = uo.index.get_indexer(pd.DatetimeIndex(f["origin"]))
        if (s < 0).any() or (pos < 0).any():
            raise ValueError(f"{int((s < 0).sum())} rows have a series outside the draws and "
                             f"{int((pos < 0).sum())} an origin without a unit")
        u = u_index.get_indexer(uo.to_numpy()[pos])
        if (u < 0).any():
            raise ValueError(f"{int((u < 0).sum())} rows map to a unit outside the draws")
        k = f[stat].to_numpy()
        if pd.isna(k).any() or not np.isin(k, (0, 1)).all():
            raise ValueError(f"{stat!r} must be boolean, without NaN")
        flat = (code * S + s) * U + u
        K = np.bincount(flat, weights=k.astype(float), minlength=C * S * U).reshape(C, S, U)
        N = np.bincount(flat, minlength=C * S * U).astype(float).reshape(C, S, U)
        counts.append((K, N))
    if not partial:
        tot = sum(N for _, N in counts).sum(axis=0)          # S x U, over frames and cells
        s_none = [draws.series[i] for i in np.flatnonzero(tot.sum(axis=1) == 0)]
        u_none = [f"{draws.units[i]:%Y-%m}" for i in np.flatnonzero(tot.sum(axis=0) == 0)]
        if s_none or u_none:
            raise ValueError("draws must be built from the series and origin units present in "
                             f"the table (§7.4); without rows: series {s_none}, units {u_none}")
    return keys, counts


def _resample(K: np.ndarray, N: np.ndarray, draws: Draws) -> np.ndarray:
    """(4, B, C): numerators and denominators of every resample's share, two-way (W, V), then
    within-period (W, V = 1). All counts are integers, so the float sums are exact."""
    C, S, U = K.shape
    W, V = draws.W.astype(float), draws.V.astype(float)[:, None, :]
    B = len(W)
    out = np.empty((4, B, C))
    step = max(1, _CHUNK // (B * U))
    for i in range(0, C, step):
        j = slice(i, min(i + step, C))
        for m, X in enumerate((K, N)):
            WX = (W @ X[j].transpose(1, 0, 2).reshape(S, -1)).reshape(B, -1, U)
            out[m, :, j] = (WX * V).sum(axis=2)
            out[m + 2, :, j] = WX.sum(axis=2)
    return out


def _ratio(num: np.ndarray, den: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    ok = den > 0
    return num / np.where(ok, den, 1.0), ok


def _interval(r: np.ndarray, ok: np.ndarray) -> tuple[np.ndarray, ...]:
    """Per column of a B x C resample matrix: 2.5 and 97.5 percentiles (numpy linear), mean,
    and the number of dropped (not ok) resamples."""
    lo, hi, mean = (np.full(r.shape[1], np.nan) for _ in range(3))
    for c in range(r.shape[1]):
        v = r[ok[:, c], c]
        if len(v):
            lo[c], hi[c] = np.percentile(v, [2.5, 97.5])
            mean[c] = v.mean()
    return lo, hi, mean, (~ok).sum(axis=0)


def _share(K: np.ndarray, N: np.ndarray) -> np.ndarray:
    tot = N.sum(axis=(1, 2))
    return np.divide(K.sum(axis=(1, 2)), tot, out=np.full(len(tot), np.nan), where=tot > 0)


_TWO_WAY_COLS = ["point", "lo", "hi", "lo_within", "hi_within", "boot_mean_minus_point",
                 "n_rows", "n_series", "n_units", "zero_den", "zero_den_within", "degenerate"]
_DIFF_COLS = ["point", "lo", "hi", "lo_within", "hi_within", "boot_mean_minus_point",
              "n_units", "zero_den", "zero_den_within", "degenerate"]


def _empty(cells: list[str], cols: list[str], partial: bool) -> pd.DataFrame:
    """An empty table leaves every series and unit in the draws without a row (a filter that
    matched nothing), so it raises unless ``partial``."""
    if not partial:
        raise ValueError("empty table: every series and origin unit in the draws is without "
                         "rows (§7.4); pass partial=True for a slice that may be empty")
    return pd.DataFrame(columns=[*cells, *cols])


def two_way(rows: pd.DataFrame, cells: Iterable[str], stat: str, draws: Draws,
            unit_of: Mapping, series_col: str = "series", partial: bool = False) -> pd.DataFrame:
    """Row-weighted two-way interval of ``rows[stat]`` per cell. A frame mixing models, modes
    or levels outside ``cells``, duplicate rows, and rows whose series is not in the draws or
    whose origin has no unit in the draws raise; so, unless ``partial``, do series and units
    in the draws without a row, and an empty table. ``zero_den`` counts the two-way resamples
    dropped (``zero_den_within`` the within-period ones); for a degenerate cell, lo, hi and
    boot_mean_minus_point come from the within-period resamples."""
    cells = list(cells)
    if rows.empty:
        return _empty(cells, _TWO_WAY_COLS, partial)
    keys, [(K, N)] = _prepare([rows], cells, stat, draws, unit_of, series_col, partial)
    num, den, num_w, den_w = _resample(K, N, draws)
    point = _share(K, N)
    lo, hi, mean, zd = _interval(*_ratio(num, den))
    lo_w, hi_w, mean_w, zd_w = _interval(*_ratio(num_w, den_w))
    n_units = (N.sum(axis=1) > 0).sum(axis=1)
    deg = n_units < MIN_UNITS
    return keys.assign(
        point=point, lo=np.where(deg, lo_w, lo), hi=np.where(deg, hi_w, hi),
        lo_within=lo_w, hi_within=hi_w, boot_mean_minus_point=np.where(deg, mean_w, mean) - point,
        n_rows=N.sum(axis=(1, 2)).astype(np.int64), n_series=(N.sum(axis=2) > 0).sum(axis=1),
        n_units=n_units, zero_den=zd, zero_den_within=zd_w, degenerate=deg)


def two_way_diff(rows_a: pd.DataFrame, rows_b: pd.DataFrame, cells: Iterable[str], stat: str,
                 draws: Draws, unit_of: Mapping, series_col: str = "series",
                 partial: bool = False) -> pd.DataFrame:
    """Paired b - a difference of row-weighted shares per cell, on the same draws. A resample
    is dropped when either side's denominator is zero. n_units is the smaller side's count of
    contributing origin units, and a cell below MIN_UNITS is degenerate, as in ``two_way``;
    ``partial`` too, over the rows of both frames, and the slice and duplicate checks, per
    frame."""
    cells = list(cells)
    if rows_a.empty and rows_b.empty:
        return _empty(cells, _DIFF_COLS, partial)
    keys, [(Ka, Na), (Kb, Nb)] = _prepare([rows_a, rows_b], cells, stat, draws, unit_of,
                                          series_col, partial)
    ra, rb = _resample(Ka, Na, draws), _resample(Kb, Nb, draws)
    point = _share(Kb, Nb) - _share(Ka, Na)
    out = []
    for i in (0, 2):
        (xa, oka), (xb, okb) = _ratio(ra[i], ra[i + 1]), _ratio(rb[i], rb[i + 1])
        out.append(_interval(xb - xa, oka & okb))
    (lo, hi, mean, zd), (lo_w, hi_w, mean_w, zd_w) = out
    n_units = np.minimum((Na.sum(axis=1) > 0).sum(axis=1), (Nb.sum(axis=1) > 0).sum(axis=1))
    deg = n_units < MIN_UNITS
    return keys.assign(
        point=point, lo=np.where(deg, lo_w, lo), hi=np.where(deg, hi_w, hi),
        lo_within=lo_w, hi_within=hi_w, boot_mean_minus_point=np.where(deg, mean_w, mean) - point,
        n_units=n_units, zero_den=zd, zero_den_within=zd_w, degenerate=deg)


# ---- coverage verdicts (§7.5) ------------------------------------------------------------
def band_status(x: float, band: tuple[float, float] = BAND) -> str:
    """Inclusive band edges, compared unrounded. NaN raises: an unknown value gets no label."""
    if pd.isna(x):
        raise ValueError("band_status of NaN")
    return "under" if x < band[0] else "over" if x > band[1] else "inside"


def crosses(lo: float, hi: float, band: tuple[float, float] = BAND) -> bool:
    if pd.isna(lo) or pd.isna(hi):
        raise ValueError("crosses on a NaN interval")
    return any(lo <= edge <= hi for edge in band)


def _per_horizon(tab: pd.DataFrame, cols: tuple[str, ...]) -> pd.DataFrame:
    """``cols`` indexed by horizon; the table must hold each of horizons 1-6 once."""
    t = tab if "horizon" in tab.columns else tab.reset_index()
    if "horizon" not in t.columns:
        raise ValueError("verdict table needs a horizon column")
    t = t.set_index(t["horizon"].astype(int).rename("h"))[list(cols)]
    if sorted(t.index) != list(HORIZONS):
        raise ValueError(f"verdict table has horizons {sorted(t.index)}, expected 1-6 once each")
    return t


def verdict_primary(tab: pd.DataFrame) -> dict:
    t = _per_horizon(tab, ("lo", "hi"))
    if t.isna().any().any():
        raise ValueError("primary verdict on a NaN interval")
    outside = {int(h): "under" if r.hi < BAND[0] else "over"
               for h, r in t.iterrows() if r.hi < BAND[0] or r.lo > BAND[1]}
    within = bool(((t["lo"] >= BAND[0]) & (t["hi"] <= BAND[1])).all())
    verdict = "outside tolerance" if outside else "within tolerance" if within else "inconclusive"
    return {"verdict": verdict, "outside": outside}


def _statuses(tab: pd.DataFrame) -> tuple[dict, dict]:
    t = _per_horizon(tab, ("point", "lo", "hi"))
    return ({int(h): band_status(r.point) for h, r in t.iterrows()},
            {int(h): crosses(r.lo, r.hi) for h, r in t.iterrows()})


def verdict_h2_m1(tab: pd.DataFrame) -> dict:
    d, c = _statuses(tab)
    late = [h for h in HORIZONS if h >= H2_LATE and d[h] != "inside"]
    early = [h for h in HORIZONS if h < H2_LATE and d[h] != "inside"]
    if late:
        verdict, fragile = "confirmed", all(c[h] for h in late)
    elif not early:
        verdict, fragile = "refuted", any(c.values())
    else:
        verdict = "neither"
        fragile = any(c[h] for h in HORIZONS if h >= H2_LATE) or all(c[h] for h in early)
    return {"verdict": verdict, "directions": d, "crossings": c, "fragile": fragile}


def verdict_h2_m2(tab: pd.DataFrame | None, evaluable: bool = True) -> dict:
    """Not evaluable (§4's failed-fit rule) gives no directions and fragile None."""
    if not evaluable:
        return {"verdict": "not evaluable", "directions": {}, "crossings": {}, "fragile": None}
    d, c = _statuses(tab)
    out = [h for h in HORIZONS if d[h] != "inside"]
    if out:
        return {"verdict": "refuted", "directions": d, "crossings": c,
                "fragile": all(c[h] for h in out)}
    return {"verdict": "confirmed", "directions": d, "crossings": c, "fragile": any(c.values())}


# ---- leave-one-origin-out and DEV side by side (§7.3, §7.13) -------------------------------
def range_fragile(values: Iterable, threshold: float) -> bool:
    """NaN raises: a subset that could not be evaluated gets no range, so the caller marks
    it rather than letting it drop out. Fewer than 2 values (an empty LOO) are not fragile."""
    v = pd.Series(list(values), dtype=float)
    if v.isna().any():
        raise ValueError(f"range_fragile on {int(v.isna().sum())} NaN of {len(v)} values")
    return len(v) >= 2 and bool(v.min() <= threshold <= v.max())


def loo(fn: Callable[[pd.DataFrame], dict], rows: pd.DataFrame, origins: Iterable) -> pd.DataFrame:
    """One row per dropped origin, in calendar order. Dropping an origin without rows would
    give the full sample as a subset, so it raises; one present origin gives the empty LOO
    (§10)."""
    origins = sorted(set(map(pd.Timestamp, origins)))
    col = pd.DatetimeIndex(rows["origin"])
    absent = pd.DatetimeIndex(origins).difference(col)
    if len(absent):
        raise ValueError(f"loo origins without rows: {[f'{o:%Y-%m}' for o in absent]}; pass "
                         "the origins present in the slice")
    if len(origins) < 2:
        return pd.DataFrame(columns=["dropped"])
    out = pd.DataFrame([fn(rows[np.asarray(col != o)]) for o in origins])
    out.insert(0, "dropped", origins)
    return out


def season(period) -> str:
    """Winter months only; any other month raises."""
    p = pd.Timestamp(period)
    if p.month not in WINTER_MONTHS:
        raise ValueError(f"{p:%Y-%m} is not a winter month")
    y = p.year if p.month == 12 else p.year - 1
    return f"{y}/{(y + 1) % 100:02d}"


def dev_range(values: Iterable) -> tuple[float, float]:
    v = pd.Series(list(values), dtype=float).dropna()
    return (float(v.min()), float(v.max())) if len(v) else (np.nan, np.nan)


def outside(x: float, lo: float, hi: float) -> bool:
    """Outside [lo, hi], edges inside. NaN raises: an unknown value gets no flag."""
    if pd.isna(x) or pd.isna(lo) or pd.isna(hi):
        raise ValueError("outside() on NaN")
    return bool(x < lo or x > hi)
