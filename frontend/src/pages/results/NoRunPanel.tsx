// Shown before a run is open. Runs start from the Asset Portfolio page, and
// a run from earlier can be reopened here by its ID.
import { Alert, Button, Group, Stack, TextInput } from '@mantine/core'
import { useState } from 'react'

export default function NoRunPanel({
  onRunReady,
}: {
  onRunReady: (runId: string) => void
}) {
  const [typedId, setTypedId] = useState('')

  return (
    <Stack maw={560}>
      <Alert title="No run open">
        Run a portfolio on the Asset Portfolio page, or open a run you already
        have by its ID.
      </Alert>
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
