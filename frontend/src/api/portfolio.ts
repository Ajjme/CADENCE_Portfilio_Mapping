// Asset workbooks, for the Portfolio page.
import { apiUrl, request, type Schemas } from './client'

// A link that downloads the example workbook, to use as a template.
export const EXAMPLE_WORKBOOK_URL = apiUrl('/api/portfolio/example')

// The example workbook's assets, shown before anyone uploads their own.
export function getDefaultPortfolio() {
  return request<Schemas['Portfolio']>('/api/portfolio/default')
}

// Uploads and checks a workbook. Pass the returned workbook_id to runAnalysis.
export function uploadPortfolio(file: File) {
  const body = new FormData()
  body.append('file', file)
  return request<Schemas['Portfolio']>('/api/portfolio', {
    method: 'POST',
    body,
  })
}
