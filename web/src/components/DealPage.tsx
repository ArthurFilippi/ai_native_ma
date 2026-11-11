import { useCallback } from "react";
import type { Api } from "@/lib/api";
import { DOC_TYPE_LABEL, kpiLabel } from "@/lib/constants";
import type { Citation, Deal, DocumentMeta, KpiValue } from "@/lib/contracts";
import { dateOrUnknown, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { StatusChip, TierChip } from "./Chips";
import { Loading } from "./Loading";

const KEY_FIGURES = ["revenue", "ebitda", "gross_margin", "net_debt"];

function KeyFigures({ api, dealId, onOpen }: { api: Api; dealId: string; onOpen: (c: Citation) => void }) {
  const load = useCallback(() => api.kpis(dealId).then((s) => s.value), [api, dealId]);
  const state = useAsync<KpiValue[]>(load);
  if (state.status !== "ready") return null;
  const periods = [...new Set(state.data.map((v) => v.period))].sort();
  const latest = periods[periods.length - 1];
  const figures = KEY_FIGURES.map((id) => state.data.find((v) => v.kpi_id === id && v.period === latest)).filter(
    (v): v is KpiValue => v !== undefined && v.value !== null,
  );
  if (figures.length === 0) return null;
  return (
    <section className="figures" aria-label="Key figures">
      {figures.map((v) => {
        const cite = v.citations[0];
        return (
          <div key={v.kpi_id} className="figure">
            <span className="lab">
              {kpiLabel(v.kpi_id)} {v.period}
            </span>
            <b>
              {formatNumber(v.value ?? 0)}
              <small>{v.unit}</small>
            </b>
            {cite ? (
              <button type="button" className="link sub" onClick={() => onOpen(cite)}>
                {cite.doc_title}, T{cite.tier}
              </button>
            ) : (
              <span className="sub">{v.status === "computed" ? "computed from other figures" : "no source"}</span>
            )}
          </div>
        );
      })}
    </section>
  );
}

export function DealPage({ api, deal, onOpen }: { api: Api; deal: Deal; onOpen: (c: Citation) => void }) {
  const load = useCallback(() => api.documents(deal.id), [api, deal.id]);
  const state = useAsync<DocumentMeta[]>(load);
  const docs = state.status === "ready" ? state.data : [];
  const own = docs.filter((d) => d.deal_id === deal.id);
  const byTier = [1, 2, 3, 4, 5].map((t) => own.filter((d) => d.tier === t).length);
  const newest = own.map((d) => d.published_on).filter((d): d is string => d !== null).sort().pop();

  return (
    <>
      <p className="sub deal-line">
        {deal.sector}, {deal.status}. {deal.description}
      </p>
      <section className="figures" aria-label="Data room">
        <div className="figure">
          <span className="lab">Documents</span>
          <b>{own.length}</b>
          <span className="sub">in the data room</span>
        </div>
        <div className="figure">
          <span className="lab">By source tier</span>
          <span className="tiers mono">
            {byTier.map((n, i) => (
              <span key={i}>
                T{i + 1} <b>{n}</b>
              </span>
            ))}
          </span>
          <span className="sub">T1 signed and filed, T5 web</span>
        </div>
        <div className="figure">
          <span className="lab">Latest document</span>
          <b className="mono small">{newest ?? "n/a"}</b>
          <span className="sub">publication date</span>
        </div>
      </section>

      <KeyFigures api={api} dealId={deal.id} onOpen={onOpen} />

      <section className="plate">
        <div className="plate-h">
          <h2>Data room</h2>
          <span className="sub">Also searched: {docs.length - own.length} reference documents of the firm</span>
        </div>
        <div className="plate-b flush">
          {state.status === "loading" && <Loading inline />}
          {state.status === "error" && (
            <p className="note bad" role="alert">
              {state.error.message}
            </p>
          )}
          {state.status === "ready" && (
            <div className="fill fill-list">
              <table className="tbl" aria-label="Documents">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Type</th>
                    <th>Tier</th>
                    <th>Date</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {own.map((doc) => (
                    <tr key={doc.id}>
                      <td>{doc.title}</td>
                      <td>{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}</td>
                      <td>
                        <TierChip tier={doc.tier} />
                      </td>
                      <td className="mono nowrap">{dateOrUnknown(doc.published_on)}</td>
                      <td>
                        <StatusChip status={doc.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </>
  );
}
