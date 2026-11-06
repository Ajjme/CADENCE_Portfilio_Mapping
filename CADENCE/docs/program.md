# Program View

Program View is a standalone page in the existing dashboard at `/program`.
It evaluates **one home at a time**, for a government or insurer considering
a one-time incentive for roof replacement. Launch the normal dashboard at
http://localhost:8520/; no separate application is needed.

## Workflow

1. Run Alternative Analysis from Asset Portfolio, or select a compatible saved
   physical run in Program View.
2. Expand **Create a saved Program run**, choose a physical run and home, and
   click **Calculate Program incentives**.
3. Select a target roof, counterfactual, and installation year. The initial year
   selection follows the recommendation; manual selection does not change it.
4. Review funding requirements, the comparison panels, and the NPV waterfall.
   Download candidate comparisons or the selected candidate's annual audit.
5. Reopen the saved Program run after restarting the dashboard. Its own snapshots
   are sufficient; no active workbook, insurance policy, or session is needed.

The newest saved run is never chosen implicitly. A newly calculated run is selected.
Older physical runs without a valid saved fragility snapshot require a matching
Alternative Analysis rerun. Changed removal-cost reference sources also require
a rerun, rather than silently mixing new assumptions into historical results.

## What the amounts mean

The **economic break-even grant** makes the upgrade's modeled NPV nonnegative.
The **incremental upfront gap** compares installation-year cash costs only.
These are different quantities and **must not be added together**.

This is a **pre-insurance economic proxy** using full expected roof-repair costs.
It is not actual homeowner savings net of claims, a guarantee of participation,
or an affordability assessment against income, savings, or borrowing capacity.
A zero economic grant does not imply a zero contractor bill.

Conventional replacement always uses the home's original material. Each candidate
installation year has two comparisons:

| Counterfactual | Interpretation |
|---|---|
| Keep roof; replace in kind at useful life | Follow the current roof until each required conventional replacement |
| New conventional roof in installation year | Follow the same path before the candidate year, then install a new conventional roof in that year |

The target path follows conventional replacements before the candidate year,
installs the selected roof at the beginning of that year, and replaces it in kind
at future useful-life limits. Coincident burnout and planned installation incur
only one removal and replacement. Roof ages, useful-life overrides, annual
climate factors, and prices are not frozen at their initial values.

### Formulas

For candidate installation year `Y`, study end `T`, real discount rate `r`,
target path `U`, and comparison path `B`:

```text
annual_cost = installation capex + enabled disposal + expected repair
              + enabled, validated loss of use
NPV_at_Y = sum((annual_cost_B[t] - annual_cost_U[t]) / (1+r)^(t-Y), t=Y..T)
economic_grant_at_Y = max(0, -NPV_at_Y)
upfront_gap_at_Y = max(0, installation_cash_U[Y] - installation_cash_B[Y])
```

Installation cash includes installation capex and enabled disposal, not annual
expected repairs. A keep-to-useful-life comparator pays zero installation cash
in a year when no replacement is due. Avoided repairs are already included in
the NPV; they are not added a second time.

For example, a $20,000 target roof versus a $12,000 conventional roof, with
$3,000 discounted subsequent net benefits, has an $8,000 upfront gap and a
$5,000 economic grant.

All dollar values remain **real 2026 USD**. The grant is paid once in `Y`;
its run-start PV is smaller when the discount rate is positive. A run-start
NPV of -$1,000 implies a $1,210 grant two years later at a 10% rate.
Annual cash flows follow Alternative Analysis's start-of-year installation
before expected annual damage convention.

## Recommendations and limitations

- Minimize the grant paid in the candidate year for the selected target and
  counterfactual. Compare amounts at cent precision, with earliest-year ties.
  The two counterfactuals receive independent recommendations.
- Candidate years are **mutually exclusive installation choices**, not annual
  program spending. No portfolio total or budget allocation is calculated.
- **Remaining roof value is excluded.** The recommendation is only the lowest
  modeled incentive within the selected horizon, not a lifetime optimum.
- Full repair costs are included. Insurance payouts, premium savings, financing,
  other grants, adoption behavior, and household liquidity are not modeled.
- Carbon may appear in the underlying physical audit, but is excluded from
  the Program grant. Disabled disposal/loss-of-use streams contribute zero by
  explicit policy; missing enabled streams remain unavailable.
- Incomplete years remain visible with reasons and chart gaps. A best available
  year is provisional if other candidate years are incomplete; no valid
  candidates means no recommendation.
- Same-material choices are roof renewal, not a different-material resilience
  standard. Negative repair savings mean higher modeled repair costs.
- The inherited temporary Tile policy uses Metal lifecycle/vulnerability and
  1.2x installed/repair costs after Tile installation. It is not independently
  validated Tile resilience. Existing fragility proxies and age caps still apply.

## Public-good placeholders

Three explanatory buttons are labeled **Not yet modeled**:

- Reduced post-disaster demand surge.
- Insurer claims-paying capacity.
- Financing and bond-related costs.

These buttons do not change grants or recommendations. Unknown benefits are
not represented as $0. The current P90 wage setting is not an estimate of
avoided demand surge. Future models can come from a separate repository, with
explicit beneficiaries, dollar/discount bases, uncertainty, and overlap rules
to avoid counting repair savings twice.

## Saved artifacts and implementation

Program results are immutable under:

```text
cadence_datalake/results/roof_program_analysis/schema_version=v0.1.0/run_id=.../
    candidates.parquet
    annual_cash_flows.parquet
    assets.parquet
    service_lives.parquet
    option_costs.parquet
    removal_costs.parquet
    hazard.parquet
    climate.parquet
    curves.parquet
    states.parquet
    run_metadata.json
```

Candidate keys are home, target, installation year, and counterfactual. Annual
audit keys are home, candidate year, cash-flow year, and physical scenario.
The original-material new-roof scenario is the conventional-at-year path;
`BASELINE_CURRENT` is the keep-to-useful-life path.

The manifest identifies the parent physical/economics run, source checksums,
formula version, perspective, horizon, discount rate, Tile policy, and artifact
checksums. Parent fragility curves are retained; missing candidate-path curves
are separately sourced and snapshotted with supplemental provenance. Removal
costs use the material actually removed, not the original-roof disposal price
repeated across replacement materials. Snapshots are canonically sorted before
hashing, so input row order does not change the run identity.

The [Program package](../src/cadence/program/) calculates and publishes results.
It extends the shared [lifecycle builder](../src/cadence/economics/alternative_analysis.py)
with an optional installation year; omitted arguments preserve existing behavior.
The [page](../src/cadence/ui/program_page.py),
[data adapter](../src/cadence/ui/program_data.py), and
[charts](../src/cadence/ui/program_charts.py) keep calculations outside renderers.
The launcher uses [streamlit_app.py](../streamlit_app.py), outside the legacy
`pages` directory's parent, so cold direct visits initialize native navigation
rather than auto-discovering function-only page scripts.

For related workflows, see [Streamlit Dashboard](streamlit.md),
[Alternative Analysis](../ALTERNATIVE_ANALYSIS_README.md), and [Insurance View](insurance.md).
