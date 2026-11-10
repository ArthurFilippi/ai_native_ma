import { useCallback, useState } from "react";
import type { Api } from "@/lib/api";
import type { Citation, MarketEvent } from "@/lib/contracts";
import { dateOrUnknown, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { CitationButton } from "./CitationButton";
import { Loading } from "./Loading";

const KIND_LABEL: Record<MarketEvent["kind"], string> = {
  acquisition: "Acquisition",
  leadership_change: "New chief executive",
  rumour: "Rumoured offer",
  price: "Price paid",
};

// One wording per state everywhere; a denied rumour is never shown as a fact.
const STATUS: Record<MarketEvent["status"], { label: string; tone: string }> = {
  confirmed: { label: "Confirmed", tone: "ok" },
  unconfirmed: { label: "Unconfirmed", tone: "warn" },
  denied: { label: "Denied", tone: "bad" },
  corrected: { label: "Corrected", tone: "sky" },
};

function Detail({
  event,
  onOpen,
  activeChunk,
  onClose,
}: {
  event: MarketEvent;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
  onClose: () => void;
}) {
  return (
    <section className="plate" aria-label={`Event: ${event.actor}, ${event.counterparty}`}>
      <div className="plate-h">
        <h2>
          <em>{KIND_LABEL[event.kind]}</em>
          {event.actor}, {event.counterparty}
        </h2>
        <button type="button" className="plate-x" aria-label="Close the event" onClick={onClose}>
          <span>×</span>
        </button>
      </div>
      <div className="plate-b">
        <div className="dr">
          <div className="dk">Status</div>
          <div className="dv">
            <span className={`st ${STATUS[event.status].tone}`}>{STATUS[event.status].label}</span>
          </div>
        </div>
        <div className="dr">
          <div className="dk">First reported</div>
          <div className="dv mono">{dateOrUnknown(event.event_date)}</div>
        </div>
        {event.value_eur_m !== null && (
          <div className="dr">
            <div className="dk">Value</div>
            <div className="dv mono">EUR {formatNumber(event.value_eur_m)}m</div>
          </div>
        )}
        <div className="dr">
          <div className="dk">Reports ({event.n_reports})</div>
          <div className="dv citations">
            {event.citations.map((c) => (
              <CitationButton
                key={c.chunk_id}
                citation={c}
                onOpen={onOpen}
                active={activeChunk === c.chunk_id}
              />
            ))}
          </div>
        </div>
        {event.superseded_citations.length > 0 && (
          <div className="dr">
            <div className="dk">Superseded figure</div>
            <div className="dv citations">
              {event.superseded_citations.map((c) => (
                <CitationButton
                  key={c.chunk_id}
                  citation={c}
                  onOpen={onOpen}
                  active={activeChunk === c.chunk_id}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export function EventsTab({
  api,
  dealId,
  onOpen,
  activeChunk,
}: {
  api: Api;
  dealId: string;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  const [reload, setReload] = useState(0);
  const load = useCallback(() => api.events(dealId).then((e) => ({ reload, e })), [api, dealId, reload]);
  const state = useAsync(load);
  const [selected, setSelected] = useState<string | null>(null);

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <p className="note bad mt" role="alert">
        {state.error.message}
      </p>
    );
  }
  const events = state.data.e;
  const chosen = events.find((e) => e.id === selected);
  return (
    <>
      <section className="plate">
        <div className="plate-b flush">
          {events.length === 0 ? (
            <p className="plate-b sub">
              No news in this deal space yet: run the simulated connector in Market.
            </p>
          ) : (
            <div className="fill fill-list">
              <table className="tbl" aria-label="Market events">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Event</th>
                    <th>Actor</th>
                    <th>Counterparty</th>
                    <th>Status</th>
                    <th className="num">Reports</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr
                      key={event.id}
                      className={`click${event.id === selected ? " sel" : ""}`}
                      onClick={() => setSelected(event.id)}
                    >
                      <td className="mono nowrap">{dateOrUnknown(event.event_date)}</td>
                      <td>{KIND_LABEL[event.kind]}</td>
                      <td>{event.actor}</td>
                      <td>{event.counterparty}</td>
                      <td>
                        <span className={`st ${STATUS[event.status].tone}`}>
                          {STATUS[event.status].label}
                        </span>
                      </td>
                      <td className="num mono">{event.n_reports}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div className="pager">
            <span className="sub">{events.length} events</span>
            <button type="button" className="btn sm" onClick={() => setReload((n) => n + 1)}>
              Refresh
            </button>
          </div>
        </div>
      </section>
      {chosen && (
        <Detail
          event={chosen}
          onOpen={onOpen}
          activeChunk={activeChunk}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
