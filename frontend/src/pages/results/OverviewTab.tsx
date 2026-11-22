// Overview tab: final NPV and the other totals for each replacement option,
// for the whole portfolio or one asset. For the portfolio it also lists each
// asset's NPV, so the best option for every asset is easy to see.
import {
  Badge,
  Group,
  Paper,
  SimpleGrid,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { useMemo } from 'react'
import type { Schemas } from '../../api/client'
import Chart from '../../components/Chart'
import {
  REPLACEMENTS,
  SCENARIO_COLORS,
  bestOption,
  formatUsd,
  scenarioLabel,
  type Outcome,
} from './labels'

type OverviewTabProps = {
  summary: Schemas['RunSummary']
  // Undefined for the whole portfolio.
  assetId?: string
}

export default function OverviewTab({ summary, assetId }: OverviewTabProps) {
  const portfolio = assetId === undefined
  const outcomes: Outcome[] = portfolio
    ? summary.portfolio
    : summary.assets.filter((row) => row.asset_id === assetId)
  const best = bestOption(outcomes)

  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, md: 3 }}>
        {REPLACEMENTS.map((scenarioId) => (
          <OptionCard
            key={scenarioId}
            scenarioId={scenarioId}
            outcome={outcomes.find((row) => row.scenario_id === scenarioId)}
            isBest={scenarioId === best}
            portfolio={portfolio}
          />
        ))}
      </SimpleGrid>

      <NpvChart
        outcomes={outcomes}
        title={
          portfolio ? 'Portfolio NPV by option' : `${assetId} NPV by option`
        }
      />

      {portfolio && <AssetNpvTable assets={summary.assets} />}
    </Stack>
  )
}

// One replacement option's totals, with the final NPV first.
function OptionCard({
  scenarioId,
  outcome,
  isBest,
  portfolio,
}: {
  scenarioId: string
  outcome?: Outcome
  isBest: boolean
  portfolio: boolean
}) {
  const incomplete =
    outcome?.repair_cost_incomplete ||
    outcome?.climate_risk_total_incomplete ||
    outcome?.event_cost_incomplete

  return (
    <Paper withBorder p="md" radius="md">
      <Group justify="space-between" mb="xs">
        <Title order={4}>{scenarioLabel(scenarioId, portfolio)}</Title>
        {isBest && <Badge color="green">Highest NPV</Badge>}
      </Group>
      <Text size="sm" c="dimmed">
        Final NPV
      </Text>
      <Text size="xl" fw={700} mb="sm">
        {formatUsd(outcome?.net_present_value_usd)}
      </Text>
      <Stat
        label="Cumulative avoided damage"
        value={formatUsd(outcome?.cumulative_avoided_damage_usd)}
      />
      <Stat
        label="Discounted avoided damage"
        value={formatUsd(outcome?.cumulative_discounted_avoided_damage_usd)}
      />
      <Stat
        label="Cumulative net benefit"
        value={formatUsd(outcome?.cumulative_net_benefit_usd)}
      />
      <Stat
        label="Burnout replacements"
        value={String(outcome?.burnout_replacement_count ?? 'Unavailable')}
      />
      {outcome?.active_cost_fallback_applied && (
        <Text size="sm" c="orange" mt="xs">
          Installed-cost fallback used for
          {portfolio ? ' one or more assets' : ' this asset'}.
        </Text>
      )}
      {incomplete && (
        <Text size="sm" c="orange" mt="xs">
          Some costs are incomplete, so totals may be unavailable.
        </Text>
      )}
    </Paper>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Group justify="space-between" gap="xs">
      <Text size="sm">{label}</Text>
      <Text size="sm" fw={500}>
        {value}
      </Text>
    </Group>
  )
}

function NpvChart({ outcomes, title }: { outcomes: Outcome[]; title: string }) {
  const data = useMemo(
    () =>
      REPLACEMENTS.map((scenarioId) => {
        const label = scenarioLabel(scenarioId, true)
        const npv = outcomes.find(
          (row) => row.scenario_id === scenarioId,
        )?.net_present_value_usd
        return {
          type: 'bar' as const,
          name: label,
          x: [label],
          y: [npv ?? null],
          marker: { color: SCENARIO_COLORS[scenarioId] },
          hovertemplate: '%{x}<br>%{y:$,.0f}<extra></extra>',
        }
      }),
    [outcomes],
  )
  const layout = useMemo(
    () => ({
      title: { text: title },
      showlegend: false,
      yaxis: { title: { text: 'Real 2026 USD' }, tickformat: '$,.0f' },
    }),
    [title],
  )
  return <Chart data={data} layout={layout} height={360} />
}

// Every asset's final NPV for each option, with its best option.
function AssetNpvTable({ assets }: { assets: Schemas['AssetScenario'][] }) {
  const assetIds = [...new Set(assets.map((row) => row.asset_id))].sort()

  return (
    <Stack gap="xs">
      <Title order={4}>Final NPV by asset</Title>
      <Table.ScrollContainer minWidth={600}>
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Asset</Table.Th>
              {REPLACEMENTS.map((scenarioId) => (
                <Table.Th key={scenarioId} ta="right">
                  {scenarioLabel(scenarioId, false)}
                </Table.Th>
              ))}
              <Table.Th>Best option</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {assetIds.map((assetId) => {
              const rows = assets.filter((row) => row.asset_id === assetId)
              const best = bestOption(rows)
              return (
                <Table.Tr key={assetId}>
                  <Table.Td>{assetId}</Table.Td>
                  {REPLACEMENTS.map((scenarioId) => (
                    <Table.Td
                      key={scenarioId}
                      ta="right"
                      fw={scenarioId === best ? 700 : undefined}
                    >
                      {formatUsd(
                        rows.find((row) => row.scenario_id === scenarioId)
                          ?.net_present_value_usd,
                      )}
                    </Table.Td>
                  ))}
                  <Table.Td>
                    {best ? scenarioLabel(best, false) : 'Unavailable'}
                  </Table.Td>
                </Table.Tr>
              )
            })}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}
