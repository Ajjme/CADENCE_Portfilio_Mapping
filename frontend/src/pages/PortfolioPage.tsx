// Asset Portfolio - where every run starts, like the Streamlit page of the same name.
// Reads top to bottom like the screen: pick a workbook, check its assets and
// settings, then run. The pieces are in pages/portfolio/.
import {
  Alert,
  Button,
  FileInput,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Title,
} from '@mantine/core'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import type { Schemas } from '../api/client'
import {
  EXAMPLE_WORKBOOK_URL,
  getDefaultPortfolio,
  uploadPortfolio,
} from '../api/portfolio'
import { runAnalysis } from '../api/runs'
import { getSettings } from '../api/settings'
import PageHeader from '../components/PageHeader'
import AssetTable from './portfolio/AssetTable'
import PortfolioSummary from './portfolio/PortfolioSummary'
import RunSettingsForm from './portfolio/RunSettingsForm'
import { assetIdOf } from './portfolio/assets'

type PortfolioPageProps = {
  // Called with the new run's ID once a run finishes.
  onRunFinished: (runId: string) => void
}

export default function PortfolioPage({ onRunFinished }: PortfolioPageProps) {
  // An uploaded workbook, or null to use the example one.
  const [uploaded, setUploaded] = useState<Schemas['Portfolio'] | null>(null)
  // Settings someone changed. Kept when switching workbooks.
  const [settings, setSettings] = useState<Schemas['RunSettings']>({})

  const example = useQuery({
    queryKey: ['portfolio', 'default'],
    queryFn: getDefaultPortfolio,
  })
  const defaults = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const upload = useMutation({
    mutationFn: uploadPortfolio,
    onSuccess: setUploaded,
  })
  const portfolio = uploaded ?? example.data

  return (
    <>
      <PageHeader
        title="Asset Portfolio"
        description="Load an asset workbook and run the alternative analysis."
      />
      <Stack gap="lg">
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Title order={4}>Asset workbook</Title>
            <Text size="sm">
              Using{' '}
              <b>{portfolio ? portfolio.file_name : 'the example workbook'}</b>
              {uploaded === null && ' (the repository example)'}. Assets must be
              in Sheet1.
            </Text>
            <Group align="end">
              <FileInput
                label="Upload your own workbook"
                placeholder="Choose an .xlsx file"
                accept=".xlsx"
                onChange={(file) => file && upload.mutate(file)}
                disabled={upload.isPending}
                w={300}
              />
              <Button component="a" href={EXAMPLE_WORKBOOK_URL} variant="light">
                Download the example workbook
              </Button>
              {uploaded !== null && (
                <Button variant="subtle" onClick={() => setUploaded(null)}>
                  Go back to the example
                </Button>
              )}
            </Group>
            {upload.isPending && <Loader size="sm" />}
            {upload.isError && (
              <Alert color="red" title="That workbook can't be used">
                {upload.error.message}
              </Alert>
            )}
          </Stack>
        </Paper>

        {portfolio === undefined && example.isPending && <Loader />}
        {portfolio === undefined && example.isError && (
          <Alert color="red" title="The example workbook can't be loaded">
            {example.error.message} Is the backend running?
          </Alert>
        )}
        {portfolio && defaults.data && (
          // key starts the asset checkboxes over when a different workbook loads.
          <LoadedPortfolio
            key={portfolio.workbook_id}
            portfolio={portfolio}
            defaults={defaults.data}
            settings={settings}
            onSettingsChange={setSettings}
            onRunFinished={onRunFinished}
          />
        )}
        {defaults.isError && (
          <Alert color="red" title="The run settings can't be loaded">
            {defaults.error.message}
          </Alert>
        )}
      </Stack>
    </>
  )
}

// Everything below the workbook picker: the summary, the asset table, the
// settings, and the Run button.
function LoadedPortfolio({
  portfolio,
  defaults,
  settings,
  onSettingsChange,
  onRunFinished,
}: {
  portfolio: Schemas['Portfolio']
  defaults: Schemas['SettingsChoices']
  settings: Schemas['RunSettings']
  onSettingsChange: (settings: Schemas['RunSettings']) => void
  onRunFinished: (runId: string) => void
}) {
  // Assets left out of the run. Every asset is in by default.
  const [excluded, setExcluded] = useState<Set<string>>(new Set())
  const run = useMutation({
    mutationFn: runAnalysis,
    onSuccess: (finished) => onRunFinished(finished.run_id),
  })

  const selected = portfolio.assets.filter(
    (asset) => !excluded.has(assetIdOf(asset)),
  )
  const yearsBackwards =
    (settings.end_year ?? defaults.end_year) <
    (settings.start_year ?? defaults.start_year)

  function startRun() {
    run.mutate({
      workbook_id: portfolio.workbook_id,
      // Leave asset_ids out to run every asset.
      asset_ids:
        excluded.size === 0 ? undefined : selected.map(assetIdOf).sort(),
      settings,
    })
  }

  return (
    <>
      <Stack gap="xs">
        <Title order={4}>Portfolio summary</Title>
        <Text size="sm" c="dimmed">
          {selected.length} of {portfolio.asset_count} assets selected
        </Text>
        <PortfolioSummary assets={selected} />
      </Stack>

      <Stack gap="xs">
        <Title order={4}>Assets</Title>
        <AssetTable
          assets={portfolio.assets}
          excluded={excluded}
          onExcludedChange={setExcluded}
        />
      </Stack>

      <Paper withBorder p="md" radius="md">
        <Stack>
          <Title order={4}>Analysis settings</Title>
          <RunSettingsForm
            defaults={defaults}
            value={settings}
            onChange={onSettingsChange}
          />
        </Stack>
      </Paper>

      <Stack gap="xs">
        <Group>
          <Button
            size="md"
            onClick={startRun}
            loading={run.isPending}
            disabled={selected.length === 0 || yearsBackwards}
          >
            Run Alternative Analysis
          </Button>
          {run.isPending && (
            <Text size="sm" c="dimmed">
              Running {selected.length} assets - this takes a minute or two. The
              results open when it finishes.
            </Text>
          )}
        </Group>
        {selected.length === 0 && (
          <Text size="sm" c="orange">
            Select at least one asset to run.
          </Text>
        )}
        {run.isError && (
          <Alert color="red" title="The run failed">
            {run.error.message}
          </Alert>
        )}
      </Stack>
    </>
  )
}
