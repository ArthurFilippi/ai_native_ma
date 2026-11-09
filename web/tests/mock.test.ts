import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { KpiValue, ScreeningResult } from "@/lib/contracts";
import { scoreCards } from "@/lib/scoring";

const COPIES: [string, string][] = [
  ["src/mock/answer_contradiction.json", "../tests/fixtures/answer_contradiction.json"],
  ["src/mock/answer_abstention.json", "../tests/fixtures/answer_abstention.json"],
  ["src/mock/buyer_card.json", "../tests/fixtures/buyer_card.json"],
  ["src/mock/screening_result.json", "../src/ainma/api/examples/screening_result.json"],
  ["src/mock/kpis.json", "../src/ainma/api/examples/kpis.json"],
];

describe("mock payloads", () => {
  for (const [copy, source] of COPIES) {
    it(`${copy} equals ${source}`, () => {
      expect(readFileSync(copy, "utf-8")).toBe(readFileSync(source, "utf-8"));
    });
  }

  it("screening example is consistent with the client scoring at its own weights", () => {
    const result = JSON.parse(readFileSync("src/mock/screening_result.json", "utf-8")) as ScreeningResult;
    const out = scoreCards(result.criteria, result.cards, {});
    for (const card of result.cards) {
      const got = out.find((c) => c.buyer.id === card.buyer.id);
      expect(got?.rank).toBe(card.rank);
      expect(got?.score ?? null).toBeCloseTo(card.score ?? 0, 9);
      expect(got?.coverage).toBeCloseTo(card.coverage, 9);
      expect(got?.dealbreakers).toEqual(card.dealbreakers);
    }
  });

  it("kpi example has one missing value without a number", () => {
    const kpis = JSON.parse(readFileSync("src/mock/kpis.json", "utf-8")) as KpiValue[];
    expect(kpis.filter((k) => k.status === "missing").every((k) => k.value === null)).toBe(true);
  });
});
