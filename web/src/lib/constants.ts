import type { Flag, MissingInfo, SourceTier } from "./contracts";

// Must equal VALUE_CONTRACT in src/ainma/contracts.py (a test reads that file and compares).
export const VALUE_CONTRACT =
  "I summarise the evidence clearly and show you the sources, so that you can examine them and make informed decisions.";

export const TIER_LEGEND: Record<SourceTier, { name: string; kinds: string }> = {
  1: { name: "Tier 1", kinds: "Signed agreement, regulatory filing" },
  2: { name: "Tier 2", kinds: "Deal document, company report" },
  3: { name: "Tier 3", kinds: "Internal reference, press release" },
  4: { name: "Tier 4", kinds: "Press article" },
  5: { name: "Tier 5", kinds: "Free web page" },
};

export const DOC_TYPE_LABEL: Record<string, string> = {
  signed_agreement: "Signed agreement",
  regulatory_filing: "Regulatory filing",
  deal_document: "Deal document",
  company_report: "Company report",
  internal_reference: "Internal reference",
  press_release: "Press release",
  press_article: "Press article",
  web: "Web page",
};

export const MISSING_REASON: Record<MissingInfo["reason"], string> = {
  not_found: "Not found in the sources",
  stale_only: "Only old sources were found",
  withdrawn_only: "Only withdrawn sources were found",
};

export const STATUS_LABEL = {
  inferred: "System deduction",
  missing: "Not established by the sources",
} as const;

export const KPI_LABEL: Record<string, string> = {
  revenue: "Revenue",
  revenue_growth: "Revenue growth",
  gross_margin: "Gross margin",
  largest_customer_share: "Largest customer share",
  ebitda: "EBITDA",
};

const FLAG_TEXT: Record<Flag, string> = {
  stale: "Old information",
  superseded: "Superseded",
  withdrawn: "Withdrawn",
  single_low_tier_source: "Single low-tier source",
  contradicted: "Sources disagree",
  unverified: "Not verified",
};

// `date` is the most recent publication date among the claim sources, shown for stale claims.
export function flagText(flag: Flag, date: string | null): string {
  if (flag === "stale" && date) return `${FLAG_TEXT.stale}, ${date.slice(0, 7)}`;
  return FLAG_TEXT[flag];
}

export function kpiLabel(id: string): string {
  const known = KPI_LABEL[id];
  if (known) return known;
  const spaced = id.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
