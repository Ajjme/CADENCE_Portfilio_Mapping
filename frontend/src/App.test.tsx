import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import App from './App'
import { renderWithProviders } from './test/renderWithProviders'

function renderApp() {
  renderWithProviders(<App />)
}

describe('App', () => {
  it('opens on the Asset Portfolio page', () => {
    renderApp()
    expect(
      screen.getByRole('heading', { name: 'Asset Portfolio' }),
    ).toBeInTheDocument()
  })

  it('switches pages from the sidebar', async () => {
    renderApp()
    await userEvent.click(
      screen.getByRole('button', { name: 'Alternative Analysis Results' }),
    )
    expect(
      screen.getByRole('heading', { name: 'Alternative Analysis Results' }),
    ).toBeInTheDocument()
  })
})
