// The app shell: a header, a sidebar for switching pages, and the current page.
// Works like Streamlit's page sidebar - picking a page shows that page's file.
import { AppShell, Burger, Group, NavLink, Title } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useState } from 'react'
import PortfolioPage from './pages/PortfolioPage'
import ResultsPage from './pages/ResultsPage'

type PageId = 'portfolio' | 'results'

const PAGES: { id: PageId; label: string }[] = [
  { id: 'portfolio', label: 'Asset Portfolio' },
  { id: 'results', label: 'Alternative Analysis Results' },
]

function App() {
  // Which page is showing. Changing it re-renders the app with the new page.
  const [page, setPage] = useState<PageId>('portfolio')
  // On small screens the sidebar folds into a menu button.
  const [sidebarOpen, { toggle: toggleSidebar }] = useDisclosure()

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 260,
        breakpoint: 'sm',
        collapsed: { mobile: !sidebarOpen },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md">
          <Burger
            opened={sidebarOpen}
            onClick={toggleSidebar}
            hiddenFrom="sm"
            size="sm"
            aria-label="Toggle navigation"
          />
          <Title order={3}>CADENCE</Title>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {PAGES.map((item) => (
          <NavLink
            key={item.id}
            component="button"
            label={item.label}
            active={page === item.id}
            onClick={() => setPage(item.id)}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        {page === 'portfolio' && <PortfolioPage />}
        {page === 'results' && <ResultsPage />}
      </AppShell.Main>
    </AppShell>
  )
}

export default App
