export function parseDatasetIds(value: string): number[] {
  return [
    ...new Set(
      value
        .split(/[\s,]+/)
        .map(Number)
        .filter((id) => Number.isSafeInteger(id) && id > 0),
    ),
  ]
}
