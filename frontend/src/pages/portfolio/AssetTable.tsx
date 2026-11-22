// The workbook's assets, with a checkbox on each to leave it out of the run.
// Every asset starts checked.
import { Checkbox, Table } from '@mantine/core'
import { ASSET_COLUMNS, assetIdOf, formatCell, type Asset } from './assets'

type AssetTableProps = {
  assets: Asset[]
  // IDs of the assets left out of the run.
  excluded: Set<string>
  onExcludedChange: (excluded: Set<string>) => void
}

export default function AssetTable({
  assets,
  excluded,
  onExcludedChange,
}: AssetTableProps) {
  const columns = ASSET_COLUMNS.filter((column) =>
    assets.some((asset) => column.key in asset),
  )
  const sorted = [...assets].sort((a, b) =>
    assetIdOf(a).localeCompare(assetIdOf(b)),
  )
  const noneExcluded = excluded.size === 0
  const allExcluded = excluded.size === assets.length

  function toggle(assetId: string) {
    const next = new Set(excluded)
    if (next.has(assetId)) {
      next.delete(assetId)
    } else {
      next.add(assetId)
    }
    onExcludedChange(next)
  }

  return (
    <Table.ScrollContainer minWidth={900}>
      <Table striped highlightOnHover>
        <Table.Thead>
          <Table.Tr>
            <Table.Th w={40}>
              <Checkbox
                aria-label="Include all assets"
                checked={noneExcluded}
                indeterminate={!noneExcluded && !allExcluded}
                onChange={() =>
                  onExcludedChange(
                    noneExcluded ? new Set(assets.map(assetIdOf)) : new Set(),
                  )
                }
              />
            </Table.Th>
            {columns.map((column) => (
              <Table.Th
                key={column.key}
                ta={column.numeric ? 'right' : undefined}
              >
                {column.label}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sorted.map((asset) => {
            const id = assetIdOf(asset)
            return (
              <Table.Tr key={id}>
                <Table.Td>
                  <Checkbox
                    aria-label={`Include ${id}`}
                    checked={!excluded.has(id)}
                    onChange={() => toggle(id)}
                  />
                </Table.Td>
                {columns.map((column) => (
                  <Table.Td
                    key={column.key}
                    ta={column.numeric ? 'right' : undefined}
                  >
                    {formatCell(column.key, asset[column.key])}
                  </Table.Td>
                ))}
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </Table.ScrollContainer>
  )
}
