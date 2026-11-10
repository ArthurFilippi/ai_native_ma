// TypeScript mirror of src/ainma/contracts.py (the Python file is the single source of truth).
// Only the objects the client reads are mirrored.

export type DocType =
  | "signed_agreement"
  | "regulatory_filing"
  | "deal_document"
  | "company_report"
  | "internal_reference"
  | "press_release"
  | "press_article"
  | "web";

export type SourceTier = 1 | 2 | 3 | 4 | 5;
export type DocStatus = "current" | "superseded" | "withdrawn";

export interface User {
  id: string;
  name: string;
}

export interface Deal {
  id: string;
  name: string;
  sector: string;
  description: string;
  status: "preparation" | "marketing" | "bids" | "closed";
  synthetic: boolean;
  // optional deal facts that prefill the stage 1 screening filters (D87)
  geographies?: string[];
  ev_eur_m?: number | null;
  buyer_types?: BuyerType[];
}

export interface DocumentMeta {
  id: string;
  deal_id: string | null;
  entity_id: string | null;
  title: string;
  doc_type: DocType;
  published_on: string | null;
  status: DocStatus;
  superseded_by: string | null;
  n_pages: number;
  sha256: string;
  synthetic: boolean;
  origin: string;
  tier: SourceTier;
}

export interface Chunk {
  id: string;
  document_id: string;
  deal_id: string | null;
  entity_id: string | null;
  page: number;
  char_start: number;
  char_end: number;
  text: string;
  kind: "text" | "table";
  doc_type: DocType;
  published_on: string | null;
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  doc_title: string;
  doc_type: DocType;
  tier: SourceTier;
  published_on: string | null;
  page: number;
  char_start: number;
  char_end: number;
  quote: string;
}

export type ClaimStatus = "sourced" | "inferred" | "missing";
export type Flag =
  | "stale"
  | "superseded"
  | "withdrawn"
  | "single_low_tier_source"
  | "contradicted"
  | "unverified";

export interface VerificationCheck {
  name: "verbatim_span" | "numeric_match" | "judge";
  passed: boolean;
  detail: string;
}

export interface Verification {
  supported: boolean;
  checks: VerificationCheck[];
  judge_label: "supported" | "partial" | "unsupported" | null;
}

export interface Claim {
  id: string;
  text: string;
  status: ClaimStatus;
  citations: Citation[];
  derived_from: string[];
  verification: Verification | null;
  flags: Flag[];
}

export interface ContradictionSide {
  label: string;
  claim_id: string;
  citations: Citation[];
  strength: number;
}

export interface Contradiction {
  id: string;
  subject: string;
  sides: ContradictionSide[];
  stronger_side: number | null;
  note: string;
}

export interface MissingInfo {
  topic: string;
  reason: "not_found" | "stale_only" | "withdrawn_only";
}

export interface RankedPassage {
  chunk_id: string;
  rank: number;
  final_score: number;
  components: Record<string, number>;
  explanation: string;
}

export interface Trace {
  provider: string;
  model: string;
  stage_latency_ms: Record<string, number>;
  retrieved: RankedPassage[];
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
}

export interface Answer {
  id: string;
  deal_id: string | null;
  user_id: string;
  question: string;
  sub_questions: string[];
  summary: string;
  claims: Claim[];
  contradictions: Contradiction[];
  missing: MissingInfo[];
  abstained: boolean;
  abstention_reason: string | null;
  trace: Trace;
  value_contract: string;
}

export type BuyerType = "strategic" | "financial";

export interface BuyerProfile {
  id: string;
  name: string;
  buyer_type: BuyerType;
  sectors: string[];
  geographies: string[];
  size_eur_m: number;
  ticket_min_eur_m: number | null;
  ticket_max_eur_m: number | null;
  fund_vintage_year: number | null;
  listed: boolean;
  synthetic: boolean;
}

export interface Criterion {
  key: string;
  label: string;
  kind: "prefilter" | "deep";
  weight: number;
  dealbreaker: boolean;
  description: string;
}

export type CriterionStatus = "met" | "not_met" | "unknown";

export interface CriterionResult {
  criterion_key: string;
  status: CriterionStatus;
  rationale: string;
  citations: Citation[];
  conflicting_evidence: boolean;
}

export interface BuyerCard {
  buyer: BuyerProfile;
  stage1_passed: boolean;
  results: CriterionResult[];
  score: number | null;
  coverage: number;
  // range the score can still take once the unknown criteria are known (D86)
  score_low?: number | null;
  score_high?: number | null;
  contributions: Record<string, number>;
  dealbreakers: string[];
  rank: number | null;
}

export interface ScreeningFilters {
  buyer_types: BuyerType[];
  sectors: string[];
  geographies: string[];
  min_size_eur_m: number | null;
  max_size_eur_m: number | null;
}

export interface ScreeningRequest {
  deal_id: string;
  filters: ScreeningFilters;
  weights: Record<string, number>;
  stage2_top_n: number;
}

export interface ScreeningResult {
  deal_id: string;
  request: ScreeningRequest;
  criteria: Criterion[];
  cards: BuyerCard[];
}

export interface KpiValue {
  kpi_id: string;
  period: string;
  value: number | null;
  unit: string;
  status: "sourced" | "computed" | "missing";
  citations: Citation[];
  formula_inputs: Record<string, number>;
}

// Response of GET /passages/{chunk_id}?page=true
export interface Passage {
  chunk: Chunk;
  document: DocumentMeta;
  page_text: string | null;
  highlight_start: number;
  highlight_end: number;
}
