// Market Study tab: an experimental look at which roofs homeowners would
// replace each year if they act on the numbers, and what the portfolio pays.
// Like the Streamlit tab, the study runs only when someone clicks Run, since
// it takes a while, and a study saved earlier with the same settings opens
// right away.
import {
  Alert,
  Button,
  Group,
  Loader,
  NumberInput,
  Stack,
  Switch,
  Text,
} from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { ApiError, type Schemas } from '../../api/client'
import { getMarketStudy, runMarketStudy } from '../../api/runs'
import Chart from '../../components/Chart'
import { COST_COLORS } from './labels'

// Same colors as the Streamlit roof stock chart.
const MATERIALS: { id: string; label: string; color: string }[] = [
  { id: 'OFFICIAL_ASPHALT', label: 'Asphalt', color: '#696f7b' },
  { id: 'OFFICIAL_METAL', label: 'Metal', color: '#19817d' },
  { id: 'OFFICIAL_TILE', label: 'Tile', color: '#c08b3a' },
  { id: 'UNKNOWN', label: 'Unknown', color: '#b9bdc1' },
]

type MarketStudyTabProps = {
  run: Schemas['RunInfo']
  // Undefined for the whole portfolio. The study only covers the portfolio.
  assetId?: string
}

export default function MarketStudyTab({ run, assetId }: MarketStudyTabProps) {
  const [limitOn, setLimitOn] = useState(false)
  const [limitYears, setLimitYears] = useState(10)
  const maxPaybackYears = limitOn ? limitYears : undefined
  const queryKey = ['market-study', run.run_id, maxPaybackYears ?? 'none']
  const ready = assetId === undefined && Boolean(run.market_study_ready)

  const queryClient = useQueryClient()
  const saved = useQuery({
    queryKey,
    queryFn: () => getMarketStudy(run.run_id, maxPaybackYears),
    enabled: ready,
    // A 404 just means it hasn't been run yet, so don't ask again.
    retry: false,
  })
  const calculate = useMutation({
    mutationFn: () => runMarketStudy(run.run_id, maxPaybackYears),
    onSuccess: (study) => queryClient.setQueryData(queryKey, study),
  })
  const notRunYet =
    saved.error instanceof ApiError && saved.error.status === 404

  return (
    <Stack>
      <Alert color="yellow" title="Experimental">
        An economic acceptance proxy, not a calibrated market forecast or a
        homeowner affordability assessment. Repair costs are before insurance,
        and enabled carbon costs are included. Don't rely on these projections
        for investment decisions.
      </Alert>

      {assetId !== undefined && (
        <Text>Select Portfolio at the top to view the Market Study.</Text>
      )}
      {assetId === undefined && !run.market_study_ready && (
        <Text>
          The Market Study needs the asset inputs saved when a run starts from
          the Asset Portfolio page. Run the portfolio there to use it.
        </Text>
      )}

      {ready && (
        <>
          <Text size="sm" c="dimmed">
            Every home is checked every year. A voluntary replacement needs a
            positive added NPV, and required replacements (end of life or
            damage) still happen.
          </Text>
          <Group align="end">
            <Switch
              label="Limit homeowner payback period"
              checked={limitOn}
              onChange={(event) => setLimitOn(event.currentTarget.checked)}
            />
            <NumberInput
              label="Maximum acceptable payback (years)"
              description="First discounted recovery of the added cost"
              min={1}
              allowDecimal={false}
              value={limitYears}
              onChange={(input) =>
                typeof input === 'number' && input >= 1 && setLimitYears(input)
              }
              disabled={!limitOn}
              w={260}
            />
          </Group>
          <Group>
            <Button
              onClick={() => calculate.mutate()}
              loading={calculate.isPending}
            >
              Run Market Study
            </Button>
            {calculate.isPending && (
              <Text size="sm" c="dimmed">
                Checking every home's replacement choice for each year - this
                can take a few minutes.
              </Text>
            )}
          </Group>
          {calculate.isError && (
            <Alert color="red" title="The Market Study failed">
              {calculate.error.message}
            </Alert>
          )}

          {saved.isPending && <Loader />}
          {notRunYet && !calculate.isPending && (
            <Text>
              Run the Market Study to see results for these settings. Changing
              the payback limit needs a new run.
            </Text>
          )}
          {saved.isError && !notRunYet && (
            <Alert color="red" title="The saved Market Study can't be opened">
              {saved.error.message}
            </Alert>
          )}
          {saved.data && <StudyResults study={saved.data} />}
        </>
      )}
    </Stack>
  )
}

function StudyResults({ study }: { study: Schemas['MarketStudy'] }) {
  const { shareData, costData } = useMemo(() => {
    const years = [...new Set(study.roof_share.map((row) => row.year))].sort(
      (a, b) => a - b,
    )
    const shareData = MATERIALS.map((material) => {
      const rows = years.map((year) =>
        study.roof_share.find(
          (row) => row.year === year && row.material_id === material.id,
        ),
      )
      return {
        type: 'bar' as const,
        name: material.label,
        x: years,
        y: rows.map((row) => row?.share_percent ?? 0),
        customdata: rows.map((row) => row?.asset_count ?? 0),
        marker: { color: material.color },
        hovertemplate:
          '%{x}<br>%{y:.1f}% · %{customdata} roofs<extra>%{fullData.name}</extra>',
      }
    })
    const costData = Object.entries(study.cost_labels).map(
      ([column, label]) => ({
        type: 'bar' as const,
        name: label,
        x: study.costs.map((row) => row.year),
        y: study.costs.map(
          (row) =>
            (row[column as keyof Schemas['MarketYear']] as
              number | null | undefined) ?? null,
        ),
        customdata: study.costs.map((row) => [
          row.replacement_count,
          row.eul_replacements,
          row.damage_replacements,
          row.economic_replacements,
          row.unknown_count,
        ]),
        marker: { color: COST_COLORS[column] },
        hovertemplate:
          '%{x}<br>%{y:$,.0f}<br>Replacements: %{customdata[0]} (end of life %{customdata[1]}, damage %{customdata[2]}, economic %{customdata[3]})<br>Unknown: %{customdata[4]}<extra>%{fullData.name}</extra>',
      }),
    )
    return { shareData, costData }
  }, [study])

  const shareLayout = useMemo(
    () => ({
      title: { text: 'Roof stock by material' },
      barmode: 'stack' as const,
      xaxis: { title: { text: 'Year' } },
      yaxis: { title: { text: 'Share of portfolio (%)' }, range: [0, 100] },
      legend: { orientation: 'h' as const, y: -0.2 },
    }),
    [],
  )
  const costLayout = useMemo(
    () => ({
      title: { text: 'Expected yearly portfolio costs' },
      barmode: 'stack' as const,
      xaxis: { title: { text: 'Year' } },
      yaxis: { title: { text: 'Real 2026 USD' }, tickformat: '$,.0f' },
      legend: { orientation: 'h' as const, y: -0.2 },
    }),
    [],
  )
  const unknown = study.costs.some((row) => row.unknown_count > 0)

  return (
    <Stack>
      <Text size="sm" c="dimmed">
        Study {study.study_id} ·{' '}
        {study.newly_calculated ? 'just calculated' : 'saved earlier'} · Payback
        limit:{' '}
        {study.max_payback_years ? `${study.max_payback_years} years` : 'off'} ·
        Real discount rate: {(study.real_discount_rate * 100).toFixed(1)}% ·
        Costs: {study.enabled_cost_streams.join(', ')}
        {study.tile_uses_metal_proxy &&
          ' · Tile uses the provisional metal stand-in'}
      </Text>
      <Text size="sm" c="dimmed">
        After {study.last_verified_year}, the run's last year, prices and
        climate are held constant through {study.evaluation_end_year} for the
        look-ahead. Roofs still age, and required replacements still happen.
        Those later years are extrapolated.
      </Text>
      {unknown && (
        <Text size="sm" c="orange">
          Assets with incomplete costs or damage are counted as Unknown, and the
          dollar totals they affect are unavailable.
        </Text>
      )}
      <Chart data={shareData} layout={shareLayout} />
      <Chart data={costData} layout={costLayout} />
    </Stack>
  )
}
