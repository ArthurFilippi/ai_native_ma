"use client";

import { useCallback, useMemo, useState } from "react";
import type { Api } from "@/lib/api";
import { createHttpApi } from "@/lib/api";
import type { Answer, Citation, Deal, User } from "@/lib/contracts";
import { useAsync } from "@/lib/useAsync";
import { MockBackend } from "@/mock/mockApi";
import { AskTab } from "./AskTab";
import { DocumentsTab } from "./DocumentsTab";
import { type EvidenceTarget, EvidencePanel } from "./EvidencePanel";
import { KpiTab } from "./KpiTab";
import { MarketTab } from "./MarketTab";
import { ScreeningTab } from "./ScreeningTab";

const TABS = ["Ask", "Documents", "Screening", "KPIs", "Market"] as const;
type Tab = (typeof TABS)[number];

export type MakeApi = (userId: string) => Api;

export interface AppProps {
  // Empty means mock mode: the client runs on the example payloads, no network.
  baseUrl: string;
  // Tests inject their own factory.
  makeApi?: MakeApi;
}

function useApiFactory(baseUrl: string, makeApi: MakeApi | undefined): MakeApi {
  const backend = useMemo(() => new MockBackend(), []);
  return useMemo(() => {
    if (makeApi) return makeApi;
    if (baseUrl) return (userId: string) => createHttpApi(baseUrl, userId);
    return (userId: string) => backend.forUser(userId);
  }, [baseUrl, makeApi, backend]);
}

export function App({ baseUrl, makeApi }: AppProps) {
  const factory = useApiFactory(baseUrl, makeApi);
  const [userId, setUserId] = useState("u_analyst");
  const api = useMemo(() => factory(userId), [factory, userId]);

  const loadUsers = useCallback(() => factory(userId).users(), [factory, userId]);
  const users = useAsync<User[]>(loadUsers);
  const loadDeals = useCallback(() => api.deals(), [api]);
  const deals = useAsync<Deal[]>(loadDeals);

  const [dealChoice, setDealChoice] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Ask");
  const [visited, setVisited] = useState<ReadonlySet<Tab>>(new Set<Tab>(["Ask"]));
  const [evidence, setEvidence] = useState<EvidenceTarget | null>(null);
  const [backend, setBackend] = useState<string | null>(null);

  const dealList = deals.status === "ready" ? deals.data : [];
  const deal = dealList.find((d) => d.id === dealChoice) ?? dealList[0] ?? null;

  const openEvidence = useCallback((citation: Citation, answer?: Answer) => {
    setEvidence({
      citation,
      ranking: answer?.trace.retrieved.find((r) => r.chunk_id === citation.chunk_id) ?? null,
    });
  }, []);
  const closeEvidence = useCallback(() => setEvidence(null), []);
  const activeChunk = evidence?.citation.chunk_id ?? null;

  function selectTab(next: Tab) {
    setTab(next);
    setEvidence(null);
    setVisited((v) => new Set([...v, next]));
  }

  function selectUser(next: string) {
    setUserId(next);
    setEvidence(null);
    setBackend(null);
    setVisited(new Set<Tab>([tab]));
  }

  const showEvidenceZone = tab === "Ask" || evidence !== null;
  const scope = `${userId}:${deal?.id ?? "none"}`;

  return (
    <div className="app">
      <header className="band">
        <div className="band-title">
          <strong>{deal ? deal.name : "No deal"}</strong>
          {deal && <span className="muted"> {deal.sector}, {deal.status}</span>}
          {deals.status === "ready" && dealList.length > 1 && (
            <select
              aria-label="Deal"
              value={deal?.id ?? ""}
              onChange={(event) => setDealChoice(event.target.value)}
            >
              {dealList.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="band-right">
          <span className="chip" title="Where the data on screen comes from">
            {api.mode === "mock" ? "mock data" : backend ? `backend: ${backend}` : "API"}
          </span>
          <label>
            Demo user (DEMO_AUTH, not real authentication){" "}
            <select aria-label="Demo user" value={userId} onChange={(e) => selectUser(e.target.value)}>
              {(users.status === "ready" ? users.data : [{ id: userId, name: userId }]).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.name} ({u.id})
                </option>
              ))}
            </select>
          </label>
        </div>
        <nav className="tabs" role="tablist" aria-label="Sections">
          {TABS.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={tab === name ? "tab tab-active" : "tab"}
              onClick={() => selectTab(name)}
            >
              {name}
            </button>
          ))}
        </nav>
      </header>

      {deals.status === "loading" && <p className="muted pad">Loading deals.</p>}
      {deals.status === "error" && (
        <p className="note pad" role="alert">
          Could not reach the deal list: {deals.error.message}
        </p>
      )}
      {deals.status === "ready" && !deal && (
        <p className="pad" role="status">
          No deal is visible to this user. A deal without membership is hidden, and the API answers 404
          for it.
        </p>
      )}

      {deal && (
        <main className={showEvidenceZone ? "workspace two-zones" : "workspace"} key={scope}>
          <div className="zone-left">
            {visited.has("Ask") && (
              <div hidden={tab !== "Ask"}>
                <AskTab
                  api={api}
                  dealId={deal.id}
                  onOpen={openEvidence}
                  activeChunk={activeChunk}
                  onBackend={setBackend}
                />
              </div>
            )}
            {visited.has("Documents") && (
              <div hidden={tab !== "Documents"}>
                <DocumentsTab api={api} dealId={deal.id} />
              </div>
            )}
            {visited.has("Screening") && (
              <div hidden={tab !== "Screening"}>
                <ScreeningTab
                  api={api}
                  dealId={deal.id}
                  onOpen={openEvidence}
                  activeChunk={activeChunk}
                  onBackend={setBackend}
                />
              </div>
            )}
            {visited.has("KPIs") && (
              <div hidden={tab !== "KPIs"}>
                <KpiTab
                  api={api}
                  dealId={deal.id}
                  onOpen={openEvidence}
                  activeChunk={activeChunk}
                  onBackend={setBackend}
                />
              </div>
            )}
            {visited.has("Market") && (
              <div hidden={tab !== "Market"}>
                <MarketTab api={api} dealId={deal.id} onBackend={setBackend} />
              </div>
            )}
          </div>
          {showEvidenceZone && (
            <div className="zone-right">
              {evidence ? (
                <EvidencePanel api={api} target={evidence} onClose={closeEvidence} />
              ) : (
                <aside className="evidence empty" aria-label="Evidence panel">
                  <h2>Evidence</h2>
                  <p className="muted">Click a citation to read the source passage here, with the cited text highlighted.</p>
                </aside>
              )}
            </div>
          )}
        </main>
      )}
    </div>
  );
}
