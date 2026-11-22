// The analysis settings, like the "Analysis costs" controls on the Streamlit
// page. Only the settings someone changes are kept - the backend fills in the
// rest from the repository's economics config.
import {
  NumberInput,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
} from '@mantine/core'
import type { Schemas } from '../../api/client'

type RunSettingsFormProps = {
  defaults: Schemas['SettingsChoices']
  // The changed settings only.
  value: Schemas['RunSettings']
  onChange: (value: Schemas['RunSettings']) => void
}

type CostStream = Schemas['SettingsChoices']['optional_cost_streams'][number]

const COST_STREAM_LABELS: Record<CostStream, string> = {
  disposal: 'Disposal',
  carbon: 'Carbon',
}

export default function RunSettingsForm({
  defaults,
  value,
  onChange,
}: RunSettingsFormProps) {
  // What each control shows: the change if there is one, otherwise the default.
  const startYear = value.start_year ?? defaults.start_year
  const endYear = value.end_year ?? defaults.end_year
  const rate = value.real_discount_rate ?? defaults.real_discount_rate
  const carbonRate = value.scghg_discount_rate ?? defaults.scghg_discount_rate
  const demandSurge = value.demand_surge ?? defaults.demand_surge
  const costStreams = value.cost_streams ?? defaults.cost_streams

  const change = (changes: Schemas['RunSettings']) =>
    onChange({ ...value, ...changes })
  const whole = (input: number | string) =>
    typeof input === 'number' ? Math.round(input) : undefined

  return (
    <Stack>
      <SimpleGrid cols={{ base: 1, sm: 2 }}>
        <NumberInput
          label="Start year"
          min={defaults.first_year}
          max={defaults.last_year}
          value={startYear}
          onChange={(input) => change({ start_year: whole(input) })}
          allowDecimal={false}
        />
        <NumberInput
          label="End year"
          min={defaults.first_year}
          max={defaults.last_year}
          value={endYear}
          onChange={(input) => change({ end_year: whole(input) })}
          allowDecimal={false}
          error={
            endYear < startYear
              ? 'Must be no earlier than the start year'
              : undefined
          }
        />
        <NumberInput
          label="Annual real discount rate (%)"
          min={0}
          step={0.25}
          decimalScale={2}
          value={rate * 100}
          onChange={(input) =>
            change({
              real_discount_rate:
                typeof input === 'number' ? input / 100 : undefined,
            })
          }
        />
        <Select
          label="Social cost of carbon rate (%)"
          data={defaults.scghg_discount_rate_options.map(String)}
          value={String(carbonRate)}
          onChange={(input) =>
            input && change({ scghg_discount_rate: Number(input) })
          }
          allowDeselect={false}
        />
      </SimpleGrid>

      <Switch
        label="Demand surge"
        description="Higher repair costs after a big storm, when crews and materials are scarce"
        checked={demandSurge}
        onChange={(event) =>
          change({ demand_surge: event.currentTarget.checked })
        }
      />

      <Text size="sm" fw={500}>
        Costs counted
      </Text>
      <Text size="sm" c="dimmed">
        Material and labor are always counted.
      </Text>
      {defaults.optional_cost_streams.map((stream) => (
        <Switch
          key={stream}
          label={COST_STREAM_LABELS[stream]}
          checked={costStreams.includes(stream)}
          onChange={(event) =>
            change({
              cost_streams: event.currentTarget.checked
                ? [...costStreams, stream]
                : costStreams.filter((other) => other !== stream),
            })
          }
        />
      ))}
      <Switch
        label="Loss of use"
        description="Needs verified yearly loss-of-use costs for every asset and roof material"
        checked={false}
        disabled
      />
    </Stack>
  )
}
