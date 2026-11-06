# CADENCE: Insurance Actuarial Review

**Review date:** September 30, 2026  
**Perspective:** Property-insurance actuarial and catastrophe-risk decision support  
**Scope:** The current local implementation, including uncommitted work. This is a technical assessment from an actuarial perspective, not a credentialed actuarial opinion, regulatory certification, or independent validation of the underlying data.

## Principal Findings

Severity below refers to the risk of relying on the output for insurance decisions. Several findings are disclosed V1 limitations, not failures to implement the intended specification.

### 1. High: The insurance payout is a planning proxy, not expected insured loss

[The insurance calculation](../src/cadence/insurance/analysis.py#L91) applies the deductible and insured-value cap to **expected annual roof repair cost**:

$$
\widehat{P}=\min\left(\max\left(\mathbb{E}[L]-d,0\right),u\right).
$$

For one covered loss opportunity, the relevant actuarial quantity is instead:

$$
P=\mathbb{E}\left[\min\left(\max\left(L-d,0\right),u\right)\right].
$$

Here, $L$ is covered ground-up loss, $d$ the deductible, and $u$ the payment limit under this particular contract interpretation. Multiple occurrences require applying the actual policy terms to each occurrence and then any applicable aggregates. In general, applying policy terms to a mean does not give the mean policy payment.

**Illustration, not a CADENCE portfolio result:** suppose there is a 10% annual chance of one $10,000 covered roof loss, otherwise no loss, with a $2,000 deductible and a nonbinding limit. Expected ground-up loss is $1,000. The current proxy pays $0; the event-based expected payment is $800. A zero proxy payout therefore does not establish zero insured risk. With a deductible alone the approximation understates or equals the corresponding expected payment; with a binding cap, the bias need not have the same direction.

**My judgment:** I would not use the current payout, loss ratio, or margin as a rate indication, a premium credit, or an insurer profitability forecast. The documentation openly labels the approximation, which is a strength, but that warning must travel with exported figures and presentations.

### 2. High: Annual damage is sensitive to imposed distribution tails

[The loss integrator](../src/cadence/vulnerability/expected_damage.py#L12) uses six wind return periods, 10 through 500 years, and trapezoidal integration with imposed endpoints of zero damage at annual exceedance probability 1 and complete damage at probability 0.

The rare-event segment contributes $(D_{500}+1)/1000$. Consequently, even when damage is zero at every supplied return period, the formula implies a **0.001 annual damage ratio, or 0.1%**, solely from the assumed tail. The frequent-event segment contributes $0.45D_{10}$. Neither contribution should be mistaken for a directly observed loss experience estimate.

**My judgment:** these are material model assumptions, not merely numerical details. Before relying on absolute losses or differences between roofs, I would request separate reporting of frequent-event, modeled-range, and rare-tail contributions, plus sensitivity to defensible alternative endpoints and integration methods. Annual wind-maxima return levels also need a documented bridge to aggregate annual claims; they do not by themselves describe multiple damaging events in a year.

### 3. High: Building-loss curves need a defensible bridge to roof repair costs

[Fragility extraction](../src/cadence/reference_data/fragility.py#L49) explicitly selects HAZUS `building_loss` curves and averages their ratios across unresolved construction variants. [Annual economics](../src/cadence/economics/alternative_analysis.py#L255) then multiplies the resulting expected damage ratio by installed roof capital cost.

The source loss ratio and its replacement-value denominator must match the component being valued. A building-loss ratio is not automatically a roof-cover repair ratio. The code establishes the computational relationship; this review did not establish an independently validated engineering relationship between those two measures.

**My judgment:** obtain roof-component vulnerability and repair-cost functions, or document and validate the conversion. Test partial repair versus complete replacement, interior damage from water intrusion, code upgrades, demolition, and claim settlement costs separately. Equal averaging of construction variants is not a substitute for the insured portfolio's actual construction mix.

### 4. High: Material comparisons include provisional and non-independent alternatives

The [base fragility mapping](../src/cadence/reference_data/fragility.py#L8) assigns Asphalt to WSF1, Metal to SERBL, and Tile to MSF1. These are building-archetype proxies, not independently established roof-material vulnerability curves. The [annual damage output](../src/cadence/vulnerability/annual_damage.py#L126) carries explicit proxy and low-confidence flags.

There is an additional distinction in Alternative Analysis: [NEW_TILE is evaluated with Metal vulnerability](../src/cadence/economics/alternative_pipeline.py#L96), and the [temporary Tile policy](../src/cadence/economics/alternative_pipeline.py#L277) borrows Metal service life and applies 1.2 times Metal installed cost. The retained Tile name does not make it an independent scientific alternative. Do not confuse this NEW_TILE override with the base Tile/MSF1 mapping.

**My judgment:** I would withhold material-specific underwriting credits and avoid presenting the Tile comparison as evidence of actual Tile performance. The cost uplift can increase estimated Tile repair dollars without any separately modeled difference in physical vulnerability. A premium-credit study needs validated roof assemblies, installation quality, attachment, condition, and relevant construction characteristics, not material names alone.

### 5. High: Insurance coverage and metric labels are narrower than they may appear

The [policy contract](../src/cadence/insurance/contracts.py#L27) supports wind and flat-dollar Standard deductibles, one policy record per asset. It does not implement percentage deductibles, actual-cash-value roof schedules, endorsements, shared occurrence terms, or reinsurance. Repeated policy IDs do not combine coverage. `insured_value` is used as a payout cap; whether the entered value actually represents the applicable roof coverage limit must be established outside this formula.

The [Insurance View](../src/cadence/ui/pages/insurance.py#L127) labels proxy payout as "Break-even premium" and premium minus proxy payout as "Underwriting margin." The caption appropriately warns about exclusions, but these labels still invite a broader interpretation than the calculation supports.

- The numerator contains modeled wind-roof payments only. If `current_premium` is a whole-property premium, the ratio mixes incompatible coverage scopes. The input contract does not require a wind-roof premium allocation.
- Even with a properly allocated premium, the model excludes other covered losses, loss-adjustment expenses, acquisition and administrative expenses, reinsurance costs and recoveries, and the cost of capital.
- Premium remains fixed in real 2026 dollars across years and alternatives. That isolates a scenario assumption; it does not forecast renewal pricing, retention, or a mitigation discount.
- Cumulative insurance margins are arithmetic sums, not discounted present values. They should not be compared directly with lifecycle NPV.

**My judgment:** call the figures "Wind-roof payout proxy," "Premium less modeled wind-roof payout," and "Wind-roof payout-to-premium proxy ratio." Remove the implication of an all-in break-even premium. A future insurance model should explicitly distinguish covered ground-up loss, gross insured loss, and net retained loss, with corresponding earned premium and expense bases.

### 6. High: Portfolio expected values do not establish catastrophe tail risk

The reviewed path produces asset-year expected damage and insurance proxies, then [aggregates monetary values](../src/cadence/ui/insurance_data.py#L82). It does not generate a joint event-loss distribution for the portfolio. A wind return period at one grid cell is not a portfolio insured-loss return period.

Summing valid asset expected losses does **not** require an independence assumption. However, estimating occurrence or aggregate exceedance probabilities, probable maximum loss, tail value at risk, and reinsurance recoveries does require an appropriate joint loss model and contractual treatment. Common storm footprints, within-event dependence, multiple annual events, and catastrophe demand surge matter.

**My judgment:** maps and sums can support exposure review, but not diversification credits, catastrophe capital, treaty pricing, or statements such as "this is our 1-in-100-year insured portfolio loss."

### 7. Medium: Lifecycle and market outputs are normative scenarios

[Alternative Analysis](../src/cadence/economics/alternative_analysis.py#L43) ages roofs and replaces them at modeled end of useful life; it does not simulate claim events that repair or replace roofs and reset their condition. Fragility lookup age is capped at 30 even when chronological roof age continues increasing.

The [Market Study](../src/cadence/economics/market_study.py#L53) uses a specified replacement trigger and chooses the lowest modeled remaining-horizon cost among materials when that trigger occurs. It includes a terminal remaining-value assumption and can include monetized carbon in decisions. This is not an unconstrained optimum across every possible replacement date, nor a calibrated model of household behavior.

**My judgment:** interpret market shares as the consequence of those decision rules, not predicted sales or policyholder adoption. Test service life, age-cap behavior, time horizon, terminal value, and replacement thresholds. Financing, owner liquidity, contractor capacity, attachment to an existing material, code requirements, and insurer claim settlement can all change realized decisions. A monetized societal carbon benefit is not necessarily a cash incentive available to the owner.

## Overall Assessment

**I would use CADENCE as a controlled roof-resilience and capital-planning research tool. I would not yet use it as a stand-alone insurance pricing, reserving, reinsurance, or capital model.**

Its useful organizing idea is to connect property locations, roof condition, wind hazard, roof aging, replacement timing, and lifecycle economics. That is relevant to an insurer deciding where inspections, engineering advice, or a mitigation pilot could be most useful. Its current outputs are conditional scenario estimates, not calibrated predictions of claims or owner behavior.

The [current product description](../README.md) discloses important qualifications: provisional HAZUS material proxies, age-capped fragility, one climate trajectory, and a temporary Tile alternative that borrows Metal vulnerability and lifecycle timing with a 1.2 cost multiplier. Those qualifications affect both absolute losses and relative rankings. Comparative results are not automatically reliable just because every alternative runs through the same engine.

## How I Would Use It Today

| Use | Practical application | Required boundary |
| --- | --- | --- |
| Inspection triage | Identify properties where age, modeled wind exposure, and replacement economics justify engineering review. | Treat rankings as hypotheses; verify property characteristics and proxy sensitivity. |
| Mitigation pilot design | Compare maintaining the installed roof with replacement alternatives for a selected portfolio. | Do not translate modeled savings directly into premium discounts. |
| Capital planning | Compare replacement timing, repair burden, and lifecycle cost under stated assumptions. | Separate owner cash flows from insurer payments and societal benefits. |
| Exposure review | Combine portfolio maps with roof age and material to identify concentrations needing further study. | Geographic concentration is not a modeled catastrophe loss distribution. |
| Climate scenario discussion | Explore how a specified wind trajectory changes damage and replacement economics over time. | Present conditional scenarios, not probabilities or confidence intervals. |
| Underwriter and engineering communication | Make the assumed hazard-to-damage-to-cost chain inspectable for individual assets. | Retain provenance, missing-data flags, and model limitations. |

I would not use the current implementation to set an individual premium, select a hurricane deductible, estimate a 1-in-100-year portfolio loss, price an excess-of-loss treaty, establish claim reserves, or certify a regulatory filing.

## What I Think Is Well Designed

- **Traceable comparisons:** an installed-roof baseline and three replacement alternatives make the counterfactual explicit. Replacement timing, cost basis, and climate assumptions are recorded rather than left implicit.
- **Separation of physical and insurance results:** [insurance publication](../src/cadence/insurance/pipeline.py#L21) attaches a separately saved policy snapshot to a physical run. Changing a premium does not require redefining physical vulnerability.
- **Reproducibility controls:** the insurance run identity includes the physical run, formula version, workbook checksum, and normalized policy checksum. Publication uses a staging directory and checks existing artifacts before reuse. These are useful audit controls, though not proof of full production governance or tamper resistance.
- **Missingness is visible:** unsupported policy terms do not silently become zero loss. Portfolio insurance totals are withheld when included assets are incomplete, and a zero premium yields an unavailable ratio rather than a misleading percentage.
- **Appropriate portfolio ratio arithmetic:** the displayed portfolio proxy ratio is total payout divided by total premium, not an unweighted average of individual asset ratios.
- **Assumption transparency:** proxy flags, temporary Tile metadata, real-dollar labels, and linked run information provide a foundation for a model-risk register.

The strongest feature is the inspectable connection between engineering assumptions and investment decisions. I would preserve that structure while improving the scientific and insurance content.

## A Practical Insurer Pilot

I would start with a bounded mitigation study for one region and comparable policy forms, jointly owned by an actuary, an underwriter, and a roofing engineer.

1. **Define the decision.** For example: which insured buildings deserve a roof inspection or an offer to participate in a replacement pilot? Agree beforehand that the output will not automatically change premiums or eligibility.
2. **Reconcile exposures.** Load a representative asset workbook into Asset Portfolio. Validate coordinates, roof area, material, condition, installation year, construction details, insured-value basis, policy dates, deductibles, and premium scope. Report missingness by asset count and insured value; investigate whether excluded risks are systematically different.
3. **Run the physical comparison.** Choose the analysis horizon, discount rate, and enabled cost streams. Save the filtered portfolio and immutable run ID. Review individual assets and the portfolio baseline before interpreting alternative rankings. Label NEW_TILE as provisional or exclude it from decision recommendations.
4. **Stress the assumptions.** Compare plausible service lives, costs, and discount rates using supported settings. Have the model team run controlled sensitivity studies for vulnerability proxies and loss tails; these are not all exposed as current UI controls. Within V1, treat the single climate trajectory as a condition of the study, not a probability-weighted climate forecast.
5. **Separate the economic viewpoints.** Present owner installation and maintenance costs, ground-up avoided losses, provisional insurer payments, and societal carbon benefits separately. In a total-resource analysis, insurer payments and premium transfers are not additional physical damage avoided. Do not add the same avoided loss to both owner and insurer benefit totals.
6. **Compare with independent experience.** Match historical claims and engineering assessments to exposure periods. Put claims on compatible coverage, development, geographic, and cost-level bases. Check both large-loss years and non-catastrophe years; challenge the model before treating apparent agreement as calibration.
7. **Make a bounded decision and monitor it.** Produce an inspection or pilot shortlist with uncertainty and data-quality qualifications. Record actual installation, subsequent condition, claims, costs, and retention. Use a suitable comparison group to test whether observed mitigation benefits persist after accounting for selection effects.

My pilot deliverable would contain a data-quality summary, a qualified shortlist, baseline-versus-alternative economics, a sensitivity table showing ranking reversals, and an assumptions register. It would not contain an actuarially indicated premium discount until the insured-loss model and empirical evidence support one.

## What I Would Require Before Broader Insurance Use

| Priority | Work required | Evidence needed to proceed |
| --- | --- | --- |
| Immediate | Carry planning-proxy warnings into charts, downloads, and presentations; clarify premium scope and replace misleading metric labels. | A reviewer can identify the peril, component, dollar basis, exclusions, and provisional assumptions without reading the source code. |
| Before using loss levels | Validate component vulnerability, material mappings, roof-cost denominators, frequent-event behavior, and tail assumptions. | Engineering support and independent benchmarks; quantified sensitivity of losses and rankings. |
| Before using insured losses | Add loss-distribution or event-based financial calculations with the relevant policy forms. | Hand-calculated and independently reconciled deductible/limit cases, multiple-event cases, and aggregate/shared-policy cases. A full event catalog is not necessary for every narrow study, but a mean loss alone is insufficient. |
| Before premium decisions | Calibrate against credible exposure and claim experience; include expenses, trends, coverage allocation, and applicable pricing constraints. | Out-of-sample results, credibility treatment, documented uncertainty, and qualified actuarial review. |
| Before catastrophe capital or reinsurance | Add a defensible joint event model and contractual recovery treatment. | Validated occurrence and aggregate exceedance curves, dependence and tail tests, and reconciliation to external benchmarks. |
| Before production deployment | Complete model ownership, change approval, access control, data retention, recovery, and reproducibility procedures. | Independently repeatable runs, approved versions, monitoring thresholds, and documented decisions when model behavior changes. |

For data review, I would specifically check the wind statistic's compatibility with the vulnerability curves, units and exposure assumptions, grid-assignment distances, return-level monotonicity, fit quality, confidence-bound validity, and out-of-domain assets. Construction mix, retail-price fallbacks, installed-cost overrides, real cost trends, and catastrophe repair-cost inflation also need validation against the intended insurance portfolio. These are required validation questions, not findings that every input is defective.

Parameter uncertainty, model-form uncertainty, and random event variability should be distinguished. A smooth annual series is not a confidence interval. Broader climate ensembles or a full catastrophe event model would be future scope, not an assertion that V1 already supports them.

## Evidence and Review Limits

This assessment is based on the source files linked above, the [product documentation](../README.md), the [insurance specification](insurance.md), and focused execution checks. The shared Results browser page was inspected, but it was at run selection rather than displaying completed results; no new portfolio run or full browser acceptance test was performed for this review.

The focused regression run passed **63 tests** covering insurance calculations and publication, insurance UI data, annual and asset-scoped damage, alternative lifecycle economics, market decisions, and climate scaling. It emitted four warnings involving the environment's LibreSSL compatibility and unsupported Excel data-validation extensions; those warnings were not remediated in this documentation review. This was not a full-suite run.

Reproduce the focused run from the CADENCE project directory:

```shell
.venv/bin/python -m pytest -o addopts='' -q \
	tests/test_insurance_analysis.py tests/test_insurance_pipeline.py \
	tests/test_ui_insurance.py tests/test_annual_damage.py \
	tests/test_asset_scoped_damage.py tests/test_alternative_analysis.py \
	tests/test_market_study.py tests/test_climate_delta.py
```

Two additional constructed numerical checks executed the actual implementation and confirmed:

| Constructed check | Observed result |
| --- | --- |
| All six return-period damage ratios set to zero | Integrated annual damage ratio of 0.001. |
| $1,000 annual mean repair cost, $2,000 deductible, nonbinding limit | Insurance proxy payout of $0, versus $800 for the explicitly specified 10%-chance/$10,000 single-event example. |

These checks confirm what the software computes. They do not establish that its hazard, vulnerability, prices, or payouts reproduce real insurance experience. No independent claims calibration, catastrophe-event validation, security audit, or regulatory compliance assessment was completed. No production assumptions or application source code were changed.

## Bottom Line

**My actuarial view: CADENCE has a useful foundation for deciding where to investigate and invest in roof resilience. Its present insurance layer illustrates financial terms; it does not yet measure insurable risk with the fidelity needed for pricing or capital.**

I would sponsor a controlled engineering-and-actuarial pilot, preserve the transparent run history, and prioritize the loss-distribution treatment and roof-specific vulnerability evidence before adding more insurance-facing precision to the outputs.