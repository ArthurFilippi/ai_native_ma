import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { DOC_TYPE_LABEL } from "@/lib/constants";
import type { Citation, Passage, RankedPassage } from "@/lib/contracts";
import { dateOrUnknown } from "@/lib/format";
import { locateSpan, segmentPage } from "@/lib/highlight";
import { useAsync } from "@/lib/useAsync";
import { TierChip, TierLegend } from "./Chips";

const CONTEXT_CHARS = 280;

export interface EvidenceTarget {
  citation: Citation;
  ranking: RankedPassage | null;
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function PageText({ passage, citation }: { passage: Passage; citation: Citation }) {
  const [fullPage, setFullPage] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const markRef = useRef<HTMLElement>(null);
  const pageText = passage.page_text ?? passage.chunk.text;
  const chunkRange =
    passage.page_text === null
      ? { start: 0, end: passage.chunk.text.length }
      : { start: passage.highlight_start, end: passage.highlight_end };
  const located = locateSpan(pageText, citation, chunkRange);
  const segments = segmentPage(pageText, located.span, fullPage ? null : CONTEXT_CHARS);

  useEffect(() => {
    // Scroll the passage box only, so the rest of the page does not jump.
    const box = boxRef.current;
    const mark = markRef.current;
    if (box && mark) box.scrollTop = Math.max(0, mark.offsetTop - box.clientHeight / 2);
  }, [fullPage, located.span.start]);

  return (
    <>
      <div className="page-text" data-testid="page-text" tabIndex={0} ref={boxRef}>
        {segments.clippedBefore && <span className="muted">... </span>}
        {segments.before}
        <mark ref={markRef} data-testid="evidence-highlight">
          {segments.marked}
        </mark>
        {segments.after}
        {segments.clippedAfter && <span className="muted"> ...</span>}
      </div>
      {!located.exact && (
        <p className="note">
          The exact cited span could not be located, so the whole passage is marked.
        </p>
      )}
      <button type="button" onClick={() => setFullPage((v) => !v)}>
        {fullPage ? "Show the passage with its context only" : "Show the full page"}
      </button>
    </>
  );
}

function Loaded({
  passage,
  target,
}: {
  passage: Passage;
  target: EvidenceTarget;
}) {
  const { document: doc } = passage;
  return (
    <>
      <h3>{doc.title}</h3>
      <dl className="meta">
        <Meta label="Document type">{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}</Meta>
        <Meta label="Source tier">
          <TierChip tier={doc.tier} />
        </Meta>
        <Meta label="Published">{dateOrUnknown(doc.published_on)}</Meta>
        <Meta label="Status">
          <span className={`chip chip-status chip-${doc.status}`}>{doc.status}</span>
        </Meta>
        <Meta label="Page">
          {passage.chunk.page} of {doc.n_pages}
        </Meta>
        {doc.synthetic && <Meta label="Data">synthetic</Meta>}
      </dl>
      <TierLegend current={doc.tier} />
      <h4>Passage</h4>
      <PageText passage={passage} citation={target.citation} />
      <h4>Why this passage ranks here</h4>
      <p>
        {target.ranking
          ? `Rank ${target.ranking.rank}, score ${target.ranking.final_score}. ${target.ranking.explanation}`
          : "No ranking explanation: this passage was not produced by an answer."}
      </p>
    </>
  );
}

function Unavailable({ target, error }: { target: EvidenceTarget; error: Error }) {
  const { citation } = target;
  const status = error instanceof ApiError ? error.status : null;
  return (
    <>
      <h3>{citation.doc_title}</h3>
      <dl className="meta">
        <Meta label="Document type">{DOC_TYPE_LABEL[citation.doc_type] ?? citation.doc_type}</Meta>
        <Meta label="Source tier">
          <TierChip tier={citation.tier} />
        </Meta>
        <Meta label="Published">{dateOrUnknown(citation.published_on)}</Meta>
        <Meta label="Page">{citation.page}</Meta>
      </dl>
      <TierLegend current={citation.tier} />
      <p className="note" role="alert">
        The page text could not be loaded{status ? ` (${status})` : ""}. Showing the cited quote
        only.
      </p>
      <div className="page-text">
        <mark data-testid="evidence-highlight">{citation.quote}</mark>
      </div>
    </>
  );
}

export function EvidencePanel({
  api,
  target,
  onClose,
}: {
  api: Api;
  target: EvidenceTarget;
  onClose: () => void;
}) {
  const chunkId = target.citation.chunk_id;
  const load = useCallback(() => api.passage(chunkId), [api, chunkId]);
  const state = useAsync(load);

  return (
    <aside className="evidence" aria-label="Evidence panel">
      <div className="evidence-head">
        <h2>Evidence</h2>
        <button type="button" onClick={onClose}>
          Close
        </button>
      </div>
      {state.status === "loading" && <p className="muted">Loading the source passage.</p>}
      {state.status === "error" && <Unavailable target={target} error={state.error} />}
      {state.status === "ready" && (
        <Loaded key={chunkId} passage={state.data} target={target} />
      )}
    </aside>
  );
}
