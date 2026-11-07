// Asset Portfolio - where every run starts, like the Streamlit page of the same name.
// Will hold: loading the asset workbook, the asset table, and the Run button.
import { Alert } from '@mantine/core'
import PageHeader from '../components/PageHeader'

export default function PortfolioPage() {
  return (
    <>
      <PageHeader
        title="Asset Portfolio"
        description="Load an asset workbook and run the alternative analysis."
      />
      <Alert title="Coming next">
        Loading workbooks and running the analysis need the FastAPI backend.
      </Alert>
    </>
  )
}
