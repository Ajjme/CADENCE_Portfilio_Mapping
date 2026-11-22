// Time series tab: one yearly result for each option, for the whole portfolio
// or one asset. Net present value by default, and any other yearly metric
// from the picker.
import { Alert, Loader, Select, Stack, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import type { Schemas } from '../../api/client'
import { getRunSeries } from '../../api/runs'
import { getSettings } from '../../api/settings'
import Chart from '../../components/Chart'
import { SCENARIOS, SCENARIO_COLORS, scenarioLabel } from './labels'

type TimeSeriesTabProps = {
  runId: string
  // Undefined for the whole portfolio.
  assetId?: string
}

export default function TimeSeriesTab({ runId, assetId }: TimeSeriesTabProps) {
  const [metric, setMetric] = useState('net_present_value_usd')
  const settings = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const series = useQuery({
    queryKey: ['series', runId, assetId ?? 'portfolio', metric],
    queryFn: () => getRunSeries(runId, { metric, assetId }),
  })

  const metricOptions = Object.entries(settings.data?.metrics ?? {}).map(
    ([value, label]) => ({ value, label }),
  )
  const missing =
    series.data?.points.filter((point) => point.value === null).length ?? 0

  return (
    <Stack>
      <Select
        label="Metric"
        data={metricOptions}
        value={metric}
        onChange={(value) => value && setMetric(value)}
        allowDeselect={false}
        maw={320}
      />
      {series.isPending && <Loader />}
      {series.isError && (
        <Alert color="red" title="The time series can't be loaded">
          {series.error.message}
        </Alert>
      )}
      {series.data && (
        <>
          <SeriesChart series={series.data} portfolio={assetId === undefined} />
          {missing > 0 && (
            <Text size="sm" c="orange">
              {missing} values are unavailable and show as gaps.
            </Text>
          )}
        </>
      )}
    </Stack>
  )
}

function SeriesChart({
  series,
  portfolio,
}: {
  series: Schemas['Series']
  portfolio: boolean
}) {
  const data = useMemo(
    () =>
      SCENARIOS.map((scenarioId) => {
        const points = series.points
          .filter((point) => point.scenario_id === scenarioId)
          .sort((a, b) => a.year - b.year)
        return {
          type: 'scatter' as const,
          mode: 'lines+markers' as const,
          name: scenarioLabel(scenarioId, portfolio),
          x: points.map((point) => point.year),
          y: points.map((point) => point.value),
          line: { color: SCENARIO_COLORS[scenarioId] },
          hovertemplate: '%{x}<br>%{y:$,.0f}<extra>%{fullData.name}</extra>',
        }
      }),
    [series, portfolio],
  )
  const layout = useMemo(
    () => ({
      title: { text: `${series.asset_id ?? 'Portfolio'} · ${series.label}` },
      xaxis: { title: { text: 'Year' }, dtick: 2 },
      yaxis: { title: { text: 'Real 2026 USD' }, tickformat: '$,.0f' },
      legend: { orientation: 'h' as const, y: -0.2 },
    }),
    [series],
  )
  return <Chart data={data} layout={layout} />
}
