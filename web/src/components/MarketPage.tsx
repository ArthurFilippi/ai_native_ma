import { useCallback, useState } from "react";
import type { Api } from "@/lib/api";
import type { Citation, DocumentMeta, MarketEvent } from "@/lib/contracts";
import { dateOrUnknown, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { Loading } from "./Loading";

const KIND: Record<MarketEvent["kind"], string> = {
  acquisition: "Acquisition",
  leadership_change: "New CEO",
  rumour: "Rumoured offer",
  price: "Price paid",
};

// One wording per state; a denied rumour is never shown as a fact.
const STATUS: Record<MarketEvent["status"], { label: string; tone: string }> = {
  confirmed: { label: "Confirmed", tone: "ok" },
  unconfirmed: { label: "Unconfirmed", tone: "warn" },
  denied: { label: "Denied", tone: "bad" },
  corrected: { label: "Corrected", tone: "sky" },
};

const NEWS_ORIGINS = new Set(["simulated-connector", "web"]);

export function MarketPage({ api, dealId, onOpen }: { api: Api; dealId: string; onOpen: (c: Citation) => void }) {
  const [runs, setRuns] = useState(0);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const load = useCallback(
    () => Promise.all([api.events(dealId), api.documents(dealId)]).then(([events, docs]) => ({ runs, events, docs })),
    [api, dealId, runs],
  );
  const state = useAsync(load);

  async function refresh() {
    setRunning(true);
    try {
      const served = await api.runMarketIntel(dealId);
      setMessage(`${served.value.ingested} news items filed in this deal (simulated feed).`);
      setRuns((n) => n + 1);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }

  const events: MarketEvent[] = state.status === "ready" ? state.data.events : [];
  const news: DocumentMeta[] =
    state.status === "ready"
      ? state.data.docs
          .filter((d) => NEWS_ORIGINS.has(d.origin))
          .sort((a, b) => (b.published_on ?? "").localeCompare(a.published_on ?? ""))
      : [];

  return (
    <>
      <div className="market-bar">
        <button type="button" className="btn solid" onClick={() => void refresh()} disabled={running}>
          Update news
        </button>
        <span className="sub" role="status">
          {message ?? "News feeds the answers and the buyer screening, ranked like any other source (tier 4)."}
        </span>
      </div>

      {state.status === "loading" && <Loading inline />}
      {state.status === "error" && (
        <p className="note bad mt" role="alert">
          {state.error.message}
        </p>
      )}

      <section className="plate">
        <div className="plate-h">
          <h2>Events</h2>
          <span className="sub">duplicates merged, denials and corrections applied</span>
        </div>
        <div className="plate-b flush">
          {events.length === 0 ? (
            <p className="plate-b sub">No news in this deal yet. Update news to fetch it.</p>
          ) : (
            <table className="tbl" aria-label="Market events">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Event</th>
                  <th>Who</th>
                  <th>Status</th>
                  <th>Sources</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id}>
                    <td className="mono nowrap">{dateOrUnknown(e.event_date)}</td>
                    <td>
                      {KIND[e.kind]}
                      {e.value_eur_m !== null && <span className="mono"> EUR {formatNumber(e.value_eur_m)}m</span>}
                    </td>
                    <td>
                      {e.actor} <span className="sub">and</span> {e.counterparty}
                    </td>
                    <td>
                      <span className={`st ${STATUS[e.status].tone}`}>{STATUS[e.status].label}</span>
                    </td>
                    <td>
                      <span className="refs">
                        {e.citations.map((c, i) => (
                          <button key={c.chunk_id} type="button" className="ref" aria-label={`Open report ${i + 1}`} onClick={() => onOpen(c)}>
                            {i + 1}
                          </button>
                        ))}
                        {e.superseded_citations.map((c) => (
                          <button key={c.chunk_id} type="button" className="ref old" title="Superseded figure" aria-label="Open the superseded report" onClick={() => onOpen(c)}>
                            old
                          </button>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>

      {news.length > 0 && (
        <section className="plate">
          <div className="plate-h">
            <h2>Latest news</h2>
            <span className="sub">{news.length} items</span>
          </div>
          <ul className="plate-b news">
            {news.slice(0, 12).map((d) => (
              <li key={d.id}>
                <span className="mono sub">{dateOrUnknown(d.published_on)}</span> {d.title}
                <span className="st">{d.origin === "web" ? "live" : "simulated"}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
