# Streamlit Dashboard Guide

The CADENCE dashboard has three pages: **Asset Portfolio**, **Alternative Analysis Results**, and **Insurance View**. It orchestrates the Python pipelines and reads saved results; the scientific and economic calculations live outside the page renderers.

For lifecycle formulas, see [Alternative Analysis](../ALTERNATIVE_ANALYSIS_README.md). For source-cost assumptions and insurance terms, see [Economics](economics.md) and [Insurance](insurance.md).

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

## Insurance View

Choose an insurance run, Portfolio or one asset, a roof option, and a year. The dashboard shows insured value, annual premium, expected payout, underwriting margin, loss ratio, and break-even premium.

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
| Physical lifecycle | `roof_alternative_analysis/schema_version=v0.4.0/run_id=<id>/` | Annual state, damage, analysis, summary, HTML report, metadata |
| Linked economics reference | `roof_alternative_analysis/economics_reference/schema_version=v0.3.0/run_id=<id>/` | Annual option costs and metadata |
| Insurance overlay | `roof_insurance_analysis/schema_version=v0.1.0/run_id=<id>/` | Policy snapshot, annual insurance, summary, metadata |

Retain linked products together. The insurance ID is separate from the physical ID and includes policy/workbook identities and a formula version. Reopening physical results does not synthesize missing policy snapshots. Published run files must not be manually overwritten to update assumptions.

## Code Map

| Code | Responsibility |
|---|---|
| [ui/app.py](../src/cadence/ui/app.py) | Three-page navigation and shared theme |
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
| [economics/contracts.py](../src/cadence/economics/contracts.py) and [economics/labor.py](../src/cadence/economics/labor.py) | Configurable horizon/rates and demand-surge wage calculation |

## Market Study Draft

Market Study is available as an experimental tab in Alternative Analysis Results on the same dashboard server. Run Alternative Analysis from Asset Portfolio in the current browser session, keep the Portfolio selection, then open Market Study and choose Run Market Study. A separately selected historical run without its matching active input snapshot cannot initiate a study. The view displays a warning about unresolved calculation limitations; exposing it does not certify the draft model. Its source remains separate from the four-scenario lifecycle comparison:

- [economics/market_inputs.py](../src/cadence/economics/market_inputs.py) loads asset, hazard, service-life, and price inputs.
- [economics/market_study.py](../src/cadence/economics/market_study.py) explores EUL/damage-triggered replacement, in-kind alternatives, discounted future costs, and straight-line terminal roof value.
- [economics/market_pipeline.py](../src/cadence/economics/market_pipeline.py) contains draft study publication.
- [ui/market_data.py](../src/cadence/ui/market_data.py) contains draft saved-study readers.

Draft outputs use `roof_market_study/schema_version=v0.1.0/run_id=<id>/` with annual asset stock, roof shares, portfolio costs, replacement decisions, and metadata. They are deterministic roof-stock scenarios, not calibrated market-adoption predictions. Decision NPVs are relative to replacement in kind at a decision event, not the Alternative Summary baseline.

Review limitations still requiring work:

- The draft removal lookup takes option-reference costs calculated for the originally installed roof and indexes them by replacement material. After a material switch, later disposal/carbon values and replacement triggers can therefore use the wrong removed material. Resolve costs for the active roof before relying on these projections.
- The draft executes a recursive simulator once per asset and materializes per-asset pandas results. This does not meet the repository's vectorized production-execution requirement. Synthetic examples do not establish performance at 100-10,000 assets.
- Validated annual loss-of-use inputs, calibrated depreciation/adoption assumptions, and completed publication/UI integration remain outstanding.

## Verification

Run from `CADENCE/` after installing the UI, geography, and test extras:

```shell
.venv/bin/python -m pytest tests/test_ui_workbooks.py tests/test_ui_state.py tests/test_ui_pipeline.py tests/test_ui_results.py tests/test_ui_insurance.py tests/test_insurance_analysis.py tests/test_insurance_pipeline.py
.venv/bin/python -m pytest
```

The tests cover workbook filtering, session identities, orchestration, result aggregation, cost allocations, maps, insurance normalization, payout arithmetic, and saved artifacts. Passing tests do not certify the provisional fragility proxies, installation productivity, insurance model, or large-portfolio performance.

The temporary Tile policy retains Tile identity but uses Metal lifecycle timing and vulnerability, with installed/repair costs multiplied by 1.2. Review that assumption and the cost-fallback flags before interpreting results as investment recommendations.