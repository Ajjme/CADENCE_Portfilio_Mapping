# CADENCE Performance and Calculation Assurance Review

Review date: 2026-09-30. Scope: the current working tree, including uncommitted changes. Perspective: senior data engineering, emphasizing correctness, operational reliability, and measured performance.

## Recommendation

Make cache reuse provably correct before expanding it. Then reduce repeated reference-data work and unnecessary materialization while preserving the existing vectorized calculation engine. Retain the sequential lifecycle year loop and the local DuckDB/Polars/Parquet architecture.

This is an engineering review, not a certification that every calculation or source assumption is correct. Recommendations require numerical equivalence checks as well as performance measurements. No application code is changed by this review.

## Findings First

### 1. Lifecycle Cache Can Miss Changes to Cost Inputs

**Priority: P0, correctness prerequisite.** In [alternative_pipeline.py](../src/cadence/economics/alternative_pipeline.py#L36), the lifecycle pipeline checks its cache before calling the economics pipeline. Its source list does not include the material-price files, material escalation, labor productivity, projected/base wages, or temporary-housing data included by [economics/pipeline.py](../src/cadence/economics/pipeline.py#L192). Changing one of those sources can therefore leave the parent run ID unchanged and return old lifecycle results without reaching the child pipeline's invalidation check.

**Suggested improvement:** compute a lightweight, complete dependency identity before cache lookup. Include the economics dependency identity, calculation-policy versions, and a reproducible code/build identity. Keep prior runs immutable. Only after this is correct should the cache check move ahead of lifecycle-state construction and climate-factor loading.

**Required verification:** mutate each cost dependency independently in an isolated fixture; assert that economics and lifecycle run IDs change, cache reuse is rejected, and affected outputs are recomputed. Assert identical inputs reuse identical outputs. Existing repeatability tests in [test_alternative_pipeline.py](../tests/test_alternative_pipeline.py#L48) do not establish invalidation for those omitted dependencies.

**Evidence:** a runtime comparison of the two source dictionaries confirmed these omissions: `housing`, `labor_base`, `labor_base_wide`, `labor_productivity`, `labor_projection`, `material_escalation`, and `material_price_root`. The stale-return consequence follows from the cache return preceding the economics call; a full source-mutation integration test remains to be added.

### 2. Year 1 Asset Results Can Outlive Their Calculation Inputs

**Priority: P0, correctness prerequisite.** [build_asset_scoped_damage](../src/cadence/reference_data/year1_damage.py#L245) computes a version-aware calculation key, but returns existing asset results using a separate [_asset_run_key](../src/cadence/reference_data/year1_damage.py#L382) that excludes gust values and fragility identity. The asset-result cache check does not compare its saved calculation key with the newly computed one. An unchanged asset/grid/zone assignment can therefore return old damage and old hazard values after a source update.

**Suggested improvement:** include the calculation-cache identity in the asset-run identity, alongside the portfolio-specific identity. Validate that relationship on retrieval. Preserve the useful existing separation between shared numerical calculations and portfolio-specific rows.

**Evidence:** an in-memory probe changed one gust value: the calculation key changed and the asset-run key did not. Changing the supplied fragility identity also changed only the calculation key. This verifies the key mismatch, not a completed end-to-end cache repair.

**Required verification:** rerun the same portfolio after changing gusts or fragility; require a new asset run and fresh values. Also retain the existing test that different asset IDs can share calculations without sharing output rows in [test_asset_scoped_damage.py](../tests/test_asset_scoped_damage.py#L356).

### 3. Market Removal Costs Need a Material-Switch Integration Test

**Priority: P1, calculation risk before optimizing the market engine.** [market_inputs.py](../src/cadence/economics/market_inputs.py#L83) indexes removal costs by candidate material using annual option-cost rows. However, [build_annual_external_costs](../src/cadence/economics/externalities.py#L53) intentionally computes removal from the asset's original current material and repeats it across candidates. The market optimizer later asks for removal of whichever material is then installed. After a material switch, those lookup values can represent the wrong roof mass and carbon factor when disposal/carbon are enabled.

**Suggested improvement:** build removal lookups explicitly at `(asset_id, year, removed_material_id)` grain, using the actual removed material, as the lifecycle event-cost path already does in [build_scenario_event_costs](../src/cadence/economics/externalities.py#L187). Do not equate candidate option identity with removed-material identity.

**Required verification:** force Asphalt -> Metal -> replacement with deliberately different mass and emission factors. Check the second removal cost, trigger threshold, candidate NPVs, and winner against hand calculations. This is a source-traced concern, not a reproduced production incident. Current [market tests](../tests/test_market_study.py#L6) use equal removal costs across materials and cannot detect this distinction.

### 4. Fragility Identity Is File Metadata, Not Content Provenance

**Priority: P1, reproducibility.** [_fragility_identity](../src/cadence/reference_data/year1_damage.py#L353) hashes absolute paths, sizes, and modification times, not file contents. Same-size content replacement with preserved timestamps can escape detection; relocating identical files can unnecessarily invalidate results. The economics and lifecycle `_run_id` functions also do not incorporate a code/build fingerprint.

**Suggested improvement:** publish SHA-256 content digests with immutable reference versions; compose run identities from those manifests and a calculation/build version. Capture a dependency lock or environment fingerprint because Polars row hashing is not a durable cross-version serialization contract. Canonicalize schemas, column order, row order, and configuration collections before hashing.

**Required verification:** source-byte changes, calculation-policy changes, and relevant code changes must invalidate reuse. Reordering equivalent input rows must not change results. Test relocation policy explicitly. Computing each source digest once during controlled publication is preferable to rereading every large source on every request; never substitute unverified timestamps for content identity.

## Performance Priorities

Impact assessments below are hypotheses unless explicitly measured. S/M/L describe relative implementation effort, not delivery commitments. P0 findings above precede cache-related speed work.

| Order | Improvement and Current Evidence | Expected Benefit / Effort | Calculation-Preservation Gate |
| --- | --- | --- | --- |
| 1 | **Batch fragility evaluation.** [annual_damage.py](../src/cadence/vulnerability/annual_damage.py#L93) loops over unique grid/year/age/material keys and calls the curve loader for each. [Year 1 damage](../src/cadence/reference_data/year1_damage.py#L191) similarly loops over keys and materials. [fragility.py](../src/cadence/reference_data/fragility.py#L26) executes a three-Parquet SQL join and aggregation per call. | Likely substantial cold-run improvement on geographically diverse portfolios; M. Group by curve identity, load each curve once per immutable version, interpolate a block of six-gust rows with NumPy, then call the existing matrix integrator on the block. | Compare all six return-period damages, integrated damage, clamp counts, material/proxy IDs, terrain, age caps, and flags. Never average different materials, terrain classes, or grid hazards together. |
| 2 | **Reuse ingestion results.** [ui/pipeline.py](../src/cadence/ui/pipeline.py#L37) always rebuilds economics geography and Year 1 preparation. [attach_nearest_wind_grid](../src/cadence/reference_data/year1_damage.py#L112) reads the full wind CSV and builds a KD-tree before the damage cache check; [economics asset ingestion](../src/cadence/reference_data/economics_assets.py#L373) has no content-keyed reuse check. | Likely substantial benefit for repeated analyses/settings changes; M. Cache validated features by relevant uploaded fields and geography/mapping versions; cache immutable reference indexes separately. Parse the workbook once where contracts permit. | Same geographic assignments, distances, climate-zone rejection, raw labels, defaults, and terrain validation. Changing coordinates or geography rules invalidates features; changing only premium must not force spatial recomputation. |
| 3 | **Move the complete cache check earlier.** [alternative_pipeline.py](../src/cadence/economics/alternative_pipeline.py#L45) builds all lifecycle states, resolves climate factors, and hashes sources before returning a cache hit. | Faster warm runs; M. Use complete manifest identities first, then load or calculate only on a miss. | All dependency-invalidation tests must pass first. Verify required output partitions and their manifest, not just metadata-file existence. A warm hit must preserve every value and provenance field. |
| 4 | **Push reference filters and projections into reads.** [labor.py](../src/cadence/economics/labor.py#L51) eagerly reads projected wages before selecting columns. [materials.py](../src/cadence/economics/materials.py#L12) expands geography fallback candidates per asset. | Lower I/O and intermediate row counts; M. Publish typed reference Parquet, query selected markets/occupations/years with DuckDB or lazy scans, and resolve prices once per distinct geography tuple before joining back to assets. | Preserve exact-subtype ZIP -> CBSA -> state -> national precedence before official-class consolidation. Keep missing-member provenance. Retain the 2026 wage normalization row even when the requested horizon starts later. |
| 5 | **Replace per-asset market execution with batched state evaluation.** [market_pipeline.py](../src/cadence/economics/market_pipeline.py) iterates assets; [market_study.py](../src/cadence/economics/market_study.py#L15) executes recursive, memoized optimization separately for each asset; [market_inputs.py](../src/cadence/economics/market_inputs.py#L83) converts annual costs to Python dictionaries. | Potentially large benefit for market studies; L, high semantic risk. Use columnar lookup arrays and batch equivalent decision states. A backward-year dynamic-programming value pass can support a forward, sequential, vectorized asset-state pass. | First resolve finding 3. Compare every trigger, replacement, material, EUL reset, terminal value, component cash flow, and candidate NPV. Retain the scalar implementation as a small-fixture reference, not the production hot path. No cross-year parallel mutation. |
| 6 | **Reduce full-history materialization.** [alternative_analysis.py](../src/cadence/economics/alternative_analysis.py#L129) retains annual state frames; the lifecycle pipeline subsequently retains state, damage, costs, and analysis. Market input loading eagerly reads full histories. | Lower peak memory and more predictable scaling; M/L. Project away unused columns first; keep immutable asset attributes in a run-linked dimension. Then consider year-sized batches and incremental cumulative state. | Exact `N x years x scenarios` grain, no dropped/duplicated years, same event ordering and null propagation. Preserve schema compatibility through an explicit version change and reader tests if storage layout changes. |
| 7 | **Keep bulk export work out of interactive calculations.** [reporting.py](../src/cadence/economics/reporting.py#L28) turns all report rows into Python dictionaries and a self-contained HTML/JavaScript payload; the lifecycle pipeline always generates it. | Less serialization/memory on the critical path; M. Generate requested asset/portfolio exports on demand as separately versioned artifacts. Continue using DuckDB-filtered UI reads. | Exports must reconcile to stored results, retain unavailable values, and state their scenario coverage. The current HTML excludes `NEW_TILE`; do not silently change that policy while optimizing. Changing mandatory report creation also requires updating manifest/UI contracts. |
| 8 | **Vectorize UI cost allocation and cache small summaries.** [results_data.py](../src/cadence/ui/results_data.py#L209) uses `iterrows()` for installation-event allocations; portfolio charts aggregate raw annual rows. | More responsive portfolio views; S/M. Use vectorized conditional expressions, precompute small annual summaries, and keep detail reads filtered. | Material + labor must equal effective installed CapEx, all displayed components must reconcile to lifecycle totals, and one missing component must not become a partial portfolio total. |
| 9 | **Publish complete runs atomically.** Economics/lifecycle writers create final directories before all outputs finish. [insurance/pipeline.py](../src/cadence/insurance/pipeline.py#L81) already demonstrates staging then renaming. | Avoid expensive failed-run retries and half-published artifacts; M. Reuse this pattern, with a manifest containing expected partitions, row counts, schema, and output digests. | Fault-inject between writes and test simultaneous identical submissions. Readers see either one complete run or no run. Never overwrite a completed run; clean only owned staging artifacts. |
| 10 | **Keep the separate mapping app from becoming a second calculation engine.** [mapping_interface.py](../../Mapping_Application_CADENCE/mapping_interface.py#L100) uses hard-coded service lives, converts missing age to zero, derives rankings from RUL, and applies its function row by row after Excel loading. | Faster reruns and less model drift; M. Prefer displaying verified CADENCE outputs. If retained as a standalone estimator, version and label its separate assumptions, then vectorize/cache ingestion. | Do not claim its RUL ranking equals economic ranking. Test missing/invalid ages, alias handling, replacement years, and agreement with whichever approved model it displays. These formulas are outside the CADENCE pytest coverage described below. |

### Guardrails on These Changes

- Keep one climate trajectory and the existing local DuckDB/Polars/Parquet architecture. The four lifecycle scenarios are roof alternatives, not four climate scenarios. Do not introduce a distributed database, queue, or cloud service to address these local bottlenecks.
- Keep the lifecycle year loop sequential. Vectorize the assets/options inside each year; do not replace stateful aging with an independent cross-product calculation.
- Reuse [climate_delta.py](../src/cadence/reference_data/climate_delta.py#L125) and [insurance/pipeline.py](../src/cadence/insurance/pipeline.py#L63) as examples of selected-column lazy reads already present. Inspect query plans and actual row groups read; a filter on a computed grid ID does not automatically guarantee storage-level pruning.
- Keep joins and output contracts. Removing validation to improve benchmark numbers is not an acceptable optimization. Validate immutable reference data once at publication, but validate per-run key coverage, completeness, and outputs every run.
- Do not build a full CONUS grid x age x material x year damage cube. Batch only requested calculation keys. Cache curve arrays by content/mapping identity, not just by file path.
- Benchmark file sizes before introducing compaction. Preserve required year partitions and compact within staging, before publication. Do not pad small portfolios to arbitrary file-size targets or rewrite old runs in place.
- Audit process-shared Streamlit resources and DuckDB connection use before adding concurrent execution. Bound cache size and use explicit version keys/invalidation; TTL alone does not establish correctness or portfolio isolation.

## Calculation Verification Contract

### Independent Checks, Not Only Old-versus-New Matching

First establish a trusted baseline using small hand-calculated cases. Comparing an optimization with the current implementation preserves existing bugs too, including the cache issues above. Keep a formula/policy register with units, source versions, approved fallbacks, and an independent expected result for every enabled stream.

| Calculation Surface | What Must Be Verified | Existing Test Home and Important Extension |
| --- | --- | --- |
| Ingestion and geography | Unique/nonblank asset IDs; finite WGS84 coordinates; positive area; integer ages; terrain label/ID agreement; exact grid identity; climate-zone coverage; declared nearest-assignment limits and provenance. | [test_asset_scoped_damage.py](../tests/test_asset_scoped_damage.py), [test_economics_asset_ingestion.py](../tests/test_economics_asset_ingestion.py), [test_ui_workbooks.py](../tests/test_ui_workbooks.py). Add geometry/mapping-version invalidation and boundary/tie cases. |
| Climate adjustment | Convert raw m/s using `2.2369362920544` exactly once. Scale six gusts before interpolation. Factor 1 through 2024; source-year factors for 2025-2050; beyond 2050 use the 2040-2050 slope. Reject missing/nonpositive/nonfinite factors. | [test_climate_delta.py](../tests/test_climate_delta.py), [test_annual_damage.py](../tests/test_annual_damage.py). Keep source-year and extrapolation boundary cases even though economics currently restricts its horizon. |
| Fragility and AEP integration | Approved proxy and within-terrain variant average; linear interpolation; exact-endpoint versus out-of-range clamps; age lookup capped at 30 without changing actual age; trapezoidal AEP integration with the existing tails. | [test_asset_scoped_damage.py](../tests/test_asset_scoped_damage.py#L316), [test_annual_damage.py](../tests/test_annual_damage.py). Add batch/scalar equivalence for every terrain/material/age boundary and monotonicity tests only on monotone fixture curves. |
| Material cost and growth | Exact-subtype geography fallback precedes class averaging; price per roofing square / 100 = price per sqft; growth is normalized to 2026; absent members stay flagged; no invented Tile price. | [test_economics_materials.py](../tests/test_economics_materials.py), [test_economics_costs.py](../tests/test_economics_costs.py). Test repeated geography tuples and shuffled reference rows. |
| Material price expansion | Material-specific source anchors, regional/GDP inputs, distance selection, cap rules, missing geometry handling, and proxy flags remain unchanged if preprocessing is accelerated. | [test_material_price_expansion.py](../tests/test_material_price_expansion.py). Add hand-calculated boundary/cap and deterministic nearest-anchor tie cases before changing this separate builder. |
| Labor and demand surge | Per occupation: wage times variable hours/sqft plus startup hours / area; sum all modeled occupations. Surge wage = base P90 times projected median / base median. Fixed override fallback growth remains median-based. | [test_economics_labor.py](../tests/test_economics_labor.py), [test_economics_pipeline.py](../tests/test_economics_pipeline.py). Keep 2026/2050 and later-start horizons, imputation flags, missing wages, and default-geometry cases. |
| Installed value and repair | Source material + labor where complete; otherwise explicit class override with fixed material/labor growth shares. CapEx = operational USD/sqft times area. Repair = installed CapEx times damage ratio. | [test_economics_costs.py](../tests/test_economics_costs.py), [test_economics_contracts.py](../tests/test_economics_contracts.py). Reject nonfinite required values; never include removal/carbon/downtime in prorated repair. The operational override-variance check is a QA comparison, not proof all costs are correct. |
| Disposal and carbon | Removed mass = area times removed-material lbs/sqft. Disposal uses mass / 2,000 times USD/short ton. Carbon uses mass times kg CO2e/lb / 1,000 times USD/metric ton. Preserve state -> region -> national fee provenance and annual SC-GHG series. | [test_economics_externalities.py](../tests/test_economics_externalities.py). Add the material-switch market test in finding 3 and large-area unit-conversion cases. |
| Loss of use and stream toggles | Expected days times daily housing cost; candidate/year-specific joins; separate from installed CapEx. Disabled streams contribute zero by explicit policy; missing enabled streams remain null/incomplete. | [test_economics_externalities.py](../tests/test_economics_externalities.py), [test_economics_costs.py](../tests/test_economics_costs.py). Test the enabled-stream combinations and missing-input patterns. |
| Lifecycle aging and replacement | Installation before annual damage, user EUL then physical defaults, half-away-from-zero rounding, age reset, later burnout using current installed material, same-material counterfactual retained. | [test_alternative_analysis.py](../tests/test_alternative_analysis.py). Add multi-replacement histories and exact EUL boundary cases. Preserve the temporary Tile-as-Metal lifecycle/damage and 1.2x cost policy with explicit provenance. |
| Lifecycle economics | Annual net benefit = baseline lifecycle cash flow minus alternative cash flow. Discount factor = `(1 + real_discount_rate) ** -(year - start_year)`. NPV is the chronological sum of discounted annual net benefits. | [test_alternative_analysis.py](../tests/test_alternative_analysis.py#L116). Add zero-rate, negative-benefit, missing-middle-year, and complete-horizon reconciliation cases. |
| Market decisions | Trigger comparison, EUL precedence in the implemented policy, full future cost evaluation, deterministic ties, replacement payments exactly once, terminal residual value, and unresolved-state propagation. | [test_market_study.py](../tests/test_market_study.py), [test_market_pipeline.py](../tests/test_market_pipeline.py). Compare short-horizon exhaustive enumeration with optimized decision values. Explicitly verify end-of-horizon discount timing; obtain approval before changing the policy. |
| Insurance overlay | Payout = `min(max(annual_repair - deductible, 0), insured_value)`; margin = premium minus payout; loss ratio only when premium > 0; cumulative values stay unavailable after an earlier gap. | [test_insurance_analysis.py](../tests/test_insurance_analysis.py), [test_insurance_pipeline.py](../tests/test_insurance_pipeline.py), [test_ui_insurance.py](../tests/test_ui_insurance.py). Boundary cases include exact deductible, cap, zero premium, and changed policy inputs. |
| Summaries, maps, and exports | Reconcile asset/year/scenario facts to summaries, geographic totals, cost allocations, and charts. Preserve negative outcomes, incomplete totals, deterministic best-option ties, and scenario coverage. | [test_ui_results.py](../tests/test_ui_results.py), [test_economics_reporting.py](../tests/test_economics_reporting.py), [test_ui_market.py](../tests/test_ui_market.py). Add saved-fact-to-displayed-total reconciliation for representative runs. |

For AEP, use an independent scalar trapezoid calculation with points `(1, 0)`, the six `(1 / return_period, damage)` points, and `(0, 1)`. Do not verify it using the same production helper. Under this provisional endpoint rule, six zero damage values still integrate to `0.001`, not zero; a zero-output assertion would silently change the model.

The insurance calculation is explicitly an annual-loss planning proxy. Applying deductible/cap to expected annual repair is generally not the same as the expected payout over a claim-loss distribution. Passing its formula tests does not certify actuarial expected claims. Fragility proxies, the AEP tails, temporary Tile policy, fixed-real externality assumptions, and the market trigger/terminal-value rules also require domain-owner approval, separately from numerical implementation checks.

### Differential and Property-Based Gates

1. Pin reference data, approved policies, configuration, and environment. Establish independent expected fixtures first; version intentional formula corrections separately from performance-only changes.
2. Compare complete keyed outputs, not just row counts, hashes, or portfolio totals. Full-join on `(asset_id, year, scenario_id)` or `(asset_id, year, official_material_id)` and reject missing/extra/duplicate keys. Year 1 must have three material rows per asset; lifecycle and insurance must have four scenarios per asset-year.
3. Compare identifiers, integers, enums, source/fallback/proxy flags, and null masks exactly. Assert required numbers are finite. Compare every numeric output column, including intermediates, before formatting or rounding. Ignore only explicitly nonsemantic metadata such as elapsed time and run timestamp.
4. Prefer exact equality when arithmetic order is unchanged. Proposed starting tolerances for reviewed Float64 differences are `atol=1e-12, rtol=1e-12` for ratios and `atol=1e-6 USD, rtol=1e-12` for money. These require owner approval and magnitude testing, especially for portfolio totals; they are not a license to change selected options or threshold decisions.
5. Require exact event years, selected materials, threshold outcomes, and tie-break outcomes, including near-boundary fixtures. Keep rounding in the display layer unless an approved model rule explicitly rounds a value such as EUL.
6. Test shuffled input order, duplicate source keys, equivalent batched/unbatched execution, splitting and recombining a portfolio, cache hit/miss equivalence, all-null and partially-null groups, and schema round trips. For repeated identical asset attributes, numerical results should match while IDs remain separate.
7. Run cheap vectorized reconciliation and contract checks for every published run, before commit/rename. Run exhaustive scalar oracles, fault injection, and performance regressions in tests/CI, not per asset inside every production request. Emit an immutable validation summary with check names, counts, tolerances, failures, and input identities.

## Evidence Collected

### Existing Test Suite

Executed from the CADENCE project directory using its existing virtual environment:

```sh
.venv/bin/python -m pytest --durations=15 -ra
```

Result: **135 passed, 10 warnings, 3.05 seconds**. The earlier focused lifecycle run also passed all seven selected tests. No application source or existing tests were edited for this review.

Representative call durations from that single full-suite run:

| Existing Test | Duration |
| --- | ---: |
| Repository-data asset-scoped damage integration | 0.53 s |
| Repository economics, 2030-2031 | 0.22 s |
| Repository economics, 2026-2050 | 0.17 s |
| Repeatable alternative-analysis publication | 0.12 s |

These are test timings, not comparative module benchmarks: fixtures differ and some pipeline tests replace expensive dependencies. They do not identify the dominant stage of a 10,000-asset run. Warnings concerned LibreSSL/urllib3 compatibility, unsupported Excel data-validation extensions, and a pyproj/NumPy scalar-conversion deprecation. Preserve workbook validation metadata deliberately when exporting; address runtime compatibility in a separate, tested dependency change.

The numerical probes used Python 3.9.6, Polars 1.36.1, NumPy 2.0.2, and DuckDB 1.4.5 on macOS arm64, with the same project interpreter. No certification of other environments is implied.

### Focused Performance Probe

For 10,000 synthetic six-column damage rows, three timed repetitions after a batch warm-up gave median times of **0.090608 s** for repeated single-row integration and **0.000227 s** for one matrix integration. Outputs were exactly equal. A separate mocked-loader probe confirmed that two grid keys sharing the same zone/age/material/terrain still issue two curve-loader calls.

This measures the integration kernel and call structure only. It excludes fragility SQL, file reads, interpolation, joins, geography, writing, and browser rendering. It is not a promised whole-application speedup.

Reproduce the kernel methodology using the project interpreter:

```python
from statistics import median
from time import perf_counter
import numpy as np
from cadence.vulnerability.expected_damage import integrate_damage_matrix

damages = np.sort(np.random.default_rng(20260930).uniform(size=(10000, 6)), axis=1)
integrate_damage_matrix(damages)
single_times, batch_times = [], []
for repeat in range(3):
	started = perf_counter()
	single = np.array([
		integrate_damage_matrix(row.reshape(1, -1))[0] for row in damages
	])
	single_times.append(perf_counter() - started)
	started = perf_counter()
	batch = integrate_damage_matrix(damages)
	batch_times.append(perf_counter() - started)
np.testing.assert_array_equal(single, batch)
print(median(single_times), median(batch_times))
```

### What Has Not Been Verified

- No full 100/1,000/10,000-asset end-to-end benchmark, browser latency measurement, memory profile, or concurrent-session stress test was run.
- Existing passing tests are not exhaustive formula coverage. The independent oracle extensions, cache source-mutation integration tests, and material-switch removal test above are recommendations, not completed tests.
- No external audit of source datasets, domain assumptions, all fragility partitions, or every possible input combination was performed. The separate mapping application's interactive behavior was inspected in source but not executed.

## Benchmark and Rollout Plan

### Workloads and Instrumentation

Measure the current implementation before each optimization, on the same machine and pinned datasets, without competing benchmark processes. Use 100, 1,000, and 10,000 assets over the supported 2026-2050 horizon, plus a later-start short horizon. At 10,000 assets the current 25-year model produces **1,000,000 lifecycle rows per four-scenario table** and **750,000 economics option rows**, before intermediate joins. These are expected cardinalities, not measured memory usage.

Include both high-reuse and low-reuse portfolios: shared hazard keys versus distinct grids, varied climate zones, ages, terrain, roof geometry, and labor markets. Exercise default and surge labor, enabled externalities, explicit missing inputs, and frequent replacement events. Synthetic fixtures should not expose real asset identities in benchmark artifacts.

Record stage wall time, CPU profile, peak RSS, rows/bytes read and written, intermediate row counts, distinct calculation keys, curve query count, cache hits/misses, and report payload size. Separate workbook parsing, geography, hashing, climate retrieval, fragility, economics, lifecycle, market decisions, insurance, publication, and first UI query. Use standard profiling on the current runtime; choose an OS/interpreter-compatible memory profiler rather than upgrading Python solely to obtain a profiler.

Measure fresh-process cold application caches, repeated warm runs, and one-dependency invalidations separately. State that a fresh process does not necessarily clear the operating-system disk cache. Report median and spread over at least five controlled runs; collect more observations before presenting a p95 latency claim. Keep UI asset selection and year selection as separate workloads from calculation execution.

### Delivery Sequence and Acceptance

| Phase | Deliverable | Acceptance Gate |
| --- | --- | --- |
| A | Independent formula fixtures, cache dependency fixes, run-validation manifest, and market removal-cost clarification. | No stale reuse on relevant input/code changes; exact key/null/provenance checks; domain review of unresolved policies. |
| B | Grouped fragility loading and batched integration; typed, filtered reference reads; reusable ingestion features. | Full differential comparison passes. Curve query count scales with unique curve identities, not asset-year keys. Correct warm runs avoid geography and calculation work. |
| C | Reduced materialization, vectorized cost allocation, summary-first reads, separately published exports, atomic run publication. | Exact reconciliation and schema-reader tests; no partial visible runs; measured reduction in peak memory and interactive latency. |
| D | Batched market optimizer, only after its independent oracle and material-switch checks. | Same approved decisions and economics on exhaustive short-horizon fixtures and representative portfolios; measured improvement at 10,000 assets. |

Agree numeric latency/memory budgets after collecting the end-to-end baseline. A suggested performance-only change gate is at least a 20% median improvement in its targeted measured stage, or a documented memory reduction, with no greater than 5% repeatable regression in other critical workloads outside measurement noise. These are proposed acceptance targets, not observed gains or established service-level objectives. Correctness fixes remain mandatory regardless of speed.

Extend the existing test modules instead of building a second test framework. Keep fast numerical/contract tests on every change; schedule heavier performance and full-data checks separately. Retain baseline output snapshots and publish new immutable run versions so a release can be compared or rolled back without changing prior results.

**Bottom line:** the strongest immediate opportunity is to reuse less work more safely: complete the cache dependency graph, batch shared fragility calculations, and stop repeatedly preparing the same inputs. Release each performance change only when numerical, provenance, and decision-level equivalence are demonstrated.