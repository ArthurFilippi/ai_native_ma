import { useCallback, useEffect, useRef, useState } from "react";
import type { Api } from "@/lib/api";
import { ApiError } from "@/lib/api";
import { DOC_TYPE_LABEL } from "@/lib/constants";
import type { Citation, Passage } from "@/lib/contracts";
import { dateOrUnknown } from "@/lib/format";
import { locateSpan, segmentPage } from "@/lib/highlight";
import { useAsync } from "@/lib/useAsync";
import { StatusChip, TierChip, TierLegend } from "./Chips";
import { Loading } from "./Loading";

const CONTEXT_CHARS = 280;

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
        <p className="note warn mt">
          The exact cited span could not be located, so the whole passage is marked.
        </p>
      )}
      <button type="button" className="btn sm mt" onClick={() => setFullPage((v) => !v)}>
        {fullPage ? "Show the passage with its context only" : "Show the full page"}
      </button>
    </>
  );
}

function Head({
  title,
  docType,
  tier,
  published,
  page,
  status,
}: {
  title: string;
  docType: string;
  tier: Citation["tier"];
  published: string | null;
  page: string;
  status?: Passage["document"]["status"];
}) {
  return (
    <div className="plate-b">
      <h3 className="big-name">{title}</h3>
      <div className="source-line">
        <TierChip tier={tier} />
        <span>{DOC_TYPE_LABEL[docType] ?? docType}</span>
        <span className="mono">{dateOrUnknown(published)}</span>
        <span className="mono">{page}</span>
        {status && status !== "current" && <StatusChip status={status} />}
      </div>
    </div>
  );
}

function Loaded({ passage, citation }: { passage: Passage; citation: Citation }) {
  const { document: doc } = passage;
  return (
    <>
      <Head
        title={doc.title}
        docType={doc.doc_type}
        tier={doc.tier}
        published={doc.published_on}
        page={`p. ${passage.chunk.page} of ${doc.n_pages}`}
        status={doc.status}
      />
      <div className="plate-b">
        <PageText passage={passage} citation={citation} />
      </div>
      <details className="plate-b fold tier-fold">
        <summary>
          <span className="fold-t">What the tiers mean</span>
        </summary>
        <TierLegend current={doc.tier} />
      </details>
    </>
  );
}

function Unavailable({ citation, error }: { citation: Citation; error: Error }) {
  const status = error instanceof ApiError ? error.status : null;
  return (
    <>
      <Head
        title={citation.doc_title}
        docType={citation.doc_type}
        tier={citation.tier}
        published={citation.published_on}
        page={`p. ${citation.page}`}
      />
      <div className="plate-b">
        <p className="note bad" role="alert">
          The page text could not be loaded{status ? ` (${status})` : ""}. Showing the cited quote
          only.
        </p>
        <div className="page-text mt">
          <mark data-testid="evidence-highlight">{citation.quote}</mark>
        </div>
      </div>
    </>
  );
}

export function EvidencePanel({
  api,
  citation,
  onClose,
}: {
  api: Api;
  citation: Citation;
  onClose: () => void;
}) {
  const chunkId = citation.chunk_id;
  const load = useCallback(() => api.passage(chunkId), [api, chunkId]);
  const state = useAsync(load);

  return (
    <aside className="plate evidence" aria-label="Evidence panel">
      <div className="plate-h">
        <h2>Source</h2>
        <button type="button" className="plate-x" aria-label="Close the source" onClick={onClose}>
          <span>×</span>
        </button>
      </div>
      {state.status === "loading" && <Loading inline />}
      {state.status === "error" && <Unavailable citation={citation} error={state.error} />}
      {state.status === "ready" && <Loaded key={chunkId} passage={state.data} citation={citation} />}
    </aside>
  );
}
