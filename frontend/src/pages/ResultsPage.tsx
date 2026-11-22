// Alternative Analysis Results - like the Streamlit results page.
// Shows one run: pick the whole portfolio or one asset at the top, then read
// the tabs. Each tab is its own file in pages/results/.
import {
  Alert,
  Button,
  Group,
  Loader,
  Select,
  Stack,
  Tabs,
  Text,
} from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getRun, getRunSummary, runExportUrl } from '../api/runs'
import PageHeader from '../components/PageHeader'
import CostAllocationsTab from './results/CostAllocationsTab'
import NoRunPanel from './results/NoRunPanel'
import OverviewTab from './results/OverviewTab'
import RunInfoTab from './results/RunInfoTab'
import TimeSeriesTab from './results/TimeSeriesTab'
import { PORTFOLIO } from './results/labels'

type ResultsPageProps = {
  // The open run, or null before there is one.
  runId: string | null
  onRunChange: (runId: string | null) => void
}

export default function ResultsPage({ runId, onRunChange }: ResultsPageProps) {
  return (
    <>
      <PageHeader
        title="Alternative Analysis Results"
        description="Compare the replacement options for the portfolio or one asset."
      />
      {runId === null ? (
        <NoRunPanel onRunReady={onRunChange} />
      ) : (
        // key resets the asset picker and tabs when a different run opens.
        <RunResults
          key={runId}
          runId={runId}
          onClose={() => onRunChange(null)}
        />
      )}
    </>
  )
}

function RunResults({
  runId,
  onClose,
}: {
  runId: string
  onClose: () => void
}) {
  const run = useQuery({
    queryKey: ['run', runId],
    queryFn: () => getRun(runId),
  })
  const summary = useQuery({
    queryKey: ['summary', runId],
    queryFn: () => getRunSummary(runId),
  })
  // Which asset the tabs show, or PORTFOLIO for all of them.
  const [asset, setAsset] = useState<string>(PORTFOLIO)

  if (run.isPending || summary.isPending) return <Loader />
  if (run.isError || summary.isError) {
    return (
      <Stack maw={560}>
        <Alert color="red" title="Results can't be opened">
          {(run.error ?? summary.error)?.message}
        </Alert>
        <Button variant="light" onClick={onClose}>
          Open another run
        </Button>
      </Stack>
    )
  }

  const assetIds = [
    ...new Set(summary.data.assets.map((row) => row.asset_id)),
  ].sort()
  // The API calls take no asset ID for the whole portfolio.
  const assetId = asset === PORTFOLIO ? undefined : asset

  return (
    <Stack>
      <Group justify="space-between" align="end">
        <Select
          label="Asset"
          data={[
            {
              value: PORTFOLIO,
              label: `Portfolio (all ${assetIds.length} assets)`,
            },
            ...assetIds.map((id) => ({ value: id, label: id })),
          ]}
          value={asset}
          onChange={(value) => setAsset(value ?? PORTFOLIO)}
          allowDeselect={false}
          searchable
          w={300}
        />
        <Group>
          <Button component="a" href={runExportUrl(runId)} variant="light">
            Download results (Excel)
          </Button>
          <Button variant="subtle" onClick={onClose}>
            Open another run
          </Button>
        </Group>
      </Group>
      <Text size="sm" c="dimmed">
        Run {runId} · {run.data.asset_count} assets · {run.data.start_year}–
        {run.data.end_year} · Real 2026 USD
      </Text>

      <Tabs defaultValue="overview" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="overview">Overview</Tabs.Tab>
          <Tabs.Tab value="time-series">Time series</Tabs.Tab>
          <Tabs.Tab value="cost-allocations">Cost allocations</Tabs.Tab>
          <Tabs.Tab value="run">Run information</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="overview" pt="md">
          <OverviewTab summary={summary.data} assetId={assetId} />
        </Tabs.Panel>
        <Tabs.Panel value="time-series" pt="md">
          <TimeSeriesTab runId={runId} assetId={assetId} />
        </Tabs.Panel>
        <Tabs.Panel value="cost-allocations" pt="md">
          <CostAllocationsTab
            runId={runId}
            assetId={assetId}
            startYear={run.data.start_year}
            endYear={run.data.end_year}
          />
        </Tabs.Panel>
        <Tabs.Panel value="run" pt="md">
          <RunInfoTab run={run.data} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
