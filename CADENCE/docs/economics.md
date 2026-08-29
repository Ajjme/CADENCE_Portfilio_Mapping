# Economics Pipeline Guide

## Purpose And Scope

The CADENCE economics module produces annual roof-option cost records for every asset, year from 2026 through 2050, and official V1 material class:

- `OFFICIAL_ASPHALT`
- `OFFICIAL_METAL`
- `OFFICIAL_TILE`

It is a standalone Polars pipeline under `src/cadence/economics`. It can be called from Python, tests, or the `cadence-calculate-roof-economics` command without Prefect. The runtime reads ID-keyed source tables only and performs no geometry operation.

The module currently answers four questions:

1. What is the annual installed replacement value of the current roof and the two alternative material classes?
2. What calculated material and installation-labor value is used for the installed roof, and how does it compare with the class override?
3. What disposal, landfill-carbon, and expected loss-of-use costs are associated with the option?
4. Given an annual expected damage ratio, what is the provisional repair estimate?

It does not yet calculate NPV, BCR, payback, incentives, insurance effects, adoption decisions, burnout replacement, or year-to-year roof-state transitions.

## Package Layout

| Module | Responsibility |
|---|---|
| `contracts.py` | Pydantic configuration and input value contracts |
| `materials.py` | Price geography fallback, class consolidation, material growth, and mass |
| `labor.py` | Geometry defaults, size bucket, occupation productivity, wages, and startup labor |
| `externalities.py` | Disposal, landfill emissions, SC-CO2 monetization, and temporary housing |
| `costs.py` | Option expansion, valuation precedence, enabled totals, repairs, and sanity checks |
| `pipeline.py` | Source orchestration, deterministic run identity, partition writes, and manifest |
| `cli.py` | CSV/Parquet and JSON command-line interface |

## Runtime Flow

```text
precomputed asset_features
  ├── material labels already resolved to OFFICIAL_* IDs
  ├── ZIP / CBSA / state / county IDs
  └── labor_market_id
          │
          ▼
material reference builders ─┐
labor cost builder ──────────┼─> asset × 25 years × 3 classes
external cost builder ───────┤          │
optional hazard economics ───┘          ▼
                                  annual option costs
                                      │       │
                                      │       └─> current-roof sanity checks
                                      └─> immutable Parquet partitions + manifest
```

The annual option expansion is vectorized. There is no Python loop over assets or material options. The pipeline writes one compact file per annual partition.

## Inputs

### Asset Feature Table

The `--assets` argument accepts CSV or Parquet. The runtime requires these columns:

| Column | Contract | Use |
|---|---|---|
| `asset_id` | Unique, nonblank string | Asset key |
| `official_current_material_id` | One of the three official classes | Current-roof counterfactual and removal mass |
| `roof_area_sqft` | Positive number | Installed total, mass, startup-labor allocation |
| `zip_code` | Five-character string | First material-price geography |
| `cbsa_code` | Five-character string | Second material-price geography |
| `state_code` | Two-letter code | Material-price and disposal geography |
| `county_fips` | Five-character string | Temporary-housing lookup |
| `labor_market_id` | Existing BLS MSA/BOS `AREA` string | Annual wage projection lookup |
| `roof_shape` | String or null | Labor productivity key |
| `roof_deck_attachment` | String or null | Labor productivity key |
| `roof_wall_connection` | String or null | Labor productivity key |

All columns must exist. The three roof-construction values may be null only when configuration defaults are provided. `size_bucket` is derived from `roof_area_sqft`:

| Bucket | Area |
|---|---|
| `small` | Less than 1,500 sqft |
| `medium` | 1,500 through 3,000 sqft |
| `large` | Greater than 3,000 sqft |

Material resolution belongs upstream. Raw values such as `asphalt`, `metal`, or `tile` must first pass through the source-aware mapping catalog and approved defaults. The economics runtime does not fuzzy-match them.

Use the geography-backed ingestion adapter to construct this table from the CADENCE workbook:

```shell
.venv/bin/cadence-build-economics-assets \
  --assets Data/User_Inputs/asset_inventory_test_1.xlsx \
  --repository-root . \
  --output Data/User_Inputs/asset_features_test_1.parquet
```

The adapter performs geometry only at ingestion time. Asset coordinates are intersected with the 2020 TIGER ZCTA polygons and the prebuilt BLS labor-area polygons. The selected ZCTA is mapped to a dominant county by summed NHGIS block-to-ZCTA weight and to a dominant CBSA by joint block-to-ZCTA and block-to-CBSA weight. State abbreviation derives from the selected county FIPS. Required geography that is missing or multiply matched is an error, never a nearest-zone fallback.

The adapter also:

- resolves `current_roof_type` through the approved source mapping and official class map;
- renames `roof_age` to `input_roof_age`;
- normalizes roof shape, deck attachment, and wall connection to labor-productivity keys;
- validates the assigned labor market against the wage dataset; and
- emits assignment methods, crosswalk weights, mapping IDs, mapping versions, and default flags.

It writes an adjacent `.manifest.json` containing the schema version, workbook checksum, source path, build timestamp, asset count, and output path.

Example CSV:

```csv
asset_id,official_current_material_id,roof_area_sqft,zip_code,cbsa_code,state_code,county_fips,labor_market_id,roof_shape,roof_deck_attachment,roof_wall_connection
A-1,OFFICIAL_ASPHALT,1800,77001,26420,TX,48201,0010180,flat,6d_6in_12in,strap
```

### Run Configuration

The `--config` argument is a JSON document validated by `EconomicsRunConfig`.

| Field | Required | Contract |
|---|---|---|
| `start_year` | No | Must be `2026`; default `2026` |
| `end_year` | No | Must be `2050`; default `2050` |
| `enabled_cost_streams` | No | Subset of `material`, `labor`, `disposal`, `carbon`, `loss_of_use`; defaults to material and labor |
| `installed_cost_overrides` | Yes | Exactly one Asphalt, Metal, and Tile override |
| `default_roof_shape` | Yes | Nonblank labor lookup default |
| `default_roof_deck_attachment` | Yes | Nonblank labor lookup default |
| `default_roof_wall_connection` | Yes | Nonblank labor lookup default |
| `scghg_discount_rate` | No | `1.5`, `2.0`, or `2.5`; default `2.0` |
| `operational_value_tolerance_percent` | No | Nonnegative source-versus-override percentage; default `20.0` |

Each installed override has:

```json
{
  "installed_usd_per_sqft": 15.0,
  "material_share": 0.7,
  "labor_share": 0.3
}
```

The shares must each be between zero and one and sum to one. They are fixed 2026 weights used to blend annual material and local labor growth. Explicit weights are particularly important for Tile because no observed Tile material price exists.

Material and labor are the installed-cost basis and are always represented by `installed_capex_usd`. `enabled_cost_streams` controls whether disposal, carbon, and loss of use are added to the corresponding enabled totals. The material and labor names are retained in the controlled vocabulary for compatibility with the broader run configuration.

### Optional Annual Hazard Economics

The `--annual-hazard-economics` argument accepts CSV or Parquet. Supported columns are:

| Column | Required when supplied | Contract |
|---|---|---|
| `asset_id` | Yes | Existing asset key |
| `year` | Yes | 2026 through 2050 |
| `official_material_id` | Yes | Candidate official class |
| `expected_damage_ratio` | Optional | Null or value in `[0, 1]` |
| `expected_loss_of_use_days` | Optional | Expected annual downtime days |

The full intended grain is one row per asset, year, and official class. If `expected_damage_ratio` is absent, repair values remain null. If `expected_loss_of_use_days` is absent, expected loss-of-use values remain null. Missing values are never converted to zero.

## Material Cost Construction

### Price Fallback

For each asset and exact core subtype, material prices use this fallback:

```text
ZIP -> CBSA -> state -> national
```

Fallback happens before class consolidation. Price source values map to canonical IDs through `master_mapping_reference_draft.csv`, then to official classes through `official_material_class_map_v1.csv`.

The core members are:

| Official class | Core members |
|---|---|
| Asphalt | 3-tab, architectural, premium architectural |
| Metal | corrugated panel, standing seam, metal tile/shingle form |
| Tile | clay, concrete |

The source price is the arithmetic mean of available exact members at their resolved geographies. Every row records contributors and missing members.

Current expected statuses are:

| Class | Source status |
|---|---|
| Asphalt | Partial: premium architectural is missing |
| Metal | Partial: standing seam and metal tile are missing |
| Tile | `blocked_without_override`: no observed members |

Material prices are stored per roofing square and divided by 100 to produce dollars per square foot.

### Material Growth

Subtype annual material factors are mapped and averaged by official class. For year $y$:

$$
g_{m,y} = f_m^{y-2026}
$$

where $f_m$ is the consolidated annual material escalation factor. These are real relative cost-growth assumptions; general CPI is not applied.

## Labor Cost Construction

The productivity table is keyed by candidate subtype, roof shape, deck attachment, wall connection, size bucket, and occupation. Core subtype values are averaged only inside matching non-material keys.

The module uses:

- all occupation rows in the productivity model;
- `H_MEDIAN_CONSTRAINED_PROJECTED_WAGE` for 2026 through 2050;
- the asset's exact precomputed BLS `labor_market_id`;
- fixed productivity through time; and
- startup person-hours charged once per roof and allocated across roof area.

For occupation $o$:

$$
C_{variable,o,y} = h_{o} \times w_{o,y}
$$

$$
C_{startup,o,y} = \frac{s_o \times w_{o,y}}{A}
$$

The annual labor unit cost is:

$$
C_{labor,y} = \sum_o (C_{variable,o,y} + C_{startup,o,y})
$$

where $h_o$ is person-hours per sqft, $s_o$ is startup person-hours, $w_{o,y}$ is the annual hourly wage, and $A$ is roof area.

The wage projection table contains MSA and BOS rows. State/national fallback is already represented in the baseline wage provenance fields (`SOURCE_LEVEL`, `SOURCE_AREA`, and `IS_IMPUTED`) used to construct those area projections. The runtime therefore requires an exact existing `labor_market_id`; it does not perform another geography fallback.

All current productivity parameters are provisional `ASSUMPTION_V1` values. Outputs retain that status and any geometry-default or wage-imputation flags.

## Removal And External Costs

### Disposal

Removal mass uses the current roof, not the candidate replacement:

$$
M_{removed} = A \times m_{current}
$$

Disposal uses state, then EREF region, then national average:

$$
C_{disposal} = \frac{M_{removed}}{2000} \times F_{tip}
$$

where mass is pounds and $F_{tip}$ is dollars per short ton. Disposal is landfill-only in the current pipeline. EREF values are held constant as fixed 2026-real proxies through 2050.

### Landfill Carbon

The class landfill factor is catalog-mapped and consolidated from core members. Annual emissions and monetized carbon are:

$$
E_{kg} = M_{removed} \times EF_{landfill}
$$

$$
C_{carbon,y} = \frac{E_{kg}}{1000} \times SC\text{-}CO2_y
$$

The run selects the CO2 series at a 1.5%, 2.0%, or 2.5% source discount rate. This selection chooses a published SC-CO2 column; it does not discount CADENCE cash flows.

### Expected Loss Of Use

Expected loss of use is candidate-specific:

$$
C_{LOU,y} = D_{y} \times H_{county}
$$

where $D_y$ is expected annual downtime days and $H_{county}$ is the county's daily temporary-housing cost. The current implementation uses the source's two-bedroom primary rate and holds it constant as a fixed 2026-real proxy.

Loss of use is not replacement CapEx. It is added only to `enabled_economic_total_usd` when enabled.

## Valuation Tracks And Precedence

The pipeline deliberately preserves two separate values:

1. **Source-computed installed value:** annual material plus installation labor; used operationally for every current and alternative roof when available.
2. **Class installed override:** user-provided 2026 installed $/sqft projected with the class's fixed material/labor blend; used only as an explicit fallback when the source-computed total is unavailable.

For class $c$ and year $y$, the installed growth factor is:

$$
g_{c,y} = s_{material,c} g_{material,c,y} + s_{labor,c} g_{labor,c,y}
$$

Operational precedence is:

| Option row | Operational installed value |
|---|---|
| Source-computed total is available | Source-computed annual material + installation labor × roof area |
| Source-computed total is unavailable | Projected class installed override × roof area, flagged as fallback |

The same-material new-roof candidate uses the same calculated unit-cost basis as the installed roof, so repair-cost differences primarily reflect age-specific vulnerability. Rows expose `operational_cost_source` and `operational_cost_fallback_applied`; current Tile coverage uses the override fallback because source material pricing is unavailable.

## Replacement And Repair Formulas

Installed CapEx is:

$$
C_{installed} = C_{operational,sqft} \times A
$$

Replacement economic cost is:

$$
C_{replacement} = C_{installed} + C_{enabled\ disposal} + C_{enabled\ carbon}
$$

The all-enabled analytical total is:

$$
C_{enabled\ total} = C_{replacement} + C_{enabled\ loss\ of\ use}
$$

Provisional repair is:

$$
C_{repair} = C_{installed} \times r_{damage}
$$

Repair does not prorate disposal, carbon, or loss of use. This is a provisional proxy, not a repair-specific labor/material model.

## Outputs

### Directory Layout

```text
{output_root}/
└── schema_version=v0.3.0/
    └── run_id={24-character-hash}/
        ├── annual_roof_option_costs/
        │   ├── year=2026/part-00000.parquet
        │   ├── ...
        │   └── year=2050/part-00000.parquet
        ├── operational_value_checks.parquet
        └── run_metadata.json
```

### Annual Roof Option Costs

The primary key is `(asset_id, year, official_material_id)`. Important output groups are:

| Group | Columns |
|---|---|
| Identity | `asset_id`, `year`, `official_material_id`, `official_current_material_id`, `is_current_roof_option` |
| Growth | `material_growth_factor`, `labor_growth_factor`, `installed_growth_factor`, override shares |
| Source audit | `source_material_usd_per_sqft`, `source_labor_usd_per_sqft`, `source_installed_usd_per_sqft`, `material_price_status`, `missing_member_ids` |
| Operational | `operational_cost_source`, `operational_installed_usd_per_sqft`, `installed_capex_usd` |
| External costs | `disposal_cost_usd`, `carbon_cost_usd`, `expected_loss_of_use_usd` |
| Enabled totals | `replacement_economic_cost_usd`, `enabled_economic_total_usd` |
| Repair | `expected_damage_ratio`, `provisional_repair_cost_usd`, `repair_cost_incomplete` |
| Assumptions | `dollar_basis`, `loss_of_use_incomplete`, `tear_off_labor_excluded` |

Exactly three rows are emitted per asset-year, so the expected row count is:

$$
N_{rows} = N_{assets} \times 25 \times 3
$$

### Operational Value Checks

One current-roof row is emitted per asset-year with:

- source-computed installed value;
- class-override value;
- source-versus-override absolute and percentage variance;
- configured override-tolerance flag; and
- incomplete-source flag.

If source material pricing is incomplete, arithmetic involving that null remains null and the comparison is marked incomplete.

### Run Manifest And Reuse

`run_metadata.json` records:

- deterministic `run_id`;
- schema version;
- UTC timestamp;
- validated run configuration;
- checksums for every source path;
- asset and output row counts;
- real-dollar basis and tear-off exclusion; and
- output paths.

The run ID hashes assets, configuration, optional hazard economics, and source checksums. If the manifest already exists, the pipeline returns it and does not rewrite output files.

## CLI Usage

Install the project:

```shell
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test,geo]'
```

Run with replacement costs only:

```shell
.venv/bin/cadence-calculate-roof-economics \
  --assets path/to/asset_features.parquet \
  --config path/to/economics_config.json \
  --output-root cadence_datalake/results/roof_economics
```

Run with annual repair and loss-of-use inputs:

```shell
.venv/bin/cadence-calculate-roof-economics \
  --assets path/to/asset_features.parquet \
  --config path/to/economics_config.json \
  --annual-hazard-economics path/to/annual_hazard_economics.parquet \
  --repository-root . \
  --output-root cadence_datalake/results/roof_economics
```

`--repository-root` defaults to the current working directory. Input tables must be CSV or Parquet.

## Alternative Analysis

The alternative-analysis pipeline extends the annual cost references into four independent lifecycle scenarios per asset:

| Scenario | Initial state |
|---|---|
| `BASELINE_CURRENT` | The installed material at its entered chronological age |
| `NEW_ASPHALT` | New Asphalt installed at the start of 2026 |
| `NEW_METAL` | New Metal installed at the start of 2026 |
| `NEW_TILE` | New Tile installed at the start of 2026 |

The same-material alternative remains distinct from the installed baseline. An asset with an aging Asphalt roof therefore has both `BASELINE_CURRENT` and `NEW_ASPHALT` rows.

### Lifecycle State

The engine uses one sequential year loop with vectorized Polars operations across assets and scenarios. Installation and burnout replacement occur at the start of the year before wind exposure. Every scenario replaces in kind when its chronological age reaches its applied EUL.

Current-roof EUL precedence is:

1. optional asset `current_roof_eul_years`;
2. the official class physical-service-life default; and
3. an explicit error if neither resolves.

Alternatives and later in-kind replacements use official-class physical defaults. Consolidated fractional defaults round to the nearest whole year, half away from zero; raw and applied values remain in the state output. Fragility lookup age is:

$$
a_{lookup} = \min(\max(a_{chronological} + 1, 1), 30)
$$

Chronological age is never overwritten by the fragility cap. Rows above age 30 carry `age_capped=true`.

### Damage And Benefits

The pipeline reuses each asset's climate zone, terrain, wind-grid ID, and six return-period gusts from the asset-scoped vulnerability result. Baseline wind hazard remains constant from 2026 through 2050 in this phase, while vulnerability changes with active material and roof age.

Annual repair is:

$$
C_{repair,s,y} = V_{installed,s,y} \times r_{damage,s,y}
$$

When loss of use is enabled and available, annual climate risk is repair plus expected loss of use. If downtime is unavailable, repair remains chartable while the combined climate-risk total stays null and is flagged incomplete. Disposal and carbon are charged only when a roof is actually removed; they are never multiplied by damage ratio.

For alternative $s$:

$$
B_{avoided,s,y} = C_{risk,baseline,y} - C_{risk,s,y}
$$

Annual lifecycle cash flow includes climate risk, installation-event CapEx, and enabled disposal and carbon event costs. Net benefit is baseline lifecycle cash flow minus alternative lifecycle cash flow. Positive values mean the alternative is less costly. Financial discounting uses `real_discount_rate`, a decimal that defaults to `0.02` and is separate from the SC-CO2 source-series selector:

$$
NPV_s = \sum_{y=2026}^{2050}\frac{CF_{baseline,y}-CF_{s,y}}{(1+r)^{y-2026}}
$$

### Alternative Inputs And Outputs

Alternative-analysis assets require all economics columns plus `input_roof_age`. `current_roof_eul_years` is optional. The asset-scoped damage Parquet must contain one consistent set of `wind_grid_id`, `climate_zone`, `terrain_id`, and six `rp_*_3sec_gust` values per asset; its three material rows may repeat those invariant fields.

The immutable run writes:

```text
schema_version=v0.4.0/run_id={hash}/
├── annual_scenario_state/year={year}/part-00000.parquet
├── annual_scenario_damage/year={year}/part-00000.parquet
├── annual_alternative_analysis/year={year}/part-00000.parquet
├── alternative_summary.parquet
├── alternative_analysis_report.html
└── run_metadata.json
```

The annual analysis has exactly $N_{assets} \times 25 \times 4$ rows. The self-contained HTML report provides an asset selector, four scenario lines, replacement markers, avoided-damage views, lifecycle net benefits, and NPV. Null values appear as gaps rather than zero.

Run it with:

```shell
.venv/bin/cadence-run-alternative-analysis \
  --assets path/to/asset_features.parquet \
  --config path/to/economics_config.json \
  --asset-scoped-damage path/to/asset_material_damage_results.parquet \
  --fragility-root Data/Fragility_Curves/iecc2021 \
  --repository-root . \
  --output-root cadence_datalake/results/roof_alternative_analysis
```

Use `--annual-loss-of-use` for an optional table at `(asset_id, year, official_material_id)` grain containing `expected_loss_of_use_days`.

Current limitations are interim fragility proxies, age-30 fragility capping, and provisional repair as damage ratio times installed value. The annual Alternative Analysis applies `Data/Climate_Delta/wind_climate_scaling.parquet` by default before fragility interpolation. The pipeline does not yet implement repair-specific work rules, incentives, adoption decisions, BCR, payback, insurance, or changes from one alternative material to another after 2026.

## Python Usage

```python
from pathlib import Path

import polars as pl

from cadence.economics import EconomicsRunConfig, run_economics_pipeline

repository_root = Path.cwd()
assets = pl.read_parquet("path/to/asset_features.parquet")
hazard = pl.read_parquet("path/to/annual_hazard_economics.parquet")
config = EconomicsRunConfig.model_validate_json(
    Path("path/to/economics_config.json").read_text(encoding="utf-8")
)

manifest = run_economics_pipeline(
    assets=assets,
    config=config,
    repository_root=repository_root,
    output_root=repository_root / "cadence_datalake/results/roof_economics",
    annual_hazard_economics=hazard,
)
```

The lower-level public calculation function `build_annual_roof_option_costs` can be imported from `cadence.economics` when already-normalized annual growth, source cost, damage, and external-cost tables are available.

## Validation And Troubleshooting

Run the focused economics tests:

```shell
.venv/bin/python -m pytest -q tests/test_economics_*.py
```

Common failures:

| Error | Meaning | Resolution |
|---|---|---|
| Missing required asset columns | Economics did not receive a complete precomputed feature table | Add the listed columns during ingestion |
| Unsupported current material | Raw or non-V1 material reached runtime | Resolve through the mapping catalog before economics |
| Labor productivity unresolved | Roof construction values/defaults do not match the productivity vocabulary | Use values from the controlled user-input options |
| Wage projection missing | `labor_market_id` is not an existing projected BLS area | Fix the upstream labor-area crosswalk |
| Growth row-count violation | Asset-year-class growth is incomplete or duplicated | Require exactly one row per asset, year, and official class |
| Damage ratio outside `[0, 1]` | Hazard economics violates the repair contract | Correct or quarantine the source row |
| Tile source cost is null | Expected current source gap | Supply the required Tile installed override; do not invent a source price |

## Known Limitations

- Material source prices are partial for Asphalt and Metal and absent for Tile.
- Labor productivity is provisional and low confidence.
- Tear-off labor is excluded; disposal includes tipping fees only.
- Disposal and temporary-housing values are fixed real-dollar proxies through 2050.
- Landfill is the only active EOL pathway.
- The temporary-housing model uses a fixed two-bedroom rate.
- Repair is a damage-ratio proxy, not a repair-specific cost model.
- The module does not perform ingestion geography assignments.
- The module does not implement NPV, BCR, payback, incentives, insurance behavior, adoption, burnout precedence, or stock-flow state transitions.