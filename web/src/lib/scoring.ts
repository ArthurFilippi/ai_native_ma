import type { BuyerCard, Criterion, CriterionStatus } from "./contracts";

// Mirrors ainma.screening.scoring.score_cards. The rules are written in the description of
// tests/fixtures/scoring_vectors.json and a test replays every case within 1e-6:
//   score        = sum(w * met) / sum(w over known criteria), null when no weight is known
//   coverage     = known weight / total weight
//   contribution = w * met / sum(w over known criteria), so contributions sum to the score
//   dealbreakers = criteria flagged as dealbreaker whose status is not_met
//   ranking      = cards without a dealbreaker first; score desc (null last), coverage desc, buyer id asc
export function scoreCards(
  criteria: readonly Criterion[],
  cards: readonly BuyerCard[],
  weights: Readonly<Record<string, number>>,
): BuyerCard[] {
  const weightOf = (c: Criterion): number => weights[c.key] ?? c.weight;
  const total = criteria.reduce((sum, c) => sum + weightOf(c), 0);

  const scored = cards.map((card): BuyerCard => {
    const status = new Map<string, CriterionStatus>(
      card.results.map((r) => [r.criterion_key, r.status]),
    );
    let known = 0;
    let met = 0;
    for (const c of criteria) {
      const s = status.get(c.key) ?? "unknown";
      if (s === "unknown") continue;
      known += weightOf(c);
      if (s === "met") met += weightOf(c);
    }
    const contributions: Record<string, number> = {};
    for (const c of criteria) {
      const isMet = (status.get(c.key) ?? "unknown") === "met";
      contributions[c.key] = known > 0 && isMet ? weightOf(c) / known : 0;
    }
    return {
      ...card,
      score: known > 0 ? met / known : null,
      coverage: total > 0 ? known / total : 0,
      contributions,
      dealbreakers: criteria
        .filter((c) => c.dealbreaker && status.get(c.key) === "not_met")
        .map((c) => c.key),
    };
  });

  const ordered = [...scored].sort((a, b) => {
    const blocked = Number(a.dealbreakers.length > 0) - Number(b.dealbreakers.length > 0);
    if (blocked !== 0) return blocked;
    const byScore = (b.score ?? -1) - (a.score ?? -1);
    if (byScore !== 0) return byScore;
    const byCoverage = b.coverage - a.coverage;
    if (byCoverage !== 0) return byCoverage;
    return a.buyer.id < b.buyer.id ? -1 : a.buyer.id > b.buyer.id ? 1 : 0;
  });
  return ordered.map((card, index) => ({ ...card, rank: index + 1 }));
}
