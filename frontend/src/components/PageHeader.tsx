// The title and one-line description at the top of every page.
import { Stack, Text, Title } from '@mantine/core'

type PageHeaderProps = {
  title: string
  description: string
}

export default function PageHeader({ title, description }: PageHeaderProps) {
  return (
    <Stack gap={4} mb="lg">
      <Title order={2}>{title}</Title>
      <Text c="dimmed">{description}</Text>
    </Stack>
  )
}
