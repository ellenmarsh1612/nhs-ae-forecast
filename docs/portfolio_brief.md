# Briefing for the portfolio site builder

For whoever builds the public page about this project. It says what the work is, what it
found, what may and may not be claimed, and where every number and asset lives in the
repository. Written 2026-09-18, after the confirmatory run; the live forecast is published on
31 October 2026, so the site needs a slot for it.

Everything below is sourced. Where a figure has a file path next to it, that file is the
authority — use it rather than retyping from this page.

---

## 1. What the project is, in one paragraph

NHS England publishes monthly A&E attendance and emergency admission figures for every
hospital trust, and quietly revises them afterwards. This project asks a question the
revisions make possible: **does the usual practice — testing a forecasting model on the final,
revised data — flatter it?** To answer it, every version of every published file since 2015
was recovered and stored under the date it became current, so a model can be tested on exactly
what was known at the time. The answer, measured across four models and three targets, is that
revisions change accuracy by under 0.4%: backtests on revised data are *not* materially
optimistic for this collection. Around that result sits a full probabilistic forecasting
system — baselines, a gradient-boosted model, a hierarchical Bayesian model, conformal
calibration, reconciliation up the provider → ICB → region → England hierarchy — and a
bed-escalation decision layer, all tested against a pre-registration that was frozen before
the data used to judge it were opened.

**The second finding, which is the more interesting one for a lay reader:** forecasts of this
kind are routinely overconfident, and it can be fixed. The uncalibrated machine-learning model
claims 90% confidence and is right 68–75% of the time. With a calibration layer added, the
same forecasts are right 87.5–90.3% of the time, on a sealed window the calibration had never
touched.

## 2. Who the site is for, and what a visitor should believe

The audience, in priority order: prospective consulting clients (NHS planning and analytics
leads, and analysts in other bodies that publish revised statistics), then technical
reviewers, then recruiters. After two minutes on the page a visitor should be able to say:

1. She measured a thing people assume rather than test, on real public data, and published
   the answer with the evidence.
2. She works the way a regulator or a reviewer would want: hypotheses fixed in advance, the
   data for judging them sealed, every change to the plan logged with a reason and a date.
3. The honest parts are visible — the hypotheses that failed are on the page, not in an
   appendix.

That last one is the differentiator. Most portfolio projects show only what worked.

## 3. The headline, and how to word it

**Use this framing:**

> Most NHS demand forecasts are overconfident. I measured by how much, on public data, across
> ~200 trusts, and showed what it costs in beds.

**Approved supporting claims** (each is backed by a file named in §6):

- Uncalibrated, the machine-learning forecast's "90%" intervals are right 68–75% of the time;
  calibrated, 87.5–90.3%.
- Model accuracy is barely affected by data revisions: under 0.4% across every model and
  target tested, with the ranking unchanged.
- The forecasts beat the standard seasonal-naive baseline by 38–48% in winter, at the horizon
  planners care about.
- The whole thing was pre-registered: hypotheses, decision rules and sealed data, with an
  83-entry amendment log, and the confirmatory data were opened exactly once.

**Do not write any of these.** They are wrong, and a knowledgeable reader will catch them:

| Do not write | Why | Write instead |
|---|---|---|
| "Tested on data the models had never seen" | The baselines and the machine-learning model were scored on those months before the split; the *calibration layer* and the Bayesian model are what CONF tested first-hand. The project's own disclosure says so. | "Tested on a window sealed going forward; the calibration layer was tested on it first-hand" |
| "The machine-learning model won" | It does not beat a plain statistical model (ETS) overall, and the forecast actually being published is ETS. The calibration layer, not the learner, carries the result. | "The gains came from calibration, not from the learner" |
| "Proved" / "shows conclusively" | The winter tests rest on one winter (five forecast origins). Two of three reconciliation verdicts flip if a single month is dropped. | "Measured, on one sealed winter, with the fragility stated" |
| "A validated bed-occupancy model" | The registered validation **failed** (median error 8.7 percentage points against a 5-point tolerance). The decision layer ships labelled illustrative. | "An illustrative decision layer, with its failed validation stated" |
| "Endorsed by / in partnership with the NHS" | It is independent work on public data. | "Built on NHS England's published statistics" |
| "The hierarchical Bayesian model is well calibrated" | On the sealed window it is the worst of the calibrated candidates: its "90%" intervals cover 97–99%. | "The hierarchical model failed its own calibration test — one of the results that went against the prediction" |

## 4. Suggested structure

Six sections. The order matters: the method claim leads, the model zoo does not.

1. **The question** (hero). The revision problem in three sentences, with one visual: the same
   month's figure as first published and as revised. Nothing technical yet.
2. **What I found.** Three result cards: the revision null, the overconfidence gap and its
   fix, and the winter skill over the baseline. Numbers large, each with one plain sentence.
3. **How it was kept honest.** The pre-registration, the sealed window, the single unseal, the
   amendment log. This is the section that sells consulting work; give it real estate.
4. **What didn't work.** Prominent, not an appendix: the hierarchical model's calibration
   failure, reconciliation failing its test, the tuning null, the decision layer's failed
   validation, the hypothesis that turned out untestable.
5. **The method, for people who want it.** The vintage archive and as-of harness, framed for
   transfer: any series revised after publication (ONS, DWP, HMRC) has this problem.
6. **The live forecast.** A slot, not yet content: from 31 October 2026 a real forecast for
   December 2026 to March 2027 is published, and from February 2027 it is scored in public.

## 5. The results, with the numbers to put on the page

All from the confirmatory run of 2026-09-15 (`results/H-confirmatory/`), the single scoring of
the sealed window. `docs/confirmatory_results.md` is the readable version and the place to
check any of this.

**The primary result — calibration works.** 90% intervals, provider level, sealed window:

| Horizon (months ahead) | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| Calibrated forecast covers | 87.5% | 88.3% | 88.7% | 89.6% | 89.5% | 90.3% |
| Same forecast, uncalibrated | 74.9% | 72.0% | 71.9% | 70.8% | 69.3% | 68.3% |

Target: 90%. The tolerance fixed in advance was 85–95%, and every horizon is inside it.

**Winter skill over the baseline (H1).** Machine-learning model against seasonal naive,
horizon 3, winter months: **−47.6%** error on all-types attendances, **−44.8%** on Type 1
attendances, **−38.4%** on admissions. The bar set in advance was 15%; all three clear it, and
they still clear it when any single origin is dropped.

**Revisions barely matter (H4).** Largest difference between training on as-published and
on revised data, across twelve model × target combinations: **0.37%**. The ranking of models
is identical either way.

**What failed.** The hierarchical Bayesian model's "90%" intervals cover **97–99%** —
refuted, in the opposite direction from the worry. Reconciliation up the hierarchy **fails**
for the headline model, and is fragile. Late submissions outweigh revisions for one target of
three, not generally. One registered hypothesis (cold start) turned out to be untestable at
all, which is recorded rather than quietly dropped.

**The forecast being published is deliberately the boring one.** Raw ETS — a standard
statistical model, uncalibrated — because a pre-committed rule said so before the sealed data
were opened. On the sealed window its intervals cover 97–98% where 90% is intended: too wide,
erring towards over-warning. That is stated with the forecast rather than fixed after the
fact, because changing the model in response to sealed-window results would contaminate it.

**Scale, for the "how big is this" line:** 720 file versions archived across 118 snapshot
dates; a panel of 1,072,039 rows covering June 2015 to August 2026; 332 provider codes (about
195 reporting in any month); 36 ICBs, 7 regions, England; 69 development origins and 19 sealed
ones; five models; 735 automated tests.

## 6. Where everything lives

Two repositories. The public snapshot is
**https://github.com/ellenmarsh1612/nhs-ae-forecast** — code, tests, the pre-registration and
its amendments, the confirmatory run's own output, and `site/`. The private working
repository is `nhs-ae-forecast-dev`, which additionally holds the 106 MB archive of original
NHS England files and the intermediate result directories. Paths below are relative to the
repository root and resolve in both, except where noted.

| What you want | Where |
|---|---|
| The confirmatory results, readable | `docs/confirmatory_results.md` |
| The same, as the run wrote them | `results/H-confirmatory/confirmatory_results.md`, `verdicts.json` |
| Every number behind a chart | `results/H-confirmatory/tables/*.csv` (one CSV per table and slice) |
| The pre-registration | `docs/preregistration.md` (§7 is the hypotheses) |
| The amendment log, readable | `docs/amendment_log.md` (83 entries, generated from §10) |
| Development-window results and the model story | `docs/results.md` |
| The full narrative record of the project | `docs/project_dossier.md` |
| How the sealed run was designed and policed | `docs/stage_h_design.md`, `docs/confirmatory_plan.md` |
| The live forecast: how it runs, what ships | `docs/handover.md` §12, `src/nhs_ae/live.py` |
| The published forecast, once it exists | `forecasts/2026-10/ets/` (and its `manifest.json`) |
| The decision layer and its failed validation | `docs/results.md`, "Stage G", and `results/G-decision/` |
| Reconciliation and coherence | `results/F-reconciliation/`, `docs/results.md` "Stage F" |
| What the data source publishes | NHS England, *A&E Attendances and Emergency Admissions* (monthly, public) |

Two things that are **not** in the repository and must not be invented: any patient-level
data (none is used — every figure is a published trust-month total), and any NHS
endorsement.

## 7. Figures worth building, and what feeds each

| Figure | Data | Note |
|---|---|---|
| Coverage by horizon: uncalibrated vs calibrated vs target | `tables/primary.table.csv`, `tables/headline.by_horizon.csv` | The single most persuasive chart on the site. A 90% line, two series, six horizons. |
| Winter skill over baseline, three targets | `tables/h1.table.csv` (`rel`, `rel_lo`, `rel_hi`) | Show the intervals, not just the bars. |
| Revision effect, twelve cells | `tables/h4.table.csv` | The point is that everything is near zero; a dot plot on a ±2% axis makes it. |
| "What one winter buys you": verdicts with an origin dropped | `tables/h3.loo.csv`, `tables/h1.loo.csv` | Honest fragility, and it builds trust. |
| First published vs revised, for one month | `data/processed/ae_monthly_all_vintages.parquet` | Needs a small script; ask before spending time on it. |
| Timeline of the 83 amendments | `docs/amendment_log.md` (dates in each entry) | A simple dated strip, showing the plan changing before the data opened. |
| The live forecast, once published | `forecasts/2026-10/ets/quantiles.parquet` | Fan chart, December–March. Build the slot now, fill it after 31 October. |

## 8. Glossary

- **Origin** — the month a forecast is made from. Data are published on the second Thursday,
  so an October origin knows September's figures.
- **Horizon** — months ahead. Horizon 3 from an October origin is December.
- **Coverage** — how often the outturn actually fell inside the stated interval. A "90%
  interval" should contain the truth 90% of the time; if it does so 70% of the time, the
  forecast is overconfident.
- **Calibration / conformal** — a layer that widens or narrows intervals using the model's
  own recent errors, so that stated confidence matches reality.
- **As-of vs final** — as-of uses only the figures published at the time; final uses today's
  revised figures. The difference between them is what this project measures.
- **Provider / ICB / region** — a hospital trust; the 36 integrated care boards that commission
  care; the 7 NHS England regions. Forecasts are made at each level.
- **Seasonal naive** — the baseline: next December will look like last December. Harder to
  beat than people expect.
- **WIS, MASE** — scoring rules. WIS scores a whole probabilistic forecast; MASE scores the
  central estimate against the naive baseline. Lower is better for both.
- **Pre-registration** — hypotheses and decision rules written and frozen before the test, so
  results cannot be chosen after the fact.

## 9. Voice

British English. Plain words for the concepts, exact numbers for the claims. No "revolutionary",
no "leveraging", no "AI-powered". Where something failed, say so in the same tone as where it
worked — the calm is the credibility. Every number on the page should be traceable to a file in
§6; if it is not, cut it.

## 10. Before you build: ask Ellie

1. Is the repository going public, or does the site link only to a written account? Some
   figures (the decision layer) carry labels that must travel with them.
2. The bed-occupancy section: the 92% planning threshold needs its current source confirmed
   before it appears on a public page.
3. How much of the live forecast should be on the site from 31 October, and who updates it?
   A public scorecard, updated monthly, is planned but not built.
4. Naming and attribution: how she wants to be credited, and whether the client-facing memo
   is public.
