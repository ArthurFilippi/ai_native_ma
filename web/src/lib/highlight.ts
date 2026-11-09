import type { Citation } from "./contracts";

export interface Span {
  start: number;
  end: number;
}

export interface Located {
  span: Span;
  // true when the span is exactly the cited quote, false when only the chunk could be marked
  exact: boolean;
}

// Where to put the <mark> in the page text. The citation offsets are trusted only when the page
// text at those offsets is the quote. Otherwise the quote is searched inside the chunk range,
// then in the whole page, and as a last resort the whole chunk is marked and flagged as inexact.
export function locateSpan(pageText: string, citation: Citation, chunk: Span): Located {
  const { quote } = citation;
  const direct = citation.char_start + quote.length;
  if (pageText.slice(citation.char_start, direct) === quote) {
    return { span: { start: citation.char_start, end: direct }, exact: true };
  }
  const inChunk = pageText.slice(0, chunk.end).indexOf(quote, chunk.start);
  if (inChunk >= 0) return { span: { start: inChunk, end: inChunk + quote.length }, exact: true };
  const anywhere = pageText.indexOf(quote);
  if (anywhere >= 0) return { span: { start: anywhere, end: anywhere + quote.length }, exact: true };
  return { span: chunk, exact: false };
}

export interface Segments {
  before: string;
  marked: string;
  after: string;
  clippedBefore: boolean;
  clippedAfter: boolean;
}

// Split the page text around the span. With `context` set only that many characters on each side
// are kept; `null` keeps the full page.
export function segmentPage(pageText: string, span: Span, context: number | null): Segments {
  const from = context === null ? 0 : Math.max(0, span.start - context);
  const to = context === null ? pageText.length : Math.min(pageText.length, span.end + context);
  return {
    before: pageText.slice(from, span.start),
    marked: pageText.slice(span.start, span.end),
    after: pageText.slice(span.end, to),
    clippedBefore: from > 0,
    clippedAfter: to < pageText.length,
  };
}
