import { useCallback } from "react";
import type { Api } from "@/lib/api";
import { DOC_TYPE_LABEL } from "@/lib/constants";
import { dateOrUnknown } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { StatusChip, TierChip } from "./Chips";
import { Loading } from "./Loading";

export function DocumentsTab({ api, dealId }: { api: Api; dealId: string }) {
  const load = useCallback(() => api.documents(dealId), [api, dealId]);
  const state = useAsync(load);

  if (state.status === "loading") return <Loading />;
  if (state.status === "error") {
    return (
      <p className="note bad mt" role="alert">
        {state.error.message}
      </p>
    );
  }

  return (
    <section className="plate">
    <div className="plate-b flush">
    <div className="fill fill-list">
    <table className="tbl" aria-label="Documents">
      <thead>
        <tr>
          <th>Title</th>
          <th>Type</th>
          <th>Tier</th>
          <th>Date</th>
          <th>Status</th>
          <th>Data</th>
          <th className="num">Pages</th>
        </tr>
      </thead>
      <tbody>
        {state.data.map((doc) => (
          <tr key={doc.id}>
            <td>
              {doc.title}
              {doc.deal_id === null && <span className="sub"> (general layer)</span>}
            </td>
            <td>{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}</td>
            <td>
              <TierChip tier={doc.tier} />
            </td>
            <td className="mono nowrap">{dateOrUnknown(doc.published_on)}</td>
            <td>
              <StatusChip status={doc.status} />
            </td>
            <td>{doc.synthetic ? "synthetic" : "public"}</td>
            <td className="num mono">{doc.n_pages}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
    <div className="pager">
      <span className="sub">{state.data.length} documents</span>
    </div>
    </div>
    </section>
  );
}
