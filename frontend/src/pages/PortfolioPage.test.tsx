import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Schemas } from '../api/client'
import { getDefaultPortfolio, uploadPortfolio } from '../api/portfolio'
import { runAnalysis } from '../api/runs'
import { getSettings } from '../api/settings'
import { renderWithProviders } from '../test/renderWithProviders'
import PortfolioPage from './PortfolioPage'

// A pretend backend: each test sets what these calls return.
vi.mock('../api/portfolio', () => ({
  EXAMPLE_WORKBOOK_URL: '/api/portfolio/example',
  getDefaultPortfolio: vi.fn(),
  uploadPortfolio: vi.fn(),
}))
vi.mock('../api/runs', () => ({ runAnalysis: vi.fn() }))
vi.mock('../api/settings', () => ({ getSettings: vi.fn() }))

const EXAMPLE: Schemas['Portfolio'] = {
  workbook_id: 'default',
  file_name: 'asset_inventory_test_1.xlsx',
  asset_count: 2,
  assets: [
    {
      asset_id: 'durham_metal_15',
      official_material: 'Metal',
      roof_age: 15,
      roof_area_sqft: 750,
      insured_value: 50000,
      Terrain: 'open',
    },
    {
      asset_id: 'durham_asphalt_5',
      official_material: 'Asphalt',
      roof_age: 5,
      roof_area_sqft: 1250,
      insured_value: 70000,
      Terrain: 'open',
    },
  ],
}

const SETTINGS: Schemas['SettingsChoices'] = {
  start_year: 2026,
  end_year: 2050,
  real_discount_rate: 0.02,
  scghg_discount_rate: 2,
  demand_surge: false,
  cost_streams: ['disposal', 'carbon'],
  first_year: 2026,
  last_year: 2050,
  scghg_discount_rate_options: [1.5, 2, 2.5],
  optional_cost_streams: ['disposal', 'carbon'],
  metrics: { net_present_value_usd: 'Net present value' },
}

const RUN: Schemas['RunInfo'] = {
  run_id: 'new-run',
  schema_version: 'v0.4.0',
  asset_count: 1,
  start_year: 2026,
  end_year: 2050,
  enabled_cost_streams: ['labor', 'material'],
}

beforeEach(() => {
  vi.mocked(getDefaultPortfolio).mockResolvedValue(EXAMPLE)
  vi.mocked(getSettings).mockResolvedValue(SETTINGS)
  vi.mocked(runAnalysis).mockResolvedValue(RUN)
})

// The request the Run button sent.
function sentRequest() {
  return vi.mocked(runAnalysis).mock.calls[0][0]
}

describe('PortfolioPage', () => {
  it('shows the example assets and their summary', async () => {
    renderWithProviders(<PortfolioPage onRunFinished={vi.fn()} />)

    expect(await screen.findByText('durham_metal_15')).toBeInTheDocument()
    expect(screen.getByText('2 of 2 assets selected')).toBeInTheDocument()
    expect(screen.getByText('2,000 sq ft')).toBeInTheDocument()
    expect(screen.getByText('$120,000')).toBeInTheDocument()
  })

  it('runs every asset with the default settings and opens the run', async () => {
    const onRunFinished = vi.fn()
    renderWithProviders(<PortfolioPage onRunFinished={onRunFinished} />)

    await userEvent.click(
      await screen.findByRole('button', { name: 'Run Alternative Analysis' }),
    )

    expect(sentRequest()).toEqual({
      workbook_id: 'default',
      asset_ids: undefined,
      settings: {},
    })
    await waitFor(() => expect(onRunFinished).toHaveBeenCalledWith('new-run'))
  })

  it('runs only the checked assets with the changed settings', async () => {
    renderWithProviders(<PortfolioPage onRunFinished={vi.fn()} />)

    await userEvent.click(
      await screen.findByRole('checkbox', { name: 'Include durham_metal_15' }),
    )
    await userEvent.click(screen.getByRole('switch', { name: /Demand surge/ }))
    await userEvent.click(screen.getByRole('switch', { name: 'Carbon' }))
    await userEvent.click(
      screen.getByRole('button', { name: 'Run Alternative Analysis' }),
    )

    expect(screen.getByText('1 of 2 assets selected')).toBeInTheDocument()
    expect(sentRequest()).toEqual({
      workbook_id: 'default',
      asset_ids: ['durham_asphalt_5'],
      settings: { demand_surge: true, cost_streams: ['disposal'] },
    })
  })

  it("won't run with no assets checked", async () => {
    renderWithProviders(<PortfolioPage onRunFinished={vi.fn()} />)

    await userEvent.click(
      await screen.findByRole('checkbox', { name: 'Include all assets' }),
    )

    expect(
      screen.getByRole('button', { name: 'Run Alternative Analysis' }),
    ).toBeDisabled()
    expect(
      screen.getByText('Select at least one asset to run.'),
    ).toBeInTheDocument()
  })

  it('uploads a workbook and shows its assets', async () => {
    vi.mocked(uploadPortfolio).mockResolvedValue({
      ...EXAMPLE,
      workbook_id: 'f'.repeat(64),
      file_name: 'my_assets.xlsx',
      asset_count: 1,
      assets: [EXAMPLE.assets[1]],
    })
    const { container } = renderWithProviders(
      <PortfolioPage onRunFinished={vi.fn()} />,
    )
    await screen.findByText('durham_metal_15')

    const file = new File(['xlsx'], 'my_assets.xlsx')
    await userEvent.upload(
      container.querySelector('input[type="file"]') as HTMLInputElement,
      file,
    )

    expect(
      await screen.findByText('1 of 1 assets selected'),
    ).toBeInTheDocument()
    expect(vi.mocked(uploadPortfolio).mock.calls[0][0]).toBe(file)
    expect(screen.queryByText('durham_metal_15')).not.toBeInTheDocument()
    expect(
      within(screen.getByText(/^Using/)).getByText('my_assets.xlsx'),
    ).toBeInTheDocument()
  })
})
