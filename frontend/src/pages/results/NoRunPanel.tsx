// Shown before a run is open. Runs will start from the Asset Portfolio page -
// until that page is rebuilt, this can run the example portfolio or reopen a
// run by its ID.
import { Alert, Button, Group, Stack, Text, TextInput } from '@mantine/core'
import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { runAnalysis } from '../../api/runs'

export default function NoRunPanel({
  onRunReady,
}: {
  onRunReady: (runId: string) => void
}) {
  const [typedId, setTypedId] = useState('')
  const exampleRun = useMutation({
    mutationFn: () => runAnalysis({}),
    onSuccess: (run) => onRunReady(run.run_id),
  })

  return (
    <Stack maw={560}>
      <Alert title="No run open">
        Run the example portfolio, or open a run you already have by its ID.
      </Alert>

      <Group>
        <Button
          onClick={() => exampleRun.mutate()}
          loading={exampleRun.isPending}
        >
          Run the example portfolio
        </Button>
        {exampleRun.isPending && (
          <Text size="sm" c="dimmed">
            This takes a minute or two.
          </Text>
        )}
      </Group>
      {exampleRun.isError && (
        <Alert color="red" title="The run failed">
          {exampleRun.error.message}
        </Alert>
      )}

      <Group align="end">
        <TextInput
          label="Run ID"
          placeholder="272180105c1d73ad025422a7"
          value={typedId}
          onChange={(event) => setTypedId(event.currentTarget.value)}
          w={300}
        />
        <Button
          variant="light"
          disabled={!typedId.trim()}
          onClick={() => onRunReady(typedId.trim())}
        >
          Open
        </Button>
      </Group>
    </Stack>
  )
}
