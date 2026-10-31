# Streamlit Dashboard Guide

The CADENCE dashboard has four pages: **Asset Portfolio**, **Alternative Analysis Results**, **Insurance View**, and **Program View**. It orchestrates the Python pipelines and reads saved results; the scientific and economic calculations live outside the page renderers.

For lifecycle formulas, see [Alternative Analysis](../ALTERNATIVE_ANALYSIS_README.md). For source-cost assumptions and insurance terms, see [Economics](economics.md) and [Insurance](insurance.md).

## Program View

Open **Program View** (`/program`) to calculate one home's incentive requirements
for every possible installation year. Create a saved Program run from a compatible
physical run, then compare the economic break-even grant and incremental upfront
gap for a selected target roof. The page includes separate conventional-roof
counterfactuals, manual year selection, recommendations, a reconciliation waterfall,
CSV audits, and unpriced public-good explanation buttons.

This is a pre-insurance proxy, not guaranteed adoption or a portfolio budget.
Remaining roof value is excluded. Existing physical runs without valid fragility
snapshots need a matching rerun; saved Program runs reopen independently of the
session. See [Program View](program.md) for the complete workflow and formulas.

## Install And Launch

From the repository root:

```shell
cd CADENCE
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[ui,geo,test]'
bash run_dashboard.sh
```

Open **http://localhost:8520/**. The [launcher](../run_dashboard.sh) selects the CADENCE working directory and virtual environment and binds to the local machine. From the parent repository, `bash CADENCE/run_dashboard.sh` runs the same application. Reuse the canonical server if it is already running.

The source datasets must also be present: the package installation does not download the geography, wind, climate, fragility, material, or labor inputs. Configured locations are defined in [ui/paths.py](../src/cadence/ui/paths.py).

After changes to imported Python modules, restart the canonical server and refresh the browser. This clears in-memory session state, not published analysis artifacts. Explicitly select a saved run to read its results, or rerun the matching portfolio to restore an active workflow.

## Asset Portfolio

### Workbook And Filters

The page loads the [example asset workbook](../Data/User_Inputs/asset_inventory_test_1.xlsx) by default. **Download example asset workbook** provides the same template. Upload a complete `.xlsx` workbook with asset records on `Sheet1`; reference and validation sheets are not read as assets.

The map, processed registry, summary cards, and analysis subset all use the active filters:

- Current Roof Type: official Asphalt, Metal, and Tile classes.
- Roof Age and Roof Area: inclusive numeric ranges.
- Terrain: available terrain labels from the workbook.
- Asset ID: case-insensitive literal substring matching.

At least one asset must remain selected to run an analysis. The summary includes asset counts, roof age, roof area, material counts, and insured value when supplied. Incomplete insured values are not silently treated as zero.

### Analysis Settings

Defaults come from the [economics configuration](../Data/User_Inputs/economics_config_test_1.json). UI changes apply to the selected run and do not rewrite that file or the uploaded workbook.

| Control | Meaning |
|---|---|
| Start year / End year | Inclusive horizon within 2026-2050; end must not precede start |
| Annual real discount rate (%) | Discounts lifecycle cash flows; default 2% |
| Social cost of carbon rate (%) | Selects the published 1.5%, 2.0%, or 2.5% valuation series; default 2.0% |
| Demand surge? | No uses projected median installation wages; Yes uses P90-based wages grown by the local median projection |
| Disposal / Carbon | Include or exclude these event-cost streams for the entire run |
| Loss of use | Disabled in this UI pending validated annual inputs |

Material and labor remain included. Demand surge applies across all selected years, not only after a storm. Class-installed override fallbacks keep their median-based escalation; see [Labor Cost Construction](economics.md#labor-cost-construction).

Workbook roof ages are ages at the selected start year. Changing that year does not re-age the workbook from 2026. Costs remain in real 2026 USD regardless of the selected horizon. The carbon-series rate and the financial discount rate are different parameters.

### Run Workflow

1. Load and validate the workbook, then select the desired assets and settings.
2. Click **Run Alternative Analysis**.
3. The app saves a session-specific filtered workbook and constructs economics-ready asset features.
4. Year 1 damage and the four-scenario lifecycle/economics pipeline run for those assets.
5. A separate insurance overlay is published from the selected workbook's policy terms and physical results.
6. Open **Alternative Analysis Results** or **Insurance View** from the sidebar.

Changes to the source workbook, selected assets, or valid run settings invalidate the active-run link. Existing immutable results remain on disk. The provenance expander records the selected count, input checksum, configuration, and analysis identity.

## Alternative Analysis Results

The page uses the completed session run or an explicitly selected existing run ID. It supports physical schema `v0.4.0`; it does not infer the correct result from the newest directory. The Asset selector defaults to the full portfolio and can switch to one asset.

| Tab | Contents |
|---|---|
| Overview | Installed material mix, final NPV, avoided damage, net benefit, burnout counts, and portfolio replacement-opportunity maps |
| Time Series | Selected annual or cumulative metric across the baseline and three alternatives |
| Alternative Summary | Final comparison chart and table; portfolio mode also shows asset-level rows |
| Cost Allocations | Selected-year material, labor, expected repair, and enabled external-cost breakdown |
| Wind Return Period | Baseline or selected-year climate-scaled gusts from the saved hazard results |
| Roof Fragility Curves | Source wind-speed/building-loss curves for the baseline and all three alternatives in a selected modeled year |
| Market Study | Experimental roof-stock shares, annual costs, and replacement decisions for the matching active portfolio run |
| Run Information | Run location, generated HTML report path, configuration, source provenance, and metadata |

The baseline keeps the current roof and replaces it in kind at EUL. New Asphalt, Metal, and Tile alternatives install at the selected start year and subsequently replace in kind. Positive NPV means lower discounted lifecycle costs than the baseline; avoided damage alone does not include the investment cost.

Missing required costs remain unavailable or appear as chart gaps. Portfolio totals with incomplete inputs must not be interpreted as complete estimates. Fallback flags distinguish calculated prices from class-installed override values.

### Replacement Opportunities

Portfolio Overview contains separate maps for cumulative avoided damage and NPV. Each map has independent controls:

- **Replacement:** best replacement for that metric, or new Asphalt, Metal, or Tile.
- **Geography:** asset points, ZIP / ZCTA, county, or state.
- **Aggregation:** regional total or average per asset.

Best replacement is selected per asset and metric; it is not a single material recommendation for the whole region. A negative best value means all evaluated alternatives may be worse than the baseline. These maps do not impose budgets or optimize a portfolio investment schedule.

Red indicates negative outcomes, teal positive outcomes, and gray unavailable values. Each map derives its color range from the displayed values, so color intensity is not a common dollar scale across different selections. Tooltips expose values and replacement identities. Regional summaries preserve missing-value counts and keep affected aggregates unavailable.

Maps read saved outcomes and saved geography, including when a historical run is selected after restarting Streamlit. Geography boundaries and base tiles are display-layer dependencies, not new simulation inputs. Missing linked geography or boundary data is reported as an unavailable map.

### Cost Allocations

Choose a modeled year, starting with the run's first year. The stacked bars compare the installed-roof baseline and all three alternatives for one asset or the portfolio.

Installation material and labor occur only on installation/replacement events. Expected repair is annual. Enabled disposal and carbon are event costs; enabled loss of use is annual. The bars are real-dollar annual costs, not discounted NPV.

Material/labor splits allocate the effective installed cost using source shares or configured fallback shares. Under the temporary Tile policy, Tile uses Metal shares applied to Tile's effective installed cost. These allocations are not separate observed bills. The linked economics-reference run is required for the breakdown. Incomplete bars can show known components while their total remains unavailable.

### Wind Return Period

Baseline shows unscaled matched-grid 3-second gusts in mph at 10, 25, 50, 100, 250, and 500 years. Selecting a modeled year uses its saved climate-scaled gusts. The connecting curves interpolate against log return period for display; they do not fit a new hazard model. Portfolio mode shows individual asset curves, not an average portfolio wind speed.

### Roof Fragility Curves

Select a **Fragility year**, defaulting to the run's first modeled year. The shared Asset selector controls this tab: one asset shows its installed-roof baseline and New Asphalt, New Metal, and New Tile; Portfolio shows all four scenarios for every asset, without averaging or sampling.

The horizontal axis is wind speed in mph on a linear scale. The vertical axis is modeled **building loss (%)** from terrain-averaged HAZUS proxies. It is not failure probability, measured roof-area damage, or expected annual damage. Markers show the actual analysis source points, joined by straight lines without fitting or extrapolating beyond their support. These are the curves evaluated by the analysis, not a reconstruction from its six wind return-period damage values. Climate scaling changes the hazard wind speeds evaluated against these curves, not the curves themselves.

Hover exposes asset, scenario, year, active roof type, chronological age, lookup age, terrain, climate zone, wind speed, loss percentage, actual HAZUS proxy, source-curve count, and installation/replacement/age-cap flags. Asset colors and scenario line styles distinguish curves; legend entries toggle each asset/scenario. Identical curves can overlap. In particular, New Tile currently uses Metal vulnerability under the temporary Tile policy; the baseline for an existing Tile roof retains its own saved proxy.

The displayed ages are the saved lifecycle state after any start-of-year installation or replacement. Lookup age is chronological roof age plus one, capped at 30; a newly installed roof therefore uses lookup age one. The baseline follows the current roof's lifecycle, including modeled in-kind replacements, rather than holding its original age fixed.

New runs save the exact terrain-averaged points in a deduplicated `fragility_curves.parquet` snapshot. These charts can be reopened without the original reference datasets. Older runs without snapshots are shown only when their reference paths, sizes, modification timestamps, and supported mapping agree with the saved run. This legacy identity check is not a content-checksum verification; moving or touching reference files can require a rerun. Missing, changed, or inconsistent data makes this tab explicitly unavailable without disabling other tabs. A corrupt declared snapshot never falls back to current reference curves.

This view provides chart hover values only, with no table or CSV download.

## Insurance View

Choose an insurance run, then **Event stress test** (default) or **Annualized losses**. These modes are separate; neither changes any other view or the physical model.

**Event stress test:** choose a year, 100/200/300/500-year wind, and All portfolio or Selected states, then click **Run event simulation**. Defaults are the first run year, 100-year wind, and all assets. Gross damage is the selected event damage ratio times full installed roof cost, with no annual-probability multiplier. Apply the per-asset deductible and insured-value cap to obtain payout. The 300-year gust is estimated between 200 and 500 years on a log-return-period scale, then evaluated against the effective fragility curve.

Event results include gross damage, insured payout, affected asset counts, per-asset/state tables, independent roof-option comparisons, and an asset-point map. Unaffected assets show zero losses; missing policy terms do not hide complete gross damage. Missing premium does not block event payout. Unknown states block state-scoped runs; missing coordinates only affect map placement. Incomplete totals are explicitly unavailable.

Use **Saved event run** to reopen a simulation, or clear the selection to create a new one. Edited calculation inputs require another Run; stale results are hidden. Downloads contain the entire committed simulation and all roof alternatives, plus assumptions/provenance. This is a deterministic wind-roof stress test, not a storm track, portfolio loss return period, or regulatory certification. Existing building-loss/material proxies, the Tile/Metal proxy, age cap, and cost limitations remain in force. See [Insurance](insurance.md#event-stress-test) for formulas, scope, and limitations.

**Annualized losses (unchanged):** choose Portfolio or one asset, a roof option, and a year. The dashboard shows insured value, annual premium, expected payout, underwriting margin, loss ratio, and break-even premium.

The charts show annual premium/payout/margin, an all-option loss-ratio heatmap, and cumulative premiums and payouts. An individual complete policy also has a deductible/limit waterfall; portfolio mode shows the policy inventory. The year selector controls the summary values, while the time-series charts retain the full run horizon.

Insurance uses per-asset workbook terms, not a geographic insurance lookup. Supported terms are `wind` peril and `Standard` flat-dollar deductibles. Premium is fixed in real 2026 USD across years and roof alternatives. Expected payout is:

$$
P = \min\left(\max(C_{repair} - D, 0), V_{insured}\right)
$$

Margin is premium minus payout; loss ratio is payout divided by positive premium. Break-even premium equals the modeled payout and excludes expenses and risk margins. A zero premium is valid but has an unavailable loss ratio. Unsupported or missing policy terms leave insurance values unavailable without invalidating the physical analysis.

This is an annual-loss planning proxy, not event-level deductible treatment, an actuarial forecast, or total insurer profit. See [Insurance](insurance.md) for policy fields, cumulative completeness, and immutable output details. A historical physical-only run cannot be displayed here without a saved insurance snapshot.

## Saved Artifacts

Working files live beneath `cadence_datalake/streamlit_sessions/<session_id>/`, including uploads, filtered workbooks, and economics-ready asset snapshots. Published products live beneath `cadence_datalake/results/`:

| Product | Relative location | Principal artifacts |
|---|---|---|
| Physical lifecycle | `roof_alternative_analysis/schema_version=v0.4.0/run_id=<id>/` | Annual state, damage, analysis, summary, HTML report, metadata; new runs also include the fragility-curve snapshot |
| Linked economics reference | `roof_alternative_analysis/economics_reference/schema_version=v0.3.0/run_id=<id>/` | Annual option costs and metadata |
| Insurance overlay | `roof_insurance_analysis/schema_version=v0.1.0/run_id=<id>/` | Policy snapshot, annual insurance, summary, metadata |
| Insurance event stress test | `roof_insurance_event_analysis/schema_version=v0.1.0/run_id=<id>/` | Input snapshot, per-asset/state/portfolio results, 300-year curve snapshot when needed, settings/checksums/limitations |

Retain linked products together. The insurance ID is separate from the physical ID and includes policy/workbook identities and a formula version. Reopening physical results does not synthesize missing policy snapshots. Published run files must not be manually overwritten to update assumptions.

Fragility snapshots are an additive extension of physical schema `v0.4.0`, with their own format version included in run identity. Rerunning inputs previously analyzed without snapshots creates a new run instead of modifying the historical one.

## Code Map

| Code | Responsibility |
|---|---|
| [streamlit_app.py](../streamlit_app.py) / [ui/app.py](../src/cadence/ui/app.py) | Native bootstrap, four-page navigation, and shared theme |
| [program/](../src/cadence/program/) / [ui/program_page.py](../src/cadence/ui/program_page.py) | Single-home incentive calculations, immutable snapshots, and Program View |
| [ui/pages/portfolio.py](../src/cadence/ui/pages/portfolio.py) | Portfolio filters, settings, and run controls |
| [ui/pages/results.py](../src/cadence/ui/pages/results.py) | Physical result selection, tabs, and opportunity maps |
| [ui/pages/insurance.py](../src/cadence/ui/pages/insurance.py) | Insurance selection, indicators, and views |
| [ui/workbooks.py](../src/cadence/ui/workbooks.py) and [ui/state.py](../src/cadence/ui/state.py) | Workbook handling and active-run invalidation |
| [ui/pipeline.py](../src/cadence/ui/pipeline.py) | Direct pipeline orchestration and returned-run verification |
| [ui/results_data.py](../src/cadence/ui/results_data.py) | Cached DuckDB reads, completeness-aware aggregation, and map data |
| [ui/charts.py](../src/cadence/ui/charts.py) and [ui/results_map.py](../src/cadence/ui/results_map.py) | Plotly charts and Folium result maps |
| [ui/insurance_data.py](../src/cadence/ui/insurance_data.py) and [ui/insurance_charts.py](../src/cadence/ui/insurance_charts.py) | Insurance artifact checks, aggregation, and charts |
| [insurance/contracts.py](../src/cadence/insurance/contracts.py) | Direct policy-term normalization and availability flags |
| [insurance/analysis.py](../src/cadence/insurance/analysis.py) and [insurance/pipeline.py](../src/cadence/insurance/pipeline.py) | Vectorized annual payout overlay and immutable publication |
| [insurance/event_analysis.py](../src/cadence/insurance/event_analysis.py) and [insurance/event_pipeline.py](../src/cadence/insurance/event_pipeline.py) | Independent deterministic event losses and immutable event publication |
| [ui/insurance_event_data.py](../src/cadence/ui/insurance_event_data.py) and [ui/insurance_event_page.py](../src/cadence/ui/insurance_event_page.py) | Verified event inputs, controls, maps, saved runs, and downloads |
| [economics/contracts.py](../src/cadence/economics/contracts.py) and [economics/labor.py](../src/cadence/economics/labor.py) | Configurable horizon/rates and demand-surge wage calculation |

## Market Study Draft

Market Study is available as an experimental tab in Alternative Analysis Results on the same dashboard server. Run Alternative Analysis from Asset Portfolio in the current browser session, keep the Portfolio selection, then open Market Study. A separately selected historical run without its matching active input snapshot cannot initiate a study.

**Limit homeowner payback period** is off by default. Turn it on and enter a positive whole number in **Maximum acceptable payback (years)** (initially 10). Click **Run Market Study** to calculate or reopen that exact scenario. Editing a control does not automatically simulate or relabel old results. The optional limit applies to all homes; it is not capped at 10 years or one roof life.

The model evaluates every home every year, even with the limit off:

1. Compare keeping the roof until required EUL/damage replacement, followed by in-kind replacements, with installing each candidate material now and subsequently replacing it in kind when required. Same-material early renewal is included.
2. Require positive incremental NPV (at cent precision) for an elective replacement. With the limit enabled, also require first discounted recovery of incremental cost on or before that number of years.
3. Choose the largest eligible NPV; ties prefer the current material, then canonical Asphalt/Metal/Tile order. If nothing qualifies, keep a roof that is not due. A required EUL/damage replacement still occurs in kind.
4. Apply only this year's selected action to actual stock/costs, then reassess next year. Hypothetical comparison-path spending is never added to portfolio costs.

The original roof purchase is sunk and is not charged again. Remaining service is represented by the keep-roof comparison, not an extra book-value write-off. Long-term NPV includes the discounted **difference in terminal remaining roof values**, estimated using straight-line remaining life and terminal-year installed prices. Discounted payback excludes that imputed value and any unmodeled house-sale premium. Payback is a first crossing, not a guarantee that future replacement costs never make cumulative savings negative again; the separate NPV gate remains necessary.

At a required replacement, the upfront comparison is the upgrade's extra cost over a new same-material roof. For elective replacement, it includes the full install-now bill versus keeping the existing roof. Zero-time recovery is possible if the upfront differential is already nonnegative. Otherwise, recovery is evaluated at annual boundaries, inclusively and at cent precision; unrecovered payback is unavailable, not zero.

For each home, all candidates use the same rolling duration: the maximum of initial EUL (including overrides), new-material service lives, and the enabled payback limit. Opening installation/removal cash is discounted at the start of each year, operating costs at its end, and terminal value at the end of that duration. This versioned market convention does not change Alternative Analysis or Program View.

**Look-ahead is not limited by the chart end.** Beyond the last verified saved parent year, hold real prices, enabled removal rates, and climate factors constant. Continue aging, age-dependent damage, and necessary replacements. The UI shows the actual saved-data cutoff and evaluation endpoint; a shorter parent can have a cutoff before 2050. These are explicit scenario extrapolations, not sourced future forecasts. The shared Alternative Analysis configuration remains limited to 2026-2050.

Saved schema `v0.2.0` contains annual asset stock, roof shares, portfolio costs, annual accepted/rejected candidate decisions, itemized candidate cash-flow audits, verified input snapshots, and metadata/checksums. Large asset and audit tables are partitioned into Parquet datasets; aggregate charts remain small. Off, 5-year, and 10-year settings have different immutable identities. Legacy `v0.1.0` event-only results are never reused as current annual-decision results. Filter the audit by decision year and home and download the selected comparisons or home cash flows.

Implementation remains separate from the four-scenario lifecycle comparison:

- [economics/market_inputs.py](../src/cadence/economics/market_inputs.py) loads asset, hazard, service-life, and price inputs.
- [economics/market_study.py](../src/cadence/economics/market_study.py) evaluates fixed paths with batched array calculations, annual NPV decisions, and discounted payback.
- [economics/market_pipeline.py](../src/cadence/economics/market_pipeline.py) publishes scenario-specific results and provenance.
- [ui/market_data.py](../src/cadence/ui/market_data.py) locates exact saved scenarios and reads filtered audits without simulation.

Limitations:

- This is an enabled-study-cost economic acceptance proxy: full expected repairs, not costs net of insurance. Enabled carbon costs are included. Income, liquidity, finance, resale premiums, and actual homeowner adoption probabilities are not modeled.
- Remaining-value depreciation, the retained damage-cost trigger, age-30 fragility cap, and temporary Tile proxy remain provisional.
- Removal costs now use the actual removed material with verified reference sources. A source mismatch requires an Alternative Analysis rerun, rather than silently mixing assumptions.
- Missing required data remains explicitly unavailable; affected stock is Unknown and dollar totals are unavailable. Enabled loss of use is rejected until validated annual inputs are connected.
- Batched state/cash-flow calculations and cached risk lookups replace recursive optimization. Synthetic portfolio checks do not establish real-data production performance or calibrated adoption.

Focused verification:

```shell
.venv/bin/python -m pytest tests/test_market_study.py tests/test_market_inputs.py tests/test_market_pipeline.py tests/test_ui_market.py
```

Synthetic batch measurements (25 displayed years, 30-year rolling evaluation,
10-year acceptance, batches of 100, including in-memory Parquet serialization):

| Homes | Wall seconds | Peak process memory (MiB) | Serialized output (MiB) | Candidate cash-flow rows |
| --- | ---: | ---: | ---: | ---: |
| 100 | 0.84 | 264 | 1.7 | 225,000 |
| 1,000 | 6.61 | 281 | 16.9 | 2,250,000 |
| 10,000 | 61.74 | 291 | 169.1 | 22,500,000 |

Each size agreed with a single-home calculation for the sampled home. These
measurements use synthetic cached-risk inputs and exclude real reference loading,
source hashing, and disk I/O; they are not production end-to-end timings.

## Verification

Run from `CADENCE/` after installing the UI, geography, and test extras:

```shell
.venv/bin/python -m pytest tests/test_ui_workbooks.py tests/test_ui_state.py tests/test_ui_pipeline.py tests/test_ui_results.py tests/test_ui_insurance.py tests/test_insurance_analysis.py tests/test_insurance_pipeline.py
.venv/bin/python -m pytest
```

The tests cover workbook filtering, session identities, orchestration, result aggregation, cost allocations, maps, insurance normalization, payout arithmetic, and saved artifacts. Passing tests do not certify the provisional fragility proxies, installation productivity, insurance model, or large-portfolio performance.

The temporary Tile policy retains Tile identity but uses Metal lifecycle timing and vulnerability, with installed/repair costs multiplied by 1.2. Review that assumption and the cost-fallback flags before interpreting results as investment recommendations.