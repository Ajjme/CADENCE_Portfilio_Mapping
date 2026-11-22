// A Plotly chart, like st.plotly_chart. Pages use Chart.tsx instead, which
// loads this file (and Plotly) only when a chart first shows.
import Plotly from 'plotly.js-basic-dist-min'
import { useEffect, useRef } from 'react'

export type PlotlyChartProps = {
  data: Plotly.Data[]
  layout?: Partial<Plotly.Layout>
  height?: number
}

export default function PlotlyChart({
  data,
  layout,
  height = 420,
}: PlotlyChartProps) {
  const container = useRef<HTMLDivElement>(null)

  // Redraw whenever the data or layout changes.
  useEffect(() => {
    if (!container.current) return
    Plotly.react(
      container.current,
      data,
      {
        autosize: true,
        height,
        margin: { l: 70, r: 20, t: 40, b: 50 },
        ...layout,
      },
      { displaylogo: false, responsive: true },
    )
  }, [data, layout, height])

  // Free Plotly's memory when the chart leaves the page.
  useEffect(() => {
    const element = container.current
    return () => {
      if (element) Plotly.purge(element)
    }
  }, [])

  return <div ref={container} style={{ width: '100%' }} />
}
