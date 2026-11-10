"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Api } from "@/lib/api";
import { createHttpApi } from "@/lib/api";
import type { Answer, Citation, Deal, User } from "@/lib/contracts";
import { useAsync } from "@/lib/useAsync";
import { MockBackend } from "@/mock/mockApi";
import { AskTab } from "./AskTab";
import { DocumentsTab } from "./DocumentsTab";
import { Dropdown } from "./Dropdown";
import { EventsTab } from "./EventsTab";
import { type EvidenceTarget, EvidencePanel } from "./EvidencePanel";
import { KpiTab } from "./KpiTab";
import { Loading } from "./Loading";
import { MarketTab } from "./MarketTab";
import { ScreeningTab } from "./ScreeningTab";

const TABS = ["Ask", "Documents", "Screening", "KPIs", "Events", "Market"] as const;
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

// One route per place (design rule 5): the tab lives in the URL hash, `#/screening`.
function tabFromHash(): Tab {
  if (typeof window === "undefined") return "Ask";
  const slug = window.location.hash.replace(/^#\/?/, "").split("?")[0]?.toLowerCase();
  return TABS.find((t) => t.toLowerCase() === slug) ?? "Ask";
}

function Brand() {
  return (
    <div className="brand">
      <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
        <rect x="1" y="1" width="10" height="10" rx="2.5" fill="#b9ecd0" stroke="#0a0a0a" />
        <rect x="13" y="1" width="10" height="10" rx="2.5" fill="#bcd6ff" stroke="#0a0a0a" />
        <rect x="1" y="13" width="10" height="10" rx="2.5" fill="#f6e58d" stroke="#0a0a0a" />
        <rect x="13" y="13" width="10" height="10" rx="2.5" fill="#0a0a0a" />
      </svg>
      <b>AI-native M&amp;A</b>
      <span className="mono dim">Deal room</span>
    </div>
  );
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

  useEffect(() => {
    const sync = () => {
      const next = tabFromHash();
      setTab(next);
      setVisited((v) => new Set([...v, next]));
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

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
    window.history.replaceState(null, "", `#/${next.toLowerCase()}`);
  }

  function selectUser(next: string) {
    setUserId(next);
    setEvidence(null);
    setBackend(null);
    setVisited(new Set<Tab>([tab]));
  }

  const showEvidenceZone = tab === "Ask" || evidence !== null;
  const scope = `${userId}:${deal?.id ?? "none"}`;
  const userOptions = (users.status === "ready" ? users.data : [{ id: userId, name: userId }]).map(
    (u) => ({ value: u.id, label: u.name, sub: u.id }),
  );
  const source = api.mode === "mock" ? "mock data" : backend ? `backend: ${backend}` : "API";

  return (
    <>
      <div className="chrome">
        <div className="chrome-in">
          <header className="cells top">
            <Brand />
            <nav id="nav" role="tablist" aria-label="Sections">
              {TABS.map((name) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  aria-selected={tab === name}
                  className={`na${tab === name ? " on" : ""}`}
                  onClick={() => selectTab(name)}
                >
                  {name}
                </button>
              ))}
            </nav>
            <div className="who">
              <span className="who-id" title="Demo user (DEMO_AUTH, not real authentication)">
                <Dropdown
                  label="Demo user (DEMO_AUTH, not real authentication)"
                  value={userId}
                  options={userOptions}
                  onChange={selectUser}
                  small
                />
              </span>
            </div>
          </header>
        </div>
      </div>

      <div className="frame">
        {/* Simulated data is always visibly pink (design rule 10): every document here is synthetic. */}
        <div className="cells sim" aria-label="Synthetic data">
          <span className="sim-lab" style={{ flex: "0 0 auto" }}>
            Synthetic data
          </span>
          <span className="sim-count" style={{ flex: "1 1 auto" }}>
            Every company, figure and document is fictional
          </span>
          <span className="sim-word" style={{ flex: "0 0 auto" }} title="Where the data on screen comes from">
            {source}
          </span>
        </div>

        <main>
          <div className="head">
            <div>
              <h1 className="t1">{tab}</h1>
            </div>
            <div className="head-aside">
              {deal && (
                <div className="deal-pick">
                  {dealList.length > 1 ? (
                    <Dropdown
                      label="Deal"
                      value={deal.id}
                      options={dealList.map((d) => ({ value: d.id, label: d.name, sub: d.sector }))}
                      onChange={setDealChoice}
                    />
                  ) : (
                    <span className="big">{deal.name}</span>
                  )}
                  <span className="sub">
                    {deal.sector}, {deal.status}
                  </span>
                </div>
              )}
            </div>
          </div>

          {deals.status === "loading" && <Loading />}
          {deals.status === "error" && (
            <p className="note bad mt" role="alert">
              Could not reach the deal list: {deals.error.message}
            </p>
          )}
          {deals.status === "ready" && !deal && (
            <p className="note mt" role="status">
              No deal is visible to this user. A deal without membership is hidden, and the API
              answers 404 for it.
            </p>
          )}

          {deal && (
            <div className={showEvidenceZone ? "workspace two-zones" : "workspace"} key={scope}>
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
                {visited.has("Events") && (
                  <div hidden={tab !== "Events"}>
                    <EventsTab
                      api={api}
                      dealId={deal.id}
                      onOpen={openEvidence}
                      activeChunk={activeChunk}
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
                    <aside className="plate evidence empty" aria-label="Evidence panel">
                      <div className="plate-h">
                        <h2>Evidence</h2>
                      </div>
                      <div className="plate-b">
                        <p className="sub">
                          Click a citation to read the source passage here, with the cited text
                          highlighted.
                        </p>
                      </div>
                    </aside>
                  )}
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </>
  );
}
