export function percent(value: number | null, digits = 0): string {
  return value === null ? "n/a" : `${(value * 100).toFixed(digits)}%`;
}

export function dateOrUnknown(date: string | null): string {
  return date ?? "date unknown";
}

export function latestDate(dates: readonly (string | null)[]): string | null {
  const known = dates.filter((d): d is string => d !== null).sort();
  return known.length > 0 ? (known[known.length - 1] ?? null) : null;
}

export function formatNumber(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(2);
}
