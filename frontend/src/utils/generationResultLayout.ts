export const resultGridCapacity = 9

export type ResultGridLayout = {
  count: number
  className: `result-count-${number}`
  rows: number
}

/**
 * Keep every result slot tied to its server-assigned index. The CSS class only
 * controls visual placement of that immutable sequence; it never filters or
 * reorders candidates based on their completion state.
 */
export function resultGridLayout(resultCount: number): ResultGridLayout {
  const count = Number.isFinite(resultCount)
    ? Math.min(resultGridCapacity, Math.max(1, Math.trunc(resultCount)))
    : 1
  return {
    count,
    className: `result-count-${count}`,
    rows: resultGridRows(count),
  }
}

export function resultGridRows(resultCount: number, columnCount = 3): number {
  return Math.max(1, Math.ceil(Math.max(0, resultCount) / columnCount))
}

export function resultGridCapacityRows(columnCount = 3): number {
  return resultGridRows(resultGridCapacity, columnCount)
}
