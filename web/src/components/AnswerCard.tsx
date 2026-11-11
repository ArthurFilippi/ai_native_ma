import { MISSING_REASON, STATUS_LABEL, flagText } from "@/lib/constants";
import type { Answer, Citation, Claim } from "@/lib/contracts";
import { dateOrUnknown, latestDate } from "@/lib/format";
import { TierChip } from "./Chips";

const LEVEL = {
  high: { label: "High confidence", tone: "ok" },
  medium: { label: "Medium confidence", tone: "warn" },
  low: { label: "Low confidence", tone: "bad" },
} as const;

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

// Every distinct cited passage of the answer, numbered in order of first use.
export function numberedSources(answer: Answer): Citation[] {
  const seen = new Map<string, Citation>();
  for (const claim of answer.claims) {
    for (const c of claim.citations) {
      const key = `${c.chunk_id}:${c.char_start}`;
      if (!seen.has(key)) seen.set(key, c);
    }
  }
  return [...seen.values()];
}

function sourceIndex(sources: Citation[], c: Citation): number {
  return sources.findIndex((s) => s.chunk_id === c.chunk_id && s.char_start === c.char_start) + 1;
}

function ClaimLine({ claim, sources, onOpen }: { claim: Claim; sources: Citation[]; onOpen: (c: Citation) => void }) {
  const date = latestDate(claim.citations.map((c) => c.published_on));
  const label =
    claim.status === "sourced" ? "Sourced" : claim.status === "inferred" ? STATUS_LABEL.inferred : STATUS_LABEL.missing;
  return (
    <li id={`claim-${claim.id}`} tabIndex={-1} className={`claim claim-${claim.status}`}>
      <span className="status-label">{label}</span>
      <span className="claim-text">{claim.text}</span>
      {claim.origin === "structured" && <span className="st sky">Structured record</span>}
      {claim.origin === "event" && <span className="st sky">News event</span>}
      {claim.flags.map((flag) => (
        <span key={flag} className="st warn">
          {flagText(flag, date)}
        </span>
      ))}
      {claim.citations.map((c) => (
        <button
          key={`${c.chunk_id}:${c.char_start}`}
          type="button"
          className="ref"
          onClick={() => onOpen(c)}
          aria-label={`Open source ${sourceIndex(sources, c)}`}
        >
          {sourceIndex(sources, c)}
        </button>
      ))}
    </li>
  );
}

export function AnswerCard({
  answer,
  onOpen,
  activeChunk,
}: {
  answer: Answer;
  onOpen: (citation: Citation) => void;
  activeChunk: string | null;
}) {
  const sources = numberedSources(answer);
  const level = answer.confidence ? LEVEL[answer.confidence] : null;
  return (
    <article className="answer-card" data-testid="answer">
      {answer.degraded && (
        <p className="note warn" role="alert">
          Degraded: {answer.degraded_reason ?? "a live model call failed; rules answered instead."}
        </p>
      )}

      {answer.abstained ? (
        <section aria-label="Abstention">
          <p className="answer-text">Not found in the sources of this deal.</p>
          <p className="sub">{answer.abstention_reason ?? "The sources do not support an answer."}</p>
        </section>
      ) : (
        <p className="answer-text">{answer.summary}</p>
      )}

      {level && (
        <p className="confidence">
          <span className={`st ${level.tone}`}>{level.label}</span>
          <span className="sub">{capitalise(answer.confidence_reason?.replace(/^\w+: /, "") ?? "")}</span>
        </p>
      )}

      {answer.contradictions.map((k) => (
        <section key={k.id} className="disagree" aria-label={`Contradiction: ${k.subject}`}>
          <span className="st bad">Sources disagree</span>
          <span className="disagree-sides">
            {k.sides.map((side, i) => {
              const c = side.citations[0];
              return (
                <span key={side.claim_id}>
                  {i > 0 && <span className="sub"> vs </span>}
                  <b>{side.label}</b>
                  {c && (
                    <span className="sub">
                      {" "}
                      ({c.doc_title}, T{c.tier})
                    </span>
                  )}
                </span>
              );
            })}
          </span>
          <span className="sub">{k.note}</span>
        </section>
      ))}

      {sources.length > 0 && (
        <ol className="sources" aria-label="Sources">
          {sources.map((c, i) => (
            <li key={`${c.chunk_id}:${c.char_start}`}>
              <button
                type="button"
                className={`source${activeChunk === c.chunk_id ? " on" : ""}`}
                onClick={() => onOpen(c)}
                data-chunk-id={c.chunk_id}
              >
                <span className="source-n mono">{i + 1}</span>
                <TierChip tier={c.tier} />
                <span className="source-title">{c.doc_title}</span>
                <span className="source-date mono">{dateOrUnknown(c.published_on)}</span>
                <span className="source-quote">“{c.quote}”</span>
              </button>
            </li>
          ))}
        </ol>
      )}

      {answer.missing.length > 0 && !answer.abstained && (
        <p className="sub missing">
          Not found:{" "}
          {answer.missing.map((m) => `${m.topic} (${MISSING_REASON[m.reason].toLowerCase()})`).join("; ")}
        </p>
      )}

      {!answer.abstained && answer.claims.length > 0 && (
        <details className="fold claims-fold">
          <summary>
            <span className="fold-t">Claim by claim</span>
            <span className="fold-h">
              {answer.claims.length} claims, model {answer.trace.model}
            </span>
          </summary>
          <ul className="claims" aria-label="Claims">
            {answer.claims.map((claim) => (
              <ClaimLine key={claim.id} claim={claim} sources={sources} onOpen={onOpen} />
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
