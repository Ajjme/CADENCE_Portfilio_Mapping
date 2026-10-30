# V1 Official Material Consolidation Rules

Version: `v1.0.0`

## Purpose

CADENCE V1 exposes exactly three official modeled material classes: `OFFICIAL_ASPHALT`, `OFFICIAL_METAL`, and `OFFICIAL_TILE`. Consolidation does not erase physical subtype identity in raw or cleaned source data. It creates a derived class-level reference value after source labels have been resolved to canonical IDs.

The runtime chain is:

```text
raw source value
  -> source-aware canonical mapping
  -> canonical_id
  -> official_material_class_map_v1.csv
  -> domain rule in material_consolidation_rules_v1.csv
  -> versioned consolidated reference row
```

No raw string is matched directly to an official class, and no fuzzy matching is allowed.

## Core Membership

| Official class | V1 average members |
|---|---|
| Asphalt | 3-tab, architectural, premium architectural |
| Metal | corrugated panel, standing seam, metal tile/shingle form |
| Tile | clay, concrete |

Impact-resistant Class 4, aluminum, and copper retain their official family identity but do not contribute to the V1 core averages. Generic asphalt, metal, and tile are input placeholders: resolve them through their approved defaults before lookup, but never count the placeholder as another average member. Slate, wood, BUR/modified bitumen, and single-ply membranes are rejected or quarantined because coercing them into one of the three classes would change their physical meaning. Components are always excluded.

## Evaluation Contract

1. Resolve every source value through `master_mapping_reference_draft.csv` using the full source-aware key. Reject or quarantine unresolved and unapproved mappings.
2. Join the resulting `canonical_id` to `official_material_class_map_v1.csv` with the requested `mapping_version`.
3. Keep only `aggregation_eligible=true` members for class-level reference construction.
4. Apply approved source-specific shared buckets, proxies, and fallback values before aggregation. Preserve every applied mapping and fallback flag.
5. Group by the keys in the selected domain rule. Never average across geography, year, labor scenario, occupation, EOL pathway, damage type, climate zone, or roof age.
6. Apply the named aggregation and missing-value policy. `arithmetic_mean_available_members` skips unavailable core members but emits their IDs in `missing_member_ids`; `arithmetic_mean_resolved_members` requires a source value or approved member-level fallback for every core member.
7. Emit the rule version, source dataset versions, contributing canonical IDs, missing canonical IDs, member count, expected member count, mapping/proxy flags, and output status with every consolidated row.
8. Fail a simulation-time lookup when a rule is `blocked` or its empty-class policy is not satisfied. Do not invent a cross-family substitute.

The arithmetic mean is equal-weighted by core subtype, not weighted by product count or source-row count. A repeated source bucket may resolve multiple members, but source row duplication must never create extra members.

## Important Domain Behavior

- Price geography fallback runs before consolidation: ZIP, CBSA, state, national, then class-level user override. Current observed data yields an asphalt mean of 3-tab and architectural, a metal value from corrugated alone, and no tile price. These partial contributor sets must be flagged.
- Labor is averaged only after matching all scenario and occupation keys. Derived labor columns are recomputed from the consolidated base parameter and the unchanged scenario factors; they are not independently averaged.
- Mass per square is the primary measure. Derive mass per square foot as `weight_per_square_lbs / 100` after consolidation.
- Physical service life remains separate from fragility-archetype EUL. User-entered EUL retains asset-level precedence over the consolidated physical default.
- Carbon landfill and recycling are separate rules. Apply an approved same-material pathway fallback before class averaging and carry the substitution flag.
- Fragility curves are never averaged across physical materials or HAZUS proxy building types. Each official class selects one approved interim proxy: Asphalt uses `WSF1`, Metal uses `SERBL`, and Tile uses `MSF1`. Within one selected proxy, climate zone, roof age, and retained terrain class, V1 equal-averages HAZUS construction variants that current asset inputs cannot resolve. Preserve the physical class and emit the proxy ID, mapping version, low confidence, `fragility_proxy_applied=true`, and `curve_aggregation_method=equal_average_unresolved_variants_within_terrain`; `MERBL` remains excluded.

## Required Validation

A published rule version must have unique canonical IDs in the class map, exactly three nonblank official class IDs, one rule per `(rule_version, data_domain, official_class_id)`, valid defaults, no component or placeholder marked aggregation-eligible, and complete coverage of the canonical material dimension. Consolidated outputs must report contributor coverage so a partial average cannot appear complete.

## Implemented Economics Usage

The annual economics pipeline in `src/cadence/economics` applies these rules for material price, material escalation, labor productivity, material mass, and landfill carbon. Its execution order is:

```text
source label -> canonical ID -> official core membership
             -> source-specific fallback/shared value
             -> class consolidation -> annual asset-option cost
```

Material-price geography fallback occurs before consolidation. The pipeline preserves contributing and missing canonical IDs, and it leaves Tile source pricing null with `blocked_without_override`. Operational option costs use source-consolidated material plus labor whenever available. Required full-installed class overrides are explicit fallbacks when that calculated total is unavailable; fallback use is flagged and never conceals incomplete coverage.

See `docs/economics.md` for input contracts, formulas, output columns, and CLI/Python usage.

## Catalog Review and Policy Scope

The five Excel catalogs were reconciled with local producer and consumer code on
2026-10-30. Each contains per-entry evidence and review dates, an **Artifact
Schemas** worksheet, and **Catalog Metadata** documenting repository revisions,
path conventions, and review limitations. The workbooks are explicitly included
by Git's ignore rules; other raw Excel files remain ignored unless separately
allowed. Catalog review dates do not change source-data vintages or certify model
calibration.

The [source registry](source_dataset_registry_draft.csv) describes available
inputs and their integration status. Generated products are documented in the
[output catalog](../Intermidate_products_and_final_outputs_data_catalog.xlsx).
Catalog dependencies use unique IDs: `S-010` remains the demand-surge setting;
the formerly duplicated adoption-threshold entry is now `S-011`.

The [consolidated workbook](../Consolidated_data_catalog.xlsx) provides a
filterable master catalog, five domain tabs, combined schema and metadata
worksheets, and the Climate detail sheets. The five individual workbooks remain
available unchanged. The consolidated workbook is a point-in-time snapshot,
not a bidirectionally synchronized source: rebuild it after individual catalog
changes. Its metadata records source-file hashes, and each master entry retains
its source workbook, worksheet, and row.

These general material mappings are not permission to propagate a
workflow-specific proxy to every consumer. Portfolio Alternative Analysis
records `temporary_tile_as_metal_with_1_2x_cost_v1` separately: `NEW_TILE` uses
Metal lifecycle/vulnerability and 1.2 times Metal installed/repair costs while
retaining Tile identity. Geographic costing in `Economic_cost_CADENCE` has its
own county-price and Tile-proxy contract. The standalone mapping prototype's
service lives and RUL ranking buckets are not this application's physical
service-life or economic-ranking policy.

Implemented source data, provisional assumptions, unsupported future features,
and uncommitted additions remain distinct catalog statuses. In particular,
Market Study adoption is still draft, annual loss-of-use integration remains
incomplete, and run-local fragility snapshots are identified as a local
working-tree addition at this review rather than assumed present in legacy runs.