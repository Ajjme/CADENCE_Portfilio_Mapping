// Names, colors, and number formats shared by the Results page tabs.
// The colors match the Streamlit charts (SCENARIO_COLORS in ui/theme.py).
import type { Schemas } from '../../api/client'

// One replacement option's final results, for the portfolio or one asset.
export type Outcome = Schemas['PortfolioScenario'] | Schemas['AssetScenario']

export const SCENARIOS = [
  'BASELINE_CURRENT',
  'NEW_ASPHALT',
  'NEW_METAL',
  'NEW_TILE',
] as const

// The three options a roof can be replaced with.
export const REPLACEMENTS = ['NEW_ASPHALT', 'NEW_METAL', 'NEW_TILE'] as const

export const SCENARIO_COLORS: Record<string, string> = {
  BASELINE_CURRENT: '#1e3a8a',
  NEW_ASPHALT: '#424242',
  NEW_METAL: '#607d8b',
  NEW_TILE: '#8d6e63',
}

// Cost parts, in the same order and colors as the Streamlit cost chart.
export const COST_COLORS: Record<string, string> = {
  material_usd: '#65bfa2',
  labor_usd: '#efb867',
  repair_usd: '#dd7975',
  loss_of_use_usd: '#83a7de',
  disposal_usd: '#b7a0d7',
  carbon_usd: '#d1c078',
}

// The asset picker's value for the whole portfolio.
export const PORTFOLIO = '__portfolio__'

export function scenarioLabel(scenarioId: string, portfolio: boolean) {
  switch (scenarioId) {
    case 'BASELINE_CURRENT':
      return portfolio ? 'Installed roofs' : 'Installed roof'
    case 'NEW_ASPHALT':
      return 'New asphalt'
    case 'NEW_METAL':
      return 'New metal'
    case 'NEW_TILE':
      return 'New tile'
    default:
      return scenarioId
  }
}

const usd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
})

// Dollars with no cents, like "-$38,783". Missing values say so instead of
// showing $0, since a missing total means at least one asset had no value.
export function formatUsd(value: number | null | undefined) {
  return value === null || value === undefined
    ? 'Unavailable'
    : usd.format(value)
}

// The option with the highest final NPV, or undefined when any option's NPV
// is missing - a missing value could have been the highest.
export function bestOption(outcomes: Outcome[]): string | undefined {
  let best: { scenarioId: string; npv: number } | undefined
  for (const scenarioId of REPLACEMENTS) {
    const npv = outcomes.find(
      (row) => row.scenario_id === scenarioId,
    )?.net_present_value_usd
    if (npv === null || npv === undefined) return undefined
    if (!best || npv > best.npv) best = { scenarioId, npv }
  }
  return best?.scenarioId
}
