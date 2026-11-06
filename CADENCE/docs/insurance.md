# Insurance View

For installation, launch, and the complete portfolio-to-results workflow, see the [Streamlit Dashboard Guide](streamlit.md).

After running Alternative Analysis on Asset Portfolio, open the separate Insurance View in the sidebar. The selected `Sheet1` workbook, including uploaded workbooks with the same format, supplies per-asset `asset_id`, `insured_value`, `policy_id`, `deductible_amount`, `deductible_type`, `peril`, and `current_premium`. `policy_id` identifies an asset's policy; repeated IDs do not imply shared deductibles or limits.

Insurance View has two independent modes: **Event stress test** (default) and **Annualized losses**. Neither mode changes the physical model, Alternative Analysis Results, Asset Portfolio, or Program View.

## Event Stress Test

Choose an insurance run, **Event year**, **Wind return period**, and **Event footprint**, then click **Run event simulation**. Defaults are the first modeled year, 100-year wind, and All portfolio. After calculation, the display defaults to Portfolio and the current-roof baseline. All four roof options are calculated independently; the Asset and Roof option controls only change the display.

Available return periods are **100, 200, 300, and 500 years**. This is one deterministic event in the selected year, with the saved scenario's roof material/age, climate-adjusted local wind, and full installed roof cost. It does not damage future lifecycle states or assume the storm repeats every year. The current-roof baseline includes any in-kind replacement already scheduled by that year.

For every affected asset:

```text
gross_event_damage_usd = event_damage_ratio * active_installed_capex_usd
insured_event_payout_usd = min(max(gross_event_damage_usd - deductible_amount, 0), insured_value)
```

There is **no annual probability multiplier and no weighted-tail integration**. For example, 40% damage to a roof with a $100,000 full installed cost is $40,000 gross damage. With a $5,000 deductible and a $30,000 insured-value payout cap, the insurer pays $30,000. Premium is not subtracted from an event payout.

The 100/200/500-year options use the matching damage ratios already saved by the physical model. The **estimated 300-year** option interpolates local climate-scaled gusts on a log-return-period scale:

```text
w = log(300 / 200) / log(500 / 200)
gust_300 = gust_200 + w * (gust_500 - gust_200)
```

That gust is evaluated against the saved or identity-verified effective fragility curve using linear interpolation and endpoint clamping. Damage ratios themselves are not interpolated between return periods. The annual model's return-period grid remains unchanged. Event losses are not artificially forced above annual expected losses.

### State Footprint And Completeness

**All portfolio** applies each property's local return-period wind event to every asset. **Selected states** applies it only to assets in the chosen states, using saved run geography rather than the active workbook. Empty state selection disables Run. A selection containing no assets produces an explicit message. Unselected assets remain visible as unaffected with zero event damage and payout.

Unknown asset states must be resolved before a state-scoped simulation can run. All-portfolio runs can include these assets under **Unknown** state. Missing or invalid coordinates affect map placement only: those assets remain in financial totals and a warning reports the omissions.

Gross damage remains available when policy terms are unavailable but physical inputs are complete. Event payout requires a policy ID, wind peril, Standard flat-dollar deductible, and positive insured-value cap, but does **not** require premium. Missing damage/cost inputs or policy terms have explicit reasons. Gross and payout totals are checked independently; an incomplete affected asset prevents the corresponding state/portfolio total from being presented as complete. Roof options are compared, never summed together.

### Results, Maps, And Saved Runs

The committed event shows gross damage, insured payout, affected/total asset counts, per-asset details, state totals, and roof-option comparisons. The asset-point map switches between gross damage and payout. Blue denotes unaffected assets, gray unavailable amounts, and yellow-to-red affected loss. Popups show local wind, modeled damage percentage, state, and costs; the map does not imply a storm track.

Each successful Run publishes an immutable event artifact. Select **Saved event run** to reopen it. Clear that selection to create a new event; controls return to their defaults. Changing new-simulation inputs hides stale results until Run is clicked again. Event results do not show annual underwriting margin, break-even premium, or cumulative payouts.

Downloads include per-asset, state, and portfolio/roof CSVs for the **entire committed simulation**, independent of display filters, plus JSON assumptions and source checksums. Keep the assumptions with exported results. Identical inputs reuse a verified saved artifact; changed year, strength, footprint, or sources produce a distinct identity.

### Important Limitations

This is a **deterministic wind-roof stress test**, not a certified catastrophe model, storm catalog, regulatory-compliant report, or modeled portfolio loss return period. Simultaneous local 100-year winds throughout several states do not establish a 100-year portfolio loss.

Existing building-loss curves are provisional proxies applied to roof costs, not validated roof-component damage functions. Material mappings remain provisional; NEW_TILE uses Metal vulnerability and adjusted installed cost, and fragility lookup ages are capped at 30. The 300-year wind estimate is not a direct hazard observation.

Costs use the saved material-and-labor installed roof cost in real 2026 USD, excluding tear-off labor. Only wind roof repair is covered: no hail, other property damage, loss of use, carbon/disposal charges, reinsurance, percentage deductibles, or shared policy aggregates. Repeated policy IDs retain independent per-asset terms.

Older runs missing required event inputs show an actionable error; Annualized losses remains available. Unverified current reference data are never silently substituted.

## Annualized Losses (Unchanged)

The V1 overlay accepts `Standard` (flat USD) deductibles and `wind` peril, ignoring case and surrounding whitespace. Insured value must be positive; deductible and annual premium must be finite and nonnegative. Missing or unsupported fields do not block Alternative Analysis but leave the affected insurance values unavailable, with a reason. Portfolio monetary totals and ratios are unavailable if any included asset is incomplete. A zero premium is valid, but its loss ratio is N/A.

For each roof option and year, expected wind-roof payout is **min(max(expected annual repair cost - deductible, 0), insured value)**. Annual underwriting margin is annual premium minus that expected payout; loss ratio is payout divided by premium when premium is positive. Premium is held fixed in real 2026 dollars for all years and roof options. No loss of use, installation, carbon, disposal, insurer expenses, other perils, or claim events are included. This annual-loss calculation is a *planning proxy*, not event-level deductible treatment, an actuarial forecast, or total insurer profit.

The existing physical analysis remains unchanged. New runs publish a separate immutable `roof_insurance_analysis/schema_version=v0.1.0/run_id=...` artifact containing the normalized policy snapshot, annual overlay, summary, and a manifest linking to its physical run. Its identity includes the selected workbook checksum, normalized policy checksum, formula version, and physical run ID. A historical physical-only run without a matching saved insurance snapshot cannot be opened in Insurance View; it remains available in Alternative Analysis Results.

### Annualized Dashboard Controls

| Selector | Effect |
|---|---|
| Insurance run | Opens a saved policy snapshot and overlay; the active session's insurance run is preselected when available |
| Asset | Chooses the whole portfolio or an individual asset |
| Roof option | Chooses the current-roof baseline, new Asphalt, new Metal, or new Tile |
| Year | Changes the annual summary cards and individual policy waterfall |

The annual cash-flow and cumulative charts retain the full run horizon. The loss-ratio heatmap compares all four roof options. The portfolio policy inventory and missing-input table support review of unavailable values; an individual complete policy shows the repair-to-payout waterfall instead.

Break-even premium equals expected payout under this limited model, without expense loading or risk margin. Portfolio loss ratio is total payout divided by total positive premium, not an average of asset loss ratios. If any earlier year is incomplete, cumulative values remain unavailable even when a later year's annual values are present. Cumulative figures are undiscounted sums in real 2026 USD.

## Artifacts And Implementation

Each published insurance run contains:

```text
policy_snapshot.parquet
annual_insurance/year=<year>/part-00000.parquet
insurance_summary.parquet
run_metadata.json
```

[contracts.py](../src/cadence/insurance/contracts.py) normalizes policy terms and records availability reasons. [analysis.py](../src/cadence/insurance/analysis.py) performs the vectorized overlay and cumulative completeness checks. [pipeline.py](../src/cadence/insurance/pipeline.py) publishes immutable artifacts. The [UI data reader](../src/cadence/ui/insurance_data.py) verifies schemas and the linked physical run before aggregating results; [insurance_charts.py](../src/cadence/ui/insurance_charts.py) builds the figures.

Event runs are separate, under `roof_insurance_event_analysis/schema_version=v0.1.0/run_id=...`:

```text
input_snapshot.parquet
event_assets.parquet
event_portfolio.parquet
event_states.parquet
fragility_snapshot.parquet  # 300-year runs
run_metadata.json
```

The input snapshot contains the saved physical, policy, cost, and geography inputs for all four options. Metadata records settings, formula/interpolation versions, source checksums and identities, artifact checksums, dollar basis, and limitations. Publication is staged and atomic; reopening verifies identity and checksums. No annual/physical artifacts are overwritten.

[event_analysis.py](../src/cadence/insurance/event_analysis.py) owns event calculations and completeness-aware aggregation; [event_pipeline.py](../src/cadence/insurance/event_pipeline.py) owns publication. [insurance_event_data.py](../src/cadence/ui/insurance_event_data.py) loads verified inputs, and [insurance_event_page.py](../src/cadence/ui/insurance_event_page.py) owns event controls, maps, and downloads.