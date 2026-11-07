// App-wide colors and fonts, like theme.py in the Streamlit app.
// Every Mantine component reads from here, so a change here shows up everywhere.
import { createTheme } from '@mantine/core'

export const theme = createTheme({
  // Placeholder until the CIRCAD palette is pulled (see the Backlog).
  primaryColor: 'indigo',
  fontFamily: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
})
