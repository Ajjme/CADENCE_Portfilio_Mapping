// The summary cards above the asset table, for the selected assets.
import { Paper, SimpleGrid, Text } from '@mantine/core'
import { MATERIALS, summarize, type Asset } from './assets'

export default function PortfolioSummary({ assets }: { assets: Asset[] }) {
  const summary = summarize(assets)
  const number = (value: number | null, digits = 0) =>
    value === null
      ? 'Unavailable'
      : value.toLocaleString('en-US', { maximumFractionDigits: digits })

  const cards: [string, string][] = [
    ['Assets', String(summary.count)],
    ['Average roof age', `${number(summary.averageAge, 1)} yrs`],
    ['Total roof area', `${number(summary.totalArea)} sq ft`],
    ['Average roof area', `${number(summary.averageArea)} sq ft`],
    [
      'Total insured value',
      summary.insuredTotal === null
        ? 'Incomplete'
        : `$${number(summary.insuredTotal)}`,
    ],
    ...MATERIALS.map((material): [string, string] => [
      `${material} roofs`,
      String(summary.materials[material]),
    ]),
  ]

  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }}>
      {cards.map(([label, value]) => (
        <Paper key={label} withBorder p="sm" radius="md">
          <Text size="xs" c="dimmed">
            {label}
          </Text>
          <Text fw={700}>{value}</Text>
        </Paper>
      ))}
    </SimpleGrid>
  )
}
