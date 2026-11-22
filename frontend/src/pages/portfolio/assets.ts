// Reading the asset rows the backend sends for a workbook. Each row has the
// workbook's own columns plus a few the backend adds, like official_material.
import type { Schemas } from '../../api/client'

export type Asset = Schemas['Portfolio']['assets'][number]

// Columns shown in the asset table, in this order, when the workbook has them.
// Same as the Streamlit "Processed Asset Registry" table.
export const ASSET_COLUMNS: {
  key: string
  label: string
  numeric?: boolean
}[] = [
  { key: 'asset_id', label: 'Asset ID' },
  { key: 'official_material', label: 'Material' },
  { key: 'current_roof_type', label: 'Source roof type' },
  { key: 'subtype', label: 'Subtype' },
  { key: 'roof_age', label: 'Roof age', numeric: true },
  { key: 'install_year', label: 'Installed', numeric: true },
  { key: 'roof_area_sqft', label: 'Roof area (sq ft)', numeric: true },
  { key: 'Terrain', label: 'Terrain' },
  { key: 'latitude', label: 'Latitude', numeric: true },
  { key: 'longitude', label: 'Longitude', numeric: true },
  { key: 'insured_value', label: 'Insured value', numeric: true },
  { key: 'policy_id', label: 'Policy' },
  { key: 'peril', label: 'Peril' },
]

export const MATERIALS = ['Asphalt', 'Metal', 'Tile']

export function assetIdOf(asset: Asset) {
  return String(asset.asset_id)
}

export function numberOf(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  return value === null ||
    value === undefined ||
    value === '' ||
    Number.isNaN(number)
    ? null
    : number
}

// One cell of the asset table. Years and coordinates keep all their digits,
// and other numbers get thousands separators.
export function formatCell(key: string, value: unknown) {
  if (value === null || value === undefined || value === '') return ''
  if (key === 'install_year' || key === 'latitude' || key === 'longitude') {
    return String(value)
  }
  if (key === 'insured_value') {
    const number = numberOf(value)
    return number === null
      ? String(value)
      : `$${number.toLocaleString('en-US')}`
  }
  return typeof value === 'number'
    ? value.toLocaleString('en-US')
    : String(value)
}

// The numbers on the summary cards, for the selected assets.
export function summarize(assets: Asset[]) {
  const ages = assets.map((asset) => numberOf(asset.roof_age))
  const areas = assets.map((asset) => numberOf(asset.roof_area_sqft))
  const insured = assets.map((asset) => numberOf(asset.insured_value))
  const sum = (values: (number | null)[]) =>
    values.reduce<number>((total, value) => total + (value ?? 0), 0)
  const known = (values: (number | null)[]) =>
    values.filter((value) => value !== null).length

  return {
    count: assets.length,
    averageAge: known(ages) ? sum(ages) / known(ages) : null,
    totalArea: known(areas) ? sum(areas) : null,
    averageArea: known(areas) ? sum(areas) / known(areas) : null,
    // Left out when any asset is missing it, so the total isn't too low.
    insuredTotal:
      assets.length > 0 && known(insured) === assets.length
        ? sum(insured)
        : null,
    materials: Object.fromEntries(
      MATERIALS.map((material) => [
        material,
        assets.filter((asset) => asset.official_material === material).length,
      ]),
    ),
  }
}
