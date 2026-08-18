export const resultGridCapacity = 9

export function resultGridRows(resultCount: number, columnCount = 3): number {
  return Math.max(1, Math.ceil(Math.max(0, resultCount) / columnCount))
}

export function resultGridCapacityRows(columnCount = 3): number {
  return resultGridRows(resultGridCapacity, columnCount)
}
