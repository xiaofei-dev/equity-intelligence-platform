import type { DecimalValue } from "./market-intelligence/contracts";

const scoreFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const numberFormatter = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 2,
});

const timestampFormatter = new Intl.DateTimeFormat("en-US", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "America/New_York",
});

export function formatScore(value: DecimalValue | null): string {
  return value === null ? "Not assessed" : scoreFormatter.format(Number(value));
}

export function formatCurrency(
  value: DecimalValue | null,
  currency: string,
): string {
  if (value === null) return "Missing";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(Number(value));
  } catch {
    return `${numberFormatter.format(Number(value))} ${currency}`;
  }
}

export function formatTimestamp(value: string | null): string {
  return value === null ? "Not available" : `${timestampFormatter.format(new Date(value))} ET`;
}

export function humanize(value: string): string {
  return value
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
