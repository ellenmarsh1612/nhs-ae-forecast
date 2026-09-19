# Scope: NHS A&E demand forecasting (phase 1)

> **Early planning document, kept as a record.** Written before the vintage archive was
> built and before the confirmatory run. Two things in it are now known to be wrong: it says
> the monthly files are "revised in place", when in fact every revision gets a new URL and
> the original stays on the NHS England server (`README.md`, verified 2017–2024); and it
> lists a scorecard page among the deliverables, which is planned but not built. The
> provider count here ("~180") is superseded by the measured figures in
> `site/site_numbers.json`. Where this document disagrees with
> `docs/confirmatory_results.md`, that page stands.

**One line.** A measured answer to whether backtesting on revised official statistics
overstates forecast skill (for NHS England's A&E series: it does not, by at most 0.6%),
built on probabilistic monthly forecasts of A&E attendances and emergency admissions
for every English provider, evaluated on data *as it was published at the time*,
converted into a winter bed-escalation decision, and shipped with monitoring and a
handover pack an ICB analyst could run without the author.

**Why this and not a Kaggle dataset.** The data revises after publication, providers
go missing, trusts merge, and definitions change. Those are exactly the problems a
short-contract client pays to have handled. The revision-aware evaluation (H4 in
`preregistration.md`) is the differentiator: it tests whether the standard practice of
backtesting on final data overstates skill.

## In scope (phase 1)

- Targets: attendances (all types; Type 1) and emergency admissions via A&E.
- Horizons 1–6 months; winter (Dec–Mar) as the reporting focus.
- Hierarchy: provider → ICB → region → England; grouped Type 1/2/other for attendances.
- Vintage archive + as-of backtesting.
- Baselines, global LightGBM, hierarchical PyMC model, reconciliation.
- Decision layer: escalation beds per trust per winter month.
- Monthly GitHub Action, GitHub Pages scorecard, Streamlit app.
- Handover pack and one-page memo.
- First live forecast for Dec 2026–Mar 2027 published by **31 October 2026**.

## Out of scope (phase 1)

- Four-hour / twelve-hour performance (outcomes of capacity, not demand).
- Daily / weekly resolution (the winter UEC SitRep is a phase-2 input).
- Allocation optimisation across trusts (phase 2).
- Ambulance handover, workforce, elective trade-offs (phase 2).

## Data sources

| Dataset | Use | Cadence | Notes |
|---|---|---|---|
| NHS England Monthly A&E Attendances and Emergency Admissions (provider) | targets | monthly, 2nd Thursday | revised in place May & Nov; missing providers listed in commentary |
| Provider-to-system mapping; Type 3 attribution | hierarchy | with each release | check for mid-series changes |
| ODS organisation API | lineage (mergers) | on demand | `Succs` links |
| UKHSA flu / COVID / RSV surveillance | covariates | weekly | aggregate to month, lag to origin |
| Open-Meteo historical weather | covariates | daily | mean/min temperature, cold-spell days per ICB |
| Bank & school holidays (gov.uk, DfE) | covariates | annual | |
| ONS mid-year population by ICB; IMD | provider metadata / cold start | annual | |
| KH03 bed availability and occupancy (G&A) | decision layer | quarterly | |
| UEC Daily SitRep (winter) | phase 2 | weekly in winter | occupancy, handovers, discharge delays |

## Known mess and how each is handled

| Problem | Handling |
|---|---|
| Twice-yearly revisions (new URL from 2019; replaced in place before) | Vintage archive (`data/raw/<available_from>/`), SHA-256 manifest; `recover` rebuilds history from Internet Archive captures of the year pages and fetches originals from NHS England; `coverage` produces the exclusion list where the Archive has no copy |
| Missing providers each month | Stored as NaN, never zero; aggregates use missingness-aware sums and carry a "providers missing" count |
| Trust mergers / new codes | ODS lineage → canonical code map; post-merger series treated as cold start (H5) |
| Type 3 → UTC reclassification; booked appointments (Aug 2020) | Regime indicators; booked appointments excluded from targets |
| Fourteen field-testing trusts (2019–23) | Attendances continued; flag for four-hour metrics only |
| COVID (Mar 2020) | Both handling options tested: intervention term vs down-weighting 2020-03 to 2021-06; choice recorded before evaluation origins are scored |
| Weekly → monthly apportionment before Jun 2015 | Excluded |
| May 2025 errata on provider admissions | Worked example in the write-up of why vintages matter |
| Encoding / suppression (`-`, `*`) in CSVs | `parse._to_number`; cp1252 fallback |

## Models (see preregistration §5)

Baselines → global LightGBM → hierarchical PyMC → reconciliation → optional foundation
model. Every model emits the same quantile table so the evaluation harness is shared.

## Deliverables

1. This repo, runnable end-to-end from the README.
2. `data/raw/` vintage archive, growing monthly via GitHub Action.
3. `docs/preregistration.md`, frozen by tag before backtesting.
4. Scorecard page (GitHub Pages) with as-of vs final comparison.
5. Streamlit app: trust selector, fan charts, escalation-bed table.
6. `docs/handover.md` — backfill, retrain, drift triggers, missing/merged trusts, revisions.
7. `docs/memo.md` — one page for an ICB winter-planning lead.
8. Technical write-up.

## Plan (≈ 2 days/week)

| Week | Work |
|---|---|
| 1 | Ingestion (this commit), lineage, start vintage archive, Internet Archive recovery, target & hierarchy definitions |
| 2 | Baselines + as-of backtest harness + metrics; freeze pre-registration |
| 3–4 | LightGBM (quantile/Tweedie, conformal) and the PyMC model |
| 5 | Reconciliation; cold-start evaluation |
| 6 | Decision layer; memo draft |
| 7 | Monitoring, Action forecast job, Pages, Streamlit, handover pack |
| 8 | Write-up; first live forecast for Dec–Mar published |

## Risks

- **Vintage coverage.** From 2019 onward originals are still on the NHS server and are
  recoverable in full; 2015–2018 files were replaced in place and depend on sparse
  Archive file captures. Mitigation: `coverage` report drives Appendix A; report H4 on
  whatever winters are genuinely as-of.
- **Revision size.** In the five original/revised pairs checked on 2026-09-08, at most
  two providers per metric changed and national totals moved under 1%. H4 may well be
  refuted; the as-of test must also capture late submitters and provider-set changes.
- **Monthly resolution** limits operational use. Pitch phase 1 as planning; phase 2
  adds the winter SitRep.
- **PyMC scale.** ~180 providers × ~130 months × 3 targets is fine; if per-provider
  seasonality makes sampling slow, move to ICB-level random effects.
- **Scope creep.** Two targets, one hierarchy, one decision, one winter. Phase 2 is a
  separate milestone.
