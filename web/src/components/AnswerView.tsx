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
        {claim.origin === "structured" && (
          <span
            className="st sky chip-structured"
            title="Value from the structured fact base; the citation is its document of record"
          >
            Structured record
          </span>
        )}
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
    <section className="plate contradiction" aria-label={`Contradiction: ${contradiction.subject}`}>
      <div className="plate-h">
        <h2>{contradiction.subject}</h2>
        <span className="st bad">Sources disagree</span>
      </div>
      <div className="sides">
        {contradiction.sides.map((side, index) => {
          const first = side.citations[0];
          return (
            <article key={side.claim_id} className="side">
              <p className="side-value big">{side.label}</p>
              {first && (
                <p className="side-source">
                  <TierChip tier={first.tier} /> {first.doc_title}
                  <br />
                  <span className="sub mono">{dateOrUnknown(first.published_on)}</span>
                </p>
              )}
              <p className="sub">
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
      <p className="plate-b tint">{contradiction.note}</p>
    </section>
  );
}

function TraceDrawer({ answer }: { answer: Answer }) {
  const { trace } = answer;
  return (
    <details className="plate fold trace">
      <summary>
        <span className="fold-t">Trace (for engineers)</span>
        <span className="fold-h">writer, judge, latency, retrieved passages</span>
      </summary>
      <p>
        Writer {trace.provider} {trace.model}; judge{" "}
        {trace.judge_model
          ? `${trace.judge_provider ?? trace.provider} ${trace.judge_model}`
          : "same as writer"}
        ; tokens in {trace.input_tokens}, out {trace.output_tokens}.
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
        <table className="tbl tight">
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
      <section className="plate answer-head">
        <div className="plate-b">
          <p className="lab">Question</p>
          <p className="question-echo">{answer.question}</p>
          <p className="summary big">{answer.summary}</p>
        </div>
      </section>

      {answer.degraded && (
        <section className="note warn mt degraded" role="alert" aria-label="Degraded answer">
          <h3 className="lab">Degraded answer</h3>
          <p>{answer.degraded_reason ?? "A live model call failed; rules answered instead."}</p>
        </section>
      )}

      {answer.abstained && (
        <section className="plate abstention" aria-label="Abstention">
          <div className="plate-h">
            <h2>No answer given</h2>
            <span className="st">Abstained</span>
          </div>
          <div className="plate-b">
            <p>{answer.abstention_reason ?? "The sources do not support an answer."}</p>
          </div>
        </section>
      )}

      {!answer.abstained && answer.claims.length > 0 && (
        <section className="plate" aria-label="Claims">
          <div className="plate-h">
            <h2>Claims</h2>
          </div>
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
        <section className="plate" aria-label="Missing information">
          <div className="plate-h">
            <h2>Missing</h2>
          </div>
          <ul className="plate-b missing issues">
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
