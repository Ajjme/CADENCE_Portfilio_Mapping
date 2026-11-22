// Run settings, for the settings form on the Portfolio page.
import { request, type Schemas } from './client'

// Default settings, the values each one can take, and the yearly metrics.
export function getSettings() {
  return request<Schemas['SettingsChoices']>('/api/settings')
}
