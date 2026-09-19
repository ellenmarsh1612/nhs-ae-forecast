"""Feature construction (phase 1, weeks 3–4).

Planned contents
----------------
- calendar.py    : month length, bank holidays, school holidays (England), Christmas/Easter flags
- weather.py     : monthly mean/min temperature and cold-spell days per ICB from Open-Meteo
- surveillance.py: UKHSA weekly flu / COVID / RSV positivity aggregated to month, lagged
- regimes.py     : COVID break (Mar 2020–), booked appointments (Aug 2020–), Type 3 → UTC
                   reclassification, field-testing trusts, post-merger indicators
- hierarchy.py   : provider → ICB → NHS region → England summing matrix S, and the
                   Type 1/2/other grouped hierarchy

Rule: every feature is built *as-of* the forecast origin. No feature may use a value
that was published after the origin date.
"""
