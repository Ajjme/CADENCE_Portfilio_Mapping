// Cost allocations tab: one year's costs for each option, split into material,
// labor, expected repair, and the rest - the capital allocation chart.
import { Alert, Loader, Select, Stack, Table, Text } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import type { Schemas } from '../../api/client'
import { getCostAllocations } from '../../api/runs'
import Chart from '../../components/Chart'
import { COST_COLORS, SCENARIOS, formatUsd, scenarioLabel } from './labels'

type CostAllocationsTabProps = {
  runId: string
  // Undefined for the whole portfolio.
  assetId?: string
  startYear: number
  endYear: number
}

export default function CostAllocationsTab({
  runId,
  assetId,
  startYear,
  endYear,
}: CostAllocationsTabProps) {
  const [year, setYear] = useState(startYear)
  const costs = useQuery({
    queryKey: ['cost-allocations', runId, assetId ?? 'portfolio', year],
    queryFn: () => getCostAllocations(runId, year, assetId),
  })

  const years = Array.from({ length: endYear - startYear + 1 }, (_, index) =>
    String(startYear + index),
  )

  return (
    <Stack>
      <Select
        label="Cost year"
        data={years}
        value={String(year)}
        onChange={(value) => value && setYear(Number(value))}
        allowDeselect={false}
        maw={160}
      />
      {costs.isPending && <Loader />}
      {costs.isError && (
        <Alert color="red" title="Cost allocations can't be loaded">
          {costs.error.message}
        </Alert>
      )}
      {costs.data && (
        <CostDetails costs={costs.data} portfolio={assetId === undefined} />
      )}
    </Stack>
  )
}

function CostDetails({
  costs,
  portfolio,
}: {
  costs: Schemas['CostAllocations']
  portfolio: boolean
}) {
  const { rows, columns, labels, data } = useMemo(() => {
    const rows = SCENARIOS.map((scenarioId) =>
      costs.rows.find((row) => row.scenario_id === scenarioId),
    )
    const columns = Object.entries(costs.labels) as [
      keyof Schemas['CostAllocation'],
      string,
    ][]
    const labels = SCENARIOS.map((scenarioId) =>
      scenarioLabel(scenarioId, portfolio),
    )
    const data = [
      // One stacked bar part per cost, in the same color for every option.
      ...columns.map(([column, name]) => ({
        type: 'bar' as const,
        name,
        x: labels,
        y: rows.map((row) => numberOrNull(row?.[column])),
        marker: { color: COST_COLORS[column] },
        hovertemplate: `%{x}<br>${name}: %{y:$,.0f}<extra></extra>`,
      })),
      // The total above each bar.
      {
        type: 'scatter' as const,
        mode: 'text' as const,
        x: labels,
        y: rows.map((row) =>
          columns.reduce(
            (sum, [column]) => sum + (numberOrNull(row?.[column]) ?? 0),
            0,
          ),
        ),
        text: rows.map((row) =>
          row?.total_usd === null || row?.total_usd === undefined
            ? 'Incomplete'
            : formatUsd(row.total_usd),
        ),
        textposition: 'top center' as const,
        showlegend: false,
        hoverinfo: 'skip' as const,
      },
    ]
    return { rows, columns, labels, data }
  }, [costs, portfolio])
  const title = `${costs.asset_id ?? 'Portfolio'} · ${costs.year} cost allocations`
  const layout = useMemo(
    () => ({
      title: { text: title },
      barmode: 'stack' as const,
      yaxis: { title: { text: 'Real 2026 USD' }, tickformat: '$,.0f' },
      legend: { orientation: 'h' as const, y: -0.15 },
      margin: { t: 80 },
    }),
    [title],
  )

  return (
    <Stack>
      {rows.some((row) => row?.total_usd === null) && (
        <Text size="sm" c="orange">
          Some enabled costs are unavailable. Incomplete bars show the known
          parts only.
        </Text>
      )}
      <Chart data={data} layout={layout} />
      <Table.ScrollContainer minWidth={700}>
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Option</Table.Th>
              {columns.map(([column, name]) => (
                <Table.Th key={column} ta="right">
                  {name}
                </Table.Th>
              ))}
              <Table.Th ta="right">Total</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {rows.map((row, index) => (
              <Table.Tr key={SCENARIOS[index]}>
                <Table.Td>{labels[index]}</Table.Td>
                {columns.map(([column]) => (
                  <Table.Td key={column} ta="right">
                    {formatUsd(numberOrNull(row?.[column]))}
                  </Table.Td>
                ))}
                <Table.Td ta="right" fw={600}>
                  {formatUsd(row?.total_usd)}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Text size="sm" c="dimmed">
        Real 2026 USD. Installation, disposal, and carbon costs happen in the
        years a roof is installed or replaced. Repair and loss of use are
        expected yearly costs.
        {rows.some((row) => row?.allocation_estimated) &&
          ' The material and labor split uses source price shares or the configured fallback shares, and new tile uses the metal shares.'}
      </Text>
    </Stack>
  )
}

function numberOrNull(value: unknown) {
  return typeof value === 'number' ? value : null
}
