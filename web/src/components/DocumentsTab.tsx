import { useCallback } from "react";
import type { Api } from "@/lib/api";
import { DOC_TYPE_LABEL } from "@/lib/constants";
import { dateOrUnknown } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { TierChip } from "./Chips";

export function DocumentsTab({ api, dealId }: { api: Api; dealId: string }) {
  const load = useCallback(() => api.documents(dealId), [api, dealId]);
  const state = useAsync(load);

  if (state.status === "loading") return <p className="muted">Loading documents.</p>;
  if (state.status === "error") return <p className="note" role="alert">{state.error.message}</p>;

  return (
    <table className="data" aria-label="Documents">
      <thead>
        <tr>
          <th>Title</th>
          <th>Type</th>
          <th>Tier</th>
          <th>Date</th>
          <th>Status</th>
          <th>Data</th>
          <th>Pages</th>
        </tr>
      </thead>
      <tbody>
        {state.data.map((doc) => (
          <tr key={doc.id}>
            <td>
              {doc.title}
              {doc.deal_id === null && <span className="muted"> (general layer)</span>}
            </td>
            <td>{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}</td>
            <td>
              <TierChip tier={doc.tier} />
            </td>
            <td>{dateOrUnknown(doc.published_on)}</td>
            <td>
              <span className={`chip chip-status chip-${doc.status}`}>{doc.status}</span>
            </td>
            <td>{doc.synthetic ? "synthetic" : "public"}</td>
            <td>{doc.n_pages}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
