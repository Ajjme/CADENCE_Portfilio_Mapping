# Insurance View

For installation, launch, and the complete portfolio-to-results workflow, see the [Streamlit Dashboard Guide](streamlit.md).

After running Alternative Analysis on Asset Portfolio, open the separate Insurance View in the sidebar. The selected `Sheet1` workbook, including uploaded workbooks with the same format, supplies per-asset `asset_id`, `insured_value`, `policy_id`, `deductible_amount`, `deductible_type`, `peril`, and `current_premium`. `policy_id` identifies an asset's policy; repeated IDs do not imply shared deductibles or limits.

The V1 overlay accepts `Standard` (flat USD) deductibles and `wind` peril, ignoring case and surrounding whitespace. Insured value must be positive; deductible and annual premium must be finite and nonnegative. Missing or unsupported fields do not block Alternative Analysis but leave the affected insurance values unavailable, with a reason. Portfolio monetary totals and ratios are unavailable if any included asset is incomplete. A zero premium is valid, but its loss ratio is N/A.

For each roof option and year, expected wind-roof payout is **min(max(expected annual repair cost - deductible, 0), insured value)**. Annual underwriting margin is annual premium minus that expected payout; loss ratio is payout divided by premium when premium is positive. Premium is held fixed in real 2026 dollars for all years and roof options. No loss of use, installation, carbon, disposal, insurer expenses, other perils, or claim events are included. This annual-loss calculation is a *planning proxy*, not event-level deductible treatment, an actuarial forecast, or total insurer profit.

The existing physical analysis remains unchanged. New runs publish a separate immutable `roof_insurance_analysis/schema_version=v0.1.0/run_id=...` artifact containing the normalized policy snapshot, annual overlay, summary, and a manifest linking to its physical run. Its identity includes the selected workbook checksum, normalized policy checksum, formula version, and physical run ID. A historical physical-only run without a matching saved insurance snapshot cannot be opened in Insurance View; it remains available in Alternative Analysis Results.

## Dashboard Controls

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