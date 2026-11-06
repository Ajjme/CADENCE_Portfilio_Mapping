# CADENCE Carbon Analysis Implementation Plan

## Status And Objective

This is an implementation plan, not a description of a completed lifecycle-carbon feature.

CADENCE currently calculates landfill emissions from removed roof coverings and monetizes them using a selected annual social cost of CO2. The proposed extension will compare the physical carbon footprint and associated social carbon cost of keeping the existing roof versus installing new Asphalt, Metal, or Tile.

The first release will cover **roof-covering production and landfill end of life for installations, replacements, and damage-related repairs during the selected study period**. Users must see both physical emissions and their monetary social carbon cost. It must not be labeled a complete building or cradle-to-grave lifecycle assessment. Transportation and operational energy are later action items.

Related documentation:

- [Roof Alternative Analysis](ALTERNATIVE_ANALYSIS_README.md)
- [Economics model](docs/economics.md)
- [Streamlit dashboard](docs/streamlit.md)

## Agreed Scope

### Roof Quantities

Use the quantities and mappings already available:

- asset roof area;
- current and scenario roof material identities;
- roof-covering weight per square foot;
- existing service-life and replacement-event schedules.

Use [roofing_lbs.csv](Data/Material_Mass/roofing_lbs.csv) through the existing material-mass lookup. Do not require a new roof-assembly inventory for this release.

**Underlayment, fasteners, decking, insulation, and other non-roof-covering components are excluded from the calculations.** This is a simplifying scope assumption, not a finding that their actual emissions are zero or scientifically negligible. Include this exclusion in documentation, saved run metadata, and the results interface.

### Included In The Initial Extension

- Production emissions for new roof coverings installed at the start of the analysis.
- Production emissions for subsequent roof-covering replacements within the study period.
- Production emissions for new covering material used in damage-related repairs, including repairs to the baseline/current roof.
- Landfill emissions for the actual roof covering removed at each event.
- Landfill emissions for covering removed during repairs, using the quantity actually modeled as removed.
- Physical emissions by asset, scenario, year, and included lifecycle stage.
- Cumulative emissions and emissions avoided relative to keeping the existing roof.
- Separate monetization using the existing social-cost-of-carbon series, displayed alongside physical emissions even when excluded from economic totals.

### Deferred Or Excluded

| Item | Treatment |
|---|---|
| Transportation | Later action item; no explicit delivery, waste-haulage, or other transport calculation in the initial extension. |
| Operational energy | Later action item covering both energy costs and associated emissions; no heating/cooling savings claim in the initial extension. |
| Non-roof-covering components | Excluded under the agreed quantity boundary. |
| Installation equipment and site activities | Not part of the initial production-plus-landfill total; add only after activity data or compatible stage factors are available. |
| Installation waste | Initial quantities equal installed covering quantities, with no added waste allowance. Record this limitation; add a supported waste assumption later. |
| Routine maintenance unrelated to damage | Deferred pending physical activity inputs. Damage-related covering repairs are required in the initial extension, not deferred. |
| Recycling and recovery benefits | Retain landfill-only behavior initially; evaluate alternative pathways separately later. |

Published production or landfill factors may already contain transport or processing within their source boundary. Record that coverage explicitly. Deferring a separate transport calculation does not justify subtracting undocumented portions of an aggregate factor or claiming the source contains no transport.

## Existing Building Blocks

| Building block | Existing resource | Planned reuse |
|---|---|---|
| Covering mass and service-life inputs | [Material mass data](Data/Material_Mass/roofing_lbs.csv) and [material lookups](src/cadence/economics/materials.py) | Resolve covering quantities using existing official-class mappings. |
| Scenario and replacement timing | [Alternative Analysis engine](src/cadence/economics/alternative_analysis.py) | Identify installed and removed materials for each event. |
| Landfill emission factors | [End-of-life factors](Data/Carbon/roofing_eol_emission_factors.csv) | Preserve current landfill calculation and provenance. |
| Social-cost series | [SC-GHG source](Data/Carbon/table_a5_1_scghg_unrounded_2020_2080.csv) | Select the event-year CO2 valuation at 1.5%, 2.0%, or 2.5%. |
| Removal-event calculator | [Externalities](src/cadence/economics/externalities.py) | Reuse mass resolution and outgoing-material logic rather than duplicate it. |
| Run publication | [Alternative pipeline](src/cadence/economics/alternative_pipeline.py) | Save reproducible physical and monetary outputs with source checksums. |
| Results presentation | [Results data](src/cadence/ui/results_data.py) and [results page](src/cadence/ui/pages/results.py) | Present carbon separately from installation costs and expected wind damage. |

The key missing inputs are defensible **roof-covering production emissions factors** and a **validated physical quantity model for damage-related repairs**. Existing annual monetary damage estimates alone do not establish how much covering is repaired.

## Required Production Data

### Source Selection

Obtain compatible Environmental Product Declarations (EPDs) or documented industry-average lifecycle datasets for the modeled coverings. Target production-stage coverage such as A1-A3, rather than a whole-life total that would overlap separately calculated end of life.

For each factor, retain:

- source ID, publisher, document reference, publication year, and validity period;
- source material/product and mapping to the existing material catalog;
- geography and manufacturing technology where available;
- declared unit, reference thickness or mass where applicable, and conversion basis;
- lifecycle stages included and excluded;
- global-warming-potential method and time horizon;
- factor value and units;
- recycled-content and recycling-allocation assumptions;
- proxy status, confidence, and approval status.

Do not treat asphalt subtypes, different metals, or clay and concrete tile as interchangeable without an explicit aggregation or proxy rule. Reuse catalog identities, but do not assume that an approved price or mass mapping also approves a production-carbon mapping.

Normalize compatible factors to a documented runtime unit, preferably `kg CO2e/kg of covering`. Area-based factors may be used only when their declared covering specification is compatible with the modeled quantity. Do not infer emissions from material prices or labor costs.

For class averages, calculate member-level emissions using compatible member quantities and factors before aggregation where those quantities are available. Do not blindly multiply an average mass by an independently averaged factor; document any class-level approximation.

### Missing Inputs And Approval

- Require production-factor coverage for every material used in the selected scenarios.
- Missing required factors must block the expanded carbon mode with an actionable message, not silently contribute zero.
- Missing required repair-quantity inputs or an unapproved damage-to-quantity method must also block the expanded mode; do not silently omit baseline repair emissions.
- Mark provisional mappings explicitly.
- Validate finite values and valid units. Reject unsupported negative factors; accept negative values only under an explicitly reviewed accounting method.
- Preserve the existing landfill-only mode while production data is being assembled.

## Calculation And Accounting Rules

### 1. Reuse The Existing Scenario Events

For each installation or replacement event, identify:

- the newly installed covering material;
- the actual outgoing covering material;
- the event year;
- roof area and the applicable mass per square foot for each material.

The new and removed masses need not be equal.

```text
installed_mass_kg = roof_area_sqft * installed_weight_lb_per_sqft * 0.45359237
removed_mass_lb = roof_area_sqft * removed_weight_lb_per_sqft
```

### 2. Calculate Production And Landfill Emissions

For a compatible mass-based production factor:

```text
production_kg_co2e = installed_mass_kg * production_factor_kg_co2e_per_kg
landfill_kg_co2e = removed_mass_lb * landfill_factor_kg_co2e_per_lb
included_total_kg_co2e = production_kg_co2e + landfill_kg_co2e
```

Use the event year as the initial accounting-year convention for production and removal. Document that this is a model timing convention, not a reconstruction of actual manufacturing dates or the time profile of landfill emissions.

Years without a full-roof installation/replacement have zero full-roof event emissions, but can still have repair emissions. Excluded stages remain identified as excluded, not presented as measured zeros.

### 3. Include Damage-Related Repairs

Apply the same physical repair methodology to the current-roof baseline and every alternative, using the material active when damage occurs.

Required repair inputs or modeled outputs are the area of new covering installed and the area of damaged covering removed, with their respective material IDs. Reuse existing covering weights; no quantities for excluded assembly components are needed.

```text
repair_installed_mass_kg = repair_installed_area_sqft * repair_installed_weight_lb_per_sqft * 0.45359237
repair_removed_mass_lb = repair_removed_area_sqft * repair_removed_weight_lb_per_sqft
repair_production_kg_co2e = repair_installed_mass_kg * repair_production_factor_kg_co2e_per_kg
repair_landfill_kg_co2e = repair_removed_mass_lb * repair_landfill_factor_kg_co2e_per_lb
annual_production_kg_co2e = full_roof_production_kg_co2e + repair_production_kg_co2e
annual_landfill_kg_co2e = full_roof_landfill_kg_co2e + repair_landfill_kg_co2e
included_total_kg_co2e = annual_production_kg_co2e + annual_landfill_kg_co2e
```

The formulas also support expected annual repair quantities, provided they are derived from a validated damage-to-covering-quantity model. The current HAZUS building-loss proxy and monetary repair costs must not be assumed to equal the fraction of roof covering physically replaced. Selecting and validating that relationship is a prerequisite, not a later enhancement.

Record whether quantities are expected annual values or based on specified repair events. Forecast outputs must be labeled **modeled emissions** or **expected annual emissions**, not measured historical emissions. CO2e is the greenhouse-gas equivalent quantity, not a measurement of elemental carbon.

Preserve the existing start-of-year replacement-before-damage convention. Subsequent repair quantities in that year apply to the newly active roof. A single physical intervention must not be counted both as a full replacement and as repair; distinct later damage repairs may legitimately occur in a replacement year. Partial repairs must not silently reset the whole roof's age or create another full replacement.

### 4. Treat The Baseline Consistently

- Historical production emissions of the existing roof are already incurred and are excluded from this forward-looking comparison.
- Merely retaining the current roof incurs no additional covering production or removal emissions.
- If the current roof is damaged and repaired, include production of the repair covering and landfill emissions for the damaged covering removed, plus their monetary carbon cost.
- If the current roof reaches a modeled full replacement, include production and removal emissions for that replacement.
- Immediate-replacement alternatives incur production of the new covering and landfill emissions for the existing covering.
- Later replacements use the outgoing material actually present in that scenario.
- Do not force disposal at the final analysis year when the roof remains in service.
- Report results as emissions within the selected horizon, currently constrained to 2026-2050, rather than lifetime emissions beyond that horizon.

### 5. Preserve Material Identity Despite Existing Proxies

The temporary `NEW_TILE` policy currently borrows Metal lifecycle timing and vulnerability. Carbon factors and covering mass must still follow the actual Tile material identity, not automatically inherit Metal values.

Record the inherited replacement timing as a limitation of Tile carbon comparisons. Do not change the existing lifecycle or vulnerability policy as an incidental part of this extension.

### 6. Separate Footprint From Monetization

```text
included_total_tonnes_co2e = included_total_kg_co2e / 1000
carbon_cost_usd = included_total_tonnes_co2e * selected_accounting_year_scc
avoided_kg_co2e = baseline_included_kg_co2e - alternative_included_kg_co2e
```

- Physical emissions are not financially discounted.
- Positive avoided emissions indicate a reduction; negative values indicate an increase.
- The social-cost rate selects a valuation series; it does not change physical emissions.
- The financial discount rate discounts monetary cash flows and net benefits only.
- Confirm the source social-cost dollar year and convert consistently to the model's real-2026 dollar basis before claiming dollar comparability.
- Treat monetization of aggregate CO2e with the CO2 social-cost series as an explicit approximation. Do not additionally apply CH4 or N2O valuations to the same CO2e total.
- Distinguish social carbon cost from an actual contractor invoice, carbon tax, or insurance payment.
- Show both physical emissions and monetary carbon cost to the user. The carbon-cost inclusion switch controls contribution to lifecycle economic totals, not visibility of the footprint or its valuation.
- Keep ordinary repair material/labor expenditure separate from the repair's social carbon cost; do not replace the existing repair-cost calculation with carbon valuation.

When expanded carbon is enabled, its total must replace the existing landfill-only contribution to lifecycle cash flow, not be added on top of it. Keep production and landfill components available for reconciliation.

## Implementation Sequence

### Phase 1: Approve And Catalog Inputs

- [ ] Record the agreed covering-only boundary and deferred stages.
- [ ] Acquire production factors for all modeled materials.
- [ ] Review source boundaries, units, GWP methods, and compatibility.
- [ ] Approve explicit material mappings, aggregation rules, and proxies.
- [ ] Verify landfill-factor coverage and potential overlap with production sources.
- [ ] Resolve the social-cost source dollar basis and monetization convention.
- [ ] Approve and validate the physical damage-repair quantity methodology for the baseline and all alternatives, including uncertainty and expected-value interpretation.

### Phase 2: Build The Physical Carbon Ledger

- [ ] Add a validated production-factor loader using existing catalog conventions.
- [ ] Reuse scenario events and existing mass lookups.
- [ ] Calculate production and landfill quantities separately for each asset/scenario/year.
- [ ] Calculate repair covering quantities and their production/landfill emissions independently of full-roof events.
- [ ] Record event-versus-expected-annual provenance and prevent duplicate repair/replacement accounting.
- [ ] Add cumulative and baseline-relative physical emissions.
- [ ] Save an annual carbon artifact and a scenario summary.
- [ ] Record source identities, units, included stages, exclusions, proxy flags, and completeness.

Proposed annual fields include `asset_id`, `scenario_id`, `year`, installed and removed material IDs, installed and removed mass, repair installed/removed area and mass, `repair_production_kg_co2e`, `repair_landfill_kg_co2e`, `production_kg_co2e`, `landfill_kg_co2e`, `included_total_kg_co2e`, `avoided_kg_co2e`, and stage-level monetary costs. Production and landfill totals include both full-roof and repair contributions; retain separate components for reconciliation. Keep source-factor and repair-method provenance in a linked immutable lookup or the ledger itself.

### Phase 3: Integrate Economics And Publication

- [ ] Add an explicit, versioned carbon scope: existing landfill-only versus expanded production-plus-landfill including damage-related repairs.
- [ ] Preserve the current scope by default until the expanded mode is validated and deliberately selected.
- [ ] Compute physical footprints and display their monetary valuation independently of whether carbon costs are included in economic totals.
- [ ] Wire the enabled carbon cost into lifecycle cash flow, net benefit, NPV, cost allocations, and exported reports without double counting.
- [ ] Keep avoided wind damage separate from avoided carbon.
- [ ] Include carbon scope, source checksums, and methodology version in run identity.
- [ ] Version new artifacts/contracts as needed and preserve immutable historical runs.
- [ ] Label legacy runs as landfill-only; do not reconstruct missing production emissions from current inputs.

### Phase 4: Add Results And Documentation

- [ ] Show annual and cumulative tonnes CO2e for the baseline and all three alternatives.
- [ ] Show production and landfill breakdowns, distinguish full-roof events from repairs, and show avoided emissions versus baseline.
- [ ] Show physical emissions (kg or tonnes CO2e) and monetary social carbon cost (USD) side by side for each scenario, year, and cumulative summary.
- [ ] Clearly display baseline repair emissions and cost; do not imply that keeping the existing roof always has zero carbon impact.
- [ ] Label modeled/expected physical emissions accurately and distinguish annual monetary valuation from discounted present value.
- [ ] Support asset and portfolio views with reconciled totals.
- [ ] Display the study horizon, source/proxy status, and excluded stages.
- [ ] Explain that changing the carbon valuation rate affects dollars, not tonnes.
- [ ] Update the economics, Alternative Analysis, and Streamlit documentation.

## Verification And Acceptance Criteria

- Hand-calculated examples verify square-foot, pound, kilogram, and tonne conversions.
- Initial replacement charges new-covering production and old-covering landfill exactly once.
- Later replacement uses the correct outgoing material and event-year valuation.
- A baseline roof with neither replacement nor repair has no new production or landfill emissions.
- A baseline roof with repairs but no full replacement has the correct nonzero repair production/landfill emissions and monetary carbon cost.
- A hand-calculated partial repair verifies installed/removed quantities, emissions, and accounting-year valuation.
- Years without full replacement can have expected repair emissions; only years with no replacement and no repair have zero included emissions.
- Repairs use the active scenario material, including after a start-of-year replacement, without resetting whole-roof age.
- The same physical intervention is never counted as both repair and replacement.
- Missing or unapproved repair-quantity methodology cannot produce a complete-looking expanded total.
- Tile uses Tile mass and production factors even while its replacement timing follows the temporary policy.
- Incompatible units, unresolved mappings, and missing required factors produce explicit errors.
- Portfolio totals equal asset totals; summaries reconcile to annual stage totals.
- Changing the SCC rate changes costs but not physical emissions.
- Changing the financial discount rate changes discounted outcomes but not physical emissions.
- Excluding carbon from economic totals removes its contribution without hiding the physical footprint or displayed monetary valuation.
- Expanded totals include existing landfill emissions once, not twice.
- Legacy mode retains existing numerical behavior and old runs remain readable.
- New source data or methodology produces a new run identity.
- UI and exports consistently label excluded components, deferred stages, and study-period coverage.
- UI and exports show both emissions and monetary carbon cost, identify expected/model-derived quantities, and reconcile repair plus full-roof contributions.

Use the existing economics and UI test suites, extending the focused externalities, alternative-analysis, pipeline, and results tests. No runtime calculation changes are made by this planning document.

## Later Action Items

### Transportation

See the separate [Transportation Analysis Implementation Plan](TRANSPORTATION_ANALYSIS_README.md) for existing landfill-data leads, spatial nearest-neighbor matching, road-distance selection, haulage costs, and emissions.

- [ ] Obtain or approve source-to-site and site-to-disposal distances.
- [ ] Select transport modes and compatible freight-emissions factors.
- [ ] Apply installed, removed, and waste masses to the correct routes.
- [ ] Check overlap with transport already included in production or landfill sources.
- [ ] Publish transportation as a distinct stage rather than silently changing existing factors.

### Operational Energy Costs And Emissions

- [ ] Obtain roof thermal and solar properties plus relevant building/HVAC assumptions.
- [ ] Select a validated method for heating and cooling energy changes by climate and roof option.
- [ ] Obtain energy prices and electricity/fuel emissions trajectories.
- [ ] Calculate annual energy-cost differences and operational emissions separately.
- [ ] Apply financial discounting to monetary outcomes, not physical emissions.
- [ ] Include these effects only when supported; do not infer savings from roof material names alone.

### Other Extensions

- [ ] Add installation waste and site-energy emissions with defensible data.
- [ ] Develop physical quantities for routine maintenance beyond the required damage-repair scope.
- [ ] Add recycling/recovery pathway shares and compatible factors; report beyond-boundary benefits separately where required by the accounting method.
- [ ] Revisit the Tile timing proxy and material-class aggregation assumptions.
- [ ] Evaluate longer study periods if a complete roof lifetime comparison is needed.
- [ ] Revisit excluded assembly components only if the agreed project boundary changes.

## Completion Definition

The initial extension is complete when a reproducible run reports validated **production-plus-landfill roof-covering emissions for installations, replacements, and damage-related repairs within the study period**, compares them against the keep-current baseline, and shows users both physical emissions and their consistently monetized social carbon cost. Including that valuation in lifecycle economic totals remains independently selectable.

Transportation, operational energy, and other excluded stages must remain visibly out of scope until their later action items are completed.
