# CADENCE Graphics Ideas

## Recommendation

Build a **Portfolio Decision Map**, an **NPV Explanation Bridge**, and a **Roof Renewal Calendar** first. Together they answer three practical questions: Where should we look? Why does an upgrade make financial sense? When will replacement demand arrive?

CADENCE already has useful reporting charts. The next step is to connect geography, financial outcomes, and lifecycle timing into a coordinated decision workspace, not simply add more charts to the page.

This is a design proposal, not an implementation or a validation of the underlying models. Review date: September 30, 2026.

## Existing Foundation

The reviewed frontend uses Streamlit, Plotly, and Folium, with DuckDB queries over saved Parquet results. Reuse these tools and the existing visual theme.

| Existing graphic | Source | Opportunity for an addition |
| --- | --- | --- |
| Annual economic bars with installation/replacement markers | [charts.py](../src/cadence/ui/charts.py) | Make timing and cumulative recovery easier to compare. |
| Alternative NPV bars and stacked cost allocations | [charts.py](../src/cadence/ui/charts.py) | Explain the drivers behind the winning option. |
| Wind return-period curves | [charts.py](../src/cadence/ui/charts.py) | Compare changes across years without implying uncertainty intervals. |
| Roof-material stock shares and annual portfolio costs | [charts.py](../src/cadence/ui/charts.py) | Reveal transitions and replacement concentrations. |
| Asset and regional outcome mapping | [results_data.py](../src/cadence/ui/results_data.py) | Link location to asset-level investment comparisons. |
| Premium/payout bars, loss-ratio heatmap, cumulative insurance lines, policy waterfall | [insurance_charts.py](../src/cadence/ui/insurance_charts.py) | Show which assets contribute most to modeled insurance outcomes. |
| Portfolio map, filters, registry, and summary metrics | [pages/portfolio.py](../src/cadence/ui/pages/portfolio.py) | Reveal age and material concentrations hidden by averages. |
| Market replacement-decision table | [pages/results.py](../src/cadence/ui/pages/results.py) | Turn saved decision records into flows and trigger explanations. |

The separate [mapping_interface.py](../../Mapping_Application_CADENCE/mapping_interface.py) also has roof-shaped markers and age-based shading. Those graphics are already present; its age-derived remaining-life and ranking labels should not be treated as validated economic rankings or copied into the results views as such.

The shared Results and Insurance browser pages were at saved-run selection states during review. Their shell was inspected, but populated-chart behavior was assessed from source rather than a live end-to-end walkthrough.

## Readiness Key

- **A: Existing chart inputs.** The reviewed UI data helpers already expose the required fields; chart preparation and interaction work remain.
- **B: New query or derivation.** Saved fields exist, but the graphic needs additional aggregation, joins, or a defined calculation. No new scientific model is implied.
- **C: Model or data extension.** Do not present this as ready until the missing evidence or backend capability exists.

Effort is relative: **S** is a focused chart addition, **M** includes a data helper or coordinated interaction, and **L** involves a broader workflow or model change. These are not calendar estimates.

## 1. Portfolio Decision Map

**Question:** Which assets combine high avoided damage with attractive economic returns?

**Visual:** A geographic map paired with a quadrant scatterplot. Each dot is an asset; horizontal position is final NPV and vertical position is cumulative avoided damage. Keep a strong vertical zero-NPV reference line. Use the existing roof-option colors and an outlined marker for the selected asset.

**Interaction:** Select an asset in either view to highlight it in both and open its alternative comparison. Choose one replacement option or the existing best-by-NPV rule. Add total-dollar versus per-roof-area views only when a validated area field is available.

**Data:** `load_summary`, `load_map_geography`, and `map_outcomes` in [results_data.py](../src/cadence/ui/results_data.py). Both plotted outcome fields are already present. Joint selection requires new Streamlit state/event handling; it is not an existing map feature.

**Design detail:** Keep the map geographically honest: fixed-size dots at first, with a restrained diverging NPV scale. Avoid 3D columns that obscure nearby assets. For large portfolios, aggregate or cluster the map while keeping a searchable asset list.

**Guardrail:** Define what "best" means. Highest NPV and greatest avoided damage may select different roofs. An unavailable option must not silently become a losing option. A ranking is not a budget-constrained investment recommendation.

**Placement / readiness / effort:** Alternative Analysis Results / **B / M**.

## 2. NPV Explanation Bridge

**Question:** What actually makes this roof option financially better or worse than keeping the installed roof?

**Visual:** A horizontal waterfall from zero incremental value to final NPV. Separate initial investment, later replacement differences, avoided repairs, avoided loss of use, disposal differences, and carbon-cost differences. Finish with a clearly distinguished total bar.

**Interaction:** Choose asset or portfolio, replacement option, and modeled horizon. Select a component to reveal its annual contribution beneath the bridge.

**Data:** Extend the cost queries and `cost_allocations` in [results_data.py](../src/cadence/ui/results_data.py) across the modeled years. Calculate baseline-minus-alternative component differences using the same discount timing and enabled streams as the economic engine; reconcile the sum to the saved `net_present_value_usd`.

**Design detail:** Use cool tones for value added, muted warm tones for value lost, and a distinct total. Label positive and negative values directly instead of requiring users to interpret color alone.

**Guardrail:** The existing cost-allocation chart shows annual costs, not NPV contributions. Its values cannot simply be relabeled. Preserve estimated material/labor allocation flags and the temporary tile policy. Do not double-count avoided damage alongside its component costs or add insurance savings to a physical-only NPV.

**Placement / readiness / effort:** Beside the existing NPV comparison / **B / M**.

## 3. Economic Recovery Curves

**Question:** Does an option recover its investment within the modeled horizon, and can later replacements reverse that recovery?

**Visual:** Four small-multiple cumulative lifecycle net-benefit curves with shared axes, a visible zero line, and replacement diamonds. Shade negative-value portions lightly; label crossings and end-of-horizon values directly.

**Interaction:** Synchronize the year cursor across options. Switch between asset and portfolio. Selecting a replacement marker reveals the corresponding year's cost allocation.

**Data:** `load_asset_series` and `load_portfolio_series` already support `cumulative_net_benefit_usd` and carry event indicators in [results_data.py](../src/cadence/ui/results_data.py).

**Design detail:** Make the first crossing and subsequent negative periods visible instead of reducing the story to a single payback badge.

**Guardrail:** Label this version as cumulative, undiscounted lifecycle net benefit in real 2026 USD, not NPV. Show "Not reached within horizon" where appropriate. A "sustained recovery" label can only mean sustained through the modeled endpoint, not forever.

**Placement / readiness / effort:** Economic performance section / **A / S**.

## 4. Roof Renewal Calendar

**Question:** When do modeled replacements concentrate, and which assets drive those peaks?

**Visual:** A compact event raster: asset or cohort rows, year columns, and distinct installation/replacement symbols. An aligned bar strip above it shows annual replacement count. At portfolio scale, aggregate into county or installed-material cohorts and let users expand a cohort.

**Interaction:** Filter by roof option and geography; select a year to inspect affected assets. Keep independent option calendars separate from any market study's actual modeled choices.

**Data:** Annual `installation_event`, `initial_installation_event`, and `burnout_replacement_event` fields are already queried in [results_data.py](../src/cadence/ui/results_data.py). Add a compact, filtered multi-asset event query rather than requesting each asset separately.

**Design detail:** Use a square for initial installation and a diamond for burnout replacement, with quiet grid lines and aligned year ticks. On mobile, show a year-by-year list for the selected cohort.

**Guardrail:** This is a modeled event calendar, not a committed construction schedule. Do not infer contractor capacity, project duration, or a funded procurement plan from event counts.

**Placement / readiness / effort:** Lifecycle results / **B / M**.

## 5. Alternative Ranking Matrix

**Question:** Is the portfolio-level winning material also a good choice for most individual assets?

**Visual:** Asset rows by replacement-option columns, colored by NPV, with signed dollar values on hover. Outline the highest-valued complete option in each row. Add a narrow column showing the NPV gap between the best and second-best options.

**Interaction:** Sort by highest NPV, smallest winning margin, or missing data. Search for an asset and open its detail view. Offer a dollars-versus-within-asset-rank mode without mixing their legends.

**Data:** Per-asset, per-option `net_present_value_usd` from `load_summary` in [results_data.py](../src/cadence/ui/results_data.py). The winning margin is a simple derived comparison, not a model confidence interval.

**Design detail:** Anchor the dollar colors at zero. Use neutral patterned or explicitly labeled cells for missing results. Paginate or show selected cohorts instead of drawing 10,000 unreadable rows.

**Guardrail:** "Best replacement" does not mean "better than baseline" when all replacement NPVs are negative. Preserve ties and flag incomplete comparisons. Do not call a small winning margin evidence of statistical uncertainty.

**Placement / readiness / effort:** Portfolio alternative comparison / **A / S**.

## 6. Modeled Insurance Burden Concentration

**Question:** Which assets account for most of the modeled wind-roof payout, and how does the mix change by roof option?

**Visual:** A ranked contribution chart with payout bars and a separate aligned cumulative-share panel. Add a clear marker for the number of assets accounting for a chosen share of total modeled payout. Keep asset count and dollars on separate axes rather than overlaying ambiguous scales.

**Interaction:** Select year and replacement option, then choose an asset to open its existing policy waterfall. Allow a cumulative-horizon view, explicitly labeled as a different basis.

**Data:** `annual_insurance` contains `asset_id`, `year`, `scenario_id`, `expected_payout_usd`, and `insurance_issue`; these fields are used in [insurance_data.py](../src/cadence/ui/insurance_data.py). Add a filtered, multi-asset query. Join only through the insurance run's linked physical run.

**Design detail:** Show the largest contributors plus an "Other complete assets" bar. Keep excluded or incomplete assets visible as a separate count, not hidden inside Other.

**Guardrail:** These are contributions to the current model's payout estimate, not catastrophe tail-risk contributions. An all-zero total has no meaningful cumulative-share percentage. Do not imply diversification benefits or correlated-event analysis.

**Placement / readiness / effort:** Insurance View / **B / M**.

## 7. Wind Change Profile

**Question:** How does the modeled gust at a given return period change along the single climate trajectory?

**Visual:** A dumbbell chart with one row per return period. Two labeled endpoints show baseline gust and selected-year climate-scaled gust in mph; their connecting segment shows the modeled change.

**Interaction:** Select an asset and year. Keep a companion return-period curve for users who need the full shape. An optional play control may step through years, but the default should be a static, inspectable comparison.

**Data:** `load_wind_return_periods` exposes baseline `rp_*` values and selected-year `climate_scaled_rp_*` values through the same output names in [results_data.py](../src/cadence/ui/results_data.py). Request both explicitly and label the source year.

**Design detail:** Use hollow baseline markers and solid selected-year markers, with the mph change printed at the end of each row. Connect endpoints even when the change is negative.

**Guardrail:** This is a comparison within one climate trajectory, not an RCP/SSP scenario comparison. The connecting segment is a change indicator, not a confidence interval. A return period is not a countdown to the next storm.

**Placement / readiness / effort:** Wind hazard section / **A / S**.

## 8. Result Completeness Strip

**Question:** Which displayed outcomes are complete, estimated, or unavailable?

**Visual:** A compact status strip above each major chart and an expandable asset-by-category matrix below it. Separate repair completeness, climate-risk completeness, event-cost completeness, cost-source fallback, and insurance-input issues.

**Interaction:** Select an issue category to filter the asset list. Keep the relevant status in chart tooltips and downloaded reports, not only in an expander.

**Data:** `repair_cost_incomplete`, `climate_risk_total_incomplete`, `event_cost_incomplete`, and `active_cost_fallback_applied` in [results_data.py](../src/cadence/ui/results_data.py); `policy_issue` and `insurance_issue` in [insurance_data.py](../src/cadence/ui/insurance_data.py).

**Design detail:** Pair text with check, warning, and unavailable symbols. Keep fallback-derived values distinct from missing values. Use small counts such as "Complete 84/100" rather than an invented quality score.

**Guardrail:** Completeness is not model accuracy or confidence. Preserve the existing behavior that leaves incomplete portfolio totals unavailable rather than summing only the known rows and presenting them as a full total.

**Placement / readiness / effort:** Shared Results and Insurance component / **B / S-M**.

## 9. Roof Material Transition Flows

**Question:** When roofs are replaced, which materials gain assets from which installed materials?

**Visual:** A three-column Sankey: outgoing material, replacement cause, incoming material. Ribbon width represents selected replacement events. Keep source and destination material colors stable and show same-material renewal as a visible flow, not as an omission.

**Interaction:** Select a year or bounded year range. Select a ribbon to show its contributing assets and years. Offer a compact old-to-new transition matrix alongside the Sankey for exact comparison and mobile use.

**Data:** `load_study` in [market_data.py](../src/cadence/ui/market_data.py) already returns replacement decisions. The saved fields are `old_material_id`, `candidate_material_id`, `cause`, `selected`, `asset_id`, and `year`; their producer is [market_study.py](../src/cadence/economics/market_study.py).

**Design detail:** This is the most visually distinctive near-term addition: broad, translucent material ribbons show portfolio change without resorting to decorative animation. Hover reveals the event count and percentage of selected replacement events in the filtered period.

**Guardrail:** Filter to `selected == True`; each replacement has three candidate rows. Across several years, one asset can contribute multiple events, so label events rather than unique roofs. This flow excludes unchanged stock and is not an adoption forecast. A full stock-conserving time storyboard would require the additional saved `annual_asset_stock` artifact, including Unknown states.

**Placement / readiness / effort:** Market Study, beneath material stock shares / **A / M**.

## 10. Replacement Trigger Explorer

**Question:** Why did the market study replace this roof in this year?

**Visual:** Annual stacked bars separate service-life replacements from cost-triggered replacements. Selecting an event opens a paired horizontal marker chart comparing the modeled trigger amount with remaining roof value, followed by three candidate NPV dots with the selected material outlined.

**Interaction:** Select a year, cause, and asset. Show the outgoing material and selected incoming material in the detail heading. Keep the event timeline synchronized with the candidate comparison.

**Data:** `load_study` returns `eul_replacements`, `damage_replacements`, and `unknown_count` in annual costs, plus `trigger_usd`, `roof_value_usd`, `incremental_npv_usd`, `cause`, and `selected` in the decision records. See [market_pipeline.py](../src/cadence/economics/market_pipeline.py) and [market_study.py](../src/cadence/economics/market_study.py).

**Design detail:** Use an explicit service-life symbol for EUL events and a threshold marker for cost-triggered events. This explains a discrete decision more clearly than an animated gauge.

**Guardrail:** The saved `damage` cause means a deterministic cost threshold was exceeded, not that a simulated storm occurred. The trigger includes modeled repair, loss of use, disposal, and carbon amounts; it is not just physical damage. Service-life expiration takes precedence. Candidate incremental NPV is relative to replacing with the outgoing material at that event, not the Alternative Analysis keep-current baseline. Keep these comparisons separately labeled.

**Placement / readiness / effort:** Market Study decision detail / **A / M**.

## 11. Portfolio Age Profile

**Question:** Does the portfolio contain a large cohort of similarly aged roofs that an average-age metric conceals?

**Visual:** A material-by-age-band heatmap with marginal totals. Switch the cell measure between asset count and total roof area. Clicking a cell highlights that cohort on the existing map and filters the registry.

**Interaction:** Reuse current material, roof-age, area, and terrain filters. Let users inspect exact age bounds and reset the cohort selection. Make the active cohort visible before starting an analysis, because portfolio filtering changes which assets are simulated.

**Data:** The validated display frame in [pages/portfolio.py](../src/cadence/ui/pages/portfolio.py) exposes `official_material`, `roof_age`, `roof_area_sqft`, and `asset_id`. No saved analysis run is needed.

**Design detail:** Use shared, explicit age bins across materials and a single sequential intensity scale within the selected measure. Count and area modes can tell very different stories; their titles and units must change together.

**Guardrail:** Age is not measured condition, failure probability, or remaining useful life. Do not import service-life defaults or the standalone mapping application's ranking rules into this graphic. Zero-count cells and missing records must remain distinguishable.

**Placement / readiness / effort:** Asset Portfolio, adjacent to the registry / **A / S-M**.

## Visual Direction

- Retain CADENCE's existing brand header, roof-option colors, and shared theme. Make the analytical canvas quiet, with restrained grids and direct labels.
- Use color consistently within each semantic category: roof option, financial sign, and data status need separate legends. Do not casually recolor an option from one view to the next.
- Favor aligned panels, small multiples, and full-width analytical sections over nested cards. Reserve framing for individual tools or genuinely separate items.
- Use the application's existing icon system for selection, filtering, playback, reset, and export, with accessible names and tooltips. Avoid decorative icons that compete with the plotted data.
- Keep motion purposeful: short selection transitions and optional year playback. Respect reduced-motion settings; never depend on animation to communicate a value.
- On narrow screens, stack map and chart, preserve readable labels, and provide a table or selected-asset detail when a dense graphic no longer fits.
- Every chart should expose units, horizon, selected option, and whether it represents one asset or an aggregate. Preserve real 2026 USD conventions; distinguish discounted and undiscounted amounts.

## Suggested Screen Layout

Preserve the tabs in [pages/results.py](../src/cadence/ui/pages/results.py). Add views where their question belongs rather than placing all eleven graphics on one long screen.

```text
RESULTS / OVERVIEW
Run identity | Portfolio or asset | Replacement option
Completeness status

Geographic decision map       Asset NPV / avoided-damage plot
							 Selected asset detail

NPV explanation bridge       Existing option totals
```

```text
RESULTS / MARKET STUDY
Study identity | Year or period | Active cohort
Existing material-share chart

Material transition flows    Replacement-cause counts

Selected replacement: threshold comparison + candidate NPVs
Decision records
```

Use the Time Series tab for recovery curves and the renewal calendar; Alternative Summary for the ranking matrix; Wind Return Period for the change profile. Insurance concentration stays in Insurance View, and the age profile belongs on Asset Portfolio. On mobile, each two-column row becomes a vertical sequence with selection context retained.

## Delivery Approach

1. **Start with one decision workflow:** map selection opens an asset comparison; the explanation bridge then makes that comparison auditable. Add completeness status from the beginning.
2. **Add timing:** economic recovery curves and the renewal calendar make the consequences over time visible.
3. **Add specialist views:** the ranking matrix, insurance concentration, wind change profile, and market-study explanations support deeper analysis without crowding the default screen. The age profile is an independent intake improvement.

Keep pure figure builders in [charts.py](../src/cadence/ui/charts.py) and [insurance_charts.py](../src/cadence/ui/insurance_charts.py). Keep data joins and completeness-aware aggregates in [results_data.py](../src/cadence/ui/results_data.py) and [insurance_data.py](../src/cadence/ui/insurance_data.py). Extend page composition only after these functions have focused coverage.

Use [market_data.py](../src/cadence/ui/market_data.py) for study-specific reads. The current Market Study page requires a matching active session and its saved asset inputs; it is not available for every arbitrarily selected historical run. Reflect that availability in new graphics rather than silently starting a study or attaching data from a different run.

Query only needed Parquet columns and aggregate before sending data to the browser. Cache by immutable run identity and filter state. Visualization work must not mutate saved runs, recompute ingestion-time spatial assignments, or introduce geometry into simulation calculations.

Before release, reconcile chart totals to source outputs and test missing values, all-negative alternatives, ties, zero premiums/payouts, repeated replacements, and large portfolios. Check desktop and mobile layouts, keyboard access, selection persistence, empty states, and export behavior. These are acceptance criteria for future implementation, not checks completed by this proposal.

## Graphics to Defer

- **Uncertainty fans or probability-of-loss cones:** **C**. Require a defensible uncertainty method and propagated bounds or simulated samples. The current mean trajectory is not enough.
- **Carbon abatement frontier in tonnes CO2e:** **C until physical units are verified**. Monetized `carbon_usd` is not an emissions quantity and cannot be relabeled as one.
- **Budget-constrained optimal upgrade plan:** **C**. Requires a defined optimization objective, funding constraints, and scheduling policy. A cumulative ranking is not an optimizer.
- **Multi-climate scenario overlays:** Outside the current V1 single-trajectory constraint. Do not expose scenario controls merely because roof alternatives use a `scenario_id` field.
- **Decorative 3D roofs, radial gauges, and financial pie-chart galleries:** Low priority. They occupy analytical space without improving comparison, timing, or traceability.

## Review Basis

This proposal follows the architectural constraints in [CADENCE_copilot-instructions.md](../CADENCE_copilot-instructions.md): immutable runs, a single climate trajectory, ID-based data retrieval, and explicit provenance. The source links above are implementation anchors, not claims that the proposed graphics already exist.

The model-extension caveats are also informed by [Future_enhancements.md](../Future_enhancements.md), particularly its warnings about calibrated adoption, roof depreciation, and event-level insurance. Where the roadmap describes work that now appears in source, this proposal uses the reviewed implementation to distinguish existing outputs from future graphics.