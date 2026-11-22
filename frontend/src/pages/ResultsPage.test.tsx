import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../api/client'
import {
  getCostAllocations,
  getRun,
  getRunSummary,
  runAnalysis,
} from '../api/runs'
import { renderWithProviders } from '../test/renderWithProviders'
import ResultsPage from './ResultsPage'

// A pretend backend: each test sets what these calls return.
vi.mock('../api/runs', () => ({
  getRun: vi.fn(),
  getRunSummary: vi.fn(),
  getRunSeries: vi.fn(() => new Promise(() => {})),
  getCostAllocations: vi.fn(),
  runAnalysis: vi.fn(),
  runExportUrl: (runId: string) => `/api/runs/${runId}/export`,
}))

const RUN: Schemas['RunInfo'] = {
  run_id: 'abc123',
  schema_version: 'v0.4.0',
  run_timestamp: '2026-11-22T17:54:56+00:00',
  asset_count: 2,
  start_year: 2026,
  end_year: 2050,
  real_discount_rate: 0.02,
  scghg_discount_rate: 2,
  demand_surge: false,
  enabled_cost_streams: ['carbon', 'disposal', 'labor', 'material'],
  dollar_basis: 'real_2026_usd',
}

function outcome(scenario_id: string, npv: number | null) {
  return {
    scenario_id,
    net_present_value_usd: npv,
    cumulative_avoided_damage_usd: 100,
    cumulative_discounted_avoided_damage_usd: 90,
    cumulative_net_benefit_usd: 50,
    burnout_replacement_count: 0,
    active_cost_fallback_applied: false,
    repair_cost_incomplete: false,
    climate_risk_total_incomplete: false,
    event_cost_incomplete: false,
  }
}

const SUMMARY: Schemas['RunSummary'] = {
  run_id: 'abc123',
  portfolio: [
    { ...outcome('NEW_ASPHALT', -38783.46), asset_count: 2 },
    { ...outcome('NEW_METAL', -2518.61), asset_count: 2 },
    { ...outcome('NEW_TILE', -8559.72), asset_count: 2 },
  ],
  assets: [
    { ...outcome('NEW_ASPHALT', -100), asset_id: 'A-1' },
    { ...outcome('NEW_METAL', 50), asset_id: 'A-1' },
    { ...outcome('NEW_TILE', 20), asset_id: 'A-1' },
    { ...outcome('NEW_ASPHALT', -10), asset_id: 'B-2' },
    { ...outcome('NEW_METAL', null), asset_id: 'B-2' },
    { ...outcome('NEW_TILE', -5), asset_id: 'B-2' },
  ],
}

beforeEach(() => {
  vi.mocked(getRun).mockResolvedValue(RUN)
  vi.mocked(getRunSummary).mockResolvedValue(SUMMARY)
})

describe('ResultsPage with no run open', () => {
  it('runs the example portfolio and opens the new run', async () => {
    vi.mocked(runAnalysis).mockResolvedValue(RUN)
    const onRunChange = vi.fn()
    renderWithProviders(<ResultsPage runId={null} onRunChange={onRunChange} />)

    await userEvent.click(
      screen.getByRole('button', { name: 'Run the example portfolio' }),
    )

    expect(runAnalysis).toHaveBeenCalledWith({})
    await waitFor(() => expect(onRunChange).toHaveBeenCalledWith('abc123'))
  })

  it('opens a run by its ID', async () => {
    const onRunChange = vi.fn()
    renderWithProviders(<ResultsPage runId={null} onRunChange={onRunChange} />)

    await userEvent.type(screen.getByLabelText('Run ID'), ' abc123 ')
    await userEvent.click(screen.getByRole('button', { name: 'Open' }))

    expect(onRunChange).toHaveBeenCalledWith('abc123')
  })
})

describe('ResultsPage with a run open', () => {
  it('shows portfolio NPV for each option and marks the highest', async () => {
    renderWithProviders(<ResultsPage runId="abc123" onRunChange={vi.fn()} />)

    const metal = (await screen.findByRole('heading', { name: 'New metal' }))
      .parentElement!.parentElement!
    expect(within(metal).getByText('-$2,519')).toBeInTheDocument()
    expect(within(metal).getByText('Highest NPV')).toBeInTheDocument()
    expect(screen.getAllByText('Highest NPV')).toHaveLength(1)
  })

  it("lists each asset's NPV and best option", async () => {
    renderWithProviders(<ResultsPage runId="abc123" onRunChange={vi.fn()} />)

    const table = await screen.findByRole('table')
    const rows = within(table).getAllByRole('row')
    expect(within(rows[1]).getByText('A-1')).toBeInTheDocument()
    expect(within(rows[1]).getAllByText('New metal')).toHaveLength(1)
    // B-2 has no metal NPV, so its best option can't be known.
    expect(within(rows[2]).getAllByText('Unavailable')).toHaveLength(2)
  })

  it('links the Excel download to the run', async () => {
    renderWithProviders(<ResultsPage runId="abc123" onRunChange={vi.fn()} />)

    const link = await screen.findByRole('link', {
      name: 'Download results (Excel)',
    })
    expect(link).toHaveAttribute('href', '/api/runs/abc123/export')
  })

  it('loads the first year of cost allocations for the portfolio', async () => {
    vi.mocked(getCostAllocations).mockResolvedValue({
      run_id: 'abc123',
      asset_id: null,
      year: 2026,
      labels: { material_usd: 'Material', labor_usd: 'Labor' },
      rows: ['BASELINE_CURRENT', 'NEW_ASPHALT', 'NEW_METAL', 'NEW_TILE'].map(
        (scenario_id) => ({
          scenario_id,
          material_usd: 600,
          labor_usd: 400,
          total_usd: scenario_id === 'NEW_TILE' ? null : 1000,
          allocation_estimated: false,
        }),
      ),
    })
    renderWithProviders(<ResultsPage runId="abc123" onRunChange={vi.fn()} />)

    await userEvent.click(
      await screen.findByRole('tab', { name: 'Cost allocations' }),
    )

    expect(getCostAllocations).toHaveBeenCalledWith('abc123', 2026, undefined)
    expect(await screen.findAllByText('$1,000')).toHaveLength(3)
    expect(
      screen.getByText(/Some enabled costs are unavailable/),
    ).toBeInTheDocument()
  })
})
