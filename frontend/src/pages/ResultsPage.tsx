// Alternative Analysis Results - like the Streamlit results page.
// Will hold: the summary cards, NPV by alternative, the map, and the charts.
import { Alert } from '@mantine/core'
import PageHeader from '../components/PageHeader'

export default function ResultsPage() {
  return (
    <>
      <PageHeader
        title="Alternative Analysis Results"
        description="Compare the replacement options for each asset."
      />
      <Alert title="Coming next">
        Results need the FastAPI backend and a finished run.
      </Alert>
    </>
  )
}
