import { useCallback, useState } from "react";
import type { Api } from "@/lib/api";
import { kpiLabel } from "@/lib/constants";
import type { Citation, KpiValue } from "@/lib/contracts";
import { formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/useAsync";
import { CitationButton } from "./CitationButton";
import { Loading } from "./Loading";

const MARKER = {
  sourced: { glyph: "●", label: "Sourced" },
  computed: { glyph: "ƒ", label: "Computed" },
  missing: { glyph: "○", label: "Missing" },
} as const;

function cellKey(value: KpiValue): string {
  return `${value.kpi_id}:${value.period}`;
}

function Detail({
  value,
  onOpen,
  activeChunk,
}: {
  value: KpiValue;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  return (
    <section className="plate kpi-detail" aria-label="KPI detail">
      <div className="plate-h">
        <h2>
          {kpiLabel(value.kpi_id)}, {value.period}
        </h2>
        <span className={`st ${value.status === "missing" ? "" : value.status === "computed" ? "sky" : "ok"}`}>
          {MARKER[value.status].label}
        </span>
      </div>
      <div className="plate-b">
      <p className="big">
        {MARKER[value.status].label}
        {value.value !== null ? `: ${formatNumber(value.value)} ${value.unit}` : ": not established by the sources"}
      </p>
      {value.status === "computed" && (
        <>
          <p className="sub mt">Computed from these inputs, not read from a document.</p>
          <table className="tbl tight" aria-label="Formula inputs">
            <tbody>
              {Object.entries(value.formula_inputs).map(([name, input]) => (
                <tr key={name}>
                  <th scope="row" className="mono">{name}</th>
                  <td className="num mono">{formatNumber(input)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="citations">
      {value.citations.map((citation) => (
        <CitationButton
          key={citation.chunk_id}
          citation={citation}
          onOpen={onOpen}
          active={activeChunk === citation.chunk_id}
        />
      ))}
      </div>
      </div>
    </section>
  );
}

export function KpiTab({
  api,
  dealId,
  onOpen,
  activeChunk,
  onBackend,
}: {
  api: Api;
  dealId: string;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
  onBackend: (backend: string) => void;
}) {
  const load = useCallback(
    () =>
      api.kpis(dealId).then((served) => {
        onBackend(served.backend);
        return served.value;
      }),
    [api, dealId, onBackend],
  );
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

  const values = state.data;
  const kpiIds = [...new Set(values.map((v) => v.kpi_id))];
  const periods = [...new Set(values.map((v) => v.period))].sort();
  const byCell = new Map(values.map((v) => [cellKey(v), v]));
  const chosen = selected ? byCell.get(selected) : undefined;

  return (
    <div>
      <section className="plate">
      <div className="plate-b flush">
      <div className="fill fill-list">
      <table className="tbl kpis" aria-label="KPIs by period">
        <thead>
          <tr>
            <th>KPI</th>
            {periods.map((p) => (
              <th key={p}>{p}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {kpiIds.map((id) => (
            <tr key={id}>
              <th scope="row">{kpiLabel(id)}</th>
              {periods.map((period) => {
                const value = byCell.get(`${id}:${period}`);
                if (!value) return <td key={period} className="sub">not extracted</td>;
                return (
                  <td key={period}>
                    <button
                      type="button"
                      className={`kpi-cell${selected === cellKey(value) ? " on" : ""}`}
                      onClick={() => setSelected(cellKey(value))}
                      aria-label={`${kpiLabel(id)} ${period}, ${MARKER[value.status].label}`}
                    >
                      <span className={`marker marker-${value.status}`} aria-hidden="true">
                        {MARKER[value.status].glyph}
                      </span>{" "}
                      {value.value !== null ? `${formatNumber(value.value)} ${value.unit}` : "missing"}
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <p className="pager sub">
        {MARKER.sourced.glyph} sourced from a document, {MARKER.computed.glyph} computed from other
        KPIs, {MARKER.missing.glyph} missing. Click a value to see its source or its inputs.
      </p>
      </div>
      </section>
      {chosen && <Detail value={chosen} onOpen={onOpen} activeChunk={activeChunk} />}
    </div>
  );
}
