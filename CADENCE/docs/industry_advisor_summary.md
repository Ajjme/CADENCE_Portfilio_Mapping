# CADENCE Progress Summary

**Prepared for the Industry Advisor Board | October 2026**

## Executive Status

CADENCE has progressed from separate hazard, vulnerability, and economics components to an integrated, asset-level roof-resilience decision-support workflow. The current V1 implementation ingests a property portfolio, estimates wind-related roof damage, compares lifecycle outcomes for three roof material classes, and presents results through a local dashboard. It is a functioning research and engineering prototype, not a scientifically certified or production underwriting model.

## Delivered Capabilities

- **Portfolio ingestion and geospatial enrichment.** The workflow validates asset workbooks and maps locations to CONUS404 wind-grid cells and IECC climate zones. Economics-ready features include material-class and labor/geography assignments. Repeated hazard calculation keys are reused across assets.
- **Wind vulnerability and climate adjustment.** Approved HAZUS-based fragility curves are applied to six wind return periods to calculate Year 1 expected damage and annual damage estimates. Alternative Analysis scales baseline gusts using annual climate factors and retains asset-, year-, and material-level outputs.
- **Lifecycle and economic comparison.** A sequential annual engine compares the existing-roof baseline with new Asphalt, Metal, and Tile alternatives over a configurable 2026–2050 horizon. Outputs include roof age and replacement events, expected damage and repairs, installation costs, enabled disposal and carbon costs, avoided damage, lifecycle net benefit, and discounted NPV.
- **Cost construction and traceable results.** Material and labor costs use source-aware mappings, geographic price fallback, configured class-level overrides, and explicit proxy/default flags. Analyses publish versioned Parquet/JSON artifacts with run identifiers and metadata; saved results can be reopened without rerunning calculations.
- **Dashboard and insurance overlay.** The Streamlit application provides portfolio controls, lifecycle comparisons, maps, cost allocations, wind-return-period views, and an insurance page. A separate immutable insurance artifact links policy snapshots to physical runs and reports annual expected payouts and underwriting indicators.
- **Automated verification.** The modular Python package has focused tests across ingestion, hazard, economics, lifecycle, insurance, artifact publication, and UI behavior. The September 30, 2026 engineering review recorded **136 passing tests**. That result demonstrates regression coverage, not independent model validation.

## Current Boundaries And Priorities

Several assumptions remain provisional and are surfaced in run metadata: HAZUS fragility proxies are used where material-specific curves are unavailable; the Tile alternative temporarily follows Metal lifecycle/vulnerability behavior with a 1.2 cost multiplier; and the annual insurance calculation is a planning proxy, not event-level actuarial loss modeling. Loss-of-use costs are not enabled in the dashboard pending validated annual downtime inputs. The Market Study remains draft work and is outside the supported analysis workflow.

The latest engineering review also flagged correctness work that has not been certified as resolved: cache identities must cover all hazard and economic dependencies; uploaded remaining-useful-life inputs must survive workbook ingestion; and incomplete annual histories must not produce apparently complete final NPV values. No full-scale portfolio benchmark, actuarial validation, or external scientific certification is claimed.

**Near-term technical focus:** close those correctness and provenance gaps, validate fragility and lifecycle assumptions with domain experts, and benchmark representative portfolio sizes before expanding the supported decision scope.