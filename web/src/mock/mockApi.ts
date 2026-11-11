import type { Api, MarketRun, RefineOutcome, Served } from "../lib/api";
import { ApiError } from "../lib/api";
import type {
  Answer,
  BuyerCard,
  Citation,
  Deal,
  DocumentMeta,
  KpiValue,
  MarketEvent,
  Passage,
  ScreeningRequest,
  ScreeningResult,
  User,
} from "../lib/contracts";
import abstention from "./answer_abstention.json";
import contradiction from "./answer_contradiction.json";
import kpis from "./kpis.json";
import screening from "./screening_result.json";

// Everything here is built from the example payloads. Nothing is computed by a model.

const MOCK = "mock";

const USERS: User[] = [
  { id: "u_lead", name: "Lena Lead" },
  { id: "u_analyst", name: "Alex Analyst" },
  { id: "u_outsider", name: "Omar Outsider" },
];

const DEAL: Deal = {
  id: "deal_aurora",
  name: "Project Aurora",
  sector: "industrial components",
  description: "Fictional industrial components company (synthetic).",
  status: "marketing",
  synthetic: true,
};

const MEMBERS = new Set(["u_lead", "u_analyst"]);

// Market events of the simulated feed (mock): one acquisition reported twice, a denied rumour,
// a corrected price. Shown once the simulated connector has run, as in the API.
function newsCitation(chunk: string, title: string, date: string, quote: string): Citation {
  return {
    chunk_id: chunk,
    document_id: chunk.replace(/^ch_/, "doc_").replace(/_p\d+_\d+$/, ""),
    doc_title: title,
    doc_type: "press_article",
    tier: 4,
    published_on: date,
    page: 1,
    char_start: 0,
    char_end: quote.length,
    quote,
  };
}

const EVENTS: MarketEvent[] = [
  {
    id: "ev_mock_1",
    kind: "acquisition",
    actor: "Orvane Capital",
    buyer_id: "buyer_01",
    counterparty: "Tessil Works",
    event_date: "2025-01-02",
    status: "confirmed",
    value_eur_m: null,
    citations: [
      newsCitation("ch_news_m1_p1_01", "Orvane Capital completes acquisition of Tessil Works", "2025-01-02", "Orvane Capital completes acquisition of Tessil Works"),
      newsCitation("ch_news_m2_p1_01", "Trade wire: Orvane Capital buys Tessil Works", "2025-01-04", "Trade wire: Orvane Capital buys Tessil Works"),
    ],
    superseded_citations: [],
    n_reports: 2,
  },
  {
    id: "ev_mock_2",
    kind: "price",
    actor: "Orvane Capital",
    buyer_id: "buyer_01",
    counterparty: "Tessil Works",
    event_date: "2025-01-08",
    status: "corrected",
    value_eur_m: 102,
    citations: [
      newsCitation("ch_news_m4_p1_01", "Correction: price for Orvane Capital and Tessil Works", "2025-01-12", "Correction: price for Orvane Capital and Tessil Works was EUR 102 million"),
    ],
    superseded_citations: [
      newsCitation("ch_news_m3_p1_01", "Price for Orvane Capital and Tessil Works put at EUR 120 million", "2025-01-08", "Price for Orvane Capital and Tessil Works put at EUR 120 million"),
    ],
    n_reports: 2,
  },
  {
    id: "ev_mock_3",
    kind: "rumour",
    actor: "Brennan Industries",
    buyer_id: "buyer_02",
    counterparty: "Aurora Components",
    event_date: "2025-02-14",
    status: "denied",
    value_eur_m: null,
    citations: [
      newsCitation("ch_news_m5_p1_01", "Brennan Industries is said to weigh an offer for Aurora Components", "2025-02-14", "Brennan Industries is said to weigh an offer for Aurora Components"),
      newsCitation("ch_news_m6_p1_01", "Brennan Industries denies interest in Aurora Components", "2025-02-20", "Brennan Industries denies interest in Aurora Components"),
    ],
    superseded_citations: [],
    n_reports: 2,
  },
];

function documentMeta(
  id: string,
  title: string,
  docType: DocumentMeta["doc_type"],
  tier: DocumentMeta["tier"],
  publishedOn: string,
  pages: number,
  status: DocumentMeta["status"] = "current",
  origin = "generator",
): DocumentMeta {
  return {
    id,
    deal_id: id === "doc_playbook" ? null : DEAL.id,
    entity_id: null,
    title,
    doc_type: docType,
    published_on: publishedOn,
    status,
    superseded_by: null,
    n_pages: pages,
    sha256: "0".repeat(64),
    synthetic: true,
    origin,
    tier,
  };
}

const BASE_DOCUMENTS: DocumentMeta[] = [
  documentMeta("doc_cim", "Project Aurora, Confidential Information Memorandum", "deal_document", 2, "2025-03-14", 24),
  documentMeta("doc_news_17", "Trade press: Aurora Components posts record year", "press_article", 4, "2025-02-02", 1),
  documentMeta("doc_pr_orig", "Aurora press release (original, withdrawn)", "press_release", 3, "2025-02-10", 1, "withdrawn"),
  documentMeta("doc_spa_draft", "Share purchase agreement (draft, superseded)", "deal_document", 2, "2025-04-02", 41, "superseded"),
  documentMeta("doc_playbook", "Sell-side process playbook", "internal_reference", 3, "2024-09-01", 6),
];

const SIMULATED_DOCUMENTS: DocumentMeta[] = [
  documentMeta("doc_sim_1", "Simulated news: Aurora sector sees consolidation", "press_article", 4, "2025-05-06", 1, "current", "simulated-connector"),
  documentMeta("doc_sim_2", "Simulated news: Component makers report weaker orders", "press_article", 4, "2025-05-19", 1, "current", "simulated-connector"),
  documentMeta("doc_sim_3", "Simulated press release: Nordvik opens a DACH office", "press_release", 3, "2025-06-02", 1, "current", "simulated-connector"),
];

function filler(length: number): string {
  const unit = "Synthetic filler text for the mock page. ";
  return unit.repeat(Math.ceil(length / unit.length)).slice(0, length);
}

function mockPassage(citation: Citation, document: DocumentMeta | undefined): Passage {
  const start = citation.char_start;
  const end = start + citation.quote.length;
  const pageText = `${filler(start)}${citation.quote}${filler(240)}`;
  return {
    chunk: {
      id: citation.chunk_id,
      document_id: citation.document_id,
      deal_id: DEAL.id,
      entity_id: null,
      page: citation.page,
      char_start: start,
      char_end: end,
      text: citation.quote,
      kind: "text",
      doc_type: citation.doc_type,
      published_on: citation.published_on,
    },
    document:
      document ??
      documentMeta(
        citation.document_id,
        citation.doc_title,
        citation.doc_type,
        citation.tier,
        citation.published_on ?? "2025-01-01",
        Math.max(citation.page, 1),
      ),
    page_text: pageText,
    highlight_start: start,
    highlight_end: end,
  };
}

function allCitations(): Citation[] {
  const out: Citation[] = [];
  const visit = (cites: Citation[]) => out.push(...cites);
  for (const answer of [contradiction, abstention] as unknown as Answer[]) {
    for (const claim of answer.claims) visit(claim.citations);
  }
  for (const card of (screening as unknown as ScreeningResult).cards) {
    for (const r of card.results) visit(r.citations);
  }
  for (const k of kpis as unknown as KpiValue[]) visit(k.citations);
  for (const e of EVENTS) visit([...e.citations, ...e.superseded_citations]);
  return out;
}

function matchesFilters(card: BuyerCard, request: ScreeningRequest): boolean {
  const f = request.filters;
  const b = card.buyer;
  const any = (wanted: string[], have: string[]) =>
    wanted.length === 0 ||
    wanted.some((w) => have.some((h) => h.toLowerCase().includes(w.toLowerCase())));
  return (
    (f.buyer_types.length === 0 || f.buyer_types.includes(b.buyer_type)) &&
    any(f.sectors, b.sectors) &&
    any(f.geographies, b.geographies) &&
    (f.min_size_eur_m === null || b.size_eur_m >= f.min_size_eur_m) &&
    (f.max_size_eur_m === null || b.size_eur_m <= f.max_size_eur_m)
  );
}

// One instance per page load keeps the "market intel was run" state across user switches.
export class MockBackend {
  private marketRun = false;

  forUser(userId: string): Api {
    const member = MEMBERS.has(userId);
    const served = <T>(value: T): Served<T> => ({ value, backend: MOCK });
    const requireDeal = (dealId: string) => {
      if (!member || dealId !== DEAL.id) throw new ApiError(404, "404 Not Found");
    };
    const documents = (): DocumentMeta[] =>
      this.marketRun ? [...BASE_DOCUMENTS, ...SIMULATED_DOCUMENTS] : BASE_DOCUMENTS;

    return {
      mode: "mock",
      users: async () => USERS,
      deals: async () => (member ? [DEAL] : []),
      documents: async (dealId) => {
        requireDeal(dealId);
        return documents();
      },
      ask: async (dealId, question) => {
        requireDeal(dealId);
        const source = /revenue/i.test(question) ? contradiction : abstention;
        const base = source as unknown as Answer;
        const answer: Answer = {
          ...base,
          question,
          user_id: userId,
          deal_id: dealId,
          // the API computes it (D97); the example payloads predate the field
          confidence: base.abstained ? null : "medium",
          confidence_reason: base.abstained ? null : "Medium: sources disagree.",
        };
        return served(answer);
      },
      passage: async (chunkId) => {
        if (!member) throw new ApiError(404, "404 Not Found");
        const citation = allCitations().find((c) => c.chunk_id === chunkId);
        if (!citation) throw new ApiError(404, "404 Not Found");
        return mockPassage(
          citation,
          documents().find((d) => d.id === citation.document_id),
        );
      },
      screening: async (request) => {
        requireDeal(request.deal_id);
        const base = screening as unknown as ScreeningResult;
        const cards = base.cards.filter((card) => matchesFilters(card, request));
        return served({ ...base, request, cards });
      },
      kpis: async (dealId) => {
        requireDeal(dealId);
        return served(kpis as unknown as KpiValue[]);
      },
      runMarketIntel: async (dealId) => {
        requireDeal(dealId);
        this.marketRun = true;
        const run: MarketRun = { deal_id: dealId, ingested: SIMULATED_DOCUMENTS.length };
        return served(run);
      },
      liveSearch: async () => {
        throw new ApiError(503, "Live search is off in mock mode: run the API with TAVILY_API_KEY.");
      },
      refine: async (text, current) => {
        requireDeal(current.deal_id);
        return mockRefine(text, current);
      },
      events: async (dealId) => {
        requireDeal(dealId);
        return this.marketRun ? EVENTS : [];
      },
    };
  }
}

// A few wordings, as the mock provider of the API reads them (D98).
function mockRefine(text: string, current: ScreeningRequest): RefineOutcome {
  const filters = { ...current.filters };
  const understood: string[] = [];
  if (/\b(financial|sponsors?|private equity|funds?)\b/i.test(text)) {
    filters.buyer_types = ["financial"];
    understood.push("type: financial");
  } else if (/\b(strategic|corporates?|industrials?)\b/i.test(text)) {
    filters.buyer_types = ["strategic"];
    understood.push("type: strategic");
  }
  for (const region of ["DACH", "France", "Nordics", "Benelux", "Central Europe"]) {
    if (new RegExp(`\\b${region}\\b`, "i").test(text)) {
      filters.geographies = [...new Set([...filters.geographies, region])];
      understood.push(`region: ${region}`);
    }
  }
  const above = /\b(?:above|over|more than|at least)\s+(?:eur|€)?\s*([\d.,]+)\s*(bn|billion|m|million)?/i.exec(text);
  if (above?.[1]) {
    const scale = above[2] && /^b/i.test(above[2]) ? 1000 : 1;
    filters.min_size_eur_m = Number(above[1].replace(",", "")) * scale;
    understood.push(`size from EUR ${filters.min_size_eur_m}m`);
  }
  const weights = { ...current.weights };
  if (/recent (acquisitions|acquirers|deals)|acquisitive/i.test(text)) {
    weights.recent_activity = 4;
    understood.push("prefer recent acquirers");
  }
  return { request: { ...current, filters, weights }, understood };
}
