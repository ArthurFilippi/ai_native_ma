import { MISSING_REASON, STATUS_LABEL } from "@/lib/constants";
import type { Answer, Citation, Claim, Contradiction } from "@/lib/contracts";
import { dateOrUnknown, formatNumber, latestDate } from "@/lib/format";
import { CitationButton } from "./CitationButton";
import { FlagChips, TierChip } from "./Chips";

interface OpenProps {
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}

function focusClaim(id: string) {
  const el = document.getElementById(`claim-${id}`);
  el?.focus();
  el?.scrollIntoView?.({ block: "nearest" });
}

function ClaimRow({ claim, onOpen, activeChunk }: OpenProps & { claim: Claim }) {
  const date = latestDate(claim.citations.map((c) => c.published_on));
  return (
    <li id={`claim-${claim.id}`} tabIndex={-1} className={`claim claim-${claim.status}`}>
      <div className="claim-head">
        {claim.status === "sourced" && <span className="status-label">Sourced</span>}
        {claim.status === "inferred" && (
          <span className="status-label">{STATUS_LABEL.inferred}</span>
        )}
        {claim.status === "missing" && (
          <span className="status-label">
            <span className="hollow" aria-hidden="true" />
            {STATUS_LABEL.missing}
          </span>
        )}
        {date && <span className="claim-date">{date}</span>}
        <FlagChips flags={claim.flags} date={date} />
      </div>
      <p className="claim-text">{claim.text}</p>
      {claim.status === "inferred" && (
        <p className="derived">
          Derived from:{" "}
          {claim.derived_from.map((id) => (
            <button key={id} type="button" className="link" onClick={() => focusClaim(id)}>
              claim {id}
            </button>
          ))}
        </p>
      )}
      {claim.citations.length > 0 && (
        <div className="citations">
          {claim.citations.map((citation) => (
            <CitationButton
              key={`${citation.chunk_id}:${citation.char_start}`}
              citation={citation}
              onOpen={onOpen}
              active={activeChunk === citation.chunk_id}
            />
          ))}
        </div>
      )}
    </li>
  );
}

function ContradictionCards({
  contradiction,
  onOpen,
  activeChunk,
}: OpenProps & { contradiction: Contradiction }) {
  return (
    <section className="contradiction" aria-label={`Contradiction: ${contradiction.subject}`}>
      <h3>{contradiction.subject}</h3>
      <div className="sides">
        {contradiction.sides.map((side, index) => {
          const first = side.citations[0];
          return (
            <article key={side.claim_id} className="side">
              <p className="side-value">{side.label}</p>
              {first && (
                <p className="side-source">
                  <TierChip tier={first.tier} /> {first.doc_title}
                  <br />
                  <span className="muted">{dateOrUnknown(first.published_on)}</span>
                </p>
              )}
              <p className="muted">
                Strength {formatNumber(side.strength)} (tier weight x recency)
                {contradiction.stronger_side === index ? ", higher of the two (informative only)" : ""}
              </p>
              <div className="citations">
                {side.citations.map((citation) => (
                  <CitationButton
                    key={`${citation.chunk_id}:${citation.char_start}`}
                    citation={citation}
                    onOpen={onOpen}
                    active={activeChunk === citation.chunk_id}
                  />
                ))}
              </div>
            </article>
          );
        })}
      </div>
      <p className="note">{contradiction.note}</p>
    </section>
  );
}

function TraceDrawer({ answer }: { answer: Answer }) {
  const { trace } = answer;
  return (
    <details className="trace">
      <summary>Trace (for engineers)</summary>
      <p>
        Provider {trace.provider}, model {trace.model}, tokens in {trace.input_tokens}, out{" "}
        {trace.output_tokens}.
      </p>
      {answer.sub_questions.length > 0 && (
        <>
          <h4>Sub-questions</h4>
          <ul>
            {answer.sub_questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </>
      )}
      <h4>Stage latency (ms)</h4>
      <p>
        {Object.keys(trace.stage_latency_ms).length === 0
          ? "No stage ran."
          : Object.entries(trace.stage_latency_ms)
              .map(([stage, ms]) => `${stage} ${ms}`)
              .join(", ")}
      </p>
      <h4>Retrieved passages</h4>
      {trace.retrieved.length === 0 ? (
        <p>None.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Chunk</th>
              <th>Score</th>
              <th>Components</th>
            </tr>
          </thead>
          <tbody>
            {trace.retrieved.map((p) => (
              <tr key={p.chunk_id}>
                <td>{p.rank}</td>
                <td>{p.chunk_id}</td>
                <td>{formatNumber(p.final_score)}</td>
                <td>
                  {Object.entries(p.components)
                    .map(([name, value]) => `${name} ${formatNumber(value)}`)
                    .join(", ")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </details>
  );
}

export function AnswerView({ answer, onOpen, activeChunk }: OpenProps & { answer: Answer }) {
  return (
    <div className="answer" data-testid="answer">
      <p className="question-echo">
        <span className="muted">Question</span> {answer.question}
      </p>
      <p className="summary">{answer.summary}</p>

      {answer.abstained && (
        <section className="abstention" aria-label="Abstention">
          <h3>No answer given</h3>
          <p>{answer.abstention_reason ?? "The sources do not support an answer."}</p>
        </section>
      )}

      {!answer.abstained && answer.claims.length > 0 && (
        <section aria-label="Claims">
          <h3>Claims</h3>
          <ul className="claims">
            {answer.claims.map((claim) => (
              <ClaimRow key={claim.id} claim={claim} onOpen={onOpen} activeChunk={activeChunk} />
            ))}
          </ul>
        </section>
      )}

      {answer.contradictions.map((contradiction) => (
        <ContradictionCards
          key={contradiction.id}
          contradiction={contradiction}
          onOpen={onOpen}
          activeChunk={activeChunk}
        />
      ))}

      {answer.missing.length > 0 && (
        <section aria-label="Missing information">
          <h3>Missing</h3>
          <ul className="missing">
            {answer.missing.map((item) => (
              <li key={item.topic}>
                <span className="hollow" aria-hidden="true" /> <strong>{item.topic}</strong>:{" "}
                {MISSING_REASON[item.reason]}
              </li>
            ))}
          </ul>
        </section>
      )}

      <TraceDrawer answer={answer} />
    </div>
  );
}
