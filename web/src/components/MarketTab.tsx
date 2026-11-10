import { useCallback, useState } from "react";
import type { Api } from "@/lib/api";
import { DOC_TYPE_LABEL } from "@/lib/constants";
import { dateOrUnknown } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { TierChip } from "./Chips";

const SIMULATED_ORIGIN = "simulated-connector";

export function MarketTab({
  api,
  dealId,
  onBackend,
}: {
  api: Api;
  dealId: string;
  onBackend: (backend: string) => void;
}) {
  const [runs, setRuns] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  // `runs` is part of the identity so the list reloads after each run.
  const load = useCallback(() => api.documents(dealId).then((docs) => ({ runs, docs })), [api, dealId, runs]);
  const state = useAsync(load);

  async function run() {
    setRunning(true);
    try {
      const served = await api.runMarketIntel(dealId);
      onBackend(served.backend);
      setMessage(`Ingested ${served.value.ingested} simulated items into this deal.`);
      setRuns((n) => n + 1);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setRunning(false);
    }
  }

  const items =
    state.status === "ready" ? state.data.docs.filter((d) => d.origin === SIMULATED_ORIGIN) : [];

  return (
    <div>
      <section className="plate">
        <div className="plate-b row-between">
          <p className="sub">
            The connector is simulated: it serves dated, generated items and never reaches a real
            data provider. Items become press documents of this deal and are ranked like any other
            source.
          </p>
          <button type="button" className="go" onClick={() => void run()} disabled={running}>
            <span>Run simulated connector</span>
            <i aria-hidden="true">→</i>
          </button>
        </div>
        {message && (
          <p className="plate-b tint" role="status">
            {message}
          </p>
        )}
      </section>
      {state.status === "error" && (
        <p className="note bad mt" role="alert">
          {state.error.message}
        </p>
      )}
      <section className="plate">
      <div className="plate-h">
        <h2>Ingested items</h2>
      </div>
      {items.length === 0 ? (
        <p className="plate-b sub">No simulated item has been ingested for this deal.</p>
      ) : (
        <div className="plate-b flush">
        <div className="fill fill-list">
        <table className="tbl" aria-label="Ingested market items">
          <thead>
            <tr>
              <th>Title</th>
              <th>Type</th>
              <th>Tier</th>
              <th>Date</th>
              <th>Label</th>
            </tr>
          </thead>
          <tbody>
            {items.map((doc) => (
              <tr key={doc.id}>
                <td>{doc.title}</td>
                <td>{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}</td>
                <td>
                  <TierChip tier={doc.tier} />
                </td>
                <td className="mono nowrap">{dateOrUnknown(doc.published_on)}</td>
                <td>
                  <span className="st">simulated</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
        </div>
      )}
      </section>
    </div>
  );
}
