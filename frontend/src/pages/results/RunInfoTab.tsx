// Run information tab: the settings this run used.
import { Table } from '@mantine/core'
import type { Schemas } from '../../api/client'

const COST_STREAM_LABELS: Record<string, string> = {
  material: 'Material',
  labor: 'Labor',
  disposal: 'Disposal',
  carbon: 'Carbon',
  loss_of_use: 'Loss of use',
}

export default function RunInfoTab({ run }: { run: Schemas['RunInfo'] }) {
  const percent = (value?: number | null) =>
    value === null || value === undefined ? 'Not recorded' : `${value}%`
  const rows: [string, string][] = [
    ['Run ID', run.run_id],
    ['Run time (UTC)', run.run_timestamp ?? 'Not recorded'],
    ['Assets', String(run.asset_count)],
    ['Years', `${run.start_year}–${run.end_year}`],
    [
      'Real discount rate',
      percent(
        run.real_discount_rate === null || run.real_discount_rate === undefined
          ? null
          : run.real_discount_rate * 100,
      ),
    ],
    ['Social cost of carbon rate', percent(run.scghg_discount_rate)],
    [
      'Demand surge',
      run.demand_surge === null || run.demand_surge === undefined
        ? 'Not recorded'
        : run.demand_surge
          ? 'Yes'
          : 'No',
    ],
    [
      'Cost streams',
      run.enabled_cost_streams
        .map((stream) => COST_STREAM_LABELS[stream] ?? stream)
        .join(', '),
    ],
    ['Dollars', 'Real 2026 USD'],
    ['Result schema', run.schema_version],
  ]

  return (
    <Table maw={640} withRowBorders>
      <Table.Tbody>
        {rows.map(([label, value]) => (
          <Table.Tr key={label}>
            <Table.Th w={240}>{label}</Table.Th>
            <Table.Td>{value}</Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  )
}
