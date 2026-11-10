import { useState } from "react";
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
import { Drawer } from "./Drawer";
import { Loading } from "./Loading";

const EXECUTION = ["ticket_fit", "ev_ratio", "fund_lifecycle", "integration_bandwidth"];
const CELL: Record<CriterionStatus, { cell: string; glyph: string; label: string }> = {
  met: { cell: "v", glyph: "✓", label: "met" },
  not_met: { cell: "q", glyph: "✕", label: "not met" },
  unknown: { cell: "m", glyph: "?", label: "unknown" },
};

function status(card: BuyerCard, key: string): CriterionStatus | null {
  return card.results.find((r) => r.criterion_key === key)?.status ?? null;
}

// Risk flags read from the criteria: what a banker scans for first.
export function flagsOf(card: BuyerCard): { label: string; tone: string; why: string }[] {
  const out: { label: string; tone: string; why: string }[] = [];
  if (card.dealbreakers.length > 0) out.push({ label: "Dealbreaker", tone: "bad", why: card.dealbreakers.join(", ") });
  if (status(card, "antitrust") === "not_met") out.push({ label: "Antitrust", tone: "bad", why: "combined share above the threshold" });
  if (status(card, "regulatory_fdi") === "not_met") out.push({ label: "FDI", tone: "bad", why: "foreign investment screening likely" });
  const exec = EXECUTION.filter((k) => status(card, k) === "not_met");
  if (exec.length > 0) out.push({ label: "Execution risk", tone: "warn", why: exec.join(", ") });
  return out;
}

export function confidenceOf(coverage: number): { label: string; tone: string } {
  if (coverage >= 0.7) return { label: "High", tone: "ok" };
  if (coverage >= 0.4) return { label: "Medium", tone: "warn" };
  return { label: "Low", tone: "bad" };
}

function sourcesOf(card: BuyerCard): number {
  return new Set(card.results.flatMap((r) => r.citations.map((c) => c.chunk_id))).size;
}

interface Form {
  types: BuyerType[];
  regions: string;
  minSize: string;
  maxSize: string;
}

function toRequest(dealId: string, form: Form): ScreeningRequest {
  const num = (t: string) => (t.trim() === "" || Number.isNaN(Number(t)) ? null : Number(t));
  return {
    deal_id: dealId,
    filters: {
      buyer_types: form.types,
      sectors: [],
      geographies: form.regions.split(",").map((r) => r.trim()).filter(Boolean),
      min_size_eur_m: num(form.minSize),
      max_size_eur_m: num(form.maxSize),
    },
    weights: {},
    stage2_top_n: 20,
  };
}

function BuyerDetail({
  card,
  criteria,
  onOpen,
}: {
  card: BuyerCard;
  criteria: readonly Criterion[];
  onOpen: (c: Citation) => void;
}) {
  return (
    <section className="plate buyer-detail" aria-label={`Buyer card: ${card.buyer.name}`}>
      <div className="plate-b">
        <h3 className="big-name">{card.buyer.name}</h3>
        <p className="sub">
          {card.buyer.buyer_type}, {card.buyer.geographies.join(", ")}, size EUR {formatNumber(card.buyer.size_eur_m)}m.
          Fit {percent(card.score)}
          {card.score_low != null && card.score_high != null
            ? ` (could be ${percent(card.score_low)} to ${percent(card.score_high)})`
            : ""}
          , evidence on {percent(card.coverage)} of the weight.
        </p>
      </div>
      <ul className="criteria">
        {criteria
          .filter((c) => card.results.some((r) => r.criterion_key === c.key))
          .map((c) => {
            const r = card.results.find((x) => x.criterion_key === c.key);
            const s = r?.status ?? "unknown";
            return (
              <li key={c.key}>
                <span className={`cell ${CELL[s].cell}`} role="img" aria-label={`${c.label}: ${CELL[s].label}`}>
                  {CELL[s].glyph}
                </span>
                <div>
                  <b>{c.label}</b>
                  <p className="sub">{r?.rationale}</p>
                  {(r?.citations ?? []).map((cite) => (
                    <button key={cite.chunk_id} type="button" className="link sub" onClick={() => onOpen(cite)}>
                      {cite.doc_title}, T{cite.tier}
                    </button>
                  ))}
                </div>
              </li>
            );
          })}
      </ul>
    </section>
  );
}

export function BuyersPage({ api, dealId, onOpen }: { api: Api; dealId: string; onOpen: (c: Citation) => void }) {
  const [form, setForm] = useState<Form>({ types: [], regions: "", minSize: "", maxSize: "" });
  const [request, setRequest] = useState<ScreeningRequest | null>(null);
  const [result, setResult] = useState<ScreeningResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [said, setSaid] = useState("");
  const [understood, setUnderstood] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  async function screen(next: ScreeningRequest) {
    setBusy(true);
    setError(null);
    try {
      const served = await api.screening(next);
      setRequest(next);
      setResult(served.value);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function refine() {
    if (!said.trim() || !request) return;
    setBusy(true);
    try {
      const outcome = await api.refine(said, request);
      setUnderstood((u) => [...u, ...outcome.understood]);
      setSaid("");
      await screen(outcome.request);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const toggle = (t: BuyerType) =>
    setForm((f) => ({ ...f, types: f.types.includes(t) ? f.types.filter((x) => x !== t) : [...f.types, t] }));
  const ranked = (result?.cards ?? []).filter((c) => c.rank !== null);
  const chosen = ranked.find((c) => c.buyer.id === open);

  return (
    <>
      <form
        className="plate"
        aria-label="Pre-selection"
        onSubmit={(e) => {
          e.preventDefault();
          setUnderstood([]);
          void screen(toRequest(dealId, form));
        }}
      >
        <div className="plate-b">
          <div className="row">
            <div className="field" style={{ flex: "0 1 auto" }}>
              <span className="lab">Buyer type</span>
              <span className="chips">
                {(["strategic", "financial"] as const).map((t) => (
                  <button key={t} type="button" className={`opt${form.types.includes(t) ? " on" : ""}`} aria-pressed={form.types.includes(t)} onClick={() => toggle(t)}>
                    {t}
                  </button>
                ))}
              </span>
            </div>
            <div className="field">
              <label className="lab" htmlFor="b-regions">
                Regions
              </label>
              <input id="b-regions" type="text" placeholder="from the deal, e.g. DACH, France" value={form.regions} onChange={(e) => setForm((f) => ({ ...f, regions: e.target.value }))} />
            </div>
            <div className="field" style={{ flex: "0 1 150px" }}>
              <label className="lab" htmlFor="b-min">
                Min size EUR m
              </label>
              <input id="b-min" type="number" placeholder="from the deal" value={form.minSize} onChange={(e) => setForm((f) => ({ ...f, minSize: e.target.value }))} />
            </div>
            <div className="field" style={{ flex: "0 1 150px" }}>
              <label className="lab" htmlFor="b-max">
                Max size EUR m
              </label>
              <input id="b-max" type="number" placeholder="from the deal" value={form.maxSize} onChange={(e) => setForm((f) => ({ ...f, maxSize: e.target.value }))} />
            </div>
            <button type="submit" className="btn solid" disabled={busy}>
              Screen buyers
            </button>
          </div>
        </div>
      </form>

      {request && (
        <form
          className="refine"
          onSubmit={(e) => {
            e.preventDefault();
            void refine();
          }}
        >
          <div className="lg-ask">
            <label htmlFor="b-refine" className="sr">
              Refine in words
            </label>
            <input
              id="b-refine"
              type="search"
              placeholder="Refine in words, e.g. only funds above EUR 500m, prefer recent acquirers"
              value={said}
              onChange={(e) => setSaid(e.target.value)}
            />
            <button type="submit" className="btn" disabled={busy || !said.trim()}>
              Refine
            </button>
          </div>
          {understood.length > 0 && (
            <div className="lg-said">
              <span className="sub">Understood:</span>
              {understood.map((u) => (
                <span key={u} className="lg-chip">
                  {u}
                </span>
              ))}
            </div>
          )}
        </form>
      )}

      {busy && <Loading inline />}
      {error && (
        <p className="note bad mt" role="alert">
          {error}
        </p>
      )}

      {result && !busy && (
        <section className="plate">
          <div className="plate-b flush">
            {ranked.length === 0 ? (
              <p className="plate-b sub">No buyer passes these filters.</p>
            ) : (
              <div className="fill fill-list">
                <table className="tbl" aria-label="Screening results">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Buyer</th>
                      <th>Type</th>
                      <th title="Weight of met criteria over the weight with evidence; the rank uses the lower bound">Fit</th>
                      <th title="Share of the criteria weight backed by evidence">Confidence</th>
                      <th className="num">Sources</th>
                      <th>Flags</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranked.map((card, position) => {
                      const conf = confidenceOf(card.coverage);
                      return (
                        <tr key={card.buyer.id} className={`click${open === card.buyer.id ? " sel" : ""}`} onClick={() => setOpen(card.buyer.id)}>
                          <td className="mono">{position + 1}</td>
                          <td>
                            <button type="button" className="link" onClick={(e) => { e.stopPropagation(); setOpen(card.buyer.id); }}>
                              {card.buyer.name}
                            </button>
                          </td>
                          <td>{card.buyer.buyer_type}</td>
                          <td className="nowrap">
                            <b>{percent(card.score)}</b>{" "}
                            {card.score_low != null && card.score_high != null && (
                              <span className="sub mono">
                                {percent(card.score_low)}-{percent(card.score_high)}
                              </span>
                            )}
                          </td>
                          <td>
                            <span className={`st ${conf.tone}`} title={`evidence on ${percent(card.coverage)} of the weight`}>
                              {conf.label}
                            </span>
                          </td>
                          <td className="num mono">{sourcesOf(card)}</td>
                          <td>
                            <span className="flags">
                              {flagsOf(card).map((f) => (
                                <span key={f.label} className={`st ${f.tone}`} title={f.why}>
                                  {f.label}
                                </span>
                              ))}
                            </span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <p className="pager sub">
              Unknown criteria are never guessed: they lower the confidence, not the fit. Click a buyer for its evidence.
            </p>
          </div>
        </section>
      )}

      {chosen && result && (
        <Drawer onClose={() => setOpen(null)} label={`Buyer card: ${chosen.buyer.name}`}>
          <BuyerDetail
            card={chosen}
            criteria={result.criteria}
            onOpen={(c) => {
              setOpen(null);
              onOpen(c);
            }}
          />
        </Drawer>
      )}
    </>
  );
}
