import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import type { BuyerCard, Criterion, CriterionStatus } from "@/lib/contracts";
import { scoreCards } from "@/lib/scoring";

interface Vectors {
  description: string;
  criteria: { key: string; weight: number; dealbreaker: boolean }[];
  buyers: Record<string, Record<string, CriterionStatus>>;
  cases: {
    name: string;
    weight_overrides: Record<string, number>;
    expected: {
      weights: Record<string, number>;
      cards: Record<
        string,
        {
          score: number | null;
          coverage: number;
          score_low: number | null;
          score_high: number | null;
          contributions: Record<string, number>;
          dealbreakers: string[];
        }
      >;
      ranking: string[];
    };
  }[];
}

// The shared vectors live in the repository, one level above web/.
const vectors = JSON.parse(
  readFileSync("../tests/fixtures/scoring_vectors.json", "utf-8"),
) as Vectors;

const criteria: Criterion[] = vectors.criteria.map((c) => ({
  key: c.key,
  label: c.key,
  kind: "deep",
  weight: c.weight,
  dealbreaker: c.dealbreaker,
  description: "",
}));

function card(id: string, statuses: Record<string, CriterionStatus>): BuyerCard {
  return {
    buyer: {
      id,
      name: id,
      buyer_type: "financial",
      sectors: [],
      geographies: [],
      size_eur_m: 0,
      ticket_min_eur_m: null,
      ticket_max_eur_m: null,
      fund_vintage_year: null,
      listed: false,
      synthetic: true,
    },
    stage1_passed: true,
    results: Object.entries(statuses).map(([criterion_key, status]) => ({
      criterion_key,
      status,
      rationale: "",
      citations: [],
      conflicting_evidence: false,
    })),
    score: null,
    coverage: 0,
    contributions: {},
    dealbreakers: [],
    rank: null,
  };
}

const TOLERANCE = 1e-6;
const cards = Object.entries(vectors.buyers).map(([id, statuses]) => card(id, statuses));

describe("scoreCards reproduces tests/fixtures/scoring_vectors.json", () => {
  it("has cases", () => {
    expect(vectors.cases.length).toBeGreaterThan(0);
  });

  for (const testCase of vectors.cases) {
    it(testCase.name, () => {
      const out = scoreCards(criteria, cards, testCase.weight_overrides);
      const byId = new Map(out.map((c) => [c.buyer.id, c]));
      for (const [id, expected] of Object.entries(testCase.expected.cards)) {
        const got = byId.get(id);
        expect(got, id).toBeDefined();
        if (!got) continue;
        if (expected.score === null) expect(got.score, `${id} score`).toBeNull();
        else expect(Math.abs((got.score ?? NaN) - expected.score), `${id} score`).toBeLessThan(TOLERANCE);
        expect(Math.abs(got.coverage - expected.coverage), `${id} coverage`).toBeLessThan(TOLERANCE);
        expect(Math.abs((got.score_low ?? NaN) - (expected.score_low ?? NaN)), `${id} low`).toBeLessThan(
          TOLERANCE,
        );
        expect(Math.abs((got.score_high ?? NaN) - (expected.score_high ?? NaN)), `${id} high`).toBeLessThan(
          TOLERANCE,
        );
        for (const [key, value] of Object.entries(expected.contributions)) {
          expect(Math.abs((got.contributions[key] ?? NaN) - value), `${id} ${key}`).toBeLessThan(
            TOLERANCE,
          );
        }
        expect(got.dealbreakers, `${id} dealbreakers`).toEqual(expected.dealbreakers);
      }
      expect(out.map((c) => c.buyer.id)).toEqual(testCase.expected.ranking);
      expect(out.map((c) => c.rank)).toEqual(out.map((_, i) => i + 1));
    });
  }

  it("contributions sum to the score", () => {
    for (const c of scoreCards(criteria, cards, {})) {
      const sum = Object.values(c.contributions).reduce((a, b) => a + b, 0);
      expect(Math.abs(sum - (c.score ?? 0))).toBeLessThan(TOLERANCE);
    }
  });
});
