import { useCallback, useMemo, useState } from "react";
import type { Api } from "@/lib/api";
import type {
  BuyerCard,
  BuyerType,
  Citation,
  Criterion,
  CriterionStatus,
  ScreeningRequest,
  ScreeningResult,
} from "@/lib/contracts";
import { formatNumber, percent } from "@/lib/format";
import { scoreCards } from "@/lib/scoring";
import { useAsync } from "@/lib/useAsync";
import { CitationButton } from "./CitationButton";

const GLYPH: Record<CriterionStatus, { glyph: string; label: string }> = {
  met: { glyph: "✓", label: "met" },
  not_met: { glyph: "✕", label: "not met" },
  unknown: { glyph: "?", label: "unknown" },
};

const BUYER_TYPES: BuyerType[] = ["strategic", "financial"];

interface FilterDraft {
  types: BuyerType[];
  sector: string;
  geography: string;
  minSize: string;
  maxSize: string;
}

const EMPTY_FILTERS: FilterDraft = { types: [], sector: "", geography: "", minSize: "", maxSize: "" };

function toRequest(dealId: string, draft: FilterDraft): ScreeningRequest {
  const list = (text: string) =>
    text
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
  const num = (text: string) => (text.trim() === "" || Number.isNaN(Number(text)) ? null : Number(text));
  return {
    deal_id: dealId,
    filters: {
      buyer_types: draft.types,
      sectors: list(draft.sector),
      geographies: list(draft.geography),
      min_size_eur_m: num(draft.minSize),
      max_size_eur_m: num(draft.maxSize),
    },
    weights: {},
    stage2_top_n: 10,
  };
}

function Glyph({ status, label }: { status: CriterionStatus; label: string }) {
  return (
    <span
      className={`glyph glyph-${status}`}
      title={`${label}: ${GLYPH[status].label}`}
      aria-label={`${label}: ${GLYPH[status].label}`}
      role="img"
    >
      {GLYPH[status].glyph}
    </span>
  );
}

function statusOf(card: BuyerCard, key: string): CriterionStatus {
  return card.results.find((r) => r.criterion_key === key)?.status ?? "unknown";
}

function WeightControls({
  criteria,
  weights,
  onChange,
  onReset,
}: {
  criteria: readonly Criterion[];
  weights: Record<string, number>;
  onChange: (key: string, weight: number) => void;
  onReset: () => void;
}) {
  return (
    <fieldset className="weights">
      <legend>Criterion weights (the ranking is recomputed here when you change them)</legend>
      {criteria.map((c) => (
        <div key={c.key} className="weight-row">
          <label htmlFor={`w-${c.key}`} title={c.description}>
            {c.label}
            {c.dealbreaker ? " (dealbreaker)" : ""}
          </label>
          <input
            type="range"
            aria-label={`${c.label} weight slider`}
            min={0}
            max={10}
            step={0.5}
            value={weights[c.key] ?? c.weight}
            onChange={(event) => onChange(c.key, Number(event.target.value))}
          />
          <input
            id={`w-${c.key}`}
            type="number"
            min={0}
            step={0.5}
            value={weights[c.key] ?? c.weight}
            onChange={(event) => onChange(c.key, Math.max(0, Number(event.target.value) || 0))}
          />
        </div>
      ))}
      <button type="button" onClick={onReset}>
        Reset weights
      </button>
    </fieldset>
  );
}

function BuyerCardView({
  card,
  criteria,
  onOpen,
  activeChunk,
}: {
  card: BuyerCard;
  criteria: readonly Criterion[];
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  const { buyer } = card;
  return (
    <section className="buyer-card" aria-label={`Buyer card: ${buyer.name}`}>
      <h3>{buyer.name}</h3>
      <p className="muted">
        {buyer.buyer_type}, {buyer.sectors.join(", ")}; {buyer.geographies.join(", ")}; size EUR{" "}
        {formatNumber(buyer.size_eur_m)}m. Stage 1 {card.stage1_passed ? "passed" : "not passed"}.{" "}
        {buyer.synthetic ? "Synthetic buyer." : ""}
      </p>
      {card.dealbreakers.length > 0 && (
        <p className="note">
          Dealbreaker not met:{" "}
          {card.dealbreakers
            .map((key) => criteria.find((c) => c.key === key)?.label ?? key)
            .join(", ")}
          . The buyer stays visible, ranked after buyers without a dealbreaker.
        </p>
      )}
      <table className="data" aria-label="Criteria">
        <thead>
          <tr>
            <th>Criterion</th>
            <th>Status</th>
            <th>Contribution</th>
            <th>Rationale and evidence</th>
          </tr>
        </thead>
        <tbody>
          {criteria.map((criterion) => {
            const result = card.results.find((r) => r.criterion_key === criterion.key);
            const status = result?.status ?? "unknown";
            return (
              <tr key={criterion.key}>
                <td>{criterion.label}</td>
                <td>
                  <Glyph status={status} label={criterion.label} /> {GLYPH[status].label}
                </td>
                <td>{formatNumber(card.contributions[criterion.key] ?? 0)}</td>
                <td>
                  <p>{result?.rationale ?? "No result for this criterion."}</p>
                  {result?.conflicting_evidence && (
                    <span className="chip chip-flag chip-contradicted">Sources disagree</span>
                  )}
                  <div className="citations">
                    {(result?.citations ?? []).map((citation) => (
                      <CitationButton
                        key={citation.chunk_id}
                        citation={citation}
                        onOpen={onOpen}
                        active={activeChunk === citation.chunk_id}
                      />
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function Results({
  result,
  onOpen,
  activeChunk,
}: {
  result: ScreeningResult;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  const [weights, setWeights] = useState<Record<string, number>>(() =>
    Object.fromEntries(result.criteria.map((c) => [c.key, c.weight])),
  );
  const [selected, setSelected] = useState<string | null>(null);
  const ranked = useMemo(
    () => scoreCards(result.criteria, result.cards, weights),
    [result, weights],
  );
  const chosen = ranked.find((c) => c.buyer.id === selected);

  return (
    <div>
      <WeightControls
        criteria={result.criteria}
        weights={weights}
        onChange={(key, weight) => setWeights((w) => ({ ...w, [key]: weight }))}
        onReset={() => setWeights(Object.fromEntries(result.criteria.map((c) => [c.key, c.weight])))}
      />
      <div className="table-scroll">
      <table className="data results" aria-label="Screening results">
        <thead>
          <tr>
            <th>Rank</th>
            <th>Buyer</th>
            <th>Type</th>
            <th title="Score over the criteria with evidence">Score</th>
            <th title="Range the score can still take once unknown criteria are known; the rank uses the floor">
              Possible range
            </th>
            <th>Coverage</th>
            {result.criteria.map((c) => (
              <th key={c.key} title={c.description}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ranked.map((card) => (
            <tr
              key={card.buyer.id}
              className={card.buyer.id === selected ? "row-active" : undefined}
              onClick={() => setSelected(card.buyer.id)}
            >
              <td>{card.rank}</td>
              <td>
                <button
                  type="button"
                  className="link"
                  aria-pressed={card.buyer.id === selected}
                  onClick={(event) => {
                    event.stopPropagation();
                    setSelected(card.buyer.id);
                  }}
                >
                  {card.buyer.name}
                </button>
                {card.dealbreakers.length > 0 && (
                  <span className="chip chip-flag chip-contradicted">Dealbreaker</span>
                )}
              </td>
              <td>{card.buyer.buyer_type}</td>
              <td>{percent(card.score)}</td>
              <td className="score-range">
                {card.score_low == null || card.score_high == null
                  ? "n/a"
                  : `${percent(card.score_low)} to ${percent(card.score_high)}`}
              </td>
              <td>{percent(card.coverage)}</td>
              {result.criteria.map((c) => (
                <td key={c.key}>
                  <Glyph status={statusOf(card, c.key)} label={c.label} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <p className="muted">
        {GLYPH.met.glyph} met, {GLYPH.not_met.glyph} not met, {GLYPH.unknown.glyph} unknown (no
        evidence found, never guessed). Score is the weight of met criteria over the weight of known
        criteria. Coverage is the share of total weight with evidence.
      </p>
      {chosen && (
        <BuyerCardView
          card={chosen}
          criteria={result.criteria}
          onOpen={onOpen}
          activeChunk={activeChunk}
        />
      )}
    </div>
  );
}

export function ScreeningTab({
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
  const [draft, setDraft] = useState<FilterDraft>(EMPTY_FILTERS);
  const [request, setRequest] = useState<ScreeningRequest>(() => toRequest(dealId, EMPTY_FILTERS));
  const load = useCallback(
    () =>
      api.screening(request).then((served) => {
        onBackend(served.backend);
        return served.value;
      }),
    [api, request, onBackend],
  );
  const state = useAsync(load);

  return (
    <div>
      <form
        className="filters"
        onSubmit={(event) => {
          event.preventDefault();
          setRequest(toRequest(dealId, draft));
        }}
      >
        <fieldset>
          <legend>Buyer type</legend>
          {BUYER_TYPES.map((type) => (
            <label key={type}>
              <input
                type="checkbox"
                checked={draft.types.includes(type)}
                onChange={(event) =>
                  setDraft((d) => ({
                    ...d,
                    types: event.target.checked ? [...d.types, type] : d.types.filter((t) => t !== type),
                  }))
                }
              />{" "}
              {type}
            </label>
          ))}
        </fieldset>
        <label>
          Sector
          <input value={draft.sector} onChange={(e) => setDraft((d) => ({ ...d, sector: e.target.value }))} />
        </label>
        <label>
          Geography
          <input
            value={draft.geography}
            onChange={(e) => setDraft((d) => ({ ...d, geography: e.target.value }))}
          />
        </label>
        <label>
          Min size (EUR m)
          <input
            type="number"
            value={draft.minSize}
            onChange={(e) => setDraft((d) => ({ ...d, minSize: e.target.value }))}
          />
        </label>
        <label>
          Max size (EUR m)
          <input
            type="number"
            value={draft.maxSize}
            onChange={(e) => setDraft((d) => ({ ...d, maxSize: e.target.value }))}
          />
        </label>
        <button type="submit" className="primary">
          Run screening
        </button>
      </form>

      {state.status === "loading" && <p className="muted">Screening buyers.</p>}
      {state.status === "error" && <p className="note" role="alert">{state.error.message}</p>}
      {state.status === "ready" &&
        (state.data.cards.length === 0 ? (
          <p className="muted">No buyer matches these filters.</p>
        ) : (
          <Results key={state.data.cards.map((c) => c.buyer.id).join()} result={state.data} onOpen={onOpen} activeChunk={activeChunk} />
        ))}
    </div>
  );
}
