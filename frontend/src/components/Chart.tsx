// The chart pages use. Plotly is large, so it's downloaded the first time a
// chart shows instead of when the app opens, with a spinner in the meantime.
import { Center, Loader } from '@mantine/core'
import { lazy, Suspense } from 'react'
import type { PlotlyChartProps } from './PlotlyChart'

const PlotlyChart = lazy(() => import('./PlotlyChart'))

export default function Chart(props: PlotlyChartProps) {
  return (
    <Suspense
      fallback={
        <Center h={props.height ?? 420}>
          <Loader />
        </Center>
      }
    >
      <PlotlyChart {...props} />
    </Suspense>
  )
}
