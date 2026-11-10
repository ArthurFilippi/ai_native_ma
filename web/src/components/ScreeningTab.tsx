import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { Loading } from "./Loading";

// A criterion is a state cell of the design (`.cell`): mint met, rose not met, dashed unknown.
// Colour is never alone: each cell carries a glyph and an accessible label.
const GLYPH: Record<CriterionStatus, { glyph: string; label: string; cell: string }> = {
  met: { glyph: "✓", label: "met", cell: "v" },
  not_met: { glyph: "✕", label: "not met", cell: "q" },
  unknown: { glyph: "?", label: "unknown", cell: "m" },
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
      className={`cell ${GLYPH[status].cell} glyph glyph-${status}`}
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
    <details className="plate fold weights">
      <summary>
        <span className="fold-t">Criterion weights</span>
        <span className="fold-h">the ranking is recomputed here when you change them</span>
      </summary>
      <div className="weight-grid">
      {criteria.map((c) => (
        <div key={c.key} className="weight-row">
          <label htmlFor={`w-${c.key}`} title={c.description} className="lab">
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
      </div>
      <button type="button" className="btn sm mt" onClick={onReset}>
        Reset weights
      </button>
    </details>
  );
}

function BuyerCardView({
  card,
  criteria,
  onOpen,
  activeChunk,
  onClose,
}: {
  card: BuyerCard;
  criteria: readonly Criterion[];
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
  onClose: () => void;
}) {
  const { buyer } = card;
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    // the window locks the page scroll, takes the focus, and Escape closes it (design rule 6)
    closeRef.current?.focus();
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.body.style.overflow = previous;
      document.removeEventListener("keydown", escape);
    };
  }, [onClose]);
  return (
    <div className="pw-overlay">
      <div className="pw-back" onClick={onClose} />
      <section
        className="pw buyer-card"
        role="dialog"
        aria-modal="true"
        aria-label={`Buyer card: ${buyer.name}`}
      >
        <div className="pw-head">
          <div className="pw-title">
            <h2>{buyer.name}</h2>
            <span className="mono">
              rank {card.rank ?? "n/a"}, score {percent(card.score)}, range{" "}
              {card.score_low == null || card.score_high == null
                ? "n/a"
                : `${percent(card.score_low)} to ${percent(card.score_high)}`}
              , coverage {percent(card.coverage)}
            </span>
          </div>
          <button ref={closeRef} type="button" className="pw-x" aria-label="Close" onClick={onClose}>
            <span>×</span>
          </button>
        </div>
        <div className="pw-blocks">
          <p className="sub">
            {buyer.buyer_type}, {buyer.sectors.join(", ")}; {buyer.geographies.join(", ")}; size EUR{" "}
            {formatNumber(buyer.size_eur_m)}m. Stage 1 {card.stage1_passed ? "passed" : "not passed"}.{" "}
            {buyer.synthetic ? "Synthetic buyer." : ""}
          </p>
          {card.dealbreakers.length > 0 && (
            <p className="note bad mt">
              Dealbreaker not met:{" "}
              {card.dealbreakers
                .map((key) => criteria.find((c) => c.key === key)?.label ?? key)
                .join(", ")}
              . The buyer stays visible, ranked after buyers without a dealbreaker.
            </p>
          )}
          {criteria.map((criterion) => {
            const result = card.results.find((r) => r.criterion_key === criterion.key);
            const status = result?.status ?? "unknown";
            return (
              <div key={criterion.key} className="pw-block-row">
                <div>
                  <div className="pw-name">{criterion.label}</div>
                  <div className="pw-count mono">
                    <Glyph status={status} label={criterion.label} /> {GLYPH[status].label}, +
                    {formatNumber(card.contributions[criterion.key] ?? 0)}
                  </div>
                </div>
                <div className="pw-body">
                  <p>{result?.rationale ?? "No result for this criterion."}</p>
                  {result?.conflicting_evidence && (
                    <span className="st bad">Sources disagree</span>
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
                </div>
              </div>
            );
          })}
        </div>
        <div className="pw-foot">
          <span className="ov-legend tight">
            <span>
              <i className="cell v" /> Met
            </span>
            <span>
              <i className="cell q" /> Not met
            </span>
            <span>
              <i className="cell m" /> Unknown, never guessed
            </span>
          </span>
        </div>
      </section>
    </div>
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
  const closeCard = useCallback(() => setSelected(null), []);

  return (
    <div>
      <WeightControls
        criteria={result.criteria}
        weights={weights}
        onChange={(key, weight) => setWeights((w) => ({ ...w, [key]: weight }))}
        onReset={() => setWeights(Object.fromEntries(result.criteria.map((c) => [c.key, c.weight])))}
      />
      <section className="plate">
      <div className="plate-b flush">
      <div className="fill fill-list">
      <table className="tbl results" aria-label="Screening results">
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
              className={`click${card.buyer.id === selected ? " sel" : ""}`}
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
                  <span className="st bad">Dealbreaker</span>
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
      <p className="pager sub">
        {GLYPH.met.glyph} met, {GLYPH.not_met.glyph} not met, {GLYPH.unknown.glyph} unknown (no
        evidence found, never guessed). Score is the weight of met criteria over the weight of known
        criteria. Coverage is the share of total weight with evidence. The range shows the
        score once the unknowns are known; the rank uses its floor.
      </p>
      </div>
      </section>
      {chosen && (
        <BuyerCardView
          card={chosen}
          criteria={result.criteria}
          onOpen={(citation) => {
            setSelected(null);
            onOpen(citation);
          }}
          activeChunk={activeChunk}
          onClose={closeCard}
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
        className="plate filters"
        onSubmit={(event) => {
          event.preventDefault();
          setRequest(toRequest(dealId, draft));
        }}
      >
        <div className="plate-b">
          <div className="row">
            <div className="field" style={{ flex: "0 1 auto" }}>
              <span className="lab">Buyer type</span>
              <span className="chips">
                {BUYER_TYPES.map((type) => (
                  <button
                    key={type}
                    type="button"
                    className={`opt${draft.types.includes(type) ? " on" : ""}`}
                    aria-pressed={draft.types.includes(type)}
                    onClick={() =>
                      setDraft((d) => ({
                        ...d,
                        types: d.types.includes(type)
                          ? d.types.filter((t) => t !== type)
                          : [...d.types, type],
                      }))
                    }
                  >
                    {type}
                  </button>
                ))}
              </span>
            </div>
            <div className="field">
              <label className="lab" htmlFor="f-sector">
                Sector
              </label>
              <input
                id="f-sector"
                type="text"
                placeholder="from the deal"
                value={draft.sector}
                onChange={(e) => setDraft((d) => ({ ...d, sector: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="lab" htmlFor="f-geo">
                Geography
              </label>
              <input
                id="f-geo"
                type="text"
                placeholder="from the deal"
                value={draft.geography}
                onChange={(e) => setDraft((d) => ({ ...d, geography: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="lab" htmlFor="f-min">
                Min size (EUR m)
              </label>
              <input
                id="f-min"
                type="number"
                value={draft.minSize}
                onChange={(e) => setDraft((d) => ({ ...d, minSize: e.target.value }))}
              />
            </div>
            <div className="field">
              <label className="lab" htmlFor="f-max">
                Max size (EUR m)
              </label>
              <input
                id="f-max"
                type="number"
                value={draft.maxSize}
                onChange={(e) => setDraft((d) => ({ ...d, maxSize: e.target.value }))}
              />
            </div>
            <button type="submit" className="go">
              <span>Run screening</span>
              <i aria-hidden="true">→</i>
            </button>
          </div>
          <p className="sub mt">Empty filters are taken from the deal record (region, value).</p>
        </div>
      </form>

      {state.status === "loading" && <Loading />}
      {state.status === "error" && (
        <p className="note bad mt" role="alert">
          {state.error.message}
        </p>
      )}
      {state.status === "ready" &&
        (state.data.cards.length === 0 ? (
          <p className="note mt">No buyer matches these filters.</p>
        ) : (
          <Results key={state.data.cards.map((c) => c.buyer.id).join()} result={state.data} onOpen={onOpen} activeChunk={activeChunk} />
        ))}
    </div>
  );
}
