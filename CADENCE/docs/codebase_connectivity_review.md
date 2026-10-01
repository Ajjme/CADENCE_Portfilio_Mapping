# CADENCE Codebase Connectivity and Bug Review

Review date: 2026-09-30. Scope: the current working tree, including uncommitted changes. This is a review only; application code has not been changed.

Consolidation follow-up: F08 and F11 were resolved after this review. Run discovery now reads the directory on every request, and the supported Results navigation excludes Market Study while preserving its draft code. Regression tests cover both changes. Other findings below remain separate from the dashboard consolidation and have not been certified as resolved.

## Summary

**Yes: loss of use is not connected end to end.** Its daily housing prices and backend arithmetic exist, but the dashboard has no annual downtime input or producer and disables the control. See G01.

The review identified **11 actionable findings**, plus the separate disconnected/deferred features below. The highest-priority issues are stale calculation caches, discarded user service-life inputs, and incomplete histories producing numeric final NPV. Existing tests all pass; focused probes nevertheless reproduced the defects described here.

Priority definitions: **P1** means potentially incorrect analytical results; **P2** means a broken workflow, ignored input, or a release/documentation discrepancy. Draft-only and optional-input exposure are explicitly identified rather than presented as failures of every default run.

## Prioritized Findings

### F01 [P1] Year 1 asset-result cache bypasses changed hazard and fragility inputs

**Location:** [Cache return](../src/cadence/reference_data/year1_damage.py#L253), [Calculation key](../src/cadence/reference_data/year1_damage.py#L334), [Asset key](../src/cadence/reference_data/year1_damage.py#L381).

The calculation cache includes gust values and fragility identity, but the separate asset-result key includes neither. Existing asset results are returned before the new calculation key is used. Updating hazard values within the same grid cells therefore leaves the portfolio consuming old results, including old gust values carried into annual analysis. Changing fragility identity alone also fails to invalidate the Year 1 asset artifact.

**Reproduced:** With the same asset/grid/age, changed all six gusts from 75 to 100 mph and changed the fragility identity. The calculation key changed; the asset key did not. A second pipeline call returned the identical previous manifest and a saved gust of **75**, not **100**. Geography was stubbed for this isolated test; damage calculation and artifact publication used the real implementation.

**Recommended fix/test:** Include the calculation-cache identity in the asset-run identity and validate that linkage before returning a cached artifact. Add repeated-run tests for independently changed gusts and fragility. Preserve old artifacts under their original identities.

### F02 [P1] Alternative Analysis does not invalidate when economics sources change

**Location:** [Parent source list](../src/cadence/economics/alternative_pipeline.py#L238), [Early cache return](../src/cadence/economics/alternative_pipeline.py#L79), [Economics source list](../src/cadence/economics/pipeline.py#L191).

The parent run omits seven dependencies that its economics child hashes: material prices, material escalation, labor productivity, projected wages, base long-form wages, base wide-form wages, and temporary-housing prices. Its cache check occurs before calling `run_economics_pipeline`, so the child's more complete cache cannot correct an already-cached parent result.

**Reproduced:** Passed changed material-price and labor-projection checksum values to the actual key builders. The economics key changed, but the parent alternative-analysis key stayed identical. The parent then has no reason to reach the child on a repeated run.

**Impact:** Updating source costs can leave NPV, repair estimates, insurance overlays, and linked market studies based on an old physical/economic run.

**Recommended fix/test:** Include all transitive economic dependencies, or a fully resolved economics run identity, before the parent cache check. Include an explicit calculation-code/policy version as well; the current parent key does not identify arbitrary code revisions. Test each omitted source independently.

### F03 [P1] Uploaded user EUL never reaches the lifecycle engine

**Location:** [Workbook normalization](../src/cadence/reference_data/economics_assets.py#L60), [Supported input field](../src/cadence/economics/contracts.py#L61), [Lifecycle precedence](../src/cadence/economics/alternative_analysis.py#L62).

`current_roof_eul_years` is supported by the contract and lifecycle engine, but the Excel reader constructs a restricted record without this field. The UI's economics asset snapshot consequently loses an uploaded override. The engine silently uses its material default instead.

**Reproduced:** Uploaded an Asphalt roof aged 2 with EUL 3. The normalized frame did not contain the EUL column. Its baseline replacement occurred in **2048**; preserving the supplied EUL caused replacement in **2027**.

**Recommended fix/test:** Carry the optional field through workbook normalization, validate finite positive values and rounding policy, and preserve it in the saved asset snapshot. Test workbook-to-lifecycle behavior, not only direct DataFrame calls to the engine.

### F04 [P1] Missing years are skipped in cumulative economics and final NPV

**Location:** [Cumulative expressions](../src/cadence/economics/alternative_analysis.py#L363), [Final summary](../src/cadence/economics/alternative_pipeline.py#L186), [Map selection](../src/cadence/ui/results_data.py#L329).

Polars `cum_sum()` resumes after a null. Consequently, an unavailable annual cash flow produces a gap in that year but does not keep later cumulative values unavailable. The summary takes the final numeric result while separately marking an incomplete flag. Overview cards still display that number, and best-replacement map selection does not exclude rows based on those flags.

**Reproduced:** For 2026-2028, annual net benefit was `[-990, null, 10]`. NPV became `[-990, null, -980.388312...]`. The final summary contained that numeric NPV alongside `repair_cost_incomplete=true`.

**Impact:** A partial total can be displayed or ranked as a full-horizon economic outcome. This matters for optional/incomplete inputs; the default all-complete fixture does not expose it.

**Recommended fix/test:** Make cumulative completeness persistent within each asset/scenario history, as the insurance calculation already does. Add missing-first-year and missing-middle-year tests through summary and map selection.

### F05 [P1, Market Study draft] Removal costs stay tied to the original roof after material changes

**Location:** [Original-roof externality calculation](../src/cadence/economics/externalities.py#L66), [Market removal lookup](../src/cadence/economics/market_inputs.py#L98), [Replacement cost consumer](../src/cadence/economics/market_study.py#L62).

The annual option reference correctly prices removal of the asset's original roof for each candidate. Market Study incorrectly treats those candidate rows as removal-price lookups for the evolving installed material. All material keys therefore initially contain the same original-roof disposal/carbon cost, even after a material switch.

**Reproduced:** For an original 1,000 sq ft Asphalt roof in South Carolina, `load_study_inputs` assigned every material disposal **$63.225** and carbon **$4.8375** in 2026. The existing event-cost function calculated removal of a Metal roof of that area as **$30.91** and **$2.365**.

**Impact:** Later replacement costs, replacement triggers, and optimized choices can be wrong when disposal/carbon is enabled. This finding concerns Market Study; the main Alternative Analysis uses the actually removed material through `build_scenario_event_costs`.

**Recommended fix/test:** Build market removal prices by actual outgoing material, area, geography, and year. Test a material-changing lifecycle with enabled disposal/carbon instead of mocking the entire study-input adapter.

### F06 [P2] Blank workbook geometry bypasses configured labor defaults

**Location:** [Token normalization](../src/cadence/reference_data/economics_assets.py#L481), [Default resolution](../src/cadence/economics/labor.py#L201).

Blank Excel construction fields become the literal string `"none"`; blank strings can become `""`. Labor defaults only fill nulls. The uploaded values therefore do not activate the defaults, although defaults are configured and the initial workbook validation succeeds.

**Reproduced:** Blank roof shape, deck attachment, and wall connection normalized to `"none"`. `roof_shape_default_applied` was false, and labor calculation raised `labor productivity could not be resolved for one or more assets`.

**Recommended fix/test:** Preserve missing values as null through ingestion and permit documented defaultable fields at the output-validation boundary. Test actual blank workbook cells with explicit configuration defaults.

### F07 [P2] Numeric text passes workbook validation but crashes portfolio summaries

**Location:** [Display-frame construction](../src/cadence/ui/workbooks.py#L32), [Summary arithmetic](../src/cadence/ui/pages/portfolio.py#L206).

The authoritative readers accept and normalize numeric strings, but `ValidatedPortfolio.display` keeps source `roof_age` and `roof_area_sqft` instead of the normalized numeric values. Summary arithmetic then uses those raw columns.

**Reproduced:** A workbook containing text cells `"10"` and `"1000"` passed `validate_portfolio`. Both display columns had object dtype; the exact summary mean operation raised `TypeError: Could not convert string '10' to numeric`.

**Recommended fix/test:** Build operational display fields from validated numerics while retaining raw source fields separately. Test numeric Excel cells, numeric text cells, and mixed cell types through page rendering.

### F08 [P2] New saved runs do not appear in cached run discovery

**Location:** [Discovery cache](../src/cadence/ui/results_data.py#L53), [Run selector](../src/cadence/ui/pages/results.py#L149).

`discover_runs` is cached by a fixed directory string, with no TTL, publication-generation argument, or invalidation caller. Filesystem changes do not change that cache key. The active-session shortcut can hide the problem until a user chooses another run or loses active state.

**Reproduced:** Initial discovery returned 0 runs. After writing a valid new manifest, cached discovery still returned 0; the uncached function returned 1. Reference lookup found only the Results-page import and call, not an invalidation path.

**Recommended fix/test:** Avoid caching this small directory listing, or explicitly refresh/invalidate it on publication and user refresh. Test discovery before and after a second run is published.

### F09 [P2, Market Study draft] An entirely unresolved study cannot publish its Unknown results

**Location:** [Unknown-row construction](../src/cadence/economics/market_study.py#L85), [Publisher aggregation](../src/cadence/economics/market_pipeline.py#L102).

Unknown rows omit `replacement_cause`. If all rows are unresolved from the first year, the resulting DataFrame has no such column at all. The publisher unconditionally groups that column for EUL/damage replacement counts.

**Reproduced:** A two-year simulation with unavailable annual risk returned `['UNKNOWN', 'UNKNOWN']`. Applying the publisher's aggregation raised `KeyError('Column not found: replacement_cause')`.

**Impact:** The UI reports the study unavailable instead of publishing the promised Unknown stock and unavailable totals. A mixed valid/invalid portfolio may not expose this because valid rows create the missing column.

**Recommended fix/test:** Give every simulation row a stable schema, including explicit unknown replacement-cause/state fields. Add a full publisher test with every asset unresolved in the first year.

### F10 [P2, optional backend input] Tile policy overwrites candidate-specific loss of use

**Location:** [Tile cost transformation](../src/cadence/economics/alternative_pipeline.py#L301), [Loss-of-use consumer](../src/cadence/economics/alternative_analysis.py#L228).

The temporary Tile cost policy copies the entire Metal row and replaces Tile's row. This also copies `expected_loss_of_use_usd`, although the policy describes an installed-cost/vulnerability proxy and the externality contract supports candidate-specific downtime.

**Reproduced:** Supplied Metal loss of use of **$20** and Tile loss of use of **$90**. After the policy transformation, Tile loss of use was **$20**.

**Impact:** A caller supplying verified annual Tile downtime through the CLI/Python API loses that input. The default UI cannot currently trigger this because loss of use is disabled.

**Recommended fix/test:** Restrict the temporary transformation to the explicitly approved fields; preserve independently supplied Tile downtime. Add a three-material loss-of-use regression test before enabling the UI stream.

### F11 [P2] Market Study is exposed despite documentation declaring it hidden

**Location:** [Documented draft boundary](../README.md#L35), [Results tabs](../src/cadence/ui/pages/results.py#L89), [Study action](../src/cadence/ui/pages/results.py#L108).

The README says the unfinished study is deliberately not exposed in the validated dashboard. The current Results page imports its runner, renders a Market Study tab, and enables the action for a matching active run. There is no draft feature gate at that boundary.

**Evidence:** Direct inspection of the current render and callback path. This is a source/documentation discrepancy, not a claim about which code an already-running browser process has loaded.

**Recommended action:** Decide whether this draft should be accessible. Restore the documented gate or explicitly revise the supported scope after addressing draft defects. Add a UI test asserting the chosen exposure policy.

## Disconnected and Deferred Features

These are not all bugs. Some are explicitly documented future work or preserved prototypes. They are listed because a dataset, module, or control existing in the repository does not mean it affects a dashboard run.

### G01 - Loss of use: backend support, no complete dashboard connection

The [portfolio toggle](../src/cadence/ui/pages/portfolio.py#L72) is disabled. The [UI pipeline](../src/cadence/ui/pipeline.py#L64) does not pass `annual_loss_of_use`. The [externality calculation](../src/cadence/economics/externalities.py#L129) requires candidate-specific `expected_loss_of_use_days`, while the housing CSV supplies only daily prices. Missing downtime correctly remains null. The [alternative CLI](../src/cadence/economics/alternative_cli.py#L18) can accept an external annual table; that is not a dashboard input or downtime model. [Market Study](../src/cadence/economics/market_inputs.py#L67) rejects the stream when enabled, even if an external caller supplied downtime to the parent run.

**Connection needed:** An approved downtime producer or upload contract, full asset/year/material coverage validation, lifecycle/age treatment where applicable, UI-to-engine plumbing, and a defined Market Study adapter. Resolve F10 before relying on Tile downtime. Do not simply enable the toggle or fill missing values with zero.

### Other connection gaps

| ID | Area | Actual connection and consequence |
| --- | --- | --- |
| G02 | Global-input workbooks and macroeconomic source folders | [Global workbook](../Data/User_Inputs/global_inputs_test_1.xlsx) is not read by the dashboard pipeline. Defaults come from [JSON configuration](../Data/User_Inputs/economics_config_test_1.json) via [the loader](../src/cadence/ui/pipeline.py#L33), with UI overrides. Editing the workbook, mortgage/WACC inputs, or raw macroeconomic sources does not directly change these runs. Material/labor projection inputs are separate; this is not a claim that those inputs cannot incorporate upstream assumptions. |
| G03 | Expanded county/GDP material prices | [The builder](../src/cadence/reference_data/material_price_expansion.py#L45) produces an expanded county-price artifact, but [the economics lookup](../src/cadence/economics/materials.py#L12) reads only ZIP, CBSA, state, and national price files. County expansion and its Tile proxy are not a consumed runtime price surface. The README acknowledges this boundary. |
| G04 | Operational-value diagnostics | [Variance checks](../src/cadence/economics/costs.py#L218) are computed and [persisted by economics](../src/cadence/economics/pipeline.py#L157), but no dashboard consumer was found. `operational_value_tolerance_percent` affects that artifact, not a visible UI warning or a ranking gate. |
| G05 | Detailed cost provenance | [Labor](../src/cadence/economics/labor.py#L163) computes imputation/default flags and [material pricing](../src/cadence/economics/materials.py#L96) computes member geography levels. The [economics orchestrator's projections](../src/cadence/economics/pipeline.py#L66) discard several of these fields before persisted annual option costs. The UI can show high-level fallback/source status, but not the full explanation of the selected source values. |
| G06 | Duplicate vulnerability implementation | [CLI registration](../pyproject.toml#L33) and [dashboard import](../src/cadence/ui/pipeline.py#L16) use the reference-data implementation. The public [vulnerability package](../src/cadence/vulnerability/__init__.py#L14) instead exports a separate [pipeline implementation](../src/cadence/vulnerability/pipeline.py), while [the compatibility module](../src/cadence/vulnerability/year1_damage.py#L9) re-exports the reference-data version. This is split ownership: fixing one implementation does not fix all entry points. Consolidate behind one implementation and test API identity. |
| G07 | Legacy map rankings | [The separate mapping app](../../Mapping_Application_CADENCE/mapping_interface.py#L99) uses hard-coded service lives and age/RUL thresholds for ranking. It has no CADENCE NPV/ranking connection. Its [README](../../Mapping_Application_CADENCE/README.md) explicitly calls it a design-only prototype, so this is intentional legacy isolation, not a production ranking defect. |
| G08 | Energy, incentives, broader decision economics | No live energy-savings, rebate/incentive, financing, BCR, or payback calculation path was found in the reviewed package. They remain [future work](../Future_enhancements.md#L14). NPV, avoided damage, and fixed-scenario lifecycle replacement **are implemented**; do not classify all economics or all stock-state handling as absent. |
| G09 | Full production orchestration and scale | [Prefect integration remains deferred](../Future_enhancements.md#L40). The annual hazard evaluator loops through [calculation keys](../src/cadence/vulnerability/annual_damage.py#L95), and Market Study [loops over assets](../src/cadence/economics/market_pipeline.py#L76). These are not the fully vectorized production execution described in the architecture. This review did not benchmark 10,000 assets or establish a failure threshold. |

## Connections That Are Present

- Portfolio filtering feeds a derived workbook and the analysis, rather than being display-only. Source and analysis identity changes invalidate active session state.
- The main pipeline connects ingestion, asset-scoped hazard, annual climate scaling, lifecycle state, option costs, scenario event costs, summaries, and result artifacts.
- Start/end year, real discount rate, carbon valuation rate, demand surge, disposal, and carbon controls feed the run configuration. Material and labor are required in the UI; they are not optional switches.
- Disposal and carbon are charged on installation/replacement events in Alternative Analysis, using the actual outgoing roof material. Do not generalize the Market Study issue in F05 to this path.
- Insurance is connected to the selected workbook's policy snapshot and the completed physical run. Its fixed premiums and annual-loss deductible formula are explicitly disclosed proxies, not evidence of a disconnected insurance page. Event-level claim modeling, repricing, shared policy limits, and premium discounts remain outside the implemented model.
- Result maps, cost allocations, and wind-return-period views read saved run artifacts. The cache and completeness findings still apply; connection alone does not guarantee correctness.

## Verification and Limits

From the CADENCE project directory:

```shell
.venv/bin/python -m pytest -q tests/test_economics_externalities.py
.venv/bin/python -m pytest -q --tb=short
```

**Results:** 4 focused externality tests passed; all **136 existing tests** passed. The suite reported urllib3/LibreSSL, openpyxl data-validation, and pyproj/NumPy deprecation warnings, not test failures.

Additional isolated Python probes verified the exact values/errors reported in F01-F10. They exercised real functions with small constructed inputs, temporary XLSX/JSON/Parquet artifacts, and mocked geography where noted. They did not overwrite source datasets or saved runs. F11 and G02-G09 rely on explicit source/call-path inspection; absence claims are limited to the reviewed runtime package. New regression tests are recommended, not committed as part of this review.

Reviewed boundaries included Excel normalization, geography adapters, Year 1 and annual hazard, alternative lifecycle/economics, material/labor/externality inputs, immutable caches, portfolio/results/insurance UI, insurance publication, Market Study, and the legacy mapping prototype. This is not a scientific certification, exhaustive security audit, or proof that all remaining code is bug-free. No fresh full geospatial portfolio run, browser-session verification, or large-portfolio performance benchmark was performed.

## Recommended Order

1. Fix both cache identities (F01-F02), with new versioned artifacts and regression tests. Otherwise subsequent corrections can be masked by old results.
2. Repair EUL ingestion and cumulative completeness (F03-F04), then workbook normalization/defaults (F06-F07).
3. Decide the Market Study exposure boundary (F11), and correct its material-removal and Unknown-publication paths (F05/F09) before treating it as supported.
4. Repair run discovery (F08), then connect loss of use deliberately, including the Tile overwrite (F10/G01).
5. Decide which remaining connection gaps are in scope. Do not silently wire unapproved economic assumptions or legacy rankings into production.