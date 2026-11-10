"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { Api } from "@/lib/api";
import { createHttpApi } from "@/lib/api";
import type { Citation, Deal, User } from "@/lib/contracts";
import { useAsync } from "@/lib/useAsync";
import { MockBackend } from "@/mock/mockApi";
import { AskPage } from "./AskPage";
import { BuyersPage } from "./BuyersPage";
import { DealPage } from "./DealPage";
import { Drawer } from "./Drawer";
import { Dropdown } from "./Dropdown";
import { EvidencePanel } from "./EvidencePanel";
import { Loading } from "./Loading";
import { MarketPage } from "./MarketPage";

const PAGES = ["Deal", "Ask", "Buyers", "Market"] as const;
type Page = (typeof PAGES)[number];

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

// One route per place: the page lives in the URL hash (`#/buyers`), so a reload keeps it.
function pageFromHash(): Page {
  if (typeof window === "undefined") return "Ask";
  const slug = window.location.hash.replace(/^#\/?/, "").split("?")[0]?.toLowerCase();
  return PAGES.find((p) => p.toLowerCase() === slug) ?? "Ask";
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
  const [page, setPage] = useState<Page>("Ask");
  const [visited, setVisited] = useState<ReadonlySet<Page>>(new Set<Page>(["Ask"]));
  const [source, setSource] = useState<Citation | null>(null);

  useEffect(() => {
    const sync = () => {
      const next = pageFromHash();
      setPage(next);
      setVisited((v) => new Set([...v, next]));
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const dealList = deals.status === "ready" ? deals.data : [];
  const deal = dealList.find((d) => d.id === dealChoice) ?? dealList[0] ?? null;
  const openSource = useCallback((citation: Citation) => setSource(citation), []);
  const closeSource = useCallback(() => setSource(null), []);

  function go(next: Page) {
    setPage(next);
    setVisited((v) => new Set([...v, next]));
    window.history.replaceState(null, "", `#/${next.toLowerCase()}`);
  }

  const userOptions = (users.status === "ready" ? users.data : [{ id: userId, name: userId }]).map(
    (u) => ({ value: u.id, label: u.name }),
  );

  return (
    <>
      <div className="chrome">
        <div className="chrome-in">
          <header className="cells top">
            <div className="brand">
              <svg width="22" height="22" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="1" y="1" width="10" height="10" rx="2.5" fill="#b9ecd0" stroke="#0a0a0a" />
                <rect x="13" y="1" width="10" height="10" rx="2.5" fill="#bcd6ff" stroke="#0a0a0a" />
                <rect x="1" y="13" width="10" height="10" rx="2.5" fill="#f6e58d" stroke="#0a0a0a" />
                <rect x="13" y="13" width="10" height="10" rx="2.5" fill="#0a0a0a" />
              </svg>
              <b>M&amp;A desk</b>
              <span className="synthetic" title="Every company, figure and document is fictional">
                synthetic data
              </span>
            </div>
            <nav id="nav" aria-label="Sections">
              {PAGES.map((name) => (
                <button
                  key={name}
                  type="button"
                  aria-current={page === name ? "page" : undefined}
                  className={`na${page === name ? " on" : ""}`}
                  onClick={() => go(name)}
                >
                  {name}
                </button>
              ))}
            </nav>
            <div className="who">
              <span className="who-id">
                <Dropdown
                  label="Demo user (not real authentication)"
                  value={userId}
                  options={userOptions}
                  onChange={(next) => {
                    setUserId(next);
                    setSource(null);
                    setVisited(new Set<Page>([page]));
                  }}
                  small
                />
              </span>
            </div>
          </header>
        </div>
      </div>

      <div className="frame">
        <main>
          <div className="head">
            <div>
              <h1 className="t1">{page === "Deal" && deal ? deal.name : page}</h1>
            </div>
            <div className="head-aside">
              {deal && dealList.length > 1 && (
                <div className="deal-pick">
                  <Dropdown
                    label="Deal"
                    value={deal.id}
                    options={dealList.map((d) => ({ value: d.id, label: d.name, sub: d.sector }))}
                    onChange={setDealChoice}
                  />
                </div>
              )}
              {deal && dealList.length <= 1 && page !== "Deal" && (
                <span className="sub">{deal.name}</span>
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
            <div key={`${userId}:${deal.id}`}>
              {visited.has("Deal") && (
                <div hidden={page !== "Deal"}>
                  <DealPage api={api} deal={deal} onOpen={openSource} />
                </div>
              )}
              {visited.has("Ask") && (
                <div hidden={page !== "Ask"}>
                  <AskPage api={api} dealId={deal.id} onOpen={openSource} activeChunk={source?.chunk_id ?? null} />
                </div>
              )}
              {visited.has("Buyers") && (
                <div hidden={page !== "Buyers"}>
                  <BuyersPage api={api} dealId={deal.id} onOpen={openSource} />
                </div>
              )}
              {visited.has("Market") && (
                <div hidden={page !== "Market"}>
                  <MarketPage api={api} dealId={deal.id} onOpen={openSource} />
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      {source && (
        <Drawer onClose={closeSource} label="Source">
          <EvidencePanel api={api} citation={source} onClose={closeSource} />
        </Drawer>
      )}
    </>
  );
}
