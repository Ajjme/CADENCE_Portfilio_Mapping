import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type Schemas } from '../../api/client'
import { getMarketStudy, runMarketStudy } from '../../api/runs'
import { renderWithProviders } from '../../test/renderWithProviders'
import MarketStudyTab from './MarketStudyTab'

// A pretend backend: each test sets what these calls return.
vi.mock('../../api/runs', () => ({
  getMarketStudy: vi.fn(),
  runMarketStudy: vi.fn(),
}))

const RUN: Schemas['RunInfo'] = {
  run_id: 'abc123',
  schema_version: 'v0.4.0',
  asset_count: 2,
  start_year: 2026,
  end_year: 2027,
  enabled_cost_streams: ['labor', 'material'],
  market_study_ready: true,
}

const STUDY: Schemas['MarketStudy'] = {
  run_id: 'abc123',
  study_id: 'study-1',
  max_payback_years: null,
  newly_calculated: true,
  asset_count: 2,
  last_verified_year: 2027,
  evaluation_end_year: 2060,
  real_discount_rate: 0.02,
  enabled_cost_streams: ['labor', 'material'],
  tile_uses_metal_proxy: true,
  policy_id: 'policy',
  cost_labels: { repair_usd: 'Expected repair', material_usd: 'Material' },
  roof_share: [
    {
      year: 2026,
      material_id: 'OFFICIAL_ASPHALT',
      asset_count: 2,
      share_percent: 100,
    },
    {
      year: 2027,
      material_id: 'OFFICIAL_METAL',
      asset_count: 2,
      share_percent: 100,
    },
  ],
  costs: [2026, 2027].map((year) => ({
    year,
    repair_usd: 20,
    material_usd: year === 2027 ? 100 : 0,
    total_usd: 20,
    replacement_count: year === 2027 ? 2 : 0,
    eul_replacements: 0,
    damage_replacements: 0,
    economic_replacements: year === 2027 ? 2 : 0,
    unknown_count: 0,
  })),
}

beforeEach(() => {
  vi.mocked(getMarketStudy).mockRejectedValue(
    new ApiError(
      404,
      "the Market Study hasn't been run with these settings yet",
    ),
  )
  vi.mocked(runMarketStudy).mockResolvedValue(STUDY)
})

describe('MarketStudyTab', () => {
  it('asks for the portfolio when one asset is selected', () => {
    renderWithProviders(<MarketStudyTab run={RUN} assetId="A-1" />)

    expect(screen.getByText(/Select Portfolio/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Run Market Study' }),
    ).toBeNull()
  })

  it('explains when the run has no saved asset inputs', () => {
    renderWithProviders(
      <MarketStudyTab run={{ ...RUN, market_study_ready: false }} />,
    )

    expect(screen.getByText(/needs the asset inputs/)).toBeInTheDocument()
    expect(getMarketStudy).not.toHaveBeenCalled()
  })

  it('runs the study with no payback limit and shows it', async () => {
    renderWithProviders(<MarketStudyTab run={RUN} />)
    expect(
      await screen.findByText(/Run the Market Study to see results/),
    ).toBeInTheDocument()

    await userEvent.click(
      screen.getByRole('button', { name: 'Run Market Study' }),
    )

    expect(vi.mocked(runMarketStudy).mock.calls[0]).toEqual([
      'abc123',
      undefined,
    ])
    expect(await screen.findByText(/just calculated/)).toBeInTheDocument()
    expect(screen.getByText(/held constant through 2060/)).toBeInTheDocument()
  })

  it('runs the study with a payback limit', async () => {
    renderWithProviders(<MarketStudyTab run={RUN} />)

    await userEvent.click(
      screen.getByRole('switch', { name: 'Limit homeowner payback period' }),
    )
    await userEvent.click(
      screen.getByRole('button', { name: 'Run Market Study' }),
    )

    expect(vi.mocked(runMarketStudy).mock.calls[0]).toEqual(['abc123', 10])
  })

  it('opens a study saved earlier without running it again', async () => {
    vi.mocked(getMarketStudy).mockResolvedValue({
      ...STUDY,
      newly_calculated: false,
    })
    renderWithProviders(<MarketStudyTab run={RUN} />)

    expect(await screen.findByText(/saved earlier/)).toBeInTheDocument()
    expect(runMarketStudy).not.toHaveBeenCalled()
  })
})
