import type {
  Answer,
  Deal,
  DocumentMeta,
  KpiValue,
  MarketEvent,
  Passage,
  ScreeningRequest,
  ScreeningResult,
  User,
} from "./contracts";

// `backend` is "real" when served by the API, or "mock" in mock mode.
export interface Served<T> {
  value: T;
  backend: string;
}

export interface MarketRun {
  deal_id: string;
  ingested: number;
}

export interface Api {
  mode: "mock" | "http";
  users(): Promise<User[]>;
  deals(): Promise<Deal[]>;
  documents(dealId: string): Promise<DocumentMeta[]>;
  ask(dealId: string, question: string): Promise<Served<Answer>>;
  passage(chunkId: string): Promise<Passage>;
  screening(request: ScreeningRequest): Promise<Served<ScreeningResult>>;
  kpis(dealId: string): Promise<Served<KpiValue[]>>;
  runMarketIntel(dealId: string): Promise<Served<MarketRun>>;
  events(dealId: string): Promise<MarketEvent[]>;
  refine(text: string, current: ScreeningRequest): Promise<RefineOutcome>;
  liveSearch(dealId: string, query: string): Promise<DocumentMeta[]>;
}

export interface RefineOutcome {
  request: ScreeningRequest;
  understood: string[];
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// DEMO_AUTH: the user is sent in X-User-Id. This is not production authentication.
export function createHttpApi(baseUrl: string, userId: string): Api {
  const root = baseUrl.replace(/\/+$/, "");

  async function call<T>(path: string, init?: { method: string; body?: unknown }): Promise<Served<T>> {
    const response = await fetch(`${root}${path}`, {
      method: init?.method ?? "GET",
      headers: {
        "X-User-Id": userId,
        ...(init?.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
    });
    if (!response.ok) {
      let detail = "";
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") detail = `: ${body.detail}`;
      } catch {
        // no JSON body
      }
      throw new ApiError(response.status, `${response.status} ${response.statusText}${detail}`.trim());
    }
    return {
      value: (await response.json()) as T,
      backend: "real",
    };
  }

  const value = async <T>(path: string): Promise<T> => (await call<T>(path)).value;

  return {
    mode: "http",
    users: () => value<User[]>("/users"),
    deals: () => value<Deal[]>("/deals"),
    documents: (dealId) => value<DocumentMeta[]>(`/deals/${encodeURIComponent(dealId)}/documents`),
    ask: (dealId, question) =>
      call<Answer>(`/deals/${encodeURIComponent(dealId)}/ask`, {
        method: "POST",
        body: { question },
      }),
    passage: (chunkId) => value<Passage>(`/passages/${encodeURIComponent(chunkId)}?page=true`),
    screening: (request) =>
      call<ScreeningResult>(`/deals/${encodeURIComponent(request.deal_id)}/screening`, {
        method: "POST",
        body: request,
      }),
    kpis: (dealId) => call<KpiValue[]>(`/deals/${encodeURIComponent(dealId)}/kpis`),
    runMarketIntel: (dealId) =>
      call<MarketRun>(`/deals/${encodeURIComponent(dealId)}/market-intel/run`, { method: "POST" }),
    events: (dealId) => value<MarketEvent[]>(`/deals/${encodeURIComponent(dealId)}/events`),
    liveSearch: async (dealId, query) =>
      (
        await call<DocumentMeta[]>(`/deals/${encodeURIComponent(dealId)}/market-intel/live`, {
          method: "POST",
          body: { query },
        })
      ).value,
    refine: async (text, current) =>
      (
        await call<RefineOutcome>(`/deals/${encodeURIComponent(current.deal_id)}/screening/refine`, {
          method: "POST",
          body: { text, current },
        })
      ).value,
  };
}
