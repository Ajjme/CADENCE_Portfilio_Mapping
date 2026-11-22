// Running an analysis and reading its results, for the Results page.
// Leave out assetId to get the whole portfolio.
import { apiUrl, postJson, request, type Schemas } from './client'

function runPath(runId: string, rest = '') {
  return `/api/runs/${encodeURIComponent(runId)}${rest}`
}

// Runs the Alternative Analysis. Resolves when the run finishes, which can
// take a few minutes.
export function runAnalysis(run: Schemas['RunRequest']) {
  return postJson<Schemas['RunInfo']>('/api/runs', run)
}

// The run's settings and asset count.
export function getRun(runId: string) {
  return request<Schemas['RunInfo']>(runPath(runId))
}

// Final NPV and the other results by asset and replacement option, plus
// portfolio totals.
export function getRunSummary(runId: string) {
  return request<Schemas['RunSummary']>(runPath(runId, '/summary'))
}

// One yearly result for each replacement option, for the time series chart.
// metric is a key from getSettings().metrics - net present value if left out.
export function getRunSeries(
  runId: string,
  options: { metric?: string; assetId?: string } = {},
) {
  return request<Schemas['Series']>(runPath(runId, '/series'), {
    query: { metric: options.metric, asset_id: options.assetId },
  })
}

// One year's costs for each replacement option, for the cost allocation chart.
export function getCostAllocations(
  runId: string,
  year: number,
  assetId?: string,
) {
  return request<Schemas['CostAllocations']>(
    runPath(runId, '/cost-allocations'),
    { query: { year, asset_id: assetId } },
  )
}

// A link that downloads the whole run as one Excel file.
export function runExportUrl(runId: string) {
  return apiUrl(runPath(runId, '/export'))
}
