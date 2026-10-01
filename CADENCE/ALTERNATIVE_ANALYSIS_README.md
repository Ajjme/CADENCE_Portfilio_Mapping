# CADENCE Roof Alternative Analysis

> **Temporary Tile policy:** `NEW_TILE` currently mirrors `NEW_METAL` lifecycle timing and vulnerability, with installed and repair costs equal to `1.2` times Metal. Tile scenario/material identity is retained. The run manifest records `temporary_tile_as_metal_with_1_2x_cost_v1`; remove that isolated policy when authoritative Tile inputs are restored.

This guide explains the complete roof Alternative Analysis workflow, how to run it from VS Code, what the pipeline produces, and how to interpret the economic and risk results.

For the interactive portfolio, result maps, analysis controls, and Insurance View, see the [Streamlit Dashboard Guide](docs/streamlit.md).

## What The Analysis Answers

For every asset and every year in the selected horizon, CADENCE compares four independent roof lifecycle scenarios. The default is 2026 through 2050; a run may select a shorter inclusive horizon within those years.

| Scenario ID | Meaning |
|---|---|
| `BASELINE_CURRENT` | Keep the roof that is installed today at its current age; replace it in kind when it reaches end of useful life. |
| `NEW_ASPHALT` | Remove the current roof and install a new Asphalt roof at the selected start year. |
| `NEW_METAL` | Remove the current roof and install a new Metal roof at the selected start year. |
| `NEW_TILE` | Remove the current roof and install a new Tile roof at the selected start year. |

The same-material alternative is retained. For example, an existing five-year-old Asphalt roof is compared with a new Asphalt roof as well as new Metal and Tile roofs.

The pipeline calculates:

- roof age and remaining useful life;
- installation and burnout-replacement events;
- annual age-specific expected wind damage;
- annual expected repair cost;
- expected loss-of-use cost when supplied;
- disposal and carbon costs when a roof is removed;
- annual and cumulative avoided damage;
- annual and cumulative lifecycle net benefit; and
- discounted net present value (NPV).

## How The Model Works

### Lifecycle Timing

The analysis uses a sequential annual lifecycle model. Within each year:

1. Determine whether the active roof has reached end of useful life (EUL).
2. Replace a burned-out roof in kind at the start of the year.
3. Record installation, disposal, and carbon event costs.
4. Determine the active roof material and age.
5. Apply that year's wind climate scaling.
6. Calculate age- and material-specific expected damage.
7. Convert expected damage into repair and lifecycle costs.
8. Carry roof age and state into the next year.

All alternatives are installed at the selected start year. Workbook roof ages describe the installed roof at that start year; they are not automatically advanced from 2026. Every scenario replaces its active roof in kind if it later burns out during the study period. Dollar values retain a real-2026 basis.

### Useful Life

The current installed roof uses this precedence:

1. asset-level `current_roof_eul_years`, when supplied;
2. official material-class physical service life; or
3. an error if neither value can be resolved.

A replacement roof always uses the official material-class physical default. Consolidated defaults currently round to:

| Material | Applied EUL |
|---|---:|
| Asphalt | 24 years |
| Metal | 55 years |
| Tile | 60 years |

Raw and rounded values, source, and mapping version are preserved in the state output.

### Roof Age And Fragility

Chronological roof age is retained for lifecycle accounting. Fragility curves are available only for ages 1 through 30, so the lookup age is:

$$
a_{lookup}=\min(\max(a_{chronological}+1,1),30)
$$

A roof older than 30 continues to age chronologically, but uses the age-30 fragility curve and carries `age_capped=true`.

### Wind Climate Scaling

Current Alternative Analysis schema `v0.4.0` applies a dimensionless wind-speed scale factor by CONUS404 grid cell and year.

- Source years: 2025 through 2050.
- Years through 2024 use factor `1.0`.
- Years after 2050 use a linear continuation of the 2040-to-2050 factor slope.
- Scaled return-period gusts are passed to the fragility curves.

The default input is:

```text
Data/Climate_Delta/wind_climate_scaling.parquet
```

This file is present in the workspace and is automatically used when `--climate-delta` is omitted. Supply `--climate-delta` only to use a different compatible file. The previously generated schema `v0.1.0` example under `cadence_datalake/results/roof_alternative_analysis/` used constant baseline hazard and should not be interpreted as a climate-scaled `v0.4.0` run.

The default procedure was verified on August 24, 2026 by running the documented command without `--climate-delta`. The current consistent-cost, material-aware report uses schema `v0.4.0`, run `090d400500662d004958ad4a`, with 200 annual scenario rows and no missing climate factors or damage values. The manifest records the canonical climate file path and its checksum.

### Damage And Repair Cost

Expected annual repair cost is:

$$
C_{repair,s,y}=V_{installed,s,y}\times r_{damage,s,y}
$$

where:

- $V_{installed,s,y}$ is the active roof's escalated installed value; and
- $r_{damage,s,y}$ is the expected annual damage ratio for scenario $s$ in year $y$.

Example: a 1% expected damage ratio on a $100,000 roof produces a $1,000 expected repair cost.

This is an expected annual value, not a prediction that exactly $1,000 will be spent every year. It represents the probability-weighted long-run average implied by the modeled wind return periods and fragility curves.

### Climate-Risk Cost

When loss of use is disabled:

$$
C_{risk,s,y}=C_{repair,s,y}
$$

When loss of use is enabled and supplied:

$$
C_{risk,s,y}=C_{repair,s,y}+C_{LOU,s,y}
$$

If loss of use is enabled but missing, repair remains available while the combined climate-risk total remains null and is flagged incomplete.

### Avoided Damage

For each alternative:

$$
B_{avoided,s,y}=C_{risk,baseline,y}-C_{risk,s,y}
$$

Interpretation:

- Positive: the alternative has lower expected climate-risk cost than the baseline that year.
- Zero: the alternative and baseline have equal expected climate-risk cost.
- Negative: the alternative has higher expected climate-risk cost that year.

Avoided damage does not, by itself, account for the price of installing the alternative roof.

### Lifecycle Net Benefit And NPV

Annual lifecycle cash flow includes:

- annual climate-risk cost;
- roof installation cost in an installation/replacement year;
- enabled disposal cost when a roof is removed; and
- enabled carbon cost when a roof is removed.

Disposal and carbon are event costs. They are not multiplied by the annual damage ratio.

Annual net benefit is:

$$
B_{net,s,y}=CF_{baseline,y}-CF_{alternative,s,y}
$$

NPV is:

$$
NPV_s=\sum_{y=y_{start}}^{y_{end}}\frac{CF_{baseline,y}-CF_{alternative,s,y}}{(1+r)^{y-y_{start}}}
$$

where $r$ is `real_discount_rate`, and $y_{start}$ and $y_{end}$ are the selected run years. The default rate is `0.02`, or 2%, and the default horizon is 2026-2050.

Interpretation:

- Positive NPV: the alternative costs less than the baseline over the modeled lifecycle after discounting.
- Negative NPV: the alternative costs more than the baseline over the modeled lifecycle after discounting.
- Larger positive NPV: stronger modeled economic performance.
- NPV near zero: the result may be sensitive to roof prices, discount rate, EUL, or vulnerability assumptions.

`real_discount_rate` is the financial cash-flow discount rate. It is separate from `scghg_discount_rate`, which selects a published social-cost-of-carbon series.

## Prerequisites In VS Code

1. Open the `CADENCE` folder in VS Code.
2. Open **Terminal > New Terminal**.
3. Confirm the terminal is at the repository root:

```shell
pwd
```

Expected path:

```text
/Users/andrewjohnson/Documents/GitHub/CADENCE
```

4. Create and install the environment if it is not already installed:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,geo]'
```

If dependencies are already installed and the network is unavailable, refresh console commands with:

```shell
.venv/bin/python -m pip install -e . --no-build-isolation
```

5. Verify the installation:

```shell
.venv/bin/python -m pytest -q
```

## Required Inputs

### 1. Asset Workbook

The source workbook is currently:

```text
Data/User_Inputs/asset_inventory_test_1.xlsx
```

It supplies asset ID, coordinates, current roof type and age, roof area, construction attributes, and replacement value.

### 2. Economics-Ready Asset Parquet

Build it from the workbook and geography sources:

```shell
.venv/bin/cadence-build-economics-assets \
  --assets Data/User_Inputs/asset_inventory_test_1.xlsx \
  --repository-root . \
  --output Data/User_Inputs/asset_features_test_1.parquet
```

The adapter resolves:

- official roof material class;
- ZIP Code Tabulation Area;
- county FIPS;
- CBSA;
- state;
- BLS labor market; and
- normalized labor construction fields.

It writes:

```text
Data/User_Inputs/asset_features_test_1.parquet
Data/User_Inputs/asset_features_test_1.manifest.json
```

### 3. Asset-Scoped Wind Damage Input

Create the vulnerability result when needed:

```shell
.venv/bin/cadence-calculate-year1-damage \
  --assets Data/User_Inputs/asset_inventory_test_1.xlsx \
  --wind-csv Data/Wind_Return_Periods/gev_return_periods.csv \
  --climate-zones Data/Climate_Zones/ClimateZones.shp \
  --fragility-root Data/Fragility_Curves/iecc2021 \
  --output-root cadence_datalake/results/year_1_expected_roof_damage
```

The current asset-scoped result is:

```text
cadence_datalake/results/year_1_expected_roof_damage/
  version=asset-scoped-baseline-year1-v0.2.1/
  asset_runs/
  asset_run_key=0e2de59d4902367c4ca2/
  asset_material_damage_results.parquet
```

The Alternative Analysis uses its wind-grid ID, climate zone, terrain, and six return-period gust values as the annual vulnerability anchor.

### 4. Economics Configuration

The current test configuration is:

```text
Data/User_Inputs/economics_config_test_1.json
```

Important fields:

| Field | Meaning |
|---|---|
| `enabled_cost_streams` | Cost components included in lifecycle results. |
| `installed_cost_overrides` | 2026 installed $/sqft for Asphalt, Metal, and Tile. |
| `material_share`, `labor_share` | Fixed shares used to blend annual material and labor growth. |
| `real_discount_rate` | Financial rate used for discounted benefits and NPV. |
| `scghg_discount_rate` | Selects the social-cost-of-carbon source series. |
| `operational_value_tolerance_percent` | Threshold for calculated source-value versus class-override QA. |

The current config enables material, labor, disposal, and carbon. Loss of use is disabled because no annual downtime input has been supplied.

Installed-cost overrides are assumptions, not observed prices for every class. Tile requires an override because observed source pricing is unavailable.

Operational valuation is consistent across scenarios: calculated source material plus labor is used for every installed and alternative roof when available. If that total is unavailable, the class override is used as a fallback. Inspect `active_cost_source` and `active_cost_fallback_applied` in annual and summary outputs; current Tile options are fallback-based.

### 5. Climate Delta

Current schema `v0.4.0` uses this file by default:

```text
Data/Climate_Delta/wind_climate_scaling.parquet
```

Required columns include `lat_idx`, `lon_idx`, and annual `scale_YYYY` values for the requested source years. Scale values must be finite and positive, and every selected asset wind-grid cell must be present.

The repository file contains 1,387,505 CONUS404 grid rows and covers the current test assets. The pipeline includes this file's checksum in the run ID and manifest, so changing the climate scaling creates a new immutable run.

A non-default file can be provided with:

```shell
--climate-delta path/to/wind_climate_scaling.parquet
```

### 6. Optional Loss-Of-Use Input

To enable loss of use, supply a CSV or Parquet with one row per asset, year, and official material class:

```text
asset_id
year
official_material_id
expected_loss_of_use_days
```

Then add `loss_of_use` to `enabled_cost_streams` and pass:

```shell
--annual-loss-of-use path/to/annual_loss_of_use.parquet
```

Do not enable loss of use and interpret missing values as zero. Missing values remain null and are flagged.

## Run The Alternative Analysis

From the VS Code terminal at the repository root:

```shell
.venv/bin/cadence-run-alternative-analysis \
  --assets Data/User_Inputs/asset_features_test_1.parquet \
  --config Data/User_Inputs/economics_config_test_1.json \
  --asset-scoped-damage cadence_datalake/results/year_1_expected_roof_damage/version=asset-scoped-baseline-year1-v0.2.1/asset_runs/asset_run_key=0e2de59d4902367c4ca2/asset_material_damage_results.parquet \
  --fragility-root Data/Fragility_Curves/iecc2021 \
  --repository-root . \
  --output-root cadence_datalake/results/roof_alternative_analysis
```

The default climate-delta path is used automatically. To specify it explicitly:

```shell
.venv/bin/cadence-run-alternative-analysis \
  --assets Data/User_Inputs/asset_features_test_1.parquet \
  --config Data/User_Inputs/economics_config_test_1.json \
  --asset-scoped-damage cadence_datalake/results/year_1_expected_roof_damage/version=asset-scoped-baseline-year1-v0.2.1/asset_runs/asset_run_key=0e2de59d4902367c4ca2/asset_material_damage_results.parquet \
  --fragility-root Data/Fragility_Curves/iecc2021 \
  --climate-delta Data/Climate_Delta/wind_climate_scaling.parquet \
  --repository-root . \
  --output-root cadence_datalake/results/roof_alternative_analysis
```

The CLI prints a JSON manifest. Record its `run_id` and `report_path`; do not assume the most recently named directory is the correct run.

If the same validated inputs and source checksums are run again, CADENCE returns the existing immutable run instead of overwriting it.

## Output Layout

Current output layout:

```text
cadence_datalake/results/roof_alternative_analysis/
└── schema_version=v0.4.0/
    └── run_id={24-character-hash}/
        ├── annual_scenario_state/
        │   └── year=YYYY/part-00000.parquet
        ├── annual_scenario_damage/
        │   └── year=YYYY/part-00000.parquet
        ├── annual_alternative_analysis/
        │   └── year=YYYY/part-00000.parquet
        ├── alternative_summary.parquet
        ├── alternative_analysis_report.html
        └── run_metadata.json
```

For $N$ assets, expected annual analysis rows are:

$$
N_{rows}=N\times25\times4
$$

Two assets therefore produce 200 annual scenario rows and six summary rows: three alternatives per asset.

### `annual_scenario_state`

Use this dataset to audit lifecycle behavior:

- active scenario material;
- chronological and fragility lookup ages;
- applied EUL and EUL source;
- remaining useful life;
- installation and burnout events;
- removed material; and
- age-cap and mapping provenance.

### `annual_scenario_damage`

Use this dataset to audit vulnerability:

- expected damage ratio and percent;
- return-period damage ratios;
- climate scale factor and rule;
- scaled gust values;
- clamp counts;
- fragility proxy and mapping version; and
- incomplete-data flags.

### `annual_alternative_analysis`

This is the detailed economics fact table. It contains:

- active installed value and cost source;
- annual repair and climate-risk cost;
- installation, disposal, and carbon event costs;
- annual lifecycle cash flow;
- avoided damage;
- annual and cumulative net benefits;
- discount factors; and
- running NPV.

### `alternative_summary.parquet`

This is the fastest table for comparing final 25-year outcomes. It contains one row per asset and alternative, including:

- cumulative avoided damage;
- cumulative discounted avoided damage;
- cumulative net benefit;
- final NPV;
- burnout replacement count; and
- active cost source and fallback status; and
- completeness flags.

### `run_metadata.json`

Use the manifest to confirm exactly what was modeled:

- run and schema versions;
- full run configuration;
- source checksums;
- climate-delta path, checksum, and scaling rules;
- fragility identity;
- row counts;
- EUL and cash-flow timing assumptions; and
- all output paths.

## View The Interactive Graphs In VS Code

The HTML report is self-contained and can be opened directly. On macOS:

```shell
open cadence_datalake/results/roof_alternative_analysis/schema_version=v0.4.0/run_id={RUN_ID}/alternative_analysis_report.html
```

Replace `{RUN_ID}` with the ID printed by the CLI.

If direct file opening does not work, start a local server from the run directory:

```shell
.venv/bin/python -m http.server 8765 \
  --bind 127.0.0.1 \
  --directory cadence_datalake/results/roof_alternative_analysis/schema_version=v0.4.0/run_id={RUN_ID}
```

Then open:

```text
http://127.0.0.1:8765/alternative_analysis_report.html
```

Stop the server with `Control+C` in its VS Code terminal.

## Read The Interactive Report

### Asset Selector

Choose one asset at a time. Every chart then displays that asset's installed baseline and three new-roof alternatives.

### Scenario Lines

| Display label | Scenario |
|---|---|
| Installed roof `{current material}` | `BASELINE_CURRENT` |
| New asphalt | `NEW_ASPHALT` |
| New metal | `NEW_METAL` |
| New tile | `NEW_TILE` |

The baseline label includes the selected asset's material, such as `Installed roof Metal` or `Installed roof Asphalt`. Diamond markers identify installation or replacement years. A discontinuity near a marker can be caused by a roof-age reset, installation cost, disposal/carbon event, or more than one of these.

### Annual Repair Cost

This view compares expected wind repair cost by year.

- Lower is better for wind-damage exposure.
- A rising line can reflect roof aging, cost escalation, increasing wind climate scale, or all three.
- A drop after replacement usually reflects the roof age resetting.
- This chart does not include upfront installation cost.

Use this view to answer: "Which roof has the lowest expected annual wind repair cost?"

### Repair + Loss Of Use

This view adds expected temporary-housing cost when loss of use is enabled and complete.

- If loss of use is disabled, it matches annual repair cost.
- If loss-of-use values are missing, gaps are shown and the report states how many values are unavailable.
- Do not interpret a gap as zero cost.

### Annual Avoided Damage

This view shows baseline climate-risk cost minus alternative climate-risk cost for each year.

- Positive is favorable to the alternative.
- Negative means the alternative has greater expected climate-risk cost that year.
- The installed baseline line is zero by definition.
- This metric excludes the cost of buying the alternative roof.

### Cumulative Avoided Damage

This is the running, undiscounted sum of annual avoided damage.

- An upward slope means the alternative continues accumulating risk savings.
- A downward segment means the alternative is losing ground relative to baseline.
- The final point is the undiscounted 25-year avoided-damage total.

### Discounted Avoided Damage

This is cumulative avoided damage expressed in present-value terms using `real_discount_rate`.

It should generally be smaller in magnitude than undiscounted cumulative avoided damage when savings occur in later years and the discount rate is positive.

### Annual Lifecycle Net Benefit

This includes climate-risk differences and lifecycle event costs.

- Large negative values in 2026 usually represent the upfront alternative installation.
- Positive spikes can occur when the baseline requires an expensive replacement.
- Negative spikes can occur when the alternative requires replacement.
- Positive annual values do not guarantee positive final NPV.

### Cumulative Lifecycle Net Benefit

This is the running undiscounted economic difference between baseline and alternative.

- Above zero: the alternative has cost less in total up to that year.
- Below zero: the alternative has cost more in total up to that year.
- A zero crossing indicates undiscounted break-even within the modeled period.

### Net Present Value

This is the primary discounted lifecycle comparison.

- The final 2050 point is the alternative's 25-year NPV.
- Positive is economically favorable under the modeled assumptions.
- Negative is economically unfavorable under the modeled assumptions.
- Compare alternatives for the same asset; do not rank unrelated assets solely by raw NPV without considering roof size, value, and decision context.

NPV is not the same as avoided damage. An option can reduce wind damage but still have negative NPV because installation and replacement costs exceed those savings.

## Recommended Interpretation Sequence

For each asset:

1. Check `run_metadata.json` for schema version, enabled cost streams, discount rate, and climate scaling.
2. Review **Annual repair cost** to understand relative wind vulnerability.
3. Review **Cumulative avoided damage** to measure gross risk savings.
4. Review installation/replacement markers to understand lifecycle timing.
5. Review **Annual lifecycle net benefit** for major cash-flow events.
6. Review the final **Net present value** point.
7. Check `alternative_summary.parquet` for completeness flags before making a recommendation.
8. Compare the leading option against plausible changes in installed price, discount rate, EUL, and vulnerability assumptions.

A defensible conclusion should distinguish:

- physical risk reduction;
- gross avoided damage;
- lifecycle cost effectiveness; and
- uncertainty or incomplete source data.

## Example: Existing Schema `v0.1.0` Run

The existing demonstration run is:

```text
cadence_datalake/results/roof_alternative_analysis/
  schema_version=v0.1.0/
  run_id=93dc0e1df9f7284842212dbc/
```

It used constant baseline hazard and is retained as a historical example. Its final results were:

| Asset | Alternative | 25-year avoided damage | NPV |
|---|---|---:|---:|
| 1 | New Asphalt | $6,584 | -$16,839 |
| 1 | New Metal | $6,623 | -$6,242 |
| 1 | New Tile | $6,201 | -$10,299 |
| 2 | New Asphalt | $4,110 | $83,556 |
| 2 | New Metal | $4,188 | $104,750 |
| 2 | New Tile | $3,343 | $96,635 |

Interpretation of that historical run:

- New Metal had the largest NPV for both assets.
- All immediate alternatives for Asset 1 had negative NPV despite positive avoided damage.
- All alternatives for Asset 2 had positive NPV.
- Asset 2's large positive NPV was driven partly by the high user-entered baseline replacement value relative to alternative class overrides.
- These values must not be presented as current climate-scaled, consistent-cost `v0.4.0` results.

## Inspect Results From The VS Code Terminal

Print the summary table for one run:

```shell
.venv/bin/python - <<'PY'
import polars as pl

run_root = (
    "cadence_datalake/results/roof_alternative_analysis/"
    "schema_version=v0.4.0/run_id={RUN_ID}"
)
summary = pl.read_parquet(f"{run_root}/alternative_summary.parquet")
print(
    summary.select(
        "asset_id",
        "scenario_id",
        "cumulative_avoided_damage_usd",
        "cumulative_discounted_avoided_damage_usd",
        "cumulative_net_benefit_usd",
        "net_present_value_usd",
        "burnout_replacement_count",
        "repair_cost_incomplete",
        "climate_risk_total_incomplete",
        "event_cost_incomplete",
    ).sort(["asset_id", "scenario_id"])
)
PY
```

Replace `{RUN_ID}` before running the command.

Inspect one year's detailed analysis:

```shell
.venv/bin/python - <<'PY'
import polars as pl

path = (
    "cadence_datalake/results/roof_alternative_analysis/"
    "schema_version=v0.4.0/run_id={RUN_ID}/"
    "annual_alternative_analysis/year=2035/part-00000.parquet"
)
print(pl.read_parquet(path).sort(["asset_id", "scenario_id"]))
PY
```

## Completeness And Quality Checks

Before interpreting results, verify:

- `repair_cost_incomplete` is false;
- `climate_risk_total_incomplete` is false for the streams being interpreted;
- `event_cost_incomplete` is false;
- expected damage ratios are between 0 and 1;
- each asset-year has four scenarios;
- annual analysis row count equals assets × 25 × 4;
- the manifest points to the intended climate-delta source;
- installed-cost overrides are appropriate for the analysis location and roof scope; and
- source-versus-override operational value checks have been reviewed.

## Troubleshooting

| Problem | Meaning | Resolution |
|---|---|---|
| `No such file or directory` for assets | Economics-ready asset Parquet has not been built or path is wrong. | Run `cadence-build-economics-assets` and use its output path. |
| Missing climate delta | Current `v0.4.0` requires the default scaling Parquet or `--climate-delta`. | Build/provide the scaling dataset before running. |
| Climate delta missing selected grid IDs | The climate source does not cover an asset's CONUS404 cell. | Correct the climate dataset; do not substitute a nearby grid silently. |
| Missing fragility partition | Required climate-zone/age curves are unavailable. | Verify `Data/Fragility_Curves/iecc2021` and asset climate-zone assignments. |
| Wage projection missing | Assigned `labor_market_id` is absent from projected wage data. | Rebuild or correct the economics geography crosswalk. |
| Unsupported material | Raw roof type was not resolved to Asphalt, Metal, or Tile. | Correct the workbook value or approved mapping catalog. |
| Loss-of-use graph contains gaps | Downtime values are incomplete. | Supply complete annual loss-of-use data or disable that stream. |
| Report does not open directly | macOS or VS Code cannot launch the local HTML file. | Serve the run directory with `python -m http.server` and open the localhost URL. |
| Output appears unchanged | Identical inputs return the immutable cached run. | Confirm `cache_hit` and `run_id`; changed inputs create a new run. |
| NPV seems unexpectedly large | Calculated current-roof value may differ substantially from class overrides. | Review `operational_value_checks.parquet`, material coverage, labor assumptions, and config overrides. |

## Current Limitations

- Fragility proxies remain interim and low confidence: Asphalt uses `WSF1`, Metal uses `SERBL`, and Tile uses `MSF1`.
- Fragility age is capped at 30 even when physical service life is longer.
- Repair cost is installed value multiplied by expected damage ratio; repair-specific labor and material rules are not yet modeled.
- Installed class overrides are fallback assumptions and may not represent observed local bids; inspect `active_cost_fallback_applied` before interpreting results.
- Tile source pricing remains unavailable and requires an override.
- Tear-off labor is excluded; disposal currently captures tipping fees rather than full demolition labor.
- Landfill is the active end-of-life pathway.
- Loss of use requires a separate annual downtime input.
- The model does not yet include incentives, insurance behavior, energy savings, adoption decisions, BCR, or payback.
- Results are expected values from model assumptions, not guarantees of future storm damage or actual contractor cost.

## Validation Commands

Run focused Alternative Analysis tests:

```shell
.venv/bin/python -m pytest -q \
  tests/test_alternative_analysis.py \
  tests/test_annual_damage.py \
  tests/test_alternative_pipeline.py \
  tests/test_economics_reporting.py \
  tests/test_economics_asset_ingestion.py
```

Run the complete test suite:

```shell
.venv/bin/python -m pytest -q
```

## Related Documentation

- [README.md](README.md) — project overview and all primary commands.
- [docs/economics.md](docs/economics.md) — detailed economics data contracts and formulas.
- [CADENCE_copilot-instructions.md](CADENCE_copilot-instructions.md) — binding architecture and modeling rules.
- [Future_enhancements.md](Future_enhancements.md) — deferred scientific and economic features.
