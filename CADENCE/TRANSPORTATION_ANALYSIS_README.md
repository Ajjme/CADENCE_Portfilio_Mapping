# CADENCE Transportation Analysis Implementation Plan

## Status And Objective

This is a separate implementation plan; no transportation calculations are enabled by this document.

Extend the roof-covering analysis with:

- monetary transportation/hauling costs;
- physical transportation emissions in kg or tonnes CO2e;
- separate monetized social carbon costs;
- traceable facility selections and distance assumptions.

Transportation remains deferred from the initial [carbon-analysis implementation](CARBON_ANALYSIS_README.md). Build this extension after its required source data and methods are validated.

The first transportation increment should model **removed roof covering hauled from an asset to an eligible landfill**. Add delivery of new covering in a subsequent increment when supplier locations and delivery assumptions are available.

## Scope

- Use existing roof-covering areas, material identities, and mass lookups.
- Include full replacements and damage-related repairs for the baseline and all alternatives.
- Retaining an undamaged existing roof does not create a transport activity.
- Exclude underlayment, fasteners, decking, insulation, and other non-covering components, consistent with the carbon plan.
- Keep operational energy costs/emissions outside this plan.
- Do not add a whole-roof haul for a partial repair; use the removed repair quantity.
- Keep haulage charges, landfill tipping fees, and social carbon costs distinct.

## Existing Source Leads And Verification

The user expects landfill locations to exist in one of the project repositories. Reuse that dataset if it is suitable rather than creating a duplicate source.

Repository inspection identified these leads:

- [Economic-Externalities-Research-Database disposal folder](https://github.com/Ajjme/Economic-Externalities-Research-Database/tree/7209033582e0c277da16aa5932d24a016b9cb4c5/Failure%20Costs/disposal)
- [EREF-2021-LandfillTipFeeList.xlsx](https://github.com/Ajjme/Economic-Externalities-Research-Database/blob/7209033582e0c277da16aa5932d24a016b9cb4c5/Failure%20Costs/disposal/EREF-2021-LandfillTipFeeList.xlsx)
- [Disposal research plan](https://github.com/Ajjme/Economic-Externalities-Research-Database/blob/7209033582e0c277da16aa5932d24a016b9cb4c5/Failure%20Costs/disposal/readme.md)

The workbook's presence is confirmed, but its facility addresses, coordinate coverage, licensing, and current operating-status coverage have **not** been verified. The research plan also describes a proposed recycling-facility directory; that is not proof of an implemented landfill-coordinate dataset.

The current CADENCE [disposal input](Data/Disposal/EREF_2024_Tipping_Fees_Parsed.csv) provides geographic tipping-fee estimates, not a verified facility routing database.

### Source Discovery Tasks

- [ ] Inspect the candidate workbook's sheets and fields.
- [ ] Locate any existing landfill/facility coordinates or asset-to-landfill assignments in related repositories.
- [ ] Record the authoritative repository, path, source version, license, checksum, and update date.
- [ ] Confirm geographic coverage and distinguish landfills, transfer stations, and recycling facilities.
- [ ] Verify which facilities accept construction/demolition roofing waste and the modeled material types.
- [ ] Validate coordinates and facility access points; geocode addresses only if coordinates are missing and an approved process is available.
- [ ] Confirm current operation and document whether facility status is assumed fixed over future study years.
- [ ] Do not represent an unverified facility directory as complete national coverage.

## Matching Method: Spatial Nearest-Neighbor Search

The general term is **spatial nearest-neighbor matching** or a **nearest-facility spatial join**. For several candidate facilities, use a **k-nearest-neighbor search**.

There are two different distance questions:

1. **Geographically nearest eligible landfill:** shortest great-circle distance between the asset and eligible facility coordinates.
2. **Nearest eligible landfill by road distance:** shortest feasible driving route among eligible facilities.

The first is useful for finding candidates. The second is the preferred distance basis for haulage. A landfill across a river may be geographically close but require a much longer road trip.

### Proposed Workflow

1. Validate asset and facility coordinates and normalize their coordinate systems.
2. Filter facilities by known operating status, facility type, material acceptance, and applicable access restrictions.
3. Use a spatial index to find geographically nearby eligible candidates.
4. Compute feasible road distances to candidate facility entrances using an approved local routing dataset/engine.
5. Select the eligible destination with the shortest road distance; use a stable facility-ID tie-breaker.
6. Save the selected facility, distance method, route distance, eligibility evidence, and source versions.
7. Treat the result as a modeled destination, not evidence that a contractor actually uses that landfill.

CADENCE already uses a unit-sphere `cKDTree` for [nearest wind-grid matching](src/cadence/reference_data/year1_damage.py). Reuse or extract its general coordinate/indexing approach where appropriate, but do not reuse wind-grid IDs or treat angular latitude/longitude coordinates as planar distances.

A fixed number of candidates does not guarantee the globally shortest road route. Either:

- expand the candidate search until a valid geographic lower-bound stopping rule proves that no remaining facility can improve the selected route; or
- explicitly label the result "shortest routed distance among searched candidates" and record the search coverage.

For a distance-based stopping rule, account for route snapping/access connectors so the comparison uses consistent endpoints. Do not apply a distance lower bound to a travel-time objective.

### Failure And Proxy Policy

- No eligible facility, invalid coordinates, or no drivable route must produce an explicit unavailable status, not zero distance or zero cost.
- Unknown material acceptance must not silently count as confirmed eligibility.
- A straight-line-distance proxy may be offered only as an explicitly approved mode, clearly labeled as not road distance.
- Do not invent a road-distance multiplier without a documented calibration.
- Do not cross an international border or assume truck/ferry access without an explicit routing policy.
- Flag distances outside the approved service range; do not silently select a distant facility.
- Do not silently substitute a transfer station for a landfill. Transfer-station routing requires its onward haul and allocation rules.
- Use local routing by default. Do not send private asset coordinates or other portfolio data to an external routing/geocoding provider without authorization.

## Required Data

### Facility Reference

Minimum fields: `facility_id`, name, facility type, address, latitude, longitude, coordinate/access-point quality, operating status and date, accepted roofing materials, source ID, and source version.

Keep acceptance restrictions and status evidence separate from assumed defaults. A fee record alone does not establish that the facility can accept the modeled load.

### Asset-To-Facility Lookup

Save `asset_id`, removed material ID or acceptance group, selected `facility_id`, geographic distance, one-way road distance, optional travel time, matching method, candidate coverage, route status, routing-data version, and assignment confidence.

Assignments may differ by removed material or facility-status period. Do not assume one landfill is valid for every material and every year.

Perform spatial/routing work during preprocessing, not inside the annual economic loop. The annual engine should join immutable, ID-keyed assignment tables. Cache keys must include coordinates, eligibility rules, facility versions, and routing configuration.

### Haulage And Emission Inputs

Obtain or approve:

- truck/transport mode;
- usable payload and, where relevant, volume limits;
- loaded and empty travel assumptions;
- dedicated versus shared-load allocation;
- distance, time, or tonne-distance rates and fixed charges;
- rate dollar year and escalation convention;
- compatible emission factors and their units/boundaries;
- fuel, electricity, and loading assumptions where required by the selected method.

Do not assume weight alone determines truck capacity for bulky covering waste.

## Quantities, Costs, And Emissions

### Removed Quantities

```text
removed_mass_kg = removed_covering_area_sqft * covering_weight_lb_per_sqft * 0.45359237
removed_mass_tonnes = removed_mass_kg / 1000
```

For full replacement, removed covering area is the roof area. For repair, use the physical removed-covering quantity specified by the carbon repair methodology.

### Choose One Compatible Emissions Method

**Tonne-distance method**, where a source provides a compatible freight factor:

```text
loaded_tonne_km = removed_mass_tonnes * loaded_one_way_distance_km
transport_kg_co2e = loaded_tonne_km * factor_kg_co2e_per_tonne_km
```

Record whether the factor already includes utilization and empty-running assumptions. Do not automatically double tonne-distance to represent an empty return trip.

**Vehicle-distance method**, where truck activity is modeled explicitly:

```text
loaded_vehicle_km = trip_count * loaded_distance_per_trip_km
empty_vehicle_km = trip_count * empty_distance_per_trip_km
transport_kg_co2e = loaded_vehicle_km * loaded_factor + empty_vehicle_km * empty_factor
```

For a discrete dedicated load, derive trip count from payload and any applicable volume limit. Define the modeled route legs: site-to-landfill and any approved return/depot movements. An empty return is not implicitly a loaded trip.

Use one method for an activity, not both. Shared loads require an explicit allocation method.

### Expected Annual Repairs

The current damage model supplies expected annual outcomes, not a realized schedule of truck trips. Do not apply `ceil(expected_mass / payload)` and charge one dedicated truck every year for a fractional expected repair.

Use a validated expected-activity model or an approved linear shared-freight approach. If fixed charges or discrete trips are needed, model event probabilities and conditional load sizes; the expected cost of trips is not generally the cost of the expected mass.

### Monetary Outputs

- **Haulage expenditure:** compute using a compatible tariff or explicit fixed, distance, and time charges without duplicating bundled components.
- **Landfill tipping fee:** retain the existing separate disposal cost unless a verified facility-specific fee policy deliberately replaces it.
- **Social carbon cost:** `transport_kg_co2e / 1000 * selected_year_scc`, following the carbon plan's dollar-basis and CO2e monetization rules.
- Discount monetary outcomes with the financial discount rate; do not discount physical emissions.

Nearest by road distance is not necessarily cheapest. Keep the initial selection objective explicit; cost-minimizing destination choice is a separate future feature.

## Integration And Double-Counting Controls

- [ ] Keep transportation opt-in and preserve current numerical results when disabled.
- [ ] Reuse installation/replacement and physical repair records for activity timing.
- [ ] Keep delivery, waste haulage, tipping fees, and carbon valuation as distinct components.
- [ ] Check whether existing contractor, disposal, production, or landfill factors already include transport.
- [ ] For an overlap, use compatible disaggregated sources or explicitly exclude the overlapping addition; do not subtract an invented allowance.
- [ ] Keep baseline historical transport outside the forward-looking comparison; include new baseline repair/replacement activity.
- [ ] Include transport scope, factor/route versions, and assumptions in immutable run identity.
- [ ] Preserve old runs without backfilling routes or emissions from current data.
- [ ] Keep physical emissions, displayed social valuation, and inclusion in economic totals independently traceable.

## User-Facing Results

For the selected asset/scenario and portfolio, show:

- selected landfill name/ID and eligibility/proxy status;
- distance and whether it is road distance or a geographic proxy;
- removed covering mass and modeled transport activity;
- haulage expenditure in USD;
- transport emissions in kg/tonnes CO2e;
- monetized social carbon cost in USD;
- annual/cumulative totals and differences from the keep-current baseline;
- full-replacement versus repair contributions.

Map the asset and selected facility. Draw a road route only when actual route geometry is available; label a straight connector as schematic, not a driving route. Forecast values must be described as modeled or expected, not measured activity.

## Implementation Phases

1. **Find and validate landfill data:** inspect the existing repository leads, confirm facility coverage/eligibility, and publish a versioned reference.
2. **Build facility assignments:** implement spatial candidate search, road-distance comparison, explicit error states, and immutable assignment outputs.
3. **Approve transport assumptions:** select compatible rates, emission factors, payload/load allocation, and expected-repair treatment.
4. **Calculate waste-haul activity:** link full replacements and repairs to quantities, selected destinations, costs, and emissions.
5. **Integrate and display:** publish transportation artifacts, connect economic totals without double counting, and show both physical and monetary results.
6. **Add inbound delivery later:** locate compatible suppliers, define supplier-to-site distance and delivery allocation, and reuse the validated framework.

## Validation And Acceptance Criteria

- A small known-coordinate example verifies geographic nearest-neighbor assignments and units.
- A river/road-detour example proves that geographically nearest and road-nearest can differ.
- Closed, incompatible, or unknown-acceptance facilities are handled according to the explicit eligibility policy.
- Ties are deterministic; candidate limits do not produce an unsupported global-nearest claim.
- Invalid coordinates, no eligible destination, and failed routes remain explicit failures.
- Known mass/distance examples reconcile both emission methods and their monetary outputs.
- Return legs, shared loads, and factors with embedded empty-running assumptions do not double count activity.
- Partial repairs use repair mass; expected annual repairs do not trigger unjustified whole-truck rounding.
- Baseline repairs carry transportation impacts even without full replacement.
- Route/facility/factor changes produce new run identities.
- Portfolio totals reconcile to asset activity and stage totals.
- Disabled transportation preserves current results.
- Every result identifies method, scope, source vintage, and uncertainty.

## Completion Definition

The first increment is complete when a reproducible run assigns removed roof covering to a verified eligible landfill, transparently estimates haul distance/activity, and presents **haulage expenditure, physical transport emissions, and monetary social carbon cost** for replacement and repair activity.

Inbound delivery remains separately labeled as unavailable until supplier and delivery inputs are approved. Neither increment changes the agreed roof-covering-only boundary.
