import { describe, expect, it } from "vitest";
import type { Citation } from "@/lib/contracts";
import { locateSpan, segmentPage } from "@/lib/highlight";

function citation(quote: string, charStart: number): Citation {
  return {
    chunk_id: "c",
    document_id: "d",
    doc_title: "t",
    doc_type: "deal_document",
    tier: 2,
    published_on: null,
    page: 1,
    char_start: charStart,
    char_end: charStart + quote.length,
    quote,
  };
}

const PAGE = "Intro text.\n\nNet revenue reached EUR 182.4 million in FY2024.\n\nOutro text.";
const QUOTE = "EUR 182.4 million";
const START = PAGE.indexOf(QUOTE);
const CHUNK = { start: 13, end: 13 + "Net revenue reached EUR 182.4 million in FY2024.".length };

describe("locateSpan", () => {
  it("trusts offsets that point at the quote", () => {
    expect(locateSpan(PAGE, citation(QUOTE, START), CHUNK)).toEqual({
      span: { start: START, end: START + QUOTE.length },
      exact: true,
    });
  });

  it("finds the quote inside the chunk when the offsets are off", () => {
    const located = locateSpan(PAGE, citation(QUOTE, 0), CHUNK);
    expect(located).toEqual({ span: { start: START, end: START + QUOTE.length }, exact: true });
  });

  it("marks the chunk and says so when the quote is nowhere", () => {
    expect(locateSpan(PAGE, citation("not on the page", 0), CHUNK)).toEqual({
      span: CHUNK,
      exact: false,
    });
  });
});

describe("segmentPage", () => {
  const span = { start: START, end: START + QUOTE.length };

  it("keeps the full page when no context limit is given", () => {
    const s = segmentPage(PAGE, span, null);
    expect(s.before + s.marked + s.after).toBe(PAGE);
    expect(s.marked).toBe(QUOTE);
    expect(s.clippedBefore || s.clippedAfter).toBe(false);
  });

  it("clips around the span and reports it", () => {
    const s = segmentPage(PAGE, span, 5);
    expect(s.marked).toBe(QUOTE);
    expect(s.before).toHaveLength(5);
    expect(s.clippedBefore).toBe(true);
    expect(s.clippedAfter).toBe(true);
  });
});
