import { dateOrUnknown } from "@/lib/format";
import type { Citation } from "@/lib/contracts";
import { TierChip } from "./Chips";

export function CitationButton({
  citation,
  onOpen,
  active,
}: {
  citation: Citation;
  onOpen: (citation: Citation) => void;
  active: boolean;
}) {
  return (
    <button
      type="button"
      className={`citation${active ? " citation-active" : ""}`}
      onClick={() => onOpen(citation)}
      aria-pressed={active}
      data-chunk-id={citation.chunk_id}
      title={`Open the source passage: ${citation.doc_title}`}
    >
      <TierChip tier={citation.tier} />
      <span className="citation-title">{citation.doc_title}</span>
      <span className="citation-meta">
        p. {citation.page}, {dateOrUnknown(citation.published_on)}
      </span>
    </button>
  );
}
